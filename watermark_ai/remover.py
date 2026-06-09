"""Watermark removal via inpainting.

Given an image and a binary mask (from :mod:`watermark_ai.detector` or supplied
by the caller) the remover reconstructs the masked pixels from the surrounding
content so the watermark disappears.

Two backends are available:

* ``opencv``  - classic Telea / Navier-Stokes inpainting.  Always available,
                fast, no model weights, and works fully offline.
* ``lama``    - optional deep-learning inpainting (LaMa) via the
                ``simple-lama-inpainting`` package.  Used only when installed
                and explicitly requested; it produces noticeably cleaner
                results on large or textured watermarks.
"""

from __future__ import annotations

from typing import Literal

import cv2
import numpy as np


Algorithm = Literal["telea", "ns", "lama"]


class WatermarkRemover:
    """Removes watermark pixels by inpainting the masked region.

    Parameters
    ----------
    algorithm:
        ``"telea"`` (fast marching, default), ``"ns"`` (Navier-Stokes) or
        ``"lama"`` (deep learning, optional).
    radius:
        Inpainting neighbourhood radius in pixels for the OpenCV backends.
    dilate:
        Number of pixels to grow the mask before inpainting.  A little dilation
        ensures faint anti-aliased watermark edges are fully covered.
    """

    def __init__(
        self,
        algorithm: Algorithm = "telea",
        radius: int = 3,
        dilate: int = 2,
    ) -> None:
        self.algorithm = algorithm
        self.radius = int(radius)
        self.dilate = int(dilate)

    # ------------------------------------------------------------------ public
    def remove(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Return ``image`` with the masked watermark removed.

        ``image`` may be BGR or BGRA; the output keeps the same channel layout.
        ``mask`` is any non-zero/zero array the same height & width as ``image``.
        """
        if image is None or image.size == 0:
            raise ValueError("image is empty")
        if mask is None or mask.shape[:2] != image.shape[:2]:
            raise ValueError("mask shape does not match image")

        bin_mask = (mask > 0).astype(np.uint8) * 255
        if self.dilate > 0 and bin_mask.any():
            k = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (2 * self.dilate + 1, 2 * self.dilate + 1)
            )
            bin_mask = cv2.dilate(bin_mask, k)

        if not bin_mask.any():
            return image.copy()

        # Preserve / strip alpha around the BGR-only inpainting core.
        alpha = None
        if image.ndim == 3 and image.shape[2] == 4:
            alpha = image[:, :, 3]
            bgr = image[:, :, :3].copy()
        else:
            bgr = image.copy()

        if self.algorithm == "lama":
            result = self._inpaint_lama(bgr, bin_mask)
        else:
            flag = cv2.INPAINT_TELEA if self.algorithm == "telea" else cv2.INPAINT_NS
            result = cv2.inpaint(bgr, bin_mask, self.radius, flag)

        if alpha is not None:
            # Where the watermark lived, force the alpha back to fully opaque so
            # the reconstructed pixels actually show.
            alpha = alpha.copy()
            alpha[bin_mask > 0] = 255
            result = np.dstack([result, alpha])
        return result

    # --------------------------------------------------------------- backends
    def _inpaint_lama(self, bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
        try:
            from simple_lama_inpainting import SimpleLama
            from PIL import Image
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "The 'lama' backend requires the 'simple-lama-inpainting' "
                "package. Install it or use algorithm='telea'."
            ) from exc

        lama = SimpleLama()
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        out = lama(Image.fromarray(rgb), Image.fromarray(mask).convert("L"))
        out = np.array(out)[:, :, :3]
        return cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
