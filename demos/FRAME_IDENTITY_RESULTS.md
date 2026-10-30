# Frame identity experiment — 30 October 2026

**The paused images matched in all 26 checks. The demo counter briefly lagged
behind the correct image in six initial observations.** This establishes frame
identity for the tested clip and navigation sequence, with a remaining UI
synchronization issue to address before annotation integration.

## Fixture and independent check

- A generated 640x360, constant-25-FPS H.264 video, frames **0–159**.
- A large `FRAME NNNN` number and timestamp are burned into every source image.
- A separate black/white marker encodes the same ID, a fixed magic byte and an
  inverse-byte checksum. Tests read pixels instead of trusting player counters.
- A fixed 50-frame keyframe interval, closed GOP and three B-frames exercise
  seeking across compressed-video boundaries and decoder frame reordering.
- TinyTouch's existing ffmpeg extraction function generated the JPEG sequence.
  Every one of its **160 JPEGs** decoded to the correct burned-in frame ID.
- Eight focused marker tests passed, covering JPEG compression, display scaling,
  incorrect expected IDs, obscured markers and corruption. A one-frame negative
  control was detected.

## Visible playback checks

The actual mpv demo was driven through its jump button and navigation/playback
callbacks. The JPEG reference used TinyTouch's existing `FrameBuffer`, Pillow
decode/resize and Tk `PhotoImage` display. This does not exercise the rest of
TinyTouch's annotation controller.

Windows desktop captures were cropped to each visible video rectangle, with
aspect-ratio letterboxing removed. The marker was read from those pixels.
The capture process was made DPI-aware before creating windows. Earlier capture
attempts used incompatible coordinate systems or returned a black D3D surface;
those attempts were excluded from frame-identity conclusions.

| Check | Count | Settled outcome |
|---|---:|---|
| Open at frame zero | 1 | Both images and counter match |
| Explicit jumps, including keyframe boundaries and final frame | 9 | Both images and counter match |
| Forward/backward steps across frame 50 | 4 | Both images and counter match |
| Seeded random jumps | 6 | Both images and counter match |
| Rapid jumps: 150 → 2 → 75 | 1 | Final request wins; both show 75 |
| Previous at first / next at last | 2 | Stay at 0 / 159 |
| Play then pause | 3 | Both show the paused frame; image remains stable |
| **Total** | **26** | **26 passed after settling** |

The decoder reported `d3d11va`. The successful run used mpv
`v0.41.0-1227-ge471496c5` on Windows.

## Synchronization finding

At the first logical-ready observation, both video images already contained the
correct ID in all 26 checks. In **six** observations, the demo's GUI counter still
contained an earlier value:

| Action | Image ID | Counter at first observation |
|---|---:|---:|
| Forward step to 50 | 50 | 49 |
| Forward step to 51 | 51 | 50 |
| Backward step to 50 | 50 | 51 |
| Backward step to 49 | 49 | 50 |
| Random jump to 38 | 38 | 82 |
| Rapid jumps ending at 75 | 75 | 150 |

After a 150 ms settling interval the counter and images agreed in every check;
another capture 100 ms later confirmed stable paused images. The counter uses a
separate 100 ms Tk poll. Screenshot capture itself occupies the Tk thread, so
these observations identify a synchronization gap but do not measure its exact
duration under normal use.

**Integration implication:** update the confirmed annotation frame and GUI
counter together, and enable annotation only after the requested frame is ready.
Do not use a delayed display counter as the annotation-frame source of truth.
No annotation writing or save/export behavior was tested or changed here.

## Evidence and limits

- [Numbered test video](runtime/frame_identity/20261030T065029Z/numbered_25fps.mp4)
- [Side-by-side frame 50](runtime/frame_identity/20261030T065029Z/comparison_frame_50.png)
- [Per-action observations](runtime/frame_identity/20261030T065029Z/results.json)
- The same folder contains the JPEG reference sequence and captured test images.
  Generated media/evidence is local and Git-ignored.

This was one focused experiment, not coverage of all codecs, frame rates,
timestamp offsets or camera recordings. It verifies sampled paused frames and
navigation outcomes, not every frame during continuous playback or physical
monitor scanout latency. Fractional constant FPS, variable FPS, other machines,
Linux and actual annotation persistence remain unverified.

Reproduce with `uv run demos/frame_identity.py`. The two experiment windows must
remain visible and unobscured. Run only the marker checks with
`uv run pytest tests/unit/test_frame_identity_marker.py -q`.
