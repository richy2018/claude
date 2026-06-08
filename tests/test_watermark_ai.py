"""Tests for the watermark_ai package.

These are *quantitative*: a synthetic clean image is watermarked, then run
through the pipeline, and we assert the reconstruction is measurably closer to
the original than the watermarked input was. That proves the remover actually
removes — not just that the code runs.

Run:
    python -m pytest tests/test_watermark_ai.py -v
"""

import os
import sys

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from watermark_ai import WatermarkDetector, WatermarkRemover, remove_watermark
from watermark_ai.samples import make_clean_image, make_demo_pair


def _psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2)
    if mse == 0:
        return float("inf")
    return 20 * np.log10(255.0) - 10 * np.log10(mse)


# --------------------------------------------------------------------- detector
def test_detector_finds_watermark():
    _, watermarked, _ = make_demo_pair()
    det = WatermarkDetector().detect(watermarked)
    assert det.found
    assert det.coverage > 0.0
    assert len(det.boxes) >= 1


def test_detector_clean_image_low_coverage():
    """A watermark-free image should flag very little (no large false region)."""
    clean = make_clean_image()
    det = WatermarkDetector(sensitivity=0.5).detect(clean)
    assert det.coverage < 0.10


def test_detector_iou_against_ground_truth():
    _, watermarked, gt = make_demo_pair()
    det = WatermarkDetector().detect(watermarked)
    inter = np.logical_and(det.mask > 0, gt > 0).sum()
    # The detector should recover a solid share of the true watermark pixels.
    recall = inter / max((gt > 0).sum(), 1)
    assert recall > 0.30


# ---------------------------------------------------------------------- remover
def test_remove_improves_psnr():
    clean, watermarked, _ = make_demo_pair()
    result = remove_watermark(watermarked)
    before = _psnr(clean, watermarked)
    after = _psnr(clean, result[:, :, :3])
    assert after > before + 1.0  # measurable improvement


def test_remove_with_ground_truth_mask_is_strong():
    clean, watermarked, gt = make_demo_pair()
    result = remove_watermark(watermarked, mask=gt)
    before = _psnr(clean, watermarked)
    after = _psnr(clean, result[:, :, :3])
    assert after > before + 3.0


def test_manual_mask_only_touches_masked_pixels():
    clean = make_clean_image()
    mask = np.zeros(clean.shape[:2], dtype=np.uint8)
    mask[100:140, 100:300] = 255
    out = WatermarkRemover(dilate=0).remove(clean, mask)
    untouched = mask == 0
    assert np.array_equal(clean[untouched], out[untouched])


# ----------------------------------------------------------------------- shapes
def test_output_shape_and_dtype_preserved():
    _, watermarked, _ = make_demo_pair()
    out = remove_watermark(watermarked)
    assert out.shape[:2] == watermarked.shape[:2]
    assert out.dtype == np.uint8


def test_bgra_alpha_preserved():
    _, watermarked, _ = make_demo_pair()
    bgra = cv2.cvtColor(watermarked, cv2.COLOR_BGR2BGRA)
    out = remove_watermark(bgra)
    assert out.shape[2] == 4


def test_empty_mask_returns_copy():
    clean = make_clean_image()
    empty = np.zeros(clean.shape[:2], dtype=np.uint8)
    out = WatermarkRemover().remove(clean, empty)
    assert np.array_equal(clean, out)


# ------------------------------------------------------------------------ guards
def test_bad_mask_shape_raises():
    clean = make_clean_image()
    with pytest.raises(ValueError):
        WatermarkRemover().remove(clean, np.zeros((10, 10), dtype=np.uint8))


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        remove_watermark("does-not-exist-12345.png")
