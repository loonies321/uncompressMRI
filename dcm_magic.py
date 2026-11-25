"""
Convert Enhanced (multi-frame) DICOM MRI series into single-frame
``MR Image Storage`` instances that a treatment planning system
(Eclipse / Aria, Oncentra, Monaco, ...) can import.

The original implementation pasted each frame into a hard-coded
"reference slice" file (``etalonnoeMRI``) and hard-coded the patient
name.  This module instead derives every single-frame object from the
enhanced source itself, so patient / study / acquisition metadata is
preserved and the geometry comes from the per-frame functional groups.

Public API
----------
``convert_file(path, out_dir=None, ...) -> ConversionReport``
    Convert one enhanced (or classic multi-frame) DICOM file.

``convert_paths(paths, ...) -> list[ConversionReport]``
    Convert several files, returning one report per file.

``shamanstvo(...)``
    Deprecated backwards-compatible wrapper kept for old callers.

Licensed under the Apache License, Version 2.0.
"""

from __future__ import annotations

import copy
import io
import logging
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pydicom
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

import i18n

log = logging.getLogger(__name__)

__version__ = "2.3.0"

MR_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.4"
ENHANCED_MR_STORAGE = "1.2.840.10008.5.1.4.1.1.4.1"
ENHANCED_MR_COLOR_STORAGE = "1.2.840.10008.5.1.4.1.1.4.3"

_UID_PREFIX = "2.25."  # UUID derived, no registration required (PS3.5 B.2)
_IMPLEMENTATION_UID = generate_uid(
    prefix=_UID_PREFIX, entropy_srcs=["uncompress-mri", __version__]
)


class ConversionError(RuntimeError):
    """Raised when a file cannot be converted into importable slices."""


# ---------------------------------------------------------------------------
# Tag helpers
# ---------------------------------------------------------------------------

_TAG_POSITION = (0x0020, 0x0032)  # Image Position (Patient)
_TAG_ORIENTATION = (0x0020, 0x0037)  # Image Orientation (Patient)
_TAG_PIXEL_SPACING = (0x0028, 0x0030)
_TAG_SLICE_THICKNESS = (0x0018, 0x0050)
_TAG_SPACING_BETWEEN = (0x0018, 0x0088)
_TAG_WINDOW_CENTER = (0x0028, 0x1050)
_TAG_WINDOW_WIDTH = (0x0028, 0x1051)
_TAG_RESCALE_INTERCEPT = (0x0028, 0x1052)
_TAG_RESCALE_SLOPE = (0x0028, 0x1053)
_TAG_RESCALE_TYPE = (0x0028, 0x1054)
_TAG_FRAME_TYPE = (0x0008, 0x0008)
_TAG_STACK_ID = (0x0020, 0x9056)
_TAG_IN_STACK_POSITION = (0x0020, 0x9057)
_TAG_TEMPORAL_INDEX = (0x0020, 0x9128)
_TAG_ECHO_NUMBERS = (0x0018, 0x0086)
_TAG_DIMENSION_INDEX_VALUES = (0x0020, 0x9157)
_TAG_DIMENSION_INDEX_POINTER = (0x0020, 0x9165)

_SEQ_SHARED_GROUPS = (0x5200, 0x9229)
_SEQ_PER_FRAME_GROUPS = (0x5200, 0x9230)
_SEQ_DIMENSION_INDEX = (0x0020, 0x9222)
_SEQ_FRAME_TYPE = (0x0018, 0x9226)  # MR Image Frame Type Sequence
_SEQ_PLANE_POSITION = (0x0020, 0x9113)
_SEQ_PLANE_ORIENTATION = (0x0020, 0x9116)
_SEQ_PIXEL_MEASURES = (0x0028, 0x9110)
_SEQ_FRAME_VOI_LUT = (0x0028, 0x9132)
_SEQ_PIXEL_VALUE_TRANSFORM = (0x0028, 0x9145)
_SEQ_FRAME_CONTENT = (0x0020, 0x9111)
_SEQ_MR_ECHO = (0x0018, 0x9114)
_SEQ_MR_DIFFUSION = (0x0018, 0x9117)
_TAG_DIFFUSION_B_VALUE = (0x0018, 0x9087)

# Elements that describe the multi-frame *container* and must not end up in a
# single-frame object.
_CONTAINER_TAGS: tuple[tuple[int, int], ...] = (
    (0x7FE0, 0x0010),  # Pixel Data
    _SEQ_SHARED_GROUPS,
    _SEQ_PER_FRAME_GROUPS,
    (0x0028, 0x0008),  # Number of Frames
    (0x0020, 0x9221),  # Dimension Organization Sequence
    (0x0020, 0x9222),  # Dimension Index Sequence
    (0x0020, 0x9072),  # Frame Laterality
    (0x0028, 0x9001),  # Data Point Rows
    (0x0028, 0x9002),  # Data Point Columns
    (0x0028, 0x9003),  # Signal Domain Columns
    (0x0028, 0x9108),  # Data Representation
    (0x0008, 0x1140),  # Referenced Image Sequence (points at the container)
    (0x0008, 0x1111),  # Referenced Performed Procedure Step Sequence
)

