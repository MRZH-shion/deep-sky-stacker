# Deep-Sky Stacker — manual

English manual. The Chinese original is [`使用说明.txt`](使用说明.txt).

## Contents

1. [What the program does](#1-what-the-program-does)
2. [Quick start](#2-quick-start)
3. [Inputs: lights, darks, flats](#3-inputs-lights-darks-flats)
4. [Core parameters](#4-core-parameters)
5. [Output options](#5-output-options)
6. [Light pollution](#6-light-pollution)
7. [Object identification](#7-object-identification)
8. [Post-processing](#8-post-processing)
9. [Output files and pedestal](#9-output-files-and-pedestal)
10. [CLI reference](#10-cli-reference)
11. [FAQ](#11-faq)
12. [Recommended presets](#12-recommended-presets)

---

## 1. What the program does

Takes a batch of RAW lights (optionally with darks and flats), aligns them, rejects
outliers, and stacks them into a low-noise linear 16-bit TIFF. Optionally removes light
pollution, denoises, writes previews, and identifies the object.

```
RAW decode → master dark → master flat → star detection → registration
→ stacking (three modes) → demosaic → crop to common area
→ background removal → denoise → save (with pedestal)
→ preview → object identification
```

The TIFF is **linear data**: no stretch, no colour calibration, no gamma. It looks almost
black in any viewer. That is intentional — all the information is still there.

## 2. Quick start

GUI:

1. Run `DeepSkyStacker.exe`
2. Lights folder: the directory with your ARWs
3. Dark / flat folders: optional
4. Stacking mode: leave on auto (uses GPU when `gpu_runtime` is present)
5. Press **Start**
6. Result lands in `output\` next to the program, named after the start time

CLI:

```
DeepSkyStacker_CLI.exe --cli --lights "D:\lights" --darks "D:\darks" --flats "D:\flats" --threads 8
```

**Interface language.** The dropdown at the top of the window switches Chinese and English
live; the choice is stored in `settings.json` next to the program and reused next launch.
On the command line use `--lang zh|en`, which also switches the log output and `--help`.

## 3. Inputs: lights, darks, flats

**Lights** — your target frames. Files whose names contain `dark`, `flat` or `bias` are
excluded; everything else is treated as a light. Frames are sorted by EXIF capture time so
the alignment order is stable.

**Darks** — same ISO, exposure and temperature as the lights, lens cap on. Removes fixed
pattern noise, hot pixels and dark current. Without them the background shows fixed
horizontal/vertical banding and isolated bright pixels, more visible the more frames you
stack. 20–50 are enough; the tool averages them with 4σ clipping.

**Flats** — shot against a uniform source, same aperture and focus as the lights. Removes
vignetting, dust shadows and pixel response differences. This is the single biggest factor
for how the final image looks: with flats the background is even and the corners are not
dark; without them you get dark corners, a bright centre, and background-removal algorithms
start treating large areas as light pollution. 20–50 are enough. The tool normalises flats
per CFA plane — skip that and colours get flattened.

**Mixed folders** — filtering is by filename only, so a test frame called `DSC00001` will be
treated as a light. Keep the three kinds in separate folders.

## 4. Core parameters

**κ (sigma rejection factor, default 3.0)** — per pixel, frames deviating from the running
mean by more than κ·σ are dropped. Removes satellite trails, aircraft, birds, clouds, cosmic
rays, hot pixels. Small κ (2.0–2.5) is aggressive and can eat faint signal; large κ (4.0–5.0)
is conservative and may leave artefacts. Use 2.5–3.0 with more than 200 frames, 3.5–4.0 with
fewer than 30.

**Threads (default: half the CPU cores)** — parallel RAW decode and resampling. In CPU mode
setting it near the physical core count is best; beyond that memory bandwidth limits you. In
GPU mode it only controls decode prefetch. Speed only, no effect on image quality.

**Stacking mode**

- Two-pass: first pass collects per-pixel mean/σ, second pass rejects by κσ. Most
  conservative, decodes and resamples every frame twice, slowest.
- Single-pass: one pass, rejects against the running mean/σ. About 1.5× faster; measured
  difference from two-pass is 0.4 ADU at σ≈100.
- GPU: single-pass, resampling and accumulation on the graphics card (hand-written
  Catmull-Rom). 2–4× faster, more so with many frames; noise about 7% lower.

All three give equivalent images; only speed differs. The GPU entry disappears when no
GPU is detected.

**Quality weighting (default on)** — stacking is not a plain average: every frame gets a
weight from its star count, background noise and star sharpness, normalised to mean 1 (the log
prints the range). Weaker frames are pushed down, to at most a quarter weight. `--no-weight`
turns it off.

**Local normalisation (default on, `--no-ln` to disable)** — block medians from the central
70% of the frame are fitted against the reference; gain is clamped to 1+/-8% and changes under
1% are skipped. Measured over 300 frames: background σ 11.249 -> 10.989 (-2.3%) for 2.7% more
runtime. GPU stacking applies weights only.

**Threads (default 0 = auto)** — derived from image size and available memory: one stacking
thread for a 6000x4000 frame needs about 0.45 GB and the count is capped to the memory budget
(55% of free RAM). `--threads N` fixes it, `--mem-gb G` changes the budget.

**Colour calibration (default off)** — background neutralisation: per-channel gains from
background percentiles pull the sky to neutral grey. On our Orion data G/R went from 1.12 to
1.01 and G/B from 1.08 to 1.01. Gains are clamped to 0.5-2x, so no negatives. `--color-cal`.

**Drag and drop** — with `tkinterdnd2` installed, folders or files can be dropped onto the
lights/darks/flats/output fields. Without it everything works, just without the shortcut.

**Staged progress** — the progress line shows the stage and an ETA, e.g.
`[stack] 120/1050 · ETA 8:32`. Stages: decode → star detection → register → stack → post.

**Fast resampling (default off, `--fast-warp`)** — cubic interpolation is the default;
enabling this switches to bilinear. Measured on 60 frames: 126.5 s → 111.1 s (14% faster),
at the cost of softer stars (median star area 8.0 → 9.0 px) and slightly lower noise
(σ 9.36 → 7.50, bilinear acts as a low-pass). Leave it off if star sharpness matters.

## 5. Output options

**Crop to common coverage (default on)** — frames rotate and shift, so edges show black
corners or misalignment. On: keep only the area covered by every frame (e.g. 6048×4024 →
5240×3200). Off: larger canvas with black or semi-transparent edges.

**White-balanced TIFF (default off)** — multiplies by the camera white balance gains
(roughly R×2.6, B×1.8). On: colours look normal in viewers, still dark because the data is
linear. Off: raw camera RGB, green dominant, looks strongly green. Gains only, no colour
matrix (a matrix crushes shadows into colour casts).

**What to write (default: linear + stretched)**

- Linear + stretched: both `<time>.tif` and `<time>_stretched.tif`
- Linear only: just `<time>.tif`, the most complete file for post-processing
- Stretched only: just `<time>_stretched.tif`, viewable straight away

CLI: `--out-kind both|linear|stretch`. The old `--no-stretch-out` still works and equals
`--out-kind linear`.

Linear is untouched data — use it for curves, star removal, composites. Stretched applies
white balance, a 64× lift, per-channel background removal, asinh and +18 saturation, in
16 bit, ready to look at. Saturation is adjustable with `--stretch-sat` (1.0 = no boost).

**Extra 16-bit PNG preview (default off)** — a full-resolution, lossless, 16-bit colour PNG
on top of the JPG preview. Gives you more bit depth for post-processing; costs 30–60 MB and
a few seconds.

**Where files go** — leave the output box empty and files go to `output\` next to the
program, named after the stack start time (`YYMMDD_HHMM.tif`), with `_2`, `_3` appended on
collision. Alongside it you get `<time>_preview.jpg`, `<time>_preview.png` (optional),
`<time>_object.txt` and `<time>.log`.

## 6. Light pollution

This is the longest section because light pollution is the main enemy of urban deep-sky
work. Start with the automatic mode and only go manual if you are unhappy.

### Automatic grading (the dropdown, recommended)

- **Auto**: samples three frames, measures background level and gradient, picks a level
- **Low** (suburban / dark site)
- **Mid** (outskirts)
- **High** (city)
- **Manual**: the checkboxes below become active

With the first four the program applies a preset and logs its decision, e.g.

```
light pollution level: high (background median 1678, plane gradient 1433, score 2.53)
level high -> per-frame LP removal + Background2D aggressive(q=30) + structure protection + chroma denoise 3
```

The three presets:

| Level | Settings |
|---|---|
| Low | Background2D(q=40) + structure protection, no per-frame LP removal |
| Mid | Background2D(q=35) + structure protection + chroma denoise 0.35 |
| High | per-frame LP removal + Background2D(q=30) + structure protection + chroma 0.55 + luminance denoise 0.45 |

`q` is the background floor percentile: lower removes more. On the M42 data a q of 45 still
left a halo around the core, 40 was clean, and heavy light pollution needs 30.

One extra rule: **without flats the level is bumped up one step** (low→mid, mid→high),
because vignetting cannot be calibrated away and has to be handled by more aggressive
background removal.

Auto grading samples the first three frames, measures the background median and the
gradient after a plane fit, then scores as `median/1000 + relative gradient`; below 0.8 is
low, below 1.8 mid, otherwise high. Measured: M42 (2016, with flats) 0.55 → low; ISO100
Milky Way 1.28 → mid; ISO400 Milky Way 2.53 → high.

CLI: `--lp-level auto|low|mid|high|manual` (default `manual` to keep old scripts unchanged).

### Type-based tuning (default on)

Once the object is identified, its type refines the background settings:

| Type | Adjustment |
|---|---|
| Cluster | Structure protection off, Background2D(q=45), no denoise — all point sources, nothing large-scale to protect |
| Nebula | Structure protection on, Background2D(q=40), chroma 0.35 — extended soft glow is easily mistaken for light pollution |
| Galaxy | Structure protection on, Background2D(q=50), no per-frame LP, no denoise — faint outer envelope has low surface brightness |
| Planetary nebula | Structure protection on, Background2D(q=50), no denoise — colour is the main feature |

Order: LP preset first, then type overrides. Exception: when the LP level is high, type
tuning will not raise `q`.

### Field-of-view check

Before type tuning the program computes the diagonal field and only applies tuning if it
falls within the star database coverage. FOV sources, in priority order:

1. EXIF 35 mm equivalent focal length (0xA405) — independent of sensor size, most reliable
2. EXIF focal length (0x920A) + FocalPlaneXResolution (0xA20E) → sensor size → true FOV
3. EXIF focal length assuming APS-C (fallback)
4. The FOV from the plate solve, when identification succeeded

Log lines look like:

```
FOV 5.5° (EXIF), database coverage 4.0°~30.0° -> in range
FOV outside database range, skipping type tuning (use manual object to force)
```

Setting the object manually **skips the FOV check** (`target set manually, skipping FOV
check`), because you already told the program what it is — that is how narrow fields such as
5.4° at 300 mm get type tuning.

Format matrix:

| Situation | Behaviour |
|---|---|
| Auto ID + EXIF FOV | Judge by EXIF, skip when out of range |
| Auto ID + no EXIF | Judge by the solved FOV |
| Auto ID + neither | Tune anyway, log says "no FOV information" |
| Manual object | Skip the check, tune directly |

Turn it off by unchecking the box or with `--no-type-opt`.

### Manual mode parameters

Rules of thumb:

- Heavy light pollution, no flats (urban Milky Way): per-frame LP removal + Background2D + structure protection
- With flats and an already flat background (small deep-sky target): Background2D only, or nothing
- Slight gradient: polynomial of degree 2

**Per-frame LP removal `--lp`** — fits and subtracts a background from each of the four CFA
planes in every frame before registration. Light pollution and vignetting are fixed in
sensor coordinates, so subtracting per frame is more accurate than subtracting afterwards
and will not carve out the Milky Way. Benefits: strong gradients and corner vignetting are
flattened, especially effective on untracked rotating sequences. Cost: 0.5–0.8 s per frame
(about 5 minutes over 500 frames). Note that subtraction produces negative pixels; the
program adds a pedestal on save (section 9), so shadow detail survives. Skip it when you
have flats and an already clean background — it can over-correct.

**`--lp-div`** — divide by the background plane instead of subtracting, for purely
multiplicative vignetting. Subtraction measured better on our data and is the default.

**Background2D `--bg2d` (default on)** — after stacking and demosaicing, per channel: split
into a mesh (about 20×28 blocks) → take a background floor percentile per block → median
filter → cubic interpolation into a smooth background plane → subtract. Removes medium and
large-scale sky gradients (LP dome, moonlight, thin cloud); lowers the overall level a
little. `q` (floor percentile, default 40): 20–35 is aggressive and can eat large-scale
nebulosity; 50–60 is conservative and leaves more light pollution. Being a mesh method it
handles steep LP domes well and needs no model file.

**Structure protection `--bg-protect` (default on)** — fits a background once, finds regions
clearly above the model (nebulae, Milky Way core), excludes them from the sample, refits, and
repeats two or three times. Strongly reduces "Milky Way subtracted as light pollution", which
was the main cause of detail loss in early versions. Cost: Background2D becomes 2–4× slower.
Leave it on for nebulae and the Milky Way, off for plain star fields and clusters.

**RBF background `--rbf [smoothing]` (default off)** — thin-plate spline background, similar
to Siril's RBF interpolation. Very smooth, but per-channel fitting can leave colour blotches
in bright areas; better for gentle gradients than heavy light pollution. **Mutually exclusive
with Background2D** — if Background2D is on, RBF is skipped (and logged), so the two do not
stack and flatten the nebula.

**Polynomial surface `--bg-poly N` (default off)** — fits a 2D polynomial: 1 = plane (pure
linear gradient), 2–4 = curved. Very gentle, never carves structure, but cannot follow a
steep LP dome and leaves a bright patch on heavy light pollution. Good for dated deep-sky
frames with slight tilt.

**Legacy flatten `--flatten` (default off)** — old algorithm: heavy blur for the background,
then subtract. Removes large-scale Milky Way structure; superseded by Background2D, kept for
old workflows.

**Chroma denoise `--chroma-denoise` (default off)** — "Chroma denoise" dropdown: off / light /
medium / strong. CLI: `--chroma-denoise off|light|medium|strong`, `--chroma-scales 3`.

Chrominance only, luminance untouched: split into Y and three colour differences, run an
à trous wavelet denoise on each colour plane, recombine. Chroma noise is a low-frequency,
blotchy error, so a multi-scale threshold removes it without touching star sharpness. Colour
planes are denoised at half resolution then upsampled — about 4× faster and effectively
lossless for this kind of noise.

Strength: light 0.35, medium 0.55, strong 0.75. On 40 ISO400 Milky Way frames chroma σ fell
from 14.05 to 7.53 (medium); the old Gaussian blur (σ=2) only reached 8.88 and smeared colour
detail.

The old algorithm remains available as `--chroma-nr 2..4` (Gaussian blur on chroma); when both
are given the new one wins.

When to use: heavy light pollution, few frames, red/green speckle after stretching → medium or
strong. Only a little colour noise to suppress, keep star colours → light. Planetary nebulae
and colourful double stars (where colour *is* the subject) → skip.

**Luminance denoise `--denoise` (default off)** — same dropdown style. CLI:
`--denoise off|light|medium|strong`, `--denoise-scales 4`.

À trous (starlet) wavelet denoise: B3-spline decomposition into four scales, per-scale noise
σ from the MAD, soft threshold `k·σ·strength` (k=3) on small coefficients. Stars and nebula
edges are large coefficients and stay put, so denoising does not blur stars.

Luminance only; chroma is handled above.
Strength: light 0.30, medium 0.50, strong 0.70. On 20 Orion frames at 24 MP background σ fell
from 21.5 to 8.2 (medium) and 6.7 (strong), star area stayed at 9.0 px and peaks dropped only
1–4%, about 2.5 s extra per image.

Few frames (<50), high ISO, visible noise after stretching → medium is the sweet spot. Strong
smooths shadow detail; more than 200 frames are already quiet, use light or nothing. The
automatic presets already include it: low = off, mid = 0.30, high = 0.45.

**All manual controls**

```
per-frame LP [on]   mode [subtract/divide]
Background2D [on]  q [40]
structure protection [on]
chroma denoise [off]   luminance denoise [off]   polynomial degree [0]   RBF smoothing [0]
```

Corresponding flags: `--lp` / `--lp-div`, `--bg2d` / `--bg2d-q`, `--bg-protect`,
`--chroma-nr` / `--chroma-denoise` / `--denoise`, `--bg-poly`, `--rbf`.

## 7. Object identification

**Auto (default on)** — blind solve with the built-in tetra3 databases to get RA/Dec, FOV and
rotation, then look the position up in a 278-object Messier/NGC/IC catalogue. Written to
`_object.txt`. Two databases ship: narrow 4°–8°, medium 10°–30°. Narrow fields automatically
use a small-field centroid algorithm and try the first, middle and last frames, so a single
bad frame does not stop identification. Only the name is affected, never the pixels.

Failure is usually a field outside the database coverage, or too few stars, trailed stars or
thin cloud; the object then shows as unknown.

**Manual** — pick a name directly; it overrides auto identification and skips the FOV check.
Use it for narrow fields or when solving fails.

**Identify a single frame** — the GUI button that identifies one image or RAW without
stacking. It asks for sensor, crop factor, focal length and database; the first two can be
left empty (then every database is tried), filling sensor + focal makes it pick the right one.

## 8. Post-processing

**Framed output** — white border, object name in black at the bottom, auto-identified or set
manually. Writes `<name>_framed.jpg`, original pixels untouched.

**Auto stretch `--stretch`** — turns a linear TIFF into something viewable: white balance,
64× lift, per-channel background removal, asinh, +18 saturation. Writes
`<name>_stretched.tif` and `.jpg`. Display only; the original TIFF is untouched. Shadow noise
gets amplified along with everything else.

**Star reduction / removal** — "Star handling" dropdown plus a strength box, default off. CLI:
`--star-mode off|reduce|remove`, `--star-strength 0..1` (default 0.85).

- Reduce keeps the stars, only pushes halos down — smaller, cleaner stars. Writes
  `<time>_starred.tif` and a stretched version.
- Remove replaces stars entirely — writes `<time>_starless.tif`, the star layer
  `<time>_starless_stars.tif`, and stretched versions.

The main `<time>.tif` keeps the untouched stack, so you get three independent products and
nothing is overwritten.

How it works (classical, no AI model):

1. Multi-scale high-pass detection (1.2 / 2.5 / 3 / 5 px, take the maximum); connected
   components that are too small (noise) or too large (nebulosity) are dropped; thresholds use
   a local MAD, so dense fields are not misclassified wholesale.
2. Per-star radius-adaptive dilation of the mask.
3. Normalised convolution estimates the nebula/background underneath from surrounding
   unoccluded pixels.
4. Remove = replace the star area with that estimate; reduce = pull halos toward it.

Strength: removal defaults to 0.90 (1.0 = full replacement; measured residual 1% on 1050
frames, 12% on 20 frames). Reduction works well at 0.6–0.9. Nebulae (M42 and similar) suit
removal; dense star fields such as wide Milky Way frames suit reduction.

The mask coverage is logged. Between 12% and 35% it warns that the field is dense and suggests
reduction, but still runs. Above 35% it treats the result as a misdetection (usually too few
frames or too much noise) and skips star handling entirely.

Limitations: heavily overexposed stars with large halos retain a faint core; removal on dense
fields also takes away the diffuse light the stars contribute, leaving dark patches — prefer
reduction there.

## 9. Output files and the pedestal

TIFF values are 14-bit raw × 4 (65535 = 16383).

Background subtraction produces negative pixels. Clipping them to zero would black out one side
of the frame and lose the data (an early version did exactly that). On save the program checks
the minimum and, if negative, lifts everything by a pedestal of a few tens to a hundred ADU,
logging the value. So the background level is a small offset rather than zero; when you pull
curves in PS or PixInsight, set the black point just above that offset.

Preview files (`_preview.jpg` / `.png`) are stretched display images, not for post-processing.

**How the JPGs are made** — the float image is resized first and quantised afterwards. The old
path quantised to 8 bit and then resized, which dragged the 8-bit steps along, clipped
highlights before averaging, and let Lanczos ring around bright stars. Now resizing happens in
float (PIL widens the filter kernel with the scale factor, giving proper anti-aliasing), then
±0.5 LSB triangular dither is added before clipping to 0–255. `--jpg-max` (default 2600) sets
the long edge, `--jpg-quality` (default 92) the quality. On 20 M42 frames at 2600 px: 2.81 MB
before, 2.67 MB now; aliasing on a checkerboard test is equivalent; the 1-LSB plateaus in
gradients are gone. Costs about half a second.

16-bit TIFF and PNG are unaffected: full resolution, no resize, no dither.

## 10. CLI reference

```
Input/output
  --lights DIR        lights directory
  --darks DIR         darks directory (optional)
  --flats DIR         flats directory (optional)
  --out FILE          output TIFF (default output\YYMMDD_HHMM.tif)
  --limit N           only process the first N frames (debugging)

Stacking
  --stack-mode MODE   auto (default) | twopass | onepass | gpu
  --kappa 3.0         sigma rejection factor
  --threads 8         worker threads
  --no-crop           do not crop to common coverage
  --fast-warp         bilinear resampling instead of cubic

Light pollution
  --lp                per-frame LP removal
  --lp-div            per-frame LP removal, divide mode
  --lp-level LEVEL    auto | low | mid | high | manual
  --bg2d              mesh background extraction (after stacking)
  --bg2d-q 40         background floor percentile
  --bg-protect        structure protection
  --bg-poly 2         polynomial surface
  --rbf 2.0           RBF background
  --flatten           legacy post-stack flatten
  --chroma-nr 2       legacy Gaussian chroma denoise
  --chroma-denoise    off | light | medium | strong (wavelet chroma)
  --chroma-scales 3   chroma wavelet scales
  --denoise           off | light | medium | strong (wavelet luminance)
  --denoise-scales 4  luminance wavelet scales
  --no-type-opt       disable type-based tuning

Output
  --wb                white-balanced TIFF
  --png               extra 16-bit PNG preview
  --out-kind both     both (default) | linear | stretch
  --no-stretch-out    same as --out-kind linear (legacy)
  --stretch-sat 1.18  saturation of the stretched output
  --preview-sat 1.0   saturation of the preview
  --jpg-max 2600      JPG long-edge limit
  --jpg-quality 92    JPG quality

Stars
  --star-mode         off | reduce | remove
  --star-strength     0..1, default 0.85

Identification
  --no-identify       skip identification
  --object "M42"      set the object manually
  --identify FILE     identify a single file
  --sensor APS-C / --focal 300 / --crop 1.5 / --catalog auto

Other
  --stretch FILE      auto-stretch an existing linear TIFF
  --sat 1.18          saturation after stretching
  --frame FILE        add a white border with the object name
  --target "name"     name for the border
  --border 0.05       border width as a fraction of the short side
```

## 11. FAQ

**The TIFF opens black.** Correct — linear data has no gamma and no stretch. Use the stretch
button or pull curves yourself.

**One side of the frame is dead black.** Old versions clipped negatives to zero. Current
versions add a pedestal automatically; re-stack with the latest build.

**The GPU entry is gone / it stacks on CPU.** Three causes: `gpu_runtime` was deleted;
the program sits under a path with non-ASCII characters, so CuTeC's NVRTC cannot open its
headers and it silently falls back; or the driver does not support CUDA 12. The log records
`GPU stacking failed (reason), falling back to single-pass CPU`.

**Identification always says unknown.** Databases cover 4°–8° and 10°–30°. A 300 mm lens on
APS-C is about 5.4°, which uses the narrow database and does identify M42 plus NGC1980,
NGC1981, M43 and NGC1977. If it still fails (few stars, trailing, cloud), set the object
manually — that skips the FOV check.

**The Milky Way core got flattened.** Background removal is too aggressive: raise `--bg2d-q`
to 50–60, enable structure protection, or use per-frame LP removal instead of Background2D.

**Yellow-green edges.** Sodium and mercury lamp spectra on top of overexposed sky in that
region. The background algorithm cannot separate "light pollution" from "overexposed sky";
crop it out in post or use selective colour to pull yellow/green down.

**Memory and disk.** Roughly threads × 100 MB of RAM (6 threads: 2–4 GB, peaks near 6 GB).
Each run writes 30–70 MB of TIFF plus previews and PNG.

**Faster?** GPU mode; single-pass with many frames; threads near the physical core count; turn
off post-processing you do not need (`bg-protect` is the most expensive).

## 12. Recommended presets

1. Urban Milky Way, heavy light pollution, no flats, untracked
   `--lp --bg2d --bg-protect --bg2d-q 35 --chroma-denoise light --stack-mode auto`
2. Deep-sky target with darks and flats
   `--bg2d --bg-protect --bg2d-q 50 --stack-mode auto`
3. Slight gradient, flats, clean background
   `--bg-poly 2` (or nothing at all)
4. Fastest possible
   `--stack-mode gpu --bg2d --bg2d-q 45`
