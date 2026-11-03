# JPEG extraction capped at 1080p: focused experiment

On this machine, preparing the 4K sample as 1080p JPEGs reduced JPEG storage by
**88.9%**, extraction time by **52.1%**, and subsequent JPEG decode/resize wall
time by **49.2% at a 720p panel** or **66.7% at a 1080p panel**. The 1080p source
produced byte-identical JPEGs with the cap enabled. This is a CPU-only change;
it does not need GPU support.

These are component results, not measured full-app playback or annotation speed.
Production code, original videos, existing frames, and annotation data were not
changed. The proposed coding-resolution limit is 1920x1080, as requested.

## Method

Run `uv run demos/benchmark_jpeg_resolution.py`. No GUI windows open. Named
constants configure two existing samples, the first 100 frames each, two repeats,
and two display sizes. Original/capped order reverses on the second repeat.
Every extraction uses a fresh output folder; no existing cache is overwritten.

- Original extraction uses the production FFmpeg JPEG settings: `-q:v 2`,
  `-start_number 0`. Both variants also limit this experiment to 100 frames.
- The capped variant adds `scale=1920:1080:flags=bilinear` for the 3840x2160
  sample, before JPEG encoding. Already-small inputs use no scale filter.
- `capped_size` fits into 1920x1080 without upscaling, cropping, or stretching.
  Integer dimensions round down by less than one pixel. For example, a
  2160x3840 portrait source becomes **607x1080**, not 1080x1920.
- No FPS-changing filter or seeking is added. Default FFmpeg timing behavior
  remains the same as the current extractor; this experiment does not establish
  variable-frame-rate correctness for either path.
- JPEG loading reproduces the current `FrameBuffer` pipeline: read header,
  `Image.draft("RGB", target)`, `copy()` to force decoding, then BILINEAR resize
  only if necessary. No full-resolution-decode baseline is substituted.
- After five warm-up frames per case, 100 sequential frames are measured.
  Decode/read and resize wall time are recorded separately; process CPU time is
  also recorded. No Tk display, GPU upload, GUI updates, or parallel prefetch is
  included. Summary values below are medians of the two per-run means.

Machine metadata in the raw result: Windows 11, 16 logical CPUs, Pillow 11.3.0,
bundled FFmpeg 7.1. Whole-machine CPU was 9.6% in a short initial sample and 40.4%
on average during the run, including the benchmark. There was no concurrent
agent benchmark. Two repeats are enough for this directional experiment, not a
precision performance guarantee. Windows process-CPU timer granularity makes
individual stage CPU readings coarse; wall timings are the primary result.

## Results

| Input / metric | Original JPEGs | Capped JPEGs | Change |
| --- | ---: | ---: | ---: |
| 4K: dimensions | 3840x2160 | 1920x1080 | Half width/height |
| 4K: bytes for 100 JPEGs | 202,849,882 | 22,605,239 | 88.9% smaller |
| 4K: extract 100 frames | 8.045 s | 3.851 s | 52.1% less time |
| 4K: load to 1280x720 | 55.31 ms/frame | 28.10 ms/frame | 49.2% less time |
| 4K: load to 1920x1080 | 34.57 ms/frame | 11.52 ms/frame | 66.7% less time |
| 1080p: bytes for 100 JPEGs | 54,601,313 | 54,601,313 | Identical |
| 1080p: extract 100 frames | 1.550 s | 1.513 s | Same work; timing noise |
| 1080p: load to 1280x720 | 32.90 ms/frame | 33.36 ms/frame | Same JPEGs; timing noise |
| 1080p: load to 1920x1080 | 12.87 ms/frame | 13.30 ms/frame | Same JPEGs; timing noise |

The individual 4K extraction runs were 9.274/6.816 s original and 3.713/3.988 s
capped. The 1080p-display load runs were 35.14/33.99 ms original and
9.44/13.60 ms capped; absolute times varied, while both repeats favored the cap.

