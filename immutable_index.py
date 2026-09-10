"""Prospective immutable-source / disposable-runtime index controls."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_manifest(directory: Path) -> list[dict]:
    directory = directory.resolve()
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    return [
        {
            "path": path.relative_to(directory).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    ]


def tree_hash(directory: Path) -> str:
    encoded = json.dumps(
        tree_manifest(directory), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def create_verified_runtime_copy(source: Path, runtime: Path) -> dict:
    source = source.resolve()
    runtime = runtime.resolve()
    if source == runtime:
        raise ValueError("runtime path must differ from immutable source path")
    if runtime.exists():
        raise FileExistsError("runtime copy must be fresh")
    source_manifest = tree_manifest(source)
    shutil.copytree(source, runtime)
    runtime_manifest = tree_manifest(runtime)
    if source_manifest != runtime_manifest:
        raise RuntimeError("runtime copy is not byte-identical to source")
    marker = runtime.parent / f"{runtime.name}.source-verification.json"
    report = {
        "source": str(source),
        "runtime": str(runtime),
        "source_tree_sha256": tree_hash(source),
        "runtime_tree_sha256": tree_hash(runtime),
        "files": len(source_manifest),
        "verified": True,
        "copy_back_prohibited": True,
    }
    marker.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def assert_source_unchanged(source: Path, expected_tree_sha256: str) -> None:
    observed = tree_hash(source.resolve())
    if observed != expected_tree_sha256:
        raise RuntimeError(
            f"immutable source changed: expected {expected_tree_sha256}, observed {observed}"
        )
