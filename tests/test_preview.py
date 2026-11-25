"""Preview rendering: one slice at a time, plain PPM, no Pillow."""

from __future__ import annotations

import numpy as np

import preview
from dcm_magic import convert_file


def _ppm_header(data: bytes) -> tuple[int, int]:
    assert data.startswith(b"P6\n")
    _, size, maxval = data.split(b"\n", 3)[:3]
    width, height = (int(value) for value in size.split(b" "))
    assert maxval == b"255"
    return width, height


def test_render_converted_slice(tmp_path, enhanced_file):
    out = tmp_path / "out"
    report = convert_file(enhanced_file["path"], str(out))

    data = preview.render_ppm(report.output_files[0])
    width, height = _ppm_header(data)
    assert width == enhanced_file["columns"]
    assert height == enhanced_file["rows"]
    assert len(data) == len(b"P6\n%d %d\n255\n" % (width, height)) + width * height * 3


def test_render_is_downscaled(tmp_path, enhanced_file):
    out = tmp_path / "out"
    report = convert_file(enhanced_file["path"], str(out))

    data = preview.render_ppm(report.output_files[0], max_size=4)
    width, height = _ppm_header(data)
    assert max(width, height) <= 4


def test_render_uses_dicom_window(tmp_path, enhanced_file):
    out = tmp_path / "out"
    report = convert_file(enhanced_file["path"], str(out))
    path = report.output_files[0]

    import pydicom

    dataset = pydicom.dcmread(path)
    dataset.WindowCenter = 500
    dataset.WindowWidth = 100
    dataset.save_as(path, enforce_file_format=True)

    data = preview.render_ppm(path)
    pixels = np.frombuffer(data.split(b"\n", 3)[3], dtype=np.uint8)
    # Everything below 450 must be black, everything above 550 white.
    assert pixels.min() == 0
    assert pixels.max() == 255
