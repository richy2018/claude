# Watermark Removal AI

Detects a watermark in an image and removes it by inpainting the watermark
pixels from the surrounding content. Ships with a **Python API**, a **CLI**, and
a **drag-and-drop web app**.

![before / detected / after](samples/demo_before_after.png)

*Left → right: watermarked input, the watermark the detector found (red), and
the cleaned result. On the synthetic demo this lifts PSNR from ~25 dB to ~43 dB.*

---

## How it works

It's a classic two-stage **detect → remove** pipeline:

1. **Detection** (`detector.py`) — an ensemble of computer-vision signals builds
   a binary mask of the watermark pixels:
   - `tophat` — morphological top-hat / black-hat isolates the thin bright/dark
     strokes that make up text and logo watermarks.
   - `periodic` — FFT analysis catches **tiled / repeated** watermarks (regular
     spacing shows up as sharp peaks in the magnitude spectrum).
   - `color` — distance to a known watermark colour (e.g. near-white logos).
   - `alpha` — uses a PNG's transparency channel directly.
   Components that are too small (noise) or too large (real content) are dropped.

2. **Removal** (`remover.py`) — the masked region is reconstructed with
   inpainting:
   - `telea` (default) and `ns` — fast, offline OpenCV inpainting.
   - `lama` — optional deep-learning inpainting (LaMa) for cleaner results on
     large/textured watermarks; used only if `simple-lama-inpainting` is
     installed.

No watermark detected ⇒ the original is returned unchanged.

---

## Install

```bash
pip install -r watermark_ai/requirements.txt
```

The core (detection + OpenCV inpainting) only needs `opencv-python-headless`,
`numpy`, and `pillow`. FastAPI/uvicorn are only required for the web app.

## Python API

```python
import cv2
from watermark_ai import remove_watermark

clean = remove_watermark("watermarked.jpg")        # auto-detect + remove
cv2.imwrite("clean.png", clean)

# Inspect what was detected:
res = remove_watermark("watermarked.jpg", return_details=True)
print(res.found_watermark, res.detection.coverage, res.detection.boxes)

# Confine detection to a corner and use a known colour + deep inpainting:
clean = remove_watermark(
    "watermarked.jpg",
    roi=(600, 20, 200, 80),
    color=(255, 255, 255),      # BGR
    algorithm="lama",
)
```

## Command line

```bash
python -m watermark_ai.cli input.jpg -o clean.png
python -m watermark_ai.cli input.jpg -o clean.png --debug strip.png
python -m watermark_ai.cli input.jpg -o clean.png \
    --roi 600 20 200 80 --color 255 255 255 --algorithm ns --sensitivity 0.7
```

Pass your own mask to skip auto-detection: `--mask mask.png`.

## Web app

```bash
python -m watermark_ai.webapp        # http://127.0.0.1:8000
```

Drag an image in, optionally **Preview detection** to see what was found, tweak
sensitivity / algorithm, then **Remove watermark** and download the result.
Images are processed on the server and never persisted.

---

## Tips & limits

- **Sensitivity** (`0`–`1`) trades recall for false positives. If part of the
  watermark survives, raise it; if real content gets blurred, lower it or pass a
  `roi`.
- The classic backends excel at **text / line / logo** watermarks. For a large
  watermark over highly textured photos, the `lama` backend reconstructs better.
- You always get the cleanest result by giving an explicit `roi` or `mask` — the
  detector is a convenience, not magic.
- Only run this on images you have the right to modify.

## Tests

```bash
python -m pytest tests/test_watermark_ai.py -v
```

The tests are quantitative: they watermark a synthetic image, remove it, and
assert the reconstruction is measurably closer to the original (higher PSNR,
mask recall vs. ground truth), so a regression that stops actually removing
watermarks fails the build.
