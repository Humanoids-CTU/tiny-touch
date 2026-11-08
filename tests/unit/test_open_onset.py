"""The open-onset ghost lookup, with and without a reused earlier answer.

The diagram redraws the ghost on every frame change (including playback), so
`LabelingApp.find_last_green` passes the previous answer as `known`. That
shortcut must never change the result.
"""

import random

from domain.touch import find_last_open_onset


def _random_frames(rng, total, limb="RH"):
    frames = {}
    for frame in range(total):
        roll = rng.random()
        if roll < 0.05:
            frames[frame] = {limb: {"Onset": "ON", "X": [frame], "Y": [frame + 1]}}
        elif roll < 0.10:
            frames[frame] = {limb: {"Onset": "OFF", "X": [1], "Y": [2]}}
        elif roll < 0.15:
            frames[frame] = {limb: {}}
        elif roll < 0.20:
            frames[frame] = {"LH": {"Onset": "ON", "X": [9], "Y": [9]}}
        # otherwise: no bundle at all
    return frames


def test_reusing_an_earlier_answer_matches_a_full_scan():
    rng = random.Random(7)
    for _ in range(20):
        frames = _random_frames(rng, 300)
        known = None
        frame = 0
        while frame < 300:
            expected = find_last_open_onset(frames, "RH", frame)
            got = find_last_open_onset(frames, "RH", frame, known=known)
            assert got == expected, (frame, known)
            known = (frame, got)
            frame += rng.choice((1, 1, 1, 2, 7, 40))  # steps, jumps, fast play


def test_an_answer_from_a_later_frame_is_ignored():
    frames = {2: {"RH": {"Onset": "ON", "X": [5], "Y": [6]}},
              8: {"RH": {"Onset": "OFF"}}}
    stale = (8, [(None, None)])
    assert find_last_open_onset(frames, "RH", 4, known=stale) == [(5, 6)]


def test_the_known_answer_is_returned_when_nothing_changes_in_between():
    frames = {2: {"RH": {"Onset": "ON", "X": [5], "Y": [6]}}}
    known = (3, [(5, 6)])
    assert find_last_open_onset(frames, "RH", 3, known=known) == [(5, 6)]
    assert find_last_open_onset(frames, "RH", 50, known=known) == [(5, 6)]
