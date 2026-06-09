"""Command-line interface for watermark_ai.

Examples
--------
Remove a watermark, auto-detecting it::

    python -m watermark_ai.cli input.jpg -o clean.png

Save a side-by-side debug image showing what was detected::

    python -m watermark_ai.cli input.jpg -o clean.png --debug debug.png

Confine detection to a corner and use a known watermark colour::

    python -m watermark_ai.cli input.jpg -o clean.png --roi 600 20 200 80 --color 255 255 255
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

import cv2
import numpy as np

from .pipeline import overlay_mask, remove_watermark


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="watermark_ai",
        description="Detect and remove watermarks from images.",
    )
    p.add_argument("input", help="path to the watermarked image")
    p.add_argument("-o", "--output", required=True, help="path to write the cleaned image")
    p.add_argument(
        "-m",
        "--methods",
        nargs="+",
        default=["tophat", "periodic"],
        choices=["tophat", "periodic", "color", "alpha"],
        help="detection methods to run (default: tophat periodic)",
    )
    p.add_argument(
        "-a",
        "--algorithm",
        default="telea",
        choices=["telea", "ns", "lama"],
        help="inpainting algorithm (default: telea)",
    )
    p.add_argument(
        "-s",
        "--sensitivity",
        type=float,
        default=0.5,
        help="detection sensitivity 0..1 (default: 0.5)",
    )
    p.add_argument("--dilate", type=int, default=2, help="grow mask by N px (default: 2)")
    p.add_argument("--radius", type=int, default=3, help="inpaint radius (default: 3)")
    p.add_argument(
        "--roi",
        type=int,
        nargs=4,
        metavar=("X", "Y", "W", "H"),
        help="restrict detection to this region",
    )
    p.add_argument(
        "--color",
        type=int,
        nargs=3,
        metavar=("B", "G", "R"),
        help="watermark colour for the 'color' method",
    )
    p.add_argument(
        "--mask",
        help="use this binary mask image instead of auto-detection",
    )
    p.add_argument(
        "--debug",
        help="also write a side-by-side image (original | detection | result)",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    user_mask = None
    if args.mask:
        user_mask = cv2.imread(args.mask, cv2.IMREAD_GRAYSCALE)
        if user_mask is None:
            print(f"error: could not read mask {args.mask!r}", file=sys.stderr)
            return 2

    try:
        details = remove_watermark(
            args.input,
            methods=tuple(args.methods),
            roi=tuple(args.roi) if args.roi else None,
            color=tuple(args.color) if args.color else None,
            mask=user_mask,
            algorithm=args.algorithm,
            sensitivity=args.sensitivity,
            dilate=args.dilate,
            radius=args.radius,
            return_details=True,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not cv2.imwrite(args.output, details.result):
        print(f"error: could not write {args.output!r}", file=sys.stderr)
        return 2

    det = details.detection
    if det.found:
        print(
            f"Detected watermark via [{det.method}]: "
            f"{len(det.boxes)} region(s), {det.coverage * 100:.2f}% of pixels."
        )
    else:
        print("No watermark detected - wrote a copy of the input.")
    print(f"Wrote cleaned image to {args.output}")

    if args.debug:
        orig = details.original[:, :, :3] if details.original.ndim == 3 else details.original
        result = details.result[:, :, :3] if details.result.ndim == 3 else details.result
        vis = overlay_mask(details.original, details.mask)
        strip = np.hstack([orig, vis, result])
        cv2.imwrite(args.debug, strip)
        print(f"Wrote debug strip to {args.debug}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