| 4K input / stage | Original JPEGs | Capped JPEGs |
| --- | ---: | ---: |
| Decode/read, 720p output | 36.39 ms | 10.73 ms |
| Resize, 720p output | 18.92 ms | 17.37 ms |
| Decode/read, 1080p output | 34.55 ms | 11.50 ms |
| Resize, 1080p output | 0.016 ms | 0.016 ms |

The original 4K JPEG already uses half-scale JPEG draft decoding, resulting in
**1920x1080 decoded pixels in both variants** for both tested panel sizes.
Therefore this result does **not** demonstrate reduced decoded-frame buffer RAM:
at the same panel size, final RGB storage remains 2,764,800 bytes at 720p and
6,220,800 bytes at 1080p. The improvement comes mainly from reading and decoding
a much smaller compressed JPEG, before the same final resize. Disk storage and
compressed-file caching can shrink; whole-process memory was not measured.

Mean process CPU time per frame for 4K decode+resize was 22.81 to 13.67 ms at
720p and 15.16 to 4.77 ms at 1080p. These are CPU durations, not CPU percentages
or power measurements.

## Frame identity and quality

A separate 10-frame, constant-25-FPS H.264 4K fixture contains burned pixel IDs
`0, 1, 49, 50, 51, 99, 100, 101, 159, 255`, with three B-frames enabled.
Both original and capped extraction produced exactly ten consecutively numbered
JPEGs, and all **20/20** pixel-ID reads matched the expected order. The reader
also distinguishes an intentionally wrong frame ID. All eight measured sample
extractions produced exactly `frame0.jpg` through `frame99.jpg`.

For the unchanged 1080p sample, **100/100 SHA-256 comparisons matched** between
original and capped JPEG output. Displayed-pixel RMS difference was zero.

For 4K sample frame 50, the RGB RMS difference at the same 1080p display size was
**5.41 on a 0-255 channel scale**. This includes changed scaling/JPEG compression;
matching frame identity does not mean matching every pixel. A side-by-side
preview was inspected: both show the same cat frame and preserve the overall
scene; the smaller extracted image changes fine texture. This is not a clinical
or annotation-detail acceptance test. The original video retains full detail.

Evidence, all ignored under `demos/runtime/jpeg_resolution/20261103T123601Z/`:

- [Raw measurements and commands](runtime/jpeg_resolution/20261103T123601Z/results.json)
- [4K comparison, original left / capped right](runtime/jpeg_resolution/20261103T123601Z/sample_2160p_comparison_frame50.png)
- [Original JPEG shown at 1080p](runtime/jpeg_resolution/20261103T123601Z/sample_2160p_original_display_frame50.png)
- [Capped JPEG shown at 1080p](runtime/jpeg_resolution/20261103T123601Z/sample_2160p_capped_display_frame50.png)

Permanent checks are in `tests/unit/test_jpeg_resolution_experiment.py`: landscape,
portrait, square, already-small and invalid dimensions, plus actual FFmpeg 4K
encoding/extraction with burned frame IDs. The complete non-GUI suite passed:
**497 passed, 38 GUI tests deselected** (`uv run pytest`).

## Integration recommendation and limits

The 1080p extraction cap is worth integrating independently of GPU rendering.
It benefits CPU-only computers as well. Applying it consistently requires both
the FFmpeg extractor and OpenCV fallback to use the same fit rule, preserving
frame count, index, and FPS behavior. Reliability copies and already-existing
frame caches need a deliberate policy; this experiment never rewrites them.

Only the two existing samples and one synthetic constant-FPS marker fixture were
measured. Linux, rotated/anamorphic input, variable frame rates, full-video
extraction, and end-to-end playback remain unverified. Storage savings depend on
content; the measured 88.9% is not a universal ratio. Do not add the JPEG result
to earlier GPU percentage gains: they measure different stages and would require
a combined measurement to establish their joint effect.

Official references: [FFmpeg scale filter](https://ffmpeg.org/ffmpeg-filters.html#scale),
[FFmpeg filter documentation source](https://github.com/FFmpeg/FFmpeg/blob/master/doc/filters.texi),
and [Pillow JPEG draft decoding](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#jpeg).
