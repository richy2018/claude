"""Standalone FastAPI web app for watermark removal.

Run it with::

    python -m watermark_ai.webapp
    # or: uvicorn watermark_ai.webapp:app --reload

then open http://127.0.0.1:8000 and drag an image onto the page.

This app is intentionally self-contained and independent of the rest of the
repository so it can be deployed (or ignored) on its own.
"""

from __future__ import annotations

import io
import os
from typing import Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .pipeline import overlay_mask, remove_watermark

app = FastAPI(title="Watermark Removal AI", version="0.1.0")

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def _decode(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise HTTPException(status_code=400, detail="Could not decode image.")
    return img


def _encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode result.")
    return buf.tobytes()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    path = os.path.join(_STATIC_DIR, "index.html")
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/remove")
async def api_remove(
    file: UploadFile = File(...),
    algorithm: str = Form("telea"),
    sensitivity: float = Form(0.5),
    methods: str = Form("tophat,periodic"),
    preview: bool = Form(False),
) -> Response:
    """Remove the watermark from an uploaded image and return a PNG.

    When ``preview`` is true the returned PNG is the *detection overlay*
    (original with the detected watermark tinted) instead of the cleaned image,
    so the UI can show what was found.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload.")
    img = _decode(data)

    method_list = tuple(m.strip() for m in methods.split(",") if m.strip())
    try:
        details = remove_watermark(
            img,
            methods=method_list,
            algorithm=algorithm,
            sensitivity=float(sensitivity),
            return_details=True,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    out = overlay_mask(details.original, details.mask) if preview else details.result
    headers = {
        "X-Watermark-Found": str(details.found_watermark).lower(),
        "X-Watermark-Coverage": f"{details.detection.coverage:.4f}",
        "X-Watermark-Method": details.detection.method,
        "X-Watermark-Regions": str(len(details.detection.boxes)),
    }
    return Response(content=_encode_png(out), media_type="image/png", headers=headers)


def main() -> None:  # pragma: no cover - convenience launcher
    import uvicorn

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("watermark_ai.webapp:app", host=host, port=port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()
