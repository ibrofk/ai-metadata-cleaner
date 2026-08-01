"""Local, checksum-verified bootstrap for the image-cleaning toolchain."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


class ToolBootstrapError(RuntimeError):
    """Raised when a required native tool cannot be resolved safely."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    url: str
    sha256: str


# The archive is the official ExifTool project release mirrored by SourceForge.
# Keep this pinned: changing it requires updating the hash and reviewing the
# release notes before shipping a new skill version.
EXIFTOOL_SPEC = ToolSpec(
    name="exiftool",
    version="13.59",
    url="https://downloads.sourceforge.net/project/exiftool/exiftool-13.59_64.zip",
    sha256=("44b512b25af500724ba579d0a53c8fc5851628b692dd5e5d94ae4a15c2cba9ec"),
)


def _cache_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data)
    return Path(tempfile.gettempdir())


def exiftool_cache_dir() -> Path:
    return (
        _cache_root()
        / "Codex"
        / "tools"
        / "metadata-cleaner"
        / "exiftool"
        / EXIFTOOL_SPEC.version
    )


def _sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_executable(executable: Path) -> bool:
    try:
        result = subprocess.run(
            [str(executable), "-ver"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip().startswith(
        EXIFTOOL_SPEC.version
    )


def _cached_executable() -> Path | None:
    executable = exiftool_cache_dir() / "exiftool.exe"
    return (
        executable
        if executable.is_file() and _validate_executable(executable)
        else None
    )


def _write_manifest(cache_dir: Path, archive_hash: str) -> None:
    manifest = {
        "name": EXIFTOOL_SPEC.name,
        "version": EXIFTOOL_SPEC.version,
        "url": EXIFTOOL_SPEC.url,
        "sha256": archive_hash,
    }
    (cache_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def bootstrap_exiftool() -> Path:
    """Download, verify, extract, and validate the pinned Windows binary."""

    if platform.system().lower() != "windows":
        raise ToolBootstrapError(
            "Automatic ExifTool bootstrap currently supports Windows only. "
            "Install ExifTool and place it on PATH on this platform."
        )

    cache_dir = exiftool_cache_dir()
    cached = _cached_executable()
    if cached:
        return cached

    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="metadata-cleaner-", dir=cache_dir.parent
    ) as temp_dir:
        temp_root = Path(temp_dir)
        archive_path = temp_root / "exiftool.zip"
        try:
            with urllib.request.urlopen(EXIFTOOL_SPEC.url, timeout=120) as response:
                with archive_path.open("wb") as archive:
                    shutil.copyfileobj(response, archive)
        except Exception as exc:  # pragma: no cover - network-specific
            raise ToolBootstrapError(f"Failed to download ExifTool: {exc}") from exc

        actual_hash = _sha256(archive_path)
        if actual_hash.lower() != EXIFTOOL_SPEC.sha256.lower():
            raise ToolBootstrapError(
                "ExifTool checksum mismatch. "
                f"Expected {EXIFTOOL_SPEC.sha256}, got {actual_hash}."
            )

        extracted = temp_root / "extracted"
        extracted.mkdir()
        try:
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extracted)
        except (OSError, zipfile.BadZipFile) as exc:
            raise ToolBootstrapError(f"Failed to extract ExifTool: {exc}") from exc

        source_executable = next(extracted.rglob("exiftool(-k).exe"), None)
        source_files = next(extracted.rglob("exiftool_files"), None)
        if source_executable is None or source_files is None:
            raise ToolBootstrapError("The ExifTool archive has an unexpected layout.")

        install_dir = temp_root / "install"
        install_dir.mkdir()
        target_executable = install_dir / "exiftool.exe"
        shutil.copy2(source_executable, target_executable)
        shutil.copytree(source_files, install_dir / "exiftool_files")

        if not _validate_executable(target_executable):
            raise ToolBootstrapError(
                "The downloaded ExifTool executable failed validation."
            )

        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True)
        shutil.copy2(target_executable, cache_dir / "exiftool.exe")
        shutil.copytree(install_dir / "exiftool_files", cache_dir / "exiftool_files")
        _write_manifest(cache_dir, actual_hash)

    executable = _cached_executable()
    if executable is None:
        raise ToolBootstrapError("ExifTool was installed but could not be launched.")
    return executable


def resolve_exiftool(
    explicit_path: str | os.PathLike[str] | None = None,
    *,
    auto_bootstrap: bool = True,
) -> Path:
    """Resolve ExifTool from an explicit path, private cache, PATH, or bootstrap."""

    if explicit_path:
        candidate = Path(explicit_path).expanduser().resolve()
        if not candidate.is_file() or not _validate_executable(candidate):
            raise ToolBootstrapError(f"Invalid ExifTool executable: {candidate}")
        return candidate

    cached = _cached_executable()
    if cached:
        return cached

    system_executable = shutil.which("exiftool")
    if system_executable:
        return Path(system_executable).resolve()

    if auto_bootstrap:
        return bootstrap_exiftool()

    raise ToolBootstrapError(
        "ExifTool is required. Install it or run with automatic bootstrap enabled."
    )
