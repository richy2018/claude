"""High-level watermark removal pipeline: detect → remove.

This is the entry point most callers want::

    from watermark_ai import remove_watermark
    clean = remove_watermark("photo.jpg")          # auto-detect + remove
    cv2.imwrite("clean.png", clean)

It wires :class:`~watermark_ai.detector.WatermarkDetector` to
:class:`~watermark_ai.remover.WatermarkRemover` and also offers a small helper
for visualising what was detected.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple, Union

import cv2
import numpy as np

from .detector import BBox, DetectionResult, WatermarkDetector
from .remover import Algorithm, WatermarkRemover

ImageLike = Union[str, "os.PathLike[str]", np.ndarray]


@dataclass
class PipelineResult:
    """Everything produced by a full detect→remove run."""

    original: np.ndarray
    mask: np.ndarray
    result: np.ndarray
    detection: DetectionResult

    @property
    def found_watermark(self) -> bool:
        return self.detection.found


def _load(image: ImageLike) -> np.ndarray:
    if isinstance(image, np.ndarray):
        return image
    path = os.fspath(image)
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"could not read image: {path!r}")
    return img


def remove_watermark(
    image: ImageLike,
    *,
    methods: Sequence[str] = ("tophat", "periodic"),
    roi: Optional[BBox] = None,
    color: Optional[Sequence[int]] = None,
    mask: Optional[np.ndarray] = None,
    algorithm: Algorithm = "telea",
    sensitivity: float = 0.5,
    dilate: int = 2,
    radius: int = 3,
    return_details: bool = False,
) -> Union[np.ndarray, PipelineResult]:
    """Detect and remove the watermark from ``image``.

    Parameters
    ----------
    image:
        Path to an image or an already-loaded BGR/BGRA array.
    methods:
        Detection methods to run (see :meth:`WatermarkDetector.detect`).
    roi:
        Optional ``(x, y, w, h)`` region to confine detection to.
    color:
        Optional BGR watermark colour for the ``"color"`` method.
    mask:
        Supply your own binary mask and skip automatic detection entirely.
    algorithm:
        Inpainting backend: ``"telea"``, ``"ns"`` or ``"lama"``.
    sensitivity:
        Detection aggressiveness, ``0``–``1``.
    dilate, radius:
        Passed through to :class:`WatermarkRemover`.
    return_details:
        When ``True`` return a :class:`PipelineResult` with intermediate masks;
        otherwise just the cleaned image.
    """
    img = _load(image)
    detector = WatermarkDetector(sensitivity=sensitivity)

    if mask is None:
        detection = detector.detect(img, methods=methods, roi=roi, color=color)
        mask = detection.mask
    else:
        mask = (mask > 0).astype(np.uint8) * 255
        detection = DetectionResult(
            mask=mask,
            boxes=WatermarkDetector._bounding_boxes(mask),
            coverage=float((mask > 0).mean()),
            method="manual",
        )

    remover = WatermarkRemover(algorithm=algorithm, radius=radius, dilate=dilate)
    result = remover.remove(img, mask)

    if return_details:
        return PipelineResult(original=img, mask=mask, result=result, detection=detection)
    return result


def overlay_mask(
    image: np.ndarray, mask: np.ndarray, color: Tuple[int, int, int] = (0, 0, 255)
) -> np.ndarray:
    """Return a copy of ``image`` with ``mask`` tinted for visual inspection."""
    base = image[:, :, :3].copy() if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    tint = np.zeros_like(base)
    tint[mask > 0] = color
    return cv2.addWeighted(base, 1.0, tint, 0.5, 0)