# Enhanced-only top level attributes that have no meaning on a single frame.
_ENHANCED_ONLY_TAGS: tuple[tuple[int, int], ...] = (
    (0x0008, 0x9205),  # Pixel Presentation
    (0x0008, 0x9206),  # Volumetric Properties
    (0x0008, 0x9207),  # Volume Based Calculation Technique
    (0x0008, 0x9208),  # Complex Image Component
    (0x0008, 0x9209),  # Acquisition Contrast
)


def _first_item(ds: pydicom.Dataset, tag: tuple[int, int]) -> pydicom.Dataset | None:
    """Return the first item of the sequence at *tag*, or ``None``."""
    element = ds.get(tag)
    if element is None or element.VR != "SQ":
        return None
    sequence = element.value
    if not sequence:
        return None
    return sequence[0]


def _resolve(
    per_frame: pydicom.Dataset | None,
    shared: pydicom.Dataset | None,
    top: pydicom.Dataset,
    sequence_tag: tuple[int, int],
    element_tag: tuple[int, int],
    default: Any = None,
) -> Any:
    """Look a value up in per-frame -> shared -> top level datasets."""
    for container in (per_frame, shared):
        if container is None:
            continue
        item = _first_item(container, sequence_tag)
        if item is not None and element_tag in item:
            return item[element_tag].value
    if element_tag in top:
        return top[element_tag].value
    return default


def _as_floats(value: Any) -> tuple[float, ...] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace(",", "\\").split("\\")
    if isinstance(value, (int, float)):
        return (float(value),)
    try:
        return tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normal(orientation: Sequence[float]) -> np.ndarray:
    """Slice normal from a DICOM Image Orientation (Patient) triplet pair."""
    row = np.asarray(orientation[:3], dtype=float)
    column = np.asarray(orientation[3:6], dtype=float)
    normal = np.cross(row, column)
    norm = np.linalg.norm(normal)
    if norm == 0:
        raise ConversionError("Image Orientation (Patient) is degenerate")
    return normal / norm


# ---------------------------------------------------------------------------
# Frame metadata
# ---------------------------------------------------------------------------


@dataclass
class FrameInfo:
    index: int
    position: tuple[float, ...] | None
    orientation: tuple[float, ...] | None
    pixel_spacing: tuple[float, ...] | None
    slice_thickness: Any = None
    spacing_between_slices: Any = None
    window_center: Any = None
    window_width: Any = None
    rescale_intercept: Any = None
    rescale_slope: Any = None
    rescale_type: Any = None
    frame_type: tuple[str, ...] | None = None
    stack_id: str | None = None
    in_stack_position: int | None = None
    temporal_index: int | None = None
    echo_numbers: str | None = None
    b_value: float | None = None
    dimension_index_values: tuple[int, ...] | None = None
    extra_dimensions: tuple[tuple[tuple[int, int], int], ...] = ()
    slice_location: float | None = None


