"""watermark_ai - detect and remove watermarks from images.

Quick start
-----------
>>> from watermark_ai import remove_watermark
>>> import cv2
>>> clean = remove_watermark("watermarked.jpg")
>>> cv2.imwrite("clean.png", clean)

Public API
----------
* :func:`remove_watermark`  - one-call detect → remove pipeline.
* :class:`WatermarkDetector` - produce a watermark mask.
* :class:`WatermarkRemover`  - inpaint a masked watermark away.
"""

from .detector import DetectionResult, WatermarkDetector
from .pipeline import PipelineResult, overlay_mask, remove_watermark
from .remover import WatermarkRemover

__version__ = "0.1.0"

__all__ = [
    "remove_watermark",
    "overlay_mask",
    "WatermarkDetector",
    "WatermarkRemover",
    "DetectionResult",
    "PipelineResult",
    "__version__",
]
