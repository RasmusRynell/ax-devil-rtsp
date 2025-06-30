import numpy as np
from ax_devil_rtsp.utils import rgb_to_bgr


def test_rgb_to_bgr_swaps_channels():
    rgb = np.array(
        [[[255, 0, 0], [0, 255, 0], [0, 0, 255]]], dtype=np.uint8
    )
    bgr = rgb_to_bgr(rgb)
    assert np.array_equal(bgr[0, 0], [0, 0, 255])
    assert np.array_equal(bgr[0, 1], [0, 255, 0])
    assert np.array_equal(bgr[0, 2], [255, 0, 0])
    assert bgr.flags["C_CONTIGUOUS"]
