---
name: ai-metadata-cleaner
description: Clean local JPEG, PNG, TIFF, WebP, AVIF, HEIC, and HEIF images by removing embedded EXIF, GPS, IPTC, XMP, ICC, PNG generation parameters, Stable Diffusion metadata, and C2PA/JUMBF provenance. Use when Codex is asked to remove image metadata, AI signatures, prompts, seeds, generator tags, content credentials, or image provenance without uploading files.
---

# AI Metadata Cleaner

Use the bundled local `ai-clean` command for image cleanup. The implementation, tests, bootstrap scripts, and project configuration are included beside this file, so the skill can be cloned and used without a separate workspace repository. Process files locally, keep originals unchanged, verify every output independently, and report residual metadata instead of claiming an image is untraceable.

## Workflow

1. Run `scripts/run-image-metadata-cleaner.ps1` from this skill. It uses the bundled project root and only falls back to `METADATA_CLEANER_REPO` or a workspace checkout when the bundled runner is unavailable.
2. The runner creates an isolated Python environment and bootstraps the pinned ExifTool binary into a private cache.
3. Pass the user’s selected image or directory as the remaining arguments. Use the repository’s default `cleaned-ai` output unless the user supplies an explicit output path.
4. Add `--privacy-transform` only when the user requests a new binary encoding or file hash. This re-encodes in the same format; it does not defeat perceptual matching.
5. Read the JSON summary when automation or batch processing is requested. Report successful outputs, removed categories, verification status, warnings, and failed files.
6. Never upload images, overwrite originals, delete adjacent `.xmp`, `.json`, or `.c2pa` sidecars, or describe the result as anonymous or impossible to match.

## Cleanup Contract

- Supported image formats: JPEG, PNG, TIFF, WebP, AVIF, HEIC, and HEIF.
- Remove embedded EXIF/GPS, IPTC, XMP, ICC profiles, PNG text chunks, AI generation parameters, and C2PA/JUMBF data.
- Do not claim removal of pixel-level watermarks such as SynthID; metadata cleaning cannot verify or erase them.
- Treat verification as mandatory. A file is not successful if targeted metadata remains.
- Report file SHA-256 values when available. A changed file hash is not evidence that perceptual matching is impossible.
- Keep the scope to embedded metadata. External service records and adjacent sidecar files are out of scope.

If the bundled runner and configured fallback cannot be found, report the expected path and stop. If dependency bootstrap fails, report the exact failure and do not process images through a different tool.
