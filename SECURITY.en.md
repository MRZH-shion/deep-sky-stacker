# Security policy

**Language: [中文](SECURITY.md) | English**

## Supported versions

| Version | Security fixes |
|---|---|
| Latest release / main | Yes |
| Anything older | No — please upgrade |

## Reporting a vulnerability

**Please do not post vulnerability details in a public issue.**

Use GitHub's private vulnerability reporting (repository → Security → Report a
vulnerability), or contact the maintainer directly.

Include:

- affected version and OS
- reproduction steps or a minimal input (for RAW/TIFF files a description of the
  characteristics is enough if you cannot share the file)
- impact: crash, memory corruption, arbitrary code execution, information disclosure

## Process

1. Acknowledged within 48 hours
2. Assessment, then a fix plan and an estimated timeline
3. Credit in the release notes after the fix ships (unless you ask to stay anonymous)

## Attack surface

| Area | Notes |
|---|---|
| RAW parsing | Handled by LibRaw (`raw_r.dll`); a crafted RAW can crash it — keep libraw current |
| TIFF / PNG input | `tifffile` and Pillow; mind the versions when processing files from others |
| Star databases | `np.load` on npz files; a malicious pickle can execute code. The npz files shipped here are plain arrays loaded with pickle disabled |
| CLI arguments | Paths and numbers only; paths are checked for existence |
| Packaged binary | PyInstaller's onefile mode extracts to a temp directory — mind the permissions of that location |

## Out of scope

- Crashes caused by corrupt source material (send a sample; we will improve the error
  message)
- Vulnerabilities inside third-party dependencies (report them upstream; we will pick up the
  fix)