def _collect_frames(ds: pydicom.Dataset) -> list[FrameInfo]:
    """Read per-frame geometry/metadata from an enhanced DICOM dataset."""
    number_of_frames = _as_int(ds.get("NumberOfFrames")) or 1
    per_frame_sequence = ds.get(_SEQ_PER_FRAME_GROUPS)
    per_frame_items: list[pydicom.Dataset | None] = []
    if per_frame_sequence is not None and per_frame_sequence.value:
        per_frame_items = list(per_frame_sequence.value)

    if per_frame_items and len(per_frame_items) != number_of_frames:
        raise ConversionError(
            "Number of Frames (%d) does not match the number of Per-Frame "
            "Functional Groups (%d)" % (number_of_frames, len(per_frame_items))
        )
    if not per_frame_items:
        per_frame_items = [None] * number_of_frames

    shared = _first_item(ds, _SEQ_SHARED_GROUPS)
    dimension_pointers = _dimension_pointers(ds)

    frames: list[FrameInfo] = []
    for index, per_frame in enumerate(per_frame_items):
        orientation = _as_floats(
            _resolve(per_frame, shared, ds, _SEQ_PLANE_ORIENTATION, _TAG_ORIENTATION)
        )
        position = _as_floats(
            _resolve(per_frame, shared, ds, _SEQ_PLANE_POSITION, _TAG_POSITION)
        )
        pixel_spacing = _as_floats(
            _resolve(per_frame, shared, ds, _SEQ_PIXEL_MEASURES, _TAG_PIXEL_SPACING)
        )

        frame_content = _first_item(per_frame, _SEQ_FRAME_CONTENT) if per_frame else None

        frame_type_value = _resolve(
            per_frame, shared, ds, _SEQ_FRAME_TYPE, _TAG_FRAME_TYPE
        )
        if isinstance(frame_type_value, str):
            frame_type = tuple(frame_type_value.split("\\"))
        elif frame_type_value:
            frame_type = tuple(str(v) for v in frame_type_value)
        else:
            frame_type = None

        echo_numbers = None
        if frame_content is not None and _TAG_ECHO_NUMBERS in frame_content:
            echo_numbers = str(frame_content[_TAG_ECHO_NUMBERS].value)
        echo_sequence = _first_item(per_frame, _SEQ_MR_ECHO) if per_frame else None
        if (
            echo_numbers is None
            and echo_sequence is not None
            and _TAG_ECHO_NUMBERS in echo_sequence
        ):
            echo_numbers = str(echo_sequence[_TAG_ECHO_NUMBERS].value)

        diffusion = _first_item(per_frame, _SEQ_MR_DIFFUSION) if per_frame else None
        b_value = None
        if diffusion is not None and _TAG_DIFFUSION_B_VALUE in diffusion:
            try:
                b_value = float(diffusion[_TAG_DIFFUSION_B_VALUE].value)
            except (TypeError, ValueError):
                b_value = None

        dimension_values: tuple[int, ...] | None = None
        if frame_content is not None and _TAG_DIMENSION_INDEX_VALUES in frame_content:
            raw = frame_content[_TAG_DIMENSION_INDEX_VALUES].value
            if raw is not None:
                try:
                    dimension_values = tuple(int(v) for v in raw)
                except (TypeError, ValueError):
                    dimension_values = None

        info = FrameInfo(
            index=index,
            position=position,
            orientation=orientation,
            pixel_spacing=pixel_spacing,
            slice_thickness=_resolve(
                per_frame, shared, ds, _SEQ_PIXEL_MEASURES, _TAG_SLICE_THICKNESS
            ),
            spacing_between_slices=_resolve(
                per_frame, shared, ds, _SEQ_PIXEL_MEASURES, _TAG_SPACING_BETWEEN
            ),
            window_center=_resolve(
                per_frame, shared, ds, _SEQ_FRAME_VOI_LUT, _TAG_WINDOW_CENTER
            ),
            window_width=_resolve(
                per_frame, shared, ds, _SEQ_FRAME_VOI_LUT, _TAG_WINDOW_WIDTH
            ),
            rescale_intercept=_resolve(
                per_frame, shared, ds, _SEQ_PIXEL_VALUE_TRANSFORM, _TAG_RESCALE_INTERCEPT
            ),
            rescale_slope=_resolve(
                per_frame, shared, ds, _SEQ_PIXEL_VALUE_TRANSFORM, _TAG_RESCALE_SLOPE
            ),
            rescale_type=_resolve(
                per_frame, shared, ds, _SEQ_PIXEL_VALUE_TRANSFORM, _TAG_RESCALE_TYPE
            ),
            frame_type=frame_type,
            stack_id=(
                str(frame_content[_TAG_STACK_ID].value).strip()
                if frame_content is not None and _TAG_STACK_ID in frame_content
                else None
            ),
            in_stack_position=(
                _as_int(frame_content[_TAG_IN_STACK_POSITION].value)
                if frame_content is not None and _TAG_IN_STACK_POSITION in frame_content
                else None
            ),
            temporal_index=(
                _as_int(frame_content[_TAG_TEMPORAL_INDEX].value)
                if frame_content is not None and _TAG_TEMPORAL_INDEX in frame_content
                else None
            ),
            echo_numbers=echo_numbers,
            b_value=b_value,
            dimension_index_values=dimension_values,
            extra_dimensions=_extra_dimensions(dimension_pointers, dimension_values),
        )
        if info.position is not None and info.orientation is not None:
            info.slice_location = float(
                np.dot(np.asarray(info.position, dtype=float), _normal(info.orientation))
            )
        frames.append(info)

    return frames


def _dimension_pointers(ds: pydicom.Dataset) -> list[tuple[int, int]]:
    """Tags described by Dimension Index Sequence, in index order."""
    element = ds.get(_SEQ_DIMENSION_INDEX)
    if element is None or not element.value:
        return []
    pointers: list[tuple[int, int]] = []
    for item in element.value:
        pointer = item.get(_TAG_DIMENSION_INDEX_POINTER)
        if pointer is None or pointer.value is None:
            continue
        value = pointer.value
        # AT is normally a single tag, but be tolerant of multi-valued data.
        try:
            pointers.append((int(value[0]), int(value[1])))
        except (TypeError, IndexError):
            pointers.append((int(value.group), int(value.element)))
    return pointers


