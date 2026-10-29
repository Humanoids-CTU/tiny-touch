# mpv comparison results ? 29 October 2026

Hardware-decoded mpv substantially reduces CPU and process memory use, but the current demo is slower for backward steps and random frame jumps. These results do not support replacing TinyTouch's playback path unchanged.

## Measured results

Median of three runs per configuration. CPU uses the whole-machine scale; process RAM is the sampled working set in MiB. FPS describes video-timeline progression, with native dropped-frame counters listed below.

| Video | Playback path | FPS | CPU | Process RAM | Forward step | Backward step | Jump median / p95 |
|---|---|---:|---:|---:|---:|---:|---:|
| sample_1080p | Existing JPEG/Tk path | 24.68 | 14.03% | 1163 MiB | 46 ms | 47 ms | 138 / 168 ms |
| sample_1080p | mpv hardware | 24.99 | 0.58% | 246 MiB | 42 ms | 232 ms | 257 / 492 ms |
| sample_1080p | mpv software | 25.00 | 7.98% | 296 MiB | 42 ms | 512 ms | 528 / 825 ms |
| sample_2160p | Existing JPEG/Tk path | 25.00 | 19.06% | 1156 MiB | 46 ms | 47 ms | 188 / 349 ms |
| sample_2160p | mpv hardware | 25.00 | 1.86% | 655 MiB | 42 ms | 640 ms | 537 / 1128 ms |
| sample_2160p | mpv software | 21.34 | 45.61% | 898 MiB | 44 ms | 2660 ms | 2416 / 3802 ms |

## Preparation and storage

| Video | One-time JPEG extraction | Extra JPEG storage |
|---|---:|---:|
| sample_1080p.mp4 | 12.5 s | 0.41 GB |
| sample_2160p.mp4 | 49.9 s | 1.52 GB |

mpv uses the original file and avoids that extraction/cache. With an existing JPEG cache, the JPEG path reopened faster: about 0.4 s versus mpv hardware's 1.5 s at 1080p and 2.4 s at 4K.

## GPU and dropped frames

- sample_1080p / jpeg: GPU no attributable process-engine samples; VO dropped frames by repeat: not applicable; JPEG playback stalls rather than dropping frames.
- sample_1080p / mpv-auto: GPU 34.3% mean busiest engine, 2 valid samples; VO dropped frames by repeat: [0, 0, 0].
- sample_1080p / mpv-software: GPU 28.9% mean busiest engine, 2 valid samples; VO dropped frames by repeat: [0, 0, 0].
- sample_2160p / jpeg: GPU no attributable process-engine samples; VO dropped frames by repeat: not applicable; JPEG playback stalls rather than dropping frames.
- sample_2160p / mpv-auto: GPU 98.2% mean busiest engine, 4 valid samples; VO dropped frames by repeat: [0, 8, 4].
- sample_2160p / mpv-software: GPU no attributable process-engine samples; VO dropped frames by repeat: [49, 89, 7].

GPU percentages describe the busiest engine, not total GPU utilization or electrical power. Hardware mpv drove the heavy 4K sample's busiest GPU engine close to saturation. Refreshed-query samples cover the latter part of the campaign. Windows Python launcher PIDs were corrected to the actual worker PIDs emitted in phase logs before GPU attribution; launcher IDs are retained in the raw records. Process RAM excludes driver/GPU allocations and shared compositor work.

Software mode disabled hardware **decoding** while retaining the same GPU **renderer**. It is not a measurement of rendering entirely on the CPU. A dedicated GPU is unnecessary when an integrated GPU supports the codec; a machine with no usable GPU rendering path would require a separate software-rendering configuration.

## Method and limits

- Windows 11; AMD Ryzen 7 PRO 6850U with Radeon Graphics; 16 logical CPUs; 14.77 GiB RAM; AC power.
- Existing 30-second, constant-25-FPS synthetic/grainy samples, rendered into a 1280x720 panel with audio disabled.
- Eighteen fresh worker processes: three modes, two videos, three repeats. Order reversed for the second repeat.
- Each run: 20 seconds of measured playback, 25 forward steps, 25 backward steps, 24 seeded random jumps. All requested navigation targets completed.
- The legacy component uses a snapshot of the actual FrameBuffer and precise-timer adapter, with equivalent Tk image paste and playback pacing. The annotation UI is excluded.
- mpv hardware used d3d11va. Software mode explicitly disabled hardware decoding. The demo's conservative hr-seek-framedrop=no setting was retained.
- Navigation timings end at Tk image upload or mpv reaching the target with seeking finished; they are not physical input-to-screen measurements. Polling adds up to roughly one 10 ms driver interval under ideal conditions.
- OS caches were not flushed. The 4K JPEG playback runs varied from about 17 to 25 FPS; the median alone hides this variation.
- The sampled system CPU counter was close to 100% during much of this session. These are session-specific measurements, not a verified idle-machine baseline; absolute timing and power/capacity conclusions remain limited.
- CPU figures are attributable process CPU time across its threads. CPU and GPU utilization percentages cannot be added or compared as equivalent power consumption.
- This does not establish exact annotation-frame identity, physical display jitter, battery savings, Linux behavior, or performance on representative camera recordings.
- The first pilot campaign was excluded. The final 18 workers used one identical benchmark source hash and fixed playback-adapter snapshots.

## Recommendation

Keep mpv as a promising playback option, but do not replace the annotation player as-is. At 1080p, hardware mpv used about 96% less CPU and 79% less process RAM, while backward stepping was about five times slower. At 4K, CPU use was about 90% lower and process RAM about 43% lower, but backward stepping was about fourteen times slower. Software fallback was especially costly at 4K.

A future prototype should address backward/jump responsiveness, for example through a small decoded-frame cache or a short-keyframe-interval proxy. Those are follow-up options, not changes made in this benchmark.

## Reproduction and raw evidence

Run instructions and limitations: [README.md](README.md#playback-and-resource-benchmark).

Local raw evidence: [final campaign](runtime/benchmarks/20261029T144718Z/summary.json), plus per-run JSON, GPU logs, metadata, source snapshots, and hashes in that directory. JPEG preparation timing/inventory was recorded in the excluded pilot's cache directory and reused without regeneration. These large local artifacts are Git-ignored.

Optional dependencies: [benchmark-requirements.txt](benchmark-requirements.txt). No application code or annotation projects were changed.
