"""Helpers for generating synthetic watermarked images.

Used by the test-suite and the ``--demo`` CLI to produce ground-truth pairs
(clean image, watermarked image) so removal quality can be measured
objectively rather than eyeballed.
"""

from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np


def make_clean_image(size: Tuple[int, int] = (480, 640)) -> np.ndarray:
    """A deterministic, textured synthetic photo (BGR uint8).

    Smooth gradients plus a few shapes give the inpainter realistic content to
    reconstruct from while staying reproducible across runs.
    """
    h, w = size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    b = 128 + 100 * np.sin(xx / 40.0)
    g = 128 + 100 * np.cos(yy / 35.0)
    r = 128 + 100 * np.sin((xx + yy) / 50.0)
    img = np.clip(np.dstack([b, g, r]), 0, 255).astype(np.uint8)

    cv2.circle(img, (int(w * 0.3), int(h * 0.4)), 60, (40, 200, 40), -1)
    cv2.rectangle(img, (int(w * 0.55), int(h * 0.55)), (int(w * 0.8), int(h * 0.85)), (200, 80, 40), -1)
    img = cv2.GaussianBlur(img, (5, 5), 0)
    return img


def add_text_watermark(
    image: np.ndarray,
    text: str = "SAMPLE",
    opacity: float = 0.45,
    color: Tuple[int, int, int] = (255, 255, 255),
) -> Tuple[np.ndarray, np.ndarray]:
    """Blend a semi-transparent diagonal text watermark over ``image``.

    Returns ``(watermarked, ground_truth_mask)``.
    """
    h, w = image.shape[:2]
    layer = np.zeros_like(image)
    mask = np.zeros((h, w), dtype=np.uint8)

    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = w / 320.0
    thick = max(2, int(scale * 2))
    for row in range(0, h, int(80 * scale)):
        for col in range(-w, w, int(260 * scale)):
            cv2.putText(layer, text, (col, row), font, scale, color, thick, cv2.LINE_AA)
            cv2.putText(mask, text, (col, row), font, scale, 255, thick, cv2.LINE_AA)

    watermarked = image.copy()
    sel = mask > 0
    watermarked[sel] = (
        (1 - opacity) * image[sel] + opacity * layer[sel]
    ).astype(np.uint8)
    return watermarked, mask


def make_demo_pair(size: Tuple[int, int] = (480, 640)) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(clean, watermarked, ground_truth_mask)``."""
    clean = make_clean_image(size)
    watermarked, mask = add_text_watermark(clean)
    return clean, watermarked, mask