# Dimensions that are either already part of the series key or that would
# explode one series into hundreds (diffusion gradient directions).
_IGNORED_DIMENSIONS = {
    _TAG_IN_STACK_POSITION,
    _TAG_STACK_ID,
    _TAG_TEMPORAL_INDEX,
    _TAG_ECHO_NUMBERS,
    (0x0018, 0x9089),  # Diffusion Gradient Orientation
    (0x0018, 0x9079),  # Diffusion Directionality
}


def _extra_dimensions(
    pointers: Sequence[tuple[int, int]],
    values: Sequence[int] | None,
) -> tuple[tuple[tuple[int, int], int], ...]:
    """Dimension index values (other than in-stack position) for grouping."""
    if not pointers or not values or len(pointers) != len(values):
        return ()
    extras = []
    for pointer, value in zip(pointers, values):
        if pointer in _IGNORED_DIMENSIONS:
            continue
        extras.append((pointer, value))
    return tuple(extras)


def _ensure_geometry(
    frames: list[FrameInfo], ds: pydicom.Dataset
) -> list[str]:
    """Fill in missing geometry and report assumptions that had to be made."""
    warnings: list[str] = []

    default_orientation = _as_floats(ds.get("ImageOrientationPatient"))
    default_spacing = _as_floats(ds.get("PixelSpacing"))
    default_thickness = ds.get("SliceThickness")
    default_spacing_between = ds.get("SpacingBetweenSlices")

    missing_orientation = [f for f in frames if f.orientation is None]
    if missing_orientation:
        if default_orientation is None:
            raise ConversionError(
                "No Image Orientation (Patient) found for %d frame(s) and no "
                "top-level fallback." % len(missing_orientation)
            )
        for frame in missing_orientation:
            frame.orientation = default_orientation
        warnings.append(
            "Image Orientation (Patient) taken from the top-level dataset "
            "for %d frame(s)." % len(missing_orientation)
        )

    missing_spacing = [f for f in frames if f.pixel_spacing is None]
    if missing_spacing:
        if default_spacing is None:
            raise ConversionError("No Pixel Spacing found for %d frame(s)." % len(missing_spacing))
        for frame in missing_spacing:
            frame.pixel_spacing = default_spacing
        warnings.append(
            "Pixel Spacing taken from the top-level dataset for %d frame(s)."
            % len(missing_spacing)
        )

    for frame in frames:
        if frame.slice_thickness is None:
            frame.slice_thickness = default_thickness
        if frame.spacing_between_slices is None:
            frame.spacing_between_slices = default_spacing_between

    missing_position = [f for f in frames if f.position is None]
    if missing_position:
        if len(frames) == 1:
            raise ConversionError("Frame 1 has no Image Position (Patient).")
        warnings.append(
            "%d frame(s) have no Image Position (Patient); positions were "
            "reconstructed from the slice spacing. Verify the result before "
            "importing into the TPS." % len(missing_position)
        )
        anchors: dict[tuple[float, ...], np.ndarray] = {}
        counters: dict[tuple[float, ...], int] = {}
        for frame in frames:
            orientation_key = tuple(round(v, 4) for v in frame.orientation)
            if frame.position is not None:
                anchors.setdefault(
                    orientation_key, np.asarray(frame.position, dtype=float)
                )
                continue
            offset = counters.get(orientation_key, 0) + 1
            counters[orientation_key] = offset
            normal = _normal(frame.orientation)
            thickness = _as_floats(frame.spacing_between_slices) or _as_floats(
                frame.slice_thickness
            )
            step = float(thickness[0]) if thickness else 1.0
            position = normal * (step * offset)
            if orientation_key in anchors:
                position = position + anchors[orientation_key]
            frame.position = tuple(float(v) for v in position)

    for frame in frames:
        if frame.slice_location is None and frame.position is not None:
            frame.slice_location = float(
                np.dot(np.asarray(frame.position, dtype=float), _normal(frame.orientation))
            )

    return warnings


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def _group_key(frame: FrameInfo) -> tuple[Any, ...]:
    """Frames that share this key become one single-frame DICOM series."""
    orientation = (
        tuple(round(v, 4) for v in frame.orientation) if frame.orientation else None
    )
    return (
        frame.stack_id,
        frame.temporal_index,
        frame.echo_numbers,
        frame.b_value,
        frame.frame_type,
        orientation,
        frame.extra_dimensions,
    )


