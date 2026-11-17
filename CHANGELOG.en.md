# Changelog

**Language: [中文](CHANGELOG.md) | English**

Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions
follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Bilingual interface (Chinese / English): dropdown at the top of the GUI switches live,
  `--lang zh|en` on the command line, choice stored in `settings.json`

- Chroma denoise: à trous wavelet, chrominance only (`--chroma-denoise`, light / medium /
  strong)
- Luminance denoise: à trous wavelet (`--denoise`)
- Fast resampling switch `--fast-warp` (bilinear, about 14% faster)
- JPG output parameters `--jpg-max` and `--jpg-quality`
- Star reduction / removal folded into the stacking run (`--star-mode reduce|remove` with
  `--star-strength`)
- Plate solving gained a fallback attempt: try the FOV hint first, then a wider star
  combination, so narrow fields succeed more often

### Changed

- JPG output resizes in float and dithers before quantising, removing 8-bit banding
- Automatic presets use the new chroma algorithm (mid 0.35, high 0.55)
- `--bg-poly` and `--bg-protect` now work on their own; previously only `--bg2d` enabled
  background removal
- Type-based tuning no longer silently re-enables the legacy Gaussian chroma filter

### Fixed

- `_write_stretched` referenced `self` inside a module-level function
- Star handling is skipped (and logged) when the mask covers more than 35% of the frame,
  instead of writing a useless starless image
- Removed dead code left over from earlier features

### Performance

- Background2D + structure protection: 16.4 s → 5.2 s at 24 MP
- Star mask: 11.9 s → 3.5 s
- Background2D mesh: 2.0 s → 0.6 s
- 20-frame end-to-end run: 81 s → 58 s
- 100-frame single-pass stack: 164 s → 153 s

## [1.0.0] — 2026-11

### Added

- Three stacking modes: two-pass (statistics then rejection), single-pass (online
  rejection), GPU (CuPy)
- Light / dark / flat import, automatic master dark and per-CFA-plane master flat
- Star detection, triangle-invariant matching, similarity-transform registration (shift,
  rotation, scale)
- Light pollution handling: per-frame removal, Background2D (mesh + structure protection),
  polynomial, RBF
- Automatic mode that grades light pollution as low / mid / high
- Object identification: blind solve against built-in Hipparcos databases, narrow (4°–8°)
  and medium (10°–30°)
- Type-based parameter tuning (cluster / nebula / galaxy / planetary nebula)
- Output: linear 16-bit TIFF, stretched 16-bit TIFF, 16-bit PNG, preview JPG, framed image
- GUI and CLI entry points, packagable into a single-file exe
