"""
domain/playback.py
Pure playback rules — no Tk, no threads, no I/O.
"""


def compute_play_step(current_frame, total_frames, direction):
    """Pure play-step decision: (next_frame, stop).

    stop=True when playback sits at the edge it is moving toward (frame 0
    going backward, total_frames going forward) so playback ends instead of
    stepping against a boundary.
    """
    if (direction > 0 and current_frame >= total_frames) or \
       (direction < 0 and current_frame <= 0):
        return current_frame, True
    return max(0, min(total_frames, current_frame + direction)), False