@dataclass
class _SeriesGroup:
    key: tuple[Any, ...]
    frames: list[FrameInfo] = field(default_factory=list)


def _group_frames(frames: list[FrameInfo]) -> list[_SeriesGroup]:
    groups: dict[tuple[Any, ...], _SeriesGroup] = {}
    for frame in frames:
        group = groups.setdefault(_group_key(frame), _SeriesGroup(key=_group_key(frame)))
        group.frames.append(frame)

    ordered = list(groups.values())

    def sort_key(group: _SeriesGroup) -> tuple[Any, ...]:
        first = group.frames[0]
        return (
            first.stack_id or "",
            first.temporal_index or 0,
            first.echo_numbers or "",
            first.frame_type or (),
        )

    ordered.sort(key=sort_key)
    for group in ordered:
        group.frames.sort(
            key=lambda f: (
                f.in_stack_position if f.in_stack_position is not None else 0,
                f.slice_location if f.slice_location is not None else 0.0,
                f.index,
            )
        )
    return ordered


def _series_label(group: _SeriesGroup, index: int) -> str:
    first = group.frames[0]
    parts = []
    if first.stack_id:
        parts.append("stack %s" % first.stack_id)
    if first.echo_numbers:
        parts.append("echo %s" % first.echo_numbers)
    if first.temporal_index and first.temporal_index > 1:
        parts.append("t%d" % first.temporal_index)
    if not parts:
        parts.append("series %d" % (index + 1))
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


@dataclass
class SeriesInfo:
    series_instance_uid: str
    series_number: int
    description: str
    frame_count: int
    files: list[str] = field(default_factory=list)


