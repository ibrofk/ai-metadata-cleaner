"""Deep, local-only image metadata and provenance cleaning."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from m_c.core.file_utils import get_file_checksum
from m_c.core.tool_bootstrap import ToolBootstrapError, resolve_exiftool

AI_IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".avif", ".heic", ".heif"}
)

_PIL_FORMATS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".webp": "WEBP",
    ".avif": "AVIF",
    ".heic": "HEIF",
    ".heif": "HEIF",
}

_PNG_STRUCTURAL_KEYS = {
    "bitdepth",
    "colortype",
    "compression",
    "filter",
    "filesize",
    "imageheight",
    "imagelength",
    "imagesize",
    "imagewidth",
    "interlace",
    "megapixels",
}

_TIFF_STRUCTURAL_KEYS = {
    "bitspersample",
    "compression",
    "documentname",
    "imagelength",
    "imagewidth",
    "photometricinterpretation",
    "planarconfiguration",
    "rowsperstrip",
    "samplesperpixel",
    "stripbytecounts",
    "stripoffsets",
    "subfiletype",
    "tilebytecounts",
    "tilelength",
    "tileoffsets",
    "tiledimensions",
}

_WEBP_IMAGE_CHUNKS = {
    "alph",
    "anmf",
    "anim",
    "vp8 ",
    "vp8l",
    "vp8x",
}

_PNG_IMAGE_CHUNKS = {
    "acTL",
    "fdAT",
    "fcTL",
    "IDAT",
    "IHDR",
    "IEND",
    "PLTE",
    "tRNS",
}


class AIImageCleanerError(RuntimeError):
    """Raised when an image cannot be safely cleaned and verified."""


@dataclass
class ImageProperties:
    format: str | None = None
    width: int | None = None
    height: int | None = None
    mode: str | None = None
    has_alpha: bool | None = None
    frame_count: int | None = None


@dataclass
class MetadataInspection:
    categories: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    raw_findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationResult:
    ok: bool
    remaining_categories: list[str] = field(default_factory=list)
    remaining_findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CleanResult:
    input: str
    output: str
    format: str | None
    cleanup_method: str
    removed_categories: list[str]
    before: ImageProperties
    after: ImageProperties
    verification: VerificationResult
    checksums: dict[str, str | None]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "output": self.output,
            "format": self.format,
            "cleanup_method": self.cleanup_method,
            "removed_categories": self.removed_categories,
            "properties": {
                "before": asdict(self.before),
                "after": asdict(self.after),
            },
            "verification": self.verification.to_dict(),
            "checksums": self.checksums,
            "warnings": self.warnings,
        }


def is_ai_image(path: str | os.PathLike[str]) -> bool:
    return Path(path).suffix.lower() in AI_IMAGE_EXTENSIONS


def collect_ai_images(path: str | os.PathLike[str]) -> list[str]:
    """Collect image inputs while excluding generated cleaned-ai outputs."""

    root = Path(path)
    if root.is_file():
        return [str(root)] if is_ai_image(root) else []
    if not root.is_dir():
        return []

    output_dir = (root / "cleaned-ai").resolve()
    files: list[str] = []
    for current_root, dirs, names in os.walk(root):
        current_path = Path(current_root).resolve()
        dirs[:] = [
            name for name in dirs if (current_path / name).resolve() != output_dir
        ]
        for name in names:
            candidate = current_path / name
            if is_ai_image(candidate):
                files.append(str(candidate))
    return sorted(files)


def _run_exiftool(
    exiftool: Path,
    arguments: list[str],
    *,
    timeout_seconds: int = 120,
) -> str:
    try:
        result = subprocess.run(
            [str(exiftool), *arguments],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AIImageCleanerError(
            f"ExifTool timed out after {timeout_seconds} seconds."
        ) from exc
    except OSError as exc:
        raise AIImageCleanerError(f"Could not launch ExifTool: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise AIImageCleanerError(f"ExifTool failed: {detail}")
    return result.stdout


def _iter_leaf_paths(
    value: Any, prefix: tuple[str, ...] = ()
) -> Iterable[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _iter_leaf_paths(child, prefix + (str(key),))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_leaf_paths(child, prefix + (str(index),))
    else:
        yield prefix, value


def _category_for_path(path: tuple[str, ...]) -> str | None:
    if not path:
        return None
    lowered = [part.lower() for part in path]
    joined = " ".join(lowered)
    group = lowered[0]
    key = lowered[-1]

    ai_tokens = (
        "prompt",
        "negative",
        "seed",
        "cfg",
        "sampler",
        "modelhash",
        "model hash",
        "workflow",
        "parameters",
        "generation",
        "generator",
    )
    if any(token in joined for token in ai_tokens):
        return "ai_generation_parameters"

    if group in {"file", "composite", "system"}:
        return None
    if "jumbf" in joined or "c2pa" in joined:
        return "c2pa_jumbf"
    if "icc" in joined or "colorprofile" in joined:
        return "icc_profile"
    if "gps" in joined:
        return "gps"
    if "iptc" in joined or "photoshop" in joined:
        return "iptc_photoshop"
    if "xmp" in joined:
        return "xmp"
    if group in {
        "exif",
        "exififd",
        "ifd0",
        "ifd1",
        "subifd",
        "interoperability",
        "makernotes",
    }:
        if group in {"ifd0", "ifd1", "subifd"} and key in _TIFF_STRUCTURAL_KEYS:
            return None
        return "exif"
    if group.startswith("app") or "comment" in joined:
        return "container_metadata"
    if group == "png":
        if key in _PNG_STRUCTURAL_KEYS:
            return None
        return "png_metadata"

    return None


def _parse_exiftool_json(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AIImageCleanerError("ExifTool returned invalid JSON.") from exc
    if isinstance(payload, list):
        return payload[0] if payload else {}
    return payload if isinstance(payload, dict) else {}


def _inspect_metadata(exiftool: Path, path: Path) -> MetadataInspection:
    stdout = _run_exiftool(
        exiftool,
        ["-json", "-a", "-u", "-g1", "-s", "-jumbf:all", str(path)],
    )
    payload = _parse_exiftool_json(stdout)
    categories: set[str] = set()
    groups: set[str] = set()
    for leaf_path, value in _iter_leaf_paths(payload):
        if value in (None, "", [], {}):
            continue
        if leaf_path:
            groups.add(leaf_path[0])
        category = _category_for_path(leaf_path)
        if category:
            categories.add(category)

    raw_findings: list[str] = []
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        raw_findings.extend(_scan_jpeg_segments(path))
    elif path.suffix.lower() == ".png":
        raw_findings.extend(_scan_png_chunks(path))
    elif path.suffix.lower() == ".webp":
        raw_findings.extend(_scan_webp_chunks(path))

    if raw_findings:
        categories.add("container_metadata")
    return MetadataInspection(
        categories=sorted(categories),
        groups=sorted(groups),
        raw_findings=sorted(set(raw_findings)),
    )


def _scan_jpeg_segments(path: Path) -> list[str]:
    findings: list[str] = []
    data = path.read_bytes()
    if not data.startswith(b"\xff\xd8"):
        return ["invalid_jpeg_signature"]

    index = 2
    while index < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            break
        marker = data[index]
        index += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xDA:
            break
        if index + 2 > len(data):
            findings.append("truncated_jpeg_segment")
            break
        segment_length = int.from_bytes(data[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            findings.append("truncated_jpeg_segment")
            break
        payload = data[index + 2 : index + segment_length]
        if 0xE0 <= marker <= 0xEF:
            if marker == 0xE0 and payload.startswith(b"JFIF"):
                pass
            else:
                findings.append(f"jpeg_app:{marker - 0xE0:02d}")
        elif marker == 0xFE:
            findings.append("jpeg_comment")
        index += segment_length
    return findings


def _scan_png_chunks(path: Path) -> list[str]:
    findings: list[str] = []
    with path.open("rb") as stream:
        signature = stream.read(8)
        if signature != b"\x89PNG\r\n\x1a\n":
            return ["invalid_png_signature"]
        while True:
            header = stream.read(8)
            if not header:
                break
            if len(header) != 8:
                return ["truncated_png_chunk_header"]
            length = int.from_bytes(header[:4], "big")
            chunk_type = header[4:].decode("latin-1")
            stream.seek(length + 4, os.SEEK_CUR)
            if chunk_type not in _PNG_IMAGE_CHUNKS:
                findings.append(f"png_chunk:{chunk_type}")
            if chunk_type == "IEND":
                break
    return findings


def _scan_webp_chunks(path: Path) -> list[str]:
    findings: list[str] = []
    with path.open("rb") as stream:
        header = stream.read(12)
        if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WEBP":
            return ["invalid_webp_signature"]
        while True:
            chunk_header = stream.read(8)
            if not chunk_header:
                break
            if len(chunk_header) != 8:
                return ["truncated_webp_chunk_header"]
            chunk_type = chunk_header[:4].decode("latin-1")
            length = int.from_bytes(chunk_header[4:], "little")
            stream.seek(length + (length % 2), os.SEEK_CUR)
            if chunk_type.lower() not in _WEBP_IMAGE_CHUNKS:
                findings.append(f"webp_chunk:{chunk_type}")
    return findings


def _read_properties(path: Path) -> ImageProperties:
    try:
        with Image.open(path) as image:
            mode = image.mode
            has_alpha = "A" in image.getbands() or (
                mode == "P" and "transparency" in image.info
            )
            return ImageProperties(
                format=image.format or _PIL_FORMATS.get(path.suffix.lower()),
                width=image.width,
                height=image.height,
                mode=mode,
                has_alpha=has_alpha,
                frame_count=getattr(image, "n_frames", 1),
            )
    except Exception:
        return ImageProperties(format=_PIL_FORMATS.get(path.suffix.lower()))


def _format_for_path(path: Path) -> str:
    format_name = _PIL_FORMATS.get(path.suffix.lower())
    if not format_name:
        raise AIImageCleanerError(f"Unsupported image format: {path.suffix}")
    return format_name


def _clear_frame_info(frame: Image.Image) -> Image.Image:
    frame.info.clear()
    return frame


def _reencode_same_format(path: Path) -> None:
    format_name = _format_for_path(path)
    temp_name: str | None = None
    try:
        with Image.open(path) as image:
            frame_count = getattr(image, "n_frames", 1)
            if frame_count > 1 and format_name not in {"PNG", "TIFF", "WEBP"}:
                raise AIImageCleanerError(
                    f"Privacy transform does not support animated {format_name} files."
                )

            frames: list[Image.Image] = []
            durations: list[int] = []
            for index in range(frame_count):
                image.seek(index)
                duration = image.info.get("duration")
                durations.append(int(duration) if duration is not None else 100)
                frames.append(_clear_frame_info(image.copy()))

            if not frames:
                raise AIImageCleanerError("Image contains no decodable frames.")

            save_format = format_name
            save_kwargs: dict[str, Any] = {}
            first = frames[0]
            if save_format == "JPEG":
                frames = [
                    (
                        frame.convert("RGB")
                        if frame.mode not in {"L", "RGB", "CMYK"}
                        else frame
                    )
                    for frame in frames
                ]
                save_kwargs.update(quality=95, optimize=True, progressive=False)
            elif save_format == "PNG":
                save_kwargs.update(optimize=True, compress_level=9)
            elif save_format == "WEBP":
                save_kwargs.update(quality=95, method=6)
            elif save_format == "TIFF":
                save_kwargs.update(compression="tiff_lzw")
            elif save_format in {"AVIF", "HEIF"}:
                save_kwargs.update()
            else:
                raise AIImageCleanerError(f"Cannot re-encode {save_format} safely.")

            if (
                first.mode == "P"
                and "transparency" in image.info
                and save_format == "PNG"
            ):
                save_kwargs["transparency"] = image.info["transparency"]

            with tempfile.NamedTemporaryFile(
                prefix=".ai-clean-",
                suffix=path.suffix,
                dir=path.parent,
                delete=False,
            ) as temporary:
                temp_name = temporary.name

            if frame_count > 1:
                save_kwargs.update(
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=int(image.info.get("loop", 0)),
                )
            first.save(temp_name, format=save_format, **save_kwargs)
        os.replace(temp_name, path)
        temp_name = None
    except (OSError, ValueError) as exc:
        raise AIImageCleanerError(f"Could not re-encode {path.name}: {exc}") from exc
    finally:
        if temp_name and os.path.exists(temp_name):
            os.remove(temp_name)


class AIImageCleaner:
    """Clean and independently verify embedded image metadata."""

    def __init__(
        self,
        exiftool_path: str | os.PathLike[str] | None = None,
        *,
        auto_bootstrap: bool = True,
    ) -> None:
        try:
            self.exiftool = resolve_exiftool(
                exiftool_path,
                auto_bootstrap=auto_bootstrap,
            )
        except ToolBootstrapError as exc:
            raise AIImageCleanerError(str(exc)) from exc

    def inspect(self, path: str | os.PathLike[str]) -> MetadataInspection:
        image_path = Path(path)
        if not is_ai_image(image_path):
            raise AIImageCleanerError(f"Unsupported image format: {image_path.suffix}")
        return _inspect_metadata(self.exiftool, image_path)

    def verify(self, path: str | os.PathLike[str]) -> VerificationResult:
        inspection = self.inspect(path)
        return VerificationResult(
            ok=not inspection.categories and not inspection.raw_findings,
            remaining_categories=inspection.categories,
            remaining_findings=inspection.raw_findings,
        )

    def _strip(self, output_path: Path) -> None:
        _run_exiftool(
            self.exiftool,
            [
                "-all=",
                "-jumbf:all=",
                "-icc_profile:all=",
                "-overwrite_original",
                str(output_path),
            ],
        )

    def clean(
        self,
        source: str | os.PathLike[str],
        output: str | os.PathLike[str],
        *,
        privacy_transform: bool = False,
    ) -> CleanResult:
        source_path = Path(source).resolve()
        output_path = Path(output).resolve()
        if not source_path.is_file():
            raise AIImageCleanerError(f"Input file does not exist: {source_path}")
        if not is_ai_image(source_path):
            raise AIImageCleanerError(f"Unsupported image format: {source_path.suffix}")
        if source_path == output_path:
            raise AIImageCleanerError("Output path must differ from the input path.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        before_properties = _read_properties(source_path)
        before_metadata = self.inspect(source_path)
        shutil.copyfile(source_path, output_path)
        method = "exiftool"
        warnings: list[str] = []

        try:
            self._strip(output_path)
            verification = self.verify(output_path)
            if not verification.ok and not privacy_transform:
                _reencode_same_format(output_path)
                self._strip(output_path)
                method = "exiftool+reencode-fallback"
                verification = self.verify(output_path)
            elif privacy_transform:
                _reencode_same_format(output_path)
                self._strip(output_path)
                method = "exiftool+reencode"
                verification = self.verify(output_path)

            if not verification.ok:
                raise AIImageCleanerError(
                    "Verification failed: "
                    + ", ".join(
                        verification.remaining_categories
                        + verification.remaining_findings
                    )
                )
        except Exception:
            if output_path.exists():
                output_path.unlink()
            raise

        after_properties = _read_properties(output_path)
        if (
            before_properties.width is not None
            and after_properties.width is not None
            and before_properties.width != after_properties.width
        ):
            warnings.append("Output width changed during cleanup.")
        if (
            before_properties.height is not None
            and after_properties.height is not None
            and before_properties.height != after_properties.height
        ):
            warnings.append("Output height changed during cleanup.")
        if (
            before_properties.frame_count is not None
            and after_properties.frame_count is not None
            and before_properties.frame_count != after_properties.frame_count
        ):
            raise AIImageCleanerError("Cleanup changed the image frame count.")

        removed_categories = sorted(
            set(before_metadata.categories) - set(verification.remaining_categories)
        )
        return CleanResult(
            input=str(source_path),
            output=str(output_path),
            format=before_properties.format or source_path.suffix.lower().lstrip("."),
            cleanup_method=method,
            removed_categories=removed_categories,
            before=before_properties,
            after=after_properties,
            verification=verification,
            checksums={
                "input_sha256": get_file_checksum(str(source_path), "sha256"),
                "output_sha256": get_file_checksum(str(output_path), "sha256"),
            },
            warnings=warnings,
        )
