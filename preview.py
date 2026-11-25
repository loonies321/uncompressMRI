"""One-slice preview for the window: decode exactly one file at a time.

A real MRI series can be a gigabyte with thousands of frames, so nothing is
preloaded: the slider addresses the slices produced by the converter (one small
file per slice) and only the requested file is decoded. The image is encoded as
a binary PPM, which Tk renders natively - no Pillow, no extra packages.
"""

from __future__ import annotations

import numpy as np
import pydicom

MAX_SIZE = 200


def _window(dataset, array) -> tuple[float, float]:
    """Return the (low, high) display range for *array*."""
    center = dataset.get("WindowCenter")
    width = dataset.get("WindowWidth")
    try:
        if isinstance(center, (list, tuple)):
            center = center[0]
        if isinstance(width, (list, tuple)):
            width = width[0]
        center = float(center)
        width = float(width)
    except (TypeError, ValueError):
        center = width = 0.0
    if width > 0:
        return center - width / 2.0, center + width / 2.0
    low, high = np.percentile(array, (1.0, 99.0))
    if high - low < 1:
        high = low + 1
    return float(low), float(high)


def render_ppm(path: str, max_size: int = MAX_SIZE) -> bytes:
    """Return a binary PPM (P6) for one DICOM slice, downscaled to *max_size*."""
    dataset = pydicom.dcmread(path)
    array = dataset.pixel_array.astype(np.float32)
    if array.ndim == 3:  # a multi-frame source file: preview its first frame
        array = array[0]
    slope = float(dataset.get("RescaleSlope", 1) or 1)
    intercept = float(dataset.get("RescaleIntercept", 0) or 0)
    if slope != 1.0 or intercept != 0.0:
        array = array * slope + intercept
    low, high = _window(dataset, array)
    scaled = np.clip((array - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)
    height, width = scaled.shape
    scale = max_size / float(max(height, width))
    if scale < 1.0:
        # Nearest-neighbour resize with fractional steps: keeps the whole slice
        # visible at exactly max_size pixels and costs a couple of milliseconds.
        new_h = max(1, int(round(height * scale)))
        new_w = max(1, int(round(width * scale)))
        rows = (np.arange(new_h) * (height / float(new_h))).astype(np.intp)
        cols = (np.arange(new_w) * (width / float(new_w))).astype(np.intp)
        scaled = scaled[rows][:, cols]
    height, width = scaled.shape
    rgb = np.repeat(scaled[:, :, None], 3, axis=2)
    return b"P6\n%d %d\n255\n" % (width, height) + rgb.tobytes()