@dataclass
class ConversionReport:
    source: str
    output_dir: str
    series: list[SeriesInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def output_files(self) -> list[str]:
        return [path for series in self.series for path in series.files]

    @property
    def frame_count(self) -> int:
        return sum(series.frame_count for series in self.series)


def _build_base(ds: pydicom.Dataset) -> pydicom.Dataset:
    """Copy the source dataset and strip everything multi-frame specific."""
    base = copy.deepcopy(ds)
    for tag in _CONTAINER_TAGS + _ENHANCED_ONLY_TAGS:
        if tag in base:
            del base[tag]
    return base


def _pixel_bytes(
    frame: np.ndarray,
    source_bits_allocated: int | None = None,
    source_bits_stored: int | None = None,
    source_high_bit: int | None = None,
) -> tuple[bytes, int, int, int, int]:
    """Return little-endian pixel data plus bit depth and pixel representation."""
    if frame.ndim != 2:
        raise ConversionError(
            "Only single-plane grayscale frames are supported, got shape %r"
            % (frame.shape,)
        )
    if frame.dtype == np.uint8:
        bits_allocated = 8
        bits_stored = 8
    elif frame.dtype in (np.uint16, np.int16):
        bits_allocated = 16
        bits_stored = 16
    elif frame.dtype == np.uint32 or frame.dtype == np.int32:
        bits_allocated = 32
        bits_stored = 32
    else:
        raise ConversionError("Unsupported pixel data type: %s" % frame.dtype)

    # Preserve the declared bit depth (Philips enhanced MR commonly stores
    # 12 bits inside 16 allocated bits).  Only trust it when it is consistent
    # with the container width we are about to write.
    if source_bits_allocated == bits_allocated:
        if source_bits_stored and 1 <= int(source_bits_stored) <= bits_allocated:
            bits_stored = int(source_bits_stored)
        if source_high_bit is not None and 0 <= int(source_high_bit) < bits_allocated:
            high_bit = int(source_high_bit)
        else:
            high_bit = bits_stored - 1
    else:
        high_bit = bits_stored - 1

    signed = frame.dtype.kind == "i"
    kind = "i" if signed else "u"
    dtype = np.dtype("<%s%d" % (kind, bits_allocated // 8))
    payload = np.ascontiguousarray(frame, dtype=dtype)
    return payload.tobytes(), bits_allocated, bits_stored, high_bit, int(signed)


def _write_frame(
    base: pydicom.Dataset,
    frame: FrameInfo,
    pixel_data: bytes,
    bits_allocated: int,
    bits_stored: int,
    high_bit: int,
    pixel_representation: int,
    series_uid: str,
    series_number: int,
    instance_number: int,
) -> pydicom.Dataset:
    ds = copy.deepcopy(base)

    ds.SOPClassUID = MR_IMAGE_STORAGE
    ds.file_meta.MediaStorageSOPClassUID = MR_IMAGE_STORAGE
    # The series UID already contains the study UID, so a new study never
    # produces SOP Instance UIDs that Eclipse has seen before.
    ds.SOPInstanceUID = generate_uid(
        prefix=_UID_PREFIX,
        entropy_srcs=[series_uid, str(instance_number), str(frame.index)],
    )
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.ImplementationClassUID = _IMPLEMENTATION_UID
    ds.file_meta.ImplementationVersionName = "UNCOMPRESS_MRI"

    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_number
    ds.InstanceNumber = instance_number

    ds.ImagePositionPatient = list(frame.position)
    ds.ImageOrientationPatient = list(frame.orientation)
    if frame.pixel_spacing is not None:
        ds.PixelSpacing = list(frame.pixel_spacing)
    if frame.slice_thickness is not None:
        ds.SliceThickness = frame.slice_thickness
    if frame.spacing_between_slices is not None:
        ds.SpacingBetweenSlices = frame.spacing_between_slices
    if frame.slice_location is not None:
        ds.SliceLocation = "%.6f" % frame.slice_location

    if frame.frame_type:
        ds.ImageType = list(frame.frame_type)

    if frame.window_center is not None:
        ds.WindowCenter = frame.window_center
    if frame.window_width is not None:
        ds.WindowWidth = frame.window_width
    if frame.rescale_intercept is not None:
        ds.RescaleIntercept = frame.rescale_intercept
    if frame.rescale_slope is not None:
        ds.RescaleSlope = frame.rescale_slope
    if frame.rescale_type is not None:
        ds.RescaleType = frame.rescale_type

    rows = int(base.Rows)
    columns = int(base.Columns)
    ds.Rows = rows
    ds.Columns = columns
    ds.SamplesPerPixel = 1
    ds.BitsAllocated = bits_allocated
    ds.BitsStored = bits_stored
    ds.HighBit = high_bit
    ds.PixelRepresentation = pixel_representation
    ds.PixelData = pixel_data
    # Pixel Data has an ambiguous VR ("OB or OW"); set it explicitly so the
    # file can be written with an explicit VR transfer syntax.
    ds["PixelData"].VR = "OB" if bits_allocated == 8 else "OW"

    return ds


def _save(ds: pydicom.Dataset, path: str) -> None:
    try:
        ds.save_as(path, enforce_file_format=True)
    except TypeError:  # pydicom < 3.0
        ds.save_as(path, write_like_original=False)


_PIXEL_DATA_DELIMITER = b"\xfe\xff\xdd\xe0\x00\x00\x00\x00"


def _read_dataset(path: str, *, stop_before_pixels: bool = False):
    """Read a dataset, repairing a truncated pixel-data delimiter if needed."""
    try:
        return pydicom.dcmread(path, stop_before_pixels=stop_before_pixels), False
    except Exception:  # noqa: BLE001 - the retry decides whether the file is usable
        with open(path, "rb") as handle:
            data = handle.read()
        ds = pydicom.dcmread(
            io.BytesIO(data + _PIXEL_DATA_DELIMITER),
            stop_before_pixels=stop_before_pixels,
            force=True,
        )
        return ds, True


def _read_pixels(path: str):
    """Return ``(dataset, pixel_array, restored)`` for *path*.

    Some scanners (notably Siemens) write files that end right after the pixel
    data without the sequence delimiter. ``dcmread`` may accept such a file but
    decoding the pixels then fails; in that case the delimiter is appended once
    and the file is parsed again ("Siemens EOF fix").
    """
    try:
        ds, restored = _read_dataset(path)
        return ds, ds.pixel_array, restored
    except Exception as first:  # noqa: BLE001 - retried below, then re-raised
        try:
            with open(path, "rb") as handle:
                data = handle.read()
            ds = pydicom.dcmread(
                io.BytesIO(data + _PIXEL_DATA_DELIMITER), force=True
            )
            pixels = ds.pixel_array
        except Exception:  # noqa: BLE001 - not a truncation problem
            raise first
        log.warning(
            "%s: file was truncated, restored the pixel-data delimiter",
            os.path.basename(path),
        )
        return ds, pixels, True


def convert_file(
    path: str,
    out_dir: str | None = None,
    *,
    anonymize: bool = False,
    keep_study_uid: bool = False,
    keep_private_tags: bool = False,
    overwrite: bool = True,
    progress: Callable[[int, int], None] | None = None,
) -> ConversionReport:
    """Convert one enhanced / multi-frame DICOM file into single-frame slices.

    Parameters
    ----------
    path:
        Input ``.dcm`` file.
    out_dir:
        Output directory.  Defaults to ``<input name>_slices`` next to the
        input file.
    anonymize:
        Replace patient identifiers and regenerate the study UID.
    keep_study_uid:
        Reuse the source Study Instance UID. By default a new deterministic
        study UID is generated: Eclipse refuses to import a second study with
        the UID of the enhanced series that was already imported.
    keep_private_tags:
        Keep vendor private tags (dropped by default).
    overwrite:
        Allow overwriting existing files with the same name.
    progress:
        Optional callback ``progress(done, total)`` called after every slice
        is written (used by the GUI progress bar).
    """
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        raise ConversionError("File not found: %s" % path)

    if out_dir is None:
        stem, _ = os.path.splitext(os.path.basename(path))
        out_dir = os.path.join(os.path.dirname(path), stem + "_slices")
    out_dir = os.path.abspath(os.path.expanduser(out_dir))

    try:
        ds, pixel_array, restored = _read_pixels(path)
    except Exception as exc:  # pragma: no cover - depends on the file
        raise ConversionError(
            "Cannot read %s: %s\n"
            "JPEG/JPEG-2000 files need 'pylibjpeg' or 'python-gdcm'; truncated "
            "files are repaired automatically when the damage is a missing "
            "pixel-data delimiter." % (path, exc)
        ) from exc

    sop_class = str(ds.get("SOPClassUID", ""))
    if sop_class not in (ENHANCED_MR_STORAGE, ENHANCED_MR_COLOR_STORAGE, "", MR_IMAGE_STORAGE):
        log.warning(
            "%s: unexpected SOP Class %s (%s); attempting conversion anyway",
            os.path.basename(path),
            sop_class,
            getattr(ds.get("SOPClassUID"), "name", "unknown"),
        )

    if pixel_array.ndim == 2:
        pixel_array = pixel_array[np.newaxis, ...]

    number_of_frames = _as_int(ds.get("NumberOfFrames")) or 1
    if pixel_array.shape[0] != number_of_frames:
        raise ConversionError(
            "Decoded %d frame(s) but Number of Frames is %d"
            % (pixel_array.shape[0], number_of_frames)
        )
    if ds.get("SamplesPerPixel", 1) != 1:
        raise ConversionError(
            "Color enhanced MR images are not supported by the TPS importer"
        )

    frames = _collect_frames(ds)
    warnings = _ensure_geometry(frames, ds)
    if restored:
        warnings.append(
            "The file was truncated: the pixel-data delimiter was restored "
            "(Siemens EOF fix)."
        )

    base = _build_base(ds)
    if not keep_private_tags:
        base.remove_private_tags()
    base.Rows = int(pixel_array.shape[1])
    base.Columns = int(pixel_array.shape[2])

    source_study_uid = str(ds.get("StudyInstanceUID", ""))
    source_series_uid = str(ds.get("SeriesInstanceUID", ""))
    if not source_study_uid or not source_series_uid:
        raise ConversionError("Study/Series Instance UID missing from %s" % path)

    if anonymize:
        base.PatientName = "ANONYMOUS"
        base.PatientID = "ANONYMOUS"
        base.PatientBirthDate = ""
        base.PatientSex = ""
        base.PatientAge = ""
        base.PatientWeight = ""
        base.InstitutionName = ""
        base.InstitutionAddress = ""
        base.ReferringPhysicianName = ""
        base.PerformingPhysicianName = ""
        base.OperatorsName = ""
        base.StationName = ""
        base.StudyID = ""
        base.AccessionNumber = ""

    if anonymize or not keep_study_uid:
        study_uid = generate_uid(
            prefix=_UID_PREFIX,
            entropy_srcs=["study", source_study_uid, source_series_uid],
        )
        base.StudyInstanceUID = study_uid
        if "FrameOfReferenceUID" in base:
            base.FrameOfReferenceUID = generate_uid(
                prefix=_UID_PREFIX,
                entropy_srcs=["for", source_study_uid, str(base.FrameOfReferenceUID)],
            )
    else:
        study_uid = source_study_uid

    base.StudyInstanceUID = study_uid

    groups = _group_frames(frames)
    if not groups:
        raise ConversionError("No frames found in %s" % path)

    base_series_number = _as_int(ds.get("SeriesNumber")) or 1
    base_description = str(ds.get("SeriesDescription", "") or "")
    multiple = len(groups) > 1
    source_bits_allocated = _as_int(ds.get("BitsAllocated"))
    source_bits_stored = _as_int(ds.get("BitsStored"))
    source_high_bit = _as_int(ds.get("HighBit"))

    os.makedirs(out_dir, exist_ok=True)

    report = ConversionReport(
        source=path, output_dir=out_dir, warnings=list(warnings)
    )
    written = 0
    total_frames = len(frames)

    for group_index, group in enumerate(groups):
        series_number = base_series_number + group_index
        series_uid = generate_uid(
            prefix=_UID_PREFIX,
            entropy_srcs=[
                "series",
                study_uid,
                source_series_uid,
                str(series_number),
                repr(_group_key(group.frames[0])),
            ],
        )
        description = base_description
        if multiple:
            suffix = _series_label(group, group_index)
            description = (
                "%s [%s]" % (base_description, suffix) if base_description else suffix
            )

        series_info = SeriesInfo(
            series_instance_uid=series_uid,
            series_number=series_number,
            description=description,
            frame_count=len(group.frames),
        )

        for instance_number, frame in enumerate(group.frames, start=1):
            (
                pixel_data,
                bits_allocated,
                bits_stored,
                high_bit,
                pixel_representation,
            ) = _pixel_bytes(
                pixel_array[frame.index],
                source_bits_allocated,
                source_bits_stored,
                source_high_bit,
            )
            out_ds = _write_frame(
                base=base,
                frame=frame,
                pixel_data=pixel_data,
                bits_allocated=bits_allocated,
                bits_stored=bits_stored,
                high_bit=high_bit,
                pixel_representation=pixel_representation,
                series_uid=series_uid,
                series_number=series_number,
                instance_number=instance_number,
            )
            out_ds.SeriesDescription = description

            filename = "IM_%03d_%04d.dcm" % (series_number, instance_number)
            output_path = os.path.join(out_dir, filename)
            if not overwrite and os.path.exists(output_path):
                raise ConversionError("Refusing to overwrite %s" % output_path)
            _save(out_ds, output_path)
            series_info.files.append(output_path)
            written += 1
            if progress is not None:
                progress(written, total_frames)

        report.series.append(series_info)
        log.info(
            "series %d '%s': %d slice(s)",
            series_number,
            description,
            series_info.frame_count,
        )

    _verify_outputs(report)
    return report


def _verify_outputs(report: ConversionReport) -> None:
    """Sanity-check the written files (counts, pixel length, geometry)."""
    for series in report.series:
        positions: set[tuple[float, ...]] = set()
        for path in series.files:
            ds = pydicom.dcmread(path)
            expected = int(ds.Rows) * int(ds.Columns) * (int(ds.BitsAllocated) // 8)
            if len(ds.PixelData) != expected:
                raise ConversionError(
                    "%s: PixelData is %d bytes, expected %d"
                    % (path, len(ds.PixelData), expected)
                )
            if "ImagePositionPatient" in ds:
                positions.add(tuple(float(v) for v in ds.ImagePositionPatient))
        if len(positions) > 1 and len(positions) != len(series.files):
            report.warnings.append(
                "Series %d contains duplicate slice positions; check the source "
                "series for multiple echoes or temporal positions."
                % series.series_number
            )


def convert_paths(
    paths: Iterable[str],
    out_dir: str | None = None,
    **kwargs: Any,
) -> list[ConversionReport]:
    """Convert several files; one report per input file."""
    paths = list(paths)
    reports = []
    for path in paths:
        target = out_dir
        if out_dir is not None and len(paths) > 1:
            stem, _ = os.path.splitext(os.path.basename(path))
            target = os.path.join(out_dir, stem)
        reports.append(convert_file(path, target, **kwargs))
    return reports


def shamanstvo(multifile: str, normal_files_folder: str | None = None) -> list[str]:
    """Deprecated wrapper around :func:`convert_file`.

    The ``normal_files_folder`` ("etalon") argument is ignored: slices are now
    built from the source file instead of being pasted into a foreign template.
    """
    if normal_files_folder:
        log.warning(
            "The template folder argument is obsolete and will be ignored. "
            "Slices are now generated from the enhanced file itself."
        )
    return convert_file(multifile).output_files


def describe(path: str, *, compact: bool = False, lang: str = "ru") -> str:
    """Return a short human readable summary of a DICOM file."""
    ds, _restored = _read_dataset(path, stop_before_pixels=True)
    frames = _as_int(ds.get("NumberOfFrames")) or 1
    sop_class = getattr(ds.get("SOPClassUID"), "name", "unknown")
    rows = int(ds.get("Rows", 0))
    columns = int(ds.get("Columns", 0))
    bits = int(ds.get("BitsAllocated", 0))
    series = str(ds.get("SeriesDescription", "") or "")
    if compact:
        parts = [
            i18n.t(lang, "frames_n", n=frames),
            "%d×%d" % (rows, columns),
            i18n.t(lang, "bits_n", n=bits),
        ]
        if series:
            parts.append(series)
        return "%s — %s\n%s" % (os.path.basename(path), sop_class, " · ".join(parts))
    return (
        "%s\n  SOP class: %s\n  frames: %d\n  %dx%d, %d bit\n  series: %s"
        % (
            os.path.basename(path),
            sop_class,
            frames,
            rows,
            columns,
            bits,
            series,
        )
    )
