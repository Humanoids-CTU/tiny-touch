"""Timeline track pictures: canvas-like drawing into a pixel array, without Tk."""
from gui.timeline_raster import TrackRaster, rgb

RED, GREEN, BLUE, WHITE = "#ff0000", "#00ff00", "#0000ff", "#ffffff"


def colored(raster, color):
    """Sorted (x, y) of every pixel holding `color`."""
    ys, xs = (raster.pixels == rgb(color)).all(axis=-1).nonzero()
    return sorted(zip(xs.tolist(), ys.tolist()))


def test_fill_covers_the_half_open_box_and_clips_to_the_picture():
    raster = TrackRaster(10, 6, WHITE)
    raster.fill(2.4, 1, 5.6, 3, RED)
    assert colored(raster, RED) == [(x, y) for x in (2, 3, 4, 5) for y in (1, 2)]
    raster.fill(-5, -5, 50, 50, BLUE)
    assert len(colored(raster, BLUE)) == 60
    raster.fill(4, 2, 4, 5, RED)          # empty box: nothing painted
    assert not colored(raster, RED)


def test_outline_runs_through_all_four_corner_pixels():
    raster = TrackRaster(8, 6, WHITE)
    raster.outline(1, 1, 6, 4, RED)
    assert tuple(raster.pixels[1, 1]) == tuple(raster.pixels[4, 6]) == rgb(RED)
    assert tuple(raster.pixels[1, 6]) == tuple(raster.pixels[4, 1]) == rgb(RED)
    assert tuple(raster.pixels[2, 3]) == rgb(WHITE)
    assert len(colored(raster, RED)) == 2 * 6 + 2 * 2


def test_vertical_lines_share_one_dash_pattern_width_and_bounds():
    raster = TrackRaster(12, 11, WHITE)
    raster.vlines([2.2, 7.6, 40, -3], 1, 11, GREEN, dash=(3, 2))
    assert {x for x, _ in colored(raster, GREEN)} == {2, 8}
    assert [y for x, y in colored(raster, GREEN) if x == 2] == [1, 2, 3, 6, 7, 8]
    raster.vlines([5], 0, 11, RED, width=2)
    assert {x for x, _ in colored(raster, RED)} == {4, 5}
    raster.vlines([], 0, 11, BLUE)
    assert not colored(raster, BLUE)


def test_line_joins_two_points_in_any_direction():
    raster = TrackRaster(6, 6, WHITE)
    raster.line(0, 5, 5, 0, RED)
    assert colored(raster, RED) == [(i, 5 - i) for i in range(6)]


def test_rounding_blends_the_corners_of_a_copy_only():
    raster = TrackRaster(40, 20, RED)
    rounded = raster.rounded(6, WHITE)
    for y, x in ((0, 0), (19, 39), (0, 39), (19, 0)):
        # The antialiased mask may leave the outermost pixel a shade off white.
        assert rounded[y, x].min() >= 250
    assert tuple(rounded[10, 20]) == tuple(rounded[5, 5]) == rgb(RED)
    assert (raster.pixels == rgb(RED)).all()          # the source keeps square corners
    assert (TrackRaster(40, 20, RED).rounded(0, WHITE) == rgb(RED)).all()


def test_copy_is_independent():
    raster = TrackRaster(4, 4, WHITE)
    clone = raster.copy()
    clone.fill(0, 0, 4, 4, BLUE)
    assert (raster.pixels == rgb(WHITE)).all() and (clone.pixels == rgb(BLUE)).all()
