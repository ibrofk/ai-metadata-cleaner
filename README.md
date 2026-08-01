# AI Metadata Cleaner

[![CI](https://github.com/ibrofk/ai-metadata-cleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/ibrofk/ai-metadata-cleaner/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

This repository contains a self-contained Codex skill and the local CLI runtime
it uses. It is a privacy-focused tool for viewing and removing metadata from
images, documents, audio, and video files. It writes cleaned copies by default,
keeps originals unchanged, and includes CLI, JSON automation, Docker, and a
local Web UI for side-by-side metadata checks.

## Codex Skill

The repository root is directly usable as a Codex skill because it includes:

- `SKILL.md` and `agents/openai.yaml` for Codex discovery and instructions.
- `scripts/run-image-metadata-cleaner.ps1` as the skill entry point.
- The complete Python implementation, tests, project configuration, and
  Windows bootstrap scripts.

Clone or copy this repository into a Codex skills directory, for example:

```powershell
Copy-Item -Recurse . "$env:USERPROFILE\.codex\skills\ai-metadata-cleaner"
```

The runner bootstraps an isolated environment and a pinned ExifTool release on
first use. It does not modify system packages or upload image files. This is a
derived work; see [NOTICE.md](NOTICE.md) for upstream attribution.

The `ai-clean` command is the image-focused path for removing embedded EXIF,
GPS, IPTC, XMP, ICC profiles, PNG generation parameters, and C2PA/JUMBF
provenance data. It performs an independent verification pass before reporting
success. It does not remove visible watermarks, pixel watermarks such as
SynthID, visual model artifacts,
external provenance records, or perceptual image matches.

## Highlights

- View metadata before cleaning.
- Remove metadata into separate cleaned copies.
- Compare original and cleaned metadata in a local-only Web UI.
- Process individual files or recursive folders.
- Generate machine-readable JSON reports for automation.
- Add SHA-256, SHA-512, or BLAKE2b checksums to reports.
- Preserve source timestamps on cleaned outputs when needed.
- Publish-ready CI coverage for Python, package smoke tests, Docker builds,
  CodeQL, and dependency audits.

## Supported Files

- Images: JPG, JPEG, PNG, TIFF, WEBP, AVIF, HEIC, HEIF
- Documents: PDF, DOCX, EPUB, ODT, TXT
- Audio: MP3, WAV, FLAC, OGG, AAC, M4A, WMA
- Video: MP4, MKV, MOV, AVI, WEBM, FLV

Some formats need system tools for best coverage:

- `ffmpeg` and `ffprobe` are required for video metadata handling.
- `exiftool` is required for AVIF, HEIC, and HEIF cleanup and improves image
  metadata coverage.
- The published Docker image includes these optional tools.

## Install

Requires Python 3.11 or newer.

```bash
pip install ai-metadata-cleaner
ai-metadata-cleaner --help
```

Use Docker when you want the optional system tools preinstalled:

```bash
docker run --rm -v "$(pwd):/data" ghcr.io/ibrofk/ai-metadata-cleaner:latest delete /data/photos
```

For development:

```bash
git clone https://github.com/ibrofk/ai-metadata-cleaner.git
cd ai-metadata-cleaner
poetry install --with dev
poetry run ai-metadata-cleaner --help
```

## Quick Start

View metadata:

```bash
ai-metadata-cleaner view sample.jpg
```

Clean one file:

```bash
ai-metadata-cleaner delete sample.jpg
```

By default, the cleaned copy is written under a `cleaned/` directory next to the
source file. To choose the output path:

```bash
ai-metadata-cleaner delete sample.jpg --output cleaned/sample.jpg
```

Preview a folder run without writing files:

```bash
ai-metadata-cleaner delete ./photos --dry-run
```

Clean a folder recursively:

```bash
ai-metadata-cleaner delete ./photos --output ./cleaned-photos
```

## AI Image Cleaning

Clean one image without modifying the original:

```bash
ai-metadata-cleaner ai-clean sample.jpg
```

The verified output is written under `cleaned-ai/`. Clean a folder recursively:

```bash
ai-metadata-cleaner ai-clean ./images --json-summary --summary-file reports/ai-clean.json
```

Force a same-format re-encode when a new binary file hash is required:

```bash
ai-metadata-cleaner ai-clean ./images --privacy-transform
```

`--privacy-transform` changes the file encoding but does not guarantee
protection against perceptual matching. Adjacent `.xmp`, `.json`, and `.c2pa`
sidecar files are never deleted.

On Windows, the Codex runner bootstraps the pinned ExifTool release into a
private local cache and verifies its SHA-256 checksum before use:

```powershell
.\scripts\run-ai-clean.ps1 .\images --json-summary
```

## Local Web UI

Start a single-page local Web UI:

```bash
ai-metadata-cleaner web
```

The Web UI binds to `127.0.0.1` by default, shows original metadata beside
cleaned-copy metadata, and lets you download cleaned files. The `Files` button
lists uploaded originals and cleaned copies from the current local session with
view and delete actions.

Temporary Web UI files are stored in a temporary directory unless you provide a
workspace:

```bash
ai-metadata-cleaner web --workspace ./ai-metadata-cleaner-workspace
```

## Automation

Print metadata as JSON:

```bash
ai-metadata-cleaner view sample.jpg --json
```

Write metadata JSON to a file:

```bash
ai-metadata-cleaner view sample.jpg --json-output reports/metadata.json
```

Write a delete summary report:

```bash
ai-metadata-cleaner delete ./photos --summary-file reports/summary.json
```

The shared `--json-output reports/summary.json` option writes the same delete
summary payload.

Add checksums:

```bash
ai-metadata-cleaner delete ./photos --summary-file reports/summary.json --checksums
ai-metadata-cleaner delete ./photos --json-summary --checksums --checksum-algorithm sha512
```

Use compact reports for large jobs:

```bash
ai-metadata-cleaner delete ./photos --json-summary --report-detail compact
ai-metadata-cleaner delete ./photos --json-summary --report-filter failed
```

Summary reports include per-file status, output paths, optional checksums,
failure reasons, and format-specific processing notes that explain whether a
handler copies, rewrites, re-saves, uses ExifTool, deletes audio tags, or remuxes
video with FFmpeg stream copy.

## Safety Model

- Originals are not modified by metadata removal.
- Handlers reject in-place cleanup where input and output paths are the same.
- EPUB and ODT ZIP packages are checked against archive safety limits before
  metadata XML is read or rewritten.
- ExifTool, FFmpeg, and FFprobe subprocess calls use bounded timeouts.
- Logs go to stderr by default; file logging is opt-in.
- The Web UI is local-only by default and scopes file viewing/deletion to its
  managed workspace.

This tool removes common metadata fields using format-specific libraries and
system tools. It is not a guarantee that every possible identifying byte,
watermark, hidden payload, or content-derived signal has been removed. For
high-risk publishing workflows, inspect outputs with independent tools before
release.

## Edit Metadata

Editing is available only where handlers support it, currently most useful for
audio files through Mutagen:

```bash
ai-metadata-cleaner edit song.mp3 --changes '{"artist": "Unknown"}'
```

Use metadata removal when you need a cleaned copy. Editing may modify the target
file in place.

## Development Checks

```bash
python3 manage.py test
python3 manage.py lint
python3 manage.py check
```

CI runs tests, lint, `pip-audit`, package smoke coverage, Docker builds, and
CodeQL on protected branches and pull requests.

## Resources

- [Usage Guide](https://github.com/ibrofk/ai-metadata-cleaner/blob/main/docs/USAGE.md)
- [API Reference](https://github.com/ibrofk/ai-metadata-cleaner/blob/main/docs/API_REFERENCE.md)
- [Architecture](https://github.com/ibrofk/ai-metadata-cleaner/blob/main/docs/ARCHITECTURE.md)
- [Maintenance And Security](https://github.com/ibrofk/ai-metadata-cleaner/blob/main/docs/MAINTENANCE.md)
- [Roadmap](https://github.com/ibrofk/ai-metadata-cleaner/blob/main/docs/PLANNED_FEATURES.md)
- [Release Notes](https://github.com/ibrofk/ai-metadata-cleaner/blob/main/RELEASE_NOTES.md)
- [Security Policy](https://github.com/ibrofk/ai-metadata-cleaner/blob/main/SECURITY.md)
- [Contributing](https://github.com/ibrofk/ai-metadata-cleaner/blob/main/CONTRIBUTING.md)
