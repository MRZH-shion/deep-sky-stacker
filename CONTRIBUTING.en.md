# Contributing

**Language: [中文](CONTRIBUTING.md) | English**

Thanks for wanting to improve this project. Reading the four points below will save a
round trip.

## Before you open a pull request

```bash
# 1) syntax and static checks
python -m pyflakes src/astro_stack_gui.py tools/*.py
python -c "import ast; ast.parse(open('src/astro_stack_gui.py', encoding='utf-8').read())"

# 2) smoke test (no image data needed)
python src/astro_stack_gui.py --selftest
python src/astro_stack_gui.py --help
```

- Dependencies: `pip install -r requirements.txt`, plus
  `pip install git+https://github.com/esa/tetra3@master` (tetra3 is not on PyPI)
- The star databases are not in the repo; download from the Release page into `data/`.
  Without them everything runs, identification just reports "unknown"
- Do **not** hard-code local paths, drive letters or personal information
- Do **not** commit `gpu_runtime/` (NVIDIA libraries, proprietary), `*.exe`, RAW material

## Style

- Python 3.9+, four spaces, lines up to about 100 characters
- Keep the single-file layout (`src/astro_stack_gui.py`) — it is deliberate: PyInstaller
  packaging stays simple and users can copy one file
- Put new algorithms next to the related function and document the **meaning of each
  parameter** and **why the default is what it is**
- User-facing log lines are Chinese in this project, written for photographers rather than
  developers; if you add English messages, keep them consistent with the surrounding code

## Commit messages

```
<scope>: <what changed>
```

Scopes: `stack` / `register` / `bg` / `denoise` / `star` / `identify` / `gui` / `docs` /
`build`. For example:

```
denoise: add wavelet chroma denoise, luminance untouched
gui: fix overlapping controls in the options panel
```

## Adding a dependency

Update three places together, otherwise CI and the licence audit drift apart:

1. `requirements.txt`
2. `THIRD_PARTY_NOTICES.md` (component, version, licence, purpose, licence text path)
3. `LICENSES/` (full text, named like `foo-MIT.txt`)

GPL, AGPL and proprietary **runtime** dependencies are not accepted. Build-time tools are
fine (PyInstaller ships a bootloader exception).

## Data files

- `data/objects.json` is derived from OpenNGC and must stay CC BY-SA 4.0; it cannot be
  relicensed to MIT
- Star databases (`*.npz`) are produced by the scripts in `tools/`; include the command you
  used when you change their parameters

## Reporting a bug

Use the issue template and include: OS, Python version, stacking mode, the complete log
(`<output>.log`), and the smallest set of parameters that reproduces the problem. For image
quality issues attach a screenshot or a comparison image.

## Licence

Submitting a change means you agree to publish it under the project's MIT licence
(`data/objects.json` excepted — see `NOTICE.md`).
