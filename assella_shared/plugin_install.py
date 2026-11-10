"""Filesystem and download operations for signed-manifest plugins."""

import hashlib
import os
import urllib.request
from pathlib import Path

MAX_PLUGIN_BYTES = 8 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_plugin(name: str, manifest, cache_dir: Path) -> Path:
    """Fetch a plugin, trying R2/cloud sources first; fall back to bundle if offline."""
    meta = manifest.meta(name)
    if not meta or not manifest.is_deployable(name):
        raise ValueError("plugin is not deployable")
    expected = str(meta["sha256"]).lower()
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / name
    if cached.is_file() and sha256(cached) == expected:
        return cached

    # 1. Primary: Download from R2 / published cloud sources
    from .plugin_manifest import PLUGIN_SOURCES

    sources = []
    if getattr(manifest, "base_url", None):
        sources = [manifest.base_url]
    elif getattr(manifest, "use_network", True):
        sources = list(PLUGIN_SOURCES)

    for base in sources:
        url = f"{base.rstrip('/')}/{name}"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Uran/plugin-manager"})
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read(MAX_PLUGIN_BYTES + 1)
            if len(body) > MAX_PLUGIN_BYTES:
                continue
            if hashlib.sha256(body).hexdigest() != expected:
                continue
            temporary = cached.with_name(cached.name + ".tmp")
            temporary.write_bytes(body)
            os.replace(temporary, cached)
            return cached
        except Exception:
            continue

    # 2. Offline fallback: use the bundled copy if its hash matches
    bundled_dir = getattr(manifest, "bundled_dir", None)
    bundled = Path(bundled_dir) / name if bundled_dir else None
    if bundled and bundled.is_file() and sha256(bundled) == expected:
        return bundled
    raise OSError(f"Could not obtain verified plugin {name} from cloud or local fallback")


def _backup(path: Path, suffix: str = ".bak") -> Path:
    backup = path.with_name(path.name + suffix)
    index = 1
    while backup.exists():
        backup = path.with_name(path.name + f".uran-{index}{suffix}")
        index += 1
    return backup


def deploy_plugin(name: str, plugin_dirs, cache_dir: Path, manifest) -> dict:
    source = download_plugin(name, manifest, cache_dir)
    target = None
    for directory in map(Path, plugin_dirs):
        directory.mkdir(parents=True, exist_ok=True)
        candidate = directory / name
        if candidate.exists() and sha256(candidate) == manifest.meta(name)["sha256"]:
            target = candidate
            continue
        if candidate.exists():
            os.replace(candidate, _backup(candidate))
        temporary = candidate.with_name(candidate.name + ".tmp")
        temporary.write_bytes(source.read_bytes())
        os.replace(temporary, candidate)
        target = candidate

    if target is None:
        raise OSError("No SLSsteam plugin directory is available")

    if manifest.meta(name).get("category") == "interceptor":
        for directory in map(Path, plugin_dirs):
            for other in directory.glob("*.lua"):
                if other.name == name:
                    continue
                other_meta = manifest.meta(other.name)
                if other_meta and other_meta.get("category") == "interceptor":
                    os.replace(other, _backup(other, ".replaced.bak"))
    return {"ok": True, "filename": name, "path": str(target)}


def archive_retired(plugin_dirs, manifest) -> list:
    archived = []
    for directory in map(Path, plugin_dirs):
        if directory.is_dir():
            for name in manifest.retired:
                path = directory / name
                if path.exists():
                    os.replace(path, _backup(path, ".retired.bak"))
                    archived.append(str(path))
    return archived


def undeploy_plugin(name: str, plugin_dirs) -> dict:
    moved = []
    for directory in map(Path, plugin_dirs):
        path = Path(directory) / name
        if path.exists():
            os.replace(path, _backup(path, ".removed.bak"))
            moved.append(str(path))
    return {"ok": bool(moved), "filename": name, "archived": moved}
