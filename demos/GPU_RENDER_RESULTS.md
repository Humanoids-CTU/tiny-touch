# GPU rendering of JPEG frames — 3 November 2026

**GPU scaling and drawing work without mpv. They reduce the measured display
cost, but JPEG decoding remains on the CPU.** This is an isolated prototype;
TinyTouch's player, settings and annotations are unchanged.

## Design

Both renderers read the same extracted JPEGs with Pillow. Both retain the current
app's `Image.draft()` optimization: decode at a reduced JPEG resolution when
possible. At a 1280×720 output, both tested source sizes decode to 1920×1080.

- CPU: Pillow bilinear resize, followed by a reused Tk `PhotoImage`.
- GPU: copy RGB pixels into one reusable SDL texture, then scale and draw with
  Direct3D 11. JPEG decoding and the CPU-to-GPU upload still cost CPU time.
- Automatic mode attempts GPU initialization and falls back to Pillow/Tk if
  unavailable. The interactive demo also falls back after a GPU drawing error.
- The demo keeps at most eight decoded frames. Left/right, play/pause and numeric
  frame jumps use JPEG indices directly; there is no time-based frame estimate.

The GPU renderer is deliberately separate from the application. The current
pygame SDL renderer API is experimental, so embedding, packaging and long-term
API suitability require evaluation before production integration.

## Measurements

Windows, Ryzen 7 PRO 6850U, integrated AMD Radeon graphics, 16 logical CPUs.
Two fresh processes per path and source size, with mode order reversed on the
second repeat. Each worker decoded/rendered 100 frames at a requested 25 FPS,
reusing the same first 25 source JPEGs from the earlier sample-video benchmark.
Five warmup frames precede timing. No frames are skipped to maintain playback.

| Source | Display stage CPU → GPU | Whole-machine-scale process CPU, CPU → GPU | Serial loop FPS, CPU → GPU |
|---|---:|---:|---:|
| 1080p | 32.8 → 12.1 ms | 4.12% → 1.94% | 19.9 → 24.4 |
| 4K | 28.4 → 13.1 ms | 4.98% → 4.67% | 15.6 → 20.3 |

Times are the mean of two per-run medians. CPU and FPS are the mean of the two
runs. Display time includes CPU resizing/Tk upload or RGB conversion/texture
upload/GPU draw submission, presentation and toolkit event processing.

At 4K, median JPEG decode time was about 34 ms in both paths. Moving the remaining
resize/draw work to the GPU therefore improved throughput but saved little total
CPU. At 1080p, GPU mode used about 53% less process CPU in this experiment.

Process working set was roughly 50 MiB for Tk and 85–89 MiB for GPU. These numbers
exclude the app's large frame buffer and do not account for all GPU/driver memory.
This experiment demonstrates a display-cost improvement, not a RAM saving.

**These FPS numbers are not TinyTouch playback measurements.** This component
experiment decodes and renders serially; the app already overlaps background
decoding with display. No inference about the app's final FPS follows directly.
It also does not establish input-to-screen latency, power or battery savings.
System CPU averaged approximately 9–16% across runs. Only this Windows machine
and these short, warm-cache samples were measured; Linux remains unverified.
GPU linear scaling and Pillow bilinear scaling may differ in fine image detail.

An earlier full-resolution decode prototype was excluded from this table. The
final comparison retains JPEG draft decoding in both paths, matching the current
app's optimization rather than comparing against an unnecessarily costly CPU path.

## Correctness and fallback

- Eight burned-marker frame checks passed in each of GPU, explicit Tk and
  automatic fallback: **24/24**. Sequence: 0, 1, 49, 50, 51, 159, 75, 0.
- GPU checks read the rendered SDL target; Tk checks read its actual PhotoImage
  buffer. They do not merely inspect the source Pillow image.
- Desktop capture was unavailable in this session. These checks verify renderer
  buffers, not physical screen visibility or synchronization with annotations.
- Setting SDL's video device to `dummy` made GPU initialization fail. Automatic
  mode successfully selected Tk and preserved all eight requested frame IDs.
  This simulates unavailable acceleration; no physically GPU-free PC was tested.
- Three dedicated demo GUI tests passed. All **484 non-GUI tests** passed,
  including six new checks of frame access, image identity and aspect ratio.
  The application GUI suite was not run for this standalone experiment.

An integrated GPU is sufficient for the tested rendering path. Integrated graphics
are common, but not universal: Intel desktop F-series CPUs, for example, require
a separate graphics card. Runtime capability detection and a CPU fallback remain
necessary. CPU fallback still needs a usable desktop/windowing environment.

## Run and inspect

From the repository:

```powershell
uv pip install --python .venv/Scripts/python.exe -r demos/gpu-render-requirements.txt
uv run demos/gpu_render_demo.py
```

Select a folder containing a complete `frame0.jpg`, `frame1.jpg`, … sequence.
Use Space to play/pause, arrows to step, digits then Enter to jump, Escape to close.
Frame numbers and the selected renderer appear in the window title; typed jump
digits are echoed in the terminal. Playback assumes the `FPS = 25` constant;
adjust it for other constant-rate material. Navigation uses JPEG indices.
Set `GPU_PREFERENCE = "tk"` in the demo to force the CPU path.
The optional GPU package is not required for automatic fallback to Tk.

Reproduce the focused measurements with `uv run demos/benchmark_gpu_render.py`.
It uses cached benchmark JPEGs if present, otherwise extracts 25 frames from
`videos/sample_1080p.mp4` and `videos/sample_2160p.mp4` into its own output folder.

```powershell
uv run pytest tests/unit/test_gpu_render_demo.py -q
uv run pytest tests/e2e/test_gpu_render_pixels.py -m gui -q
```

Local evidence (generated and Git-ignored):

- [Final measurements and source hashes](runtime/gpu_render/20261103T122413Z/summary.json)
- [GPU-rendered frame 50](runtime/gpu_render/20261103T122413Z/sample_1080p-gpu-0/frame50.png)
- [Fallback result](runtime/gpu_render/20261103T122413Z/fallback/result.json)

Official references: [SDL renderer and texture API](https://pyga.me/docs/ref/sdl2_video.html),
[Pillow JPEG draft decoding](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#jpeg),
[Intel desktop processors without integrated graphics](https://www.intel.com/content/www/us/en/support/articles/000027144/processors/intel-core-processors.html).
Context7 was unavailable; current official documentation was consulted directly.
The optional knowledge-base search could not start because Docker was unavailable.

The result supports evaluating GPU rendering further while keeping JPEG frame
access. It does not yet justify replacing the app's renderer: Tk embedding,
annotation/display synchronization, image quality and distribution still need
verification in a separately authorized integration step.
