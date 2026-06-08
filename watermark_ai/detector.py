"""Watermark detection.

Produces a binary mask marking the pixels that belong to a watermark so that
they can be inpainted away by :mod:`watermark_ai.remover`.

The detector is an *ensemble* of classic computer-vision techniques.  No single
heuristic is reliable on its own, so several complementary signals are combined:

* ``tophat``    - morphological top-hat / black-hat to isolate the thin, bright
                  or dark strokes that make up text / logo watermarks.
* ``periodic``  - frequency-domain analysis to catch tiled / repeated
                  watermarks (their regular spacing shows up as sharp peaks in
                  the FFT magnitude spectrum).
* ``color``     - distance to a user supplied watermark colour (e.g. the near
                  white of a typical semi-transparent logo).

All of the methods can be restricted to a region of interest (``roi``) when the
caller already knows roughly where the watermark sits, which dramatically
improves precision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple

import cv2
import numpy as np


BBox = Tuple[int, int, int, int]  # (x, y, w, h)


@dataclass
class DetectionResult:
    """Result of a detection pass."""

    mask: np.ndarray            # uint8, 0 / 255, same H×W as the image
    boxes: list                 # list of (x, y, w, h) bounding boxes
    coverage: float             # fraction of the image flagged as watermark
    method: str                 # which method(s) produced the mask

    @property
    def found(self) -> bool:
        return self.coverage > 0.0


class WatermarkDetector:
    """Detects watermark pixels and returns a binary mask.

    Parameters
    ----------
    sensitivity:
        ``0.0`` – ``1.0``.  Higher values flag fainter watermarks at the cost of
        more false positives.  ``0.5`` is a sensible default.
    min_area_frac:
        Connected components smaller than this fraction of the image are
        discarded as noise.
    max_area_frac:
        Components larger than this fraction are discarded – a region that big
        is almost certainly real image content, not a watermark.
    """

    def __init__(
        self,
        sensitivity: float = 0.5,
        min_area_frac: float = 2e-4,
        max_area_frac: float = 0.6,
    ) -> None:
        self.sensitivity = float(np.clip(sensitivity, 0.0, 1.0))
        self.min_area_frac = min_area_frac
        self.max_area_frac = max_area_frac

    # ------------------------------------------------------------------ public
    def detect(
        self,
        image: np.ndarray,
        methods: Sequence[str] = ("tophat", "periodic"),
        roi: Optional[BBox] = None,
        color: Optional[Sequence[int]] = None,
    ) -> DetectionResult:
        """Run the requested detection ``methods`` and merge their masks.

        Parameters
        ----------
        image:
            BGR or BGRA image as returned by :func:`cv2.imread`.
        methods:
            Any combination of ``"tophat"``, ``"periodic"``, ``"color"``,
            ``"alpha"``.
        roi:
            Optional ``(x, y, w, h)`` region to restrict detection to.
        color:
            BGR colour used by the ``"color"`` method.
        """
        if image is None or image.size == 0:
            raise ValueError("image is empty")

        h, w = image.shape[:2]
        gray = self._to_gray(image)

        combined = np.zeros((h, w), dtype=np.uint8)
        used: list = []

        for method in methods:
            if method == "tophat":
                m = self._detect_tophat(gray)
            elif method == "periodic":
                m = self._detect_periodic(gray)
            elif method == "color":
                if color is None:
                    continue
                m = self._detect_color(image, color)
            elif method == "alpha":
                m = self._detect_alpha(image)
            else:
                raise ValueError(f"unknown detection method: {method!r}")
            if m is not None and m.any():
                combined = cv2.bitwise_or(combined, m)
                used.append(method)

        if roi is not None:
            combined = self._apply_roi(combined, roi)

        combined = self._clean(combined)
        boxes = self._bounding_boxes(combined)
        coverage = float((combined > 0).mean())

        return DetectionResult(
            mask=combined,
            boxes=boxes,
            coverage=coverage,
            method="+".join(used) if used else "none",
        )

    # --------------------------------------------------------------- methods
    def _detect_tophat(self, gray: np.ndarray) -> np.ndarray:
        """Isolate thin bright/dark strokes (text & logo watermarks).

        Morphological top-hat extracts bright features smaller than the
        structuring element; black-hat extracts the dark ones.  Watermarks –
        whether lighter or darker than the underlying image – are thin relative
        to real content, so they survive this filter while large smooth regions
        do not.
        """
        h, w = gray.shape
        ksize = max(3, int(round(min(h, w) * 0.02)) | 1)  # odd kernel ~2% of side
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))

        tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
        blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
        strokes = cv2.max(tophat, blackhat)

        # Adaptive threshold driven by sensitivity. Otsu gives a baseline; the
        # sensitivity knob shifts it lower (more aggressive) or higher.
        otsu, _ = cv2.threshold(strokes, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        thresh = otsu * (1.4 - 0.9 * self.sensitivity)
        thresh = float(np.clip(thresh, 5, 250))
        _, mask = cv2.threshold(strokes, thresh, 255, cv2.THRESH_BINARY)

        # Connect neighbouring strokes into solid blobs (whole words / logos).
        connect = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, connect)
        return mask

    def _detect_periodic(self, gray: np.ndarray) -> np.ndarray:
        """Detect tiled / repeated watermarks via the FFT spectrum.

        A watermark that repeats on a regular grid produces sharp off-centre
        peaks in the magnitude spectrum.  When such peaks are present we fall
        back to a top-hat mask over the whole frame (the repetition confirms a
        watermark exists, the strokes localise it).  When no periodicity is
        found we return an empty mask so this method contributes nothing.
        """
        f = np.fft.fftshift(np.fft.fft2(gray.astype(np.float32)))
        mag = np.log1p(np.abs(f))

        # Suppress the DC component / central cross which is always strong.
        ch, cw = (s // 2 for s in mag.shape)
        mag[ch - 2 : ch + 3, :] = 0
        mag[:, cw - 2 : cw + 3] = 0

        norm = (mag - mag.mean()) / (mag.std() + 1e-6)
        peaks = norm > (7.0 - 3.0 * self.sensitivity)
        # A handful of strong, isolated peaks ⇒ periodic texture is present.
        if 2 <= int(peaks.sum()) <= 400:
            return self._detect_tophat(gray)
        return np.zeros_like(gray)

    def _detect_color(self, image: np.ndarray, color: Sequence[int]) -> np.ndarray:
        """Flag pixels close to ``color`` (BGR)."""
        bgr = image[:, :, :3].astype(np.int16)
        target = np.array(color[:3], dtype=np.int16)
        dist = np.sqrt(((bgr - target) ** 2).sum(axis=2))
        tol = 30 + 90 * self.sensitivity
        return (dist < tol).astype(np.uint8) * 255

    def _detect_alpha(self, image: np.ndarray) -> np.ndarray:
        """Use a PNG alpha channel, if present, as the watermark mask.

        Semi-transparent watermarks baked into a 4-channel PNG expose
        themselves through partially transparent pixels.
        """
        if image.ndim != 3 or image.shape[2] != 4:
            return np.zeros(image.shape[:2], dtype=np.uint8)
        alpha = image[:, :, 3]
        partial = ((alpha > 0) & (alpha < 255)).astype(np.uint8) * 255
        return partial

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _to_gray(image: np.ndarray) -> np.ndarray:
        if image.ndim == 2:
            return image
        if image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def _apply_roi(mask: np.ndarray, roi: BBox) -> np.ndarray:
        x, y, w, h = roi
        keep = np.zeros_like(mask)
        keep[y : y + h, x : x + w] = mask[y : y + h, x : x + w]
        return keep

    def _clean(self, mask: np.ndarray) -> np.ndarray:
        """Drop components that are too small (noise) or too big (content)."""
        if not mask.any():
            return mask
        total = mask.shape[0] * mask.shape[1]
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        out = np.zeros_like(mask)
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            frac = area / total
            if self.min_area_frac <= frac <= self.max_area_frac:
                out[labels == i] = 255
        return out

    @staticmethod
    def _bounding_boxes(mask: np.ndarray) -> list:
        if not mask.any():
            return []
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        boxes = []
        for i in range(1, n):
            x = int(stats[i, cv2.CC_STAT_LEFT])
            y = int(stats[i, cv2.CC_STAT_TOP])
            w = int(stats[i, cv2.CC_STAT_WIDTH])
            h = int(stats[i, cv2.CC_STAT_HEIGHT])
            boxes.append((x, y, w, h))
        return boxes
