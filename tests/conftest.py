"""Test fixtures: build a synthetic Enhanced MR Image Storage file.

The builder mimics a Philips enhanced MR series: several stacks (localizer
planes) with per-frame functional groups, private-ish values and 12-bit pixel
data stored in 16 allocated bits.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian

STUDY_UID = "1.3.46.670589.11.99999.5.0.1.2024010100000000001"
SERIES_UID = "1.3.46.670589.11.99999.5.0.2.2024010100000000002"
FRAME_OF_REFERENCE_UID = "1.3.46.670589.11.99999.5.0.3.2024010100000000003"


@dataclass
class Stack:
    stack_id: str
    orientation: tuple[float, float, float, float, float, float]
    origin: tuple[float, float, float]
    normal: tuple[float, float, float]
    slices: int
    spacing: float = 5.0


def _item(*elements: tuple[tuple[int, int], str, object]) -> Dataset:
    ds = Dataset()
    for tag, vr, value in elements:
        ds.add_new(tag, vr, value)
    return ds


def build_enhanced_file(
    path,
    stacks: list[Stack] | None = None,
    rows: int = 16,
    columns: int = 16,
    patient_name: str = "TEST^PATIENT",
    patient_id: str = "TESTID",
    b_value_by_frame: dict[int, float] | None = None,
    modality: str = "MR",
    sop_class: str = "1.2.840.10008.5.1.4.1.1.4.1",
    frame_type_sequence_tag: tuple[int, int] = (0x0018, 0x9226),
    image_type: list[str] | None = None,
    dimension_pointers: tuple[tuple[int, int], ...] = ((0x0020, 0x9057),),
    dimension_values_by_frame: dict[int, tuple[int, ...]] | None = None,
    specific_character_set: str | None = None,
) -> dict:
    """Write a synthetic enhanced MR/CT file and return bookkeeping info."""
    if stacks is None:
        stacks = [
            Stack("1", (0.0, 1.0, 0.0, 0.0, 0.0, -1.0), (10.0, -20.0, 30.0), (-1.0, 0.0, 0.0), 3),
            Stack("2", (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), (-10.0, 0.0, 40.0), (0.0, 0.0, 1.0), 2, 7.5),
        ]

    frames: list[tuple[Stack, int, tuple[float, float, float]]] = []
    for stack in stacks:
        for index in range(stack.slices):
            position = tuple(
                stack.origin[axis] + stack.normal[axis] * stack.spacing * index
                for axis in range(3)
            )
            frames.append((stack, index, position))

    total = len(frames)
    pixels = np.arange(total * rows * columns, dtype=np.uint16).reshape(
        total, rows, columns
    ) % 4096

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = sop_class
    file_meta.MediaStorageSOPInstanceUID = "1.3.46.670589.11.99999.5.0.4.1"
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = "1.2.826.0.1.3680043.8.498.1"

    ds = Dataset()
    ds.file_meta = file_meta
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = "1.3.46.670589.11.99999.5.0.4.1"
    ds.StudyInstanceUID = STUDY_UID
    ds.SeriesInstanceUID = SERIES_UID
    ds.FrameOfReferenceUID = FRAME_OF_REFERENCE_UID
    ds.Modality = modality
    ds.Manufacturer = "Philips Medical Systems"
    ds.ManufacturerModelName = "Achieva"
    ds.InstitutionName = "TEST HOSPITAL"
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.PatientBirthDate = "19800101"
    ds.PatientSex = "M"
    if specific_character_set:
        ds.SpecificCharacterSet = specific_character_set
    ds.StudyDate = "20240101"
    ds.StudyTime = "120000"
    ds.SeriesDate = "20240101"
    ds.SeriesTime = "120500"
    ds.ContentDate = "20240101"
    ds.ContentTime = "120500"
    ds.StudyID = "1"
    ds.SeriesNumber = 12
    ds.SeriesDescription = "Synthetic enhanced"
    ds.AccessionNumber = "ACC123"
    ds.BodyPartExamined = "HEAD"
    ds.ImageType = image_type or (
        ["ORIGINAL", "PRIMARY", "AXIAL"] if modality == "CT"
        else ["ORIGINAL", "PRIMARY", "T1", "NONE"]
    )
    ds.PixelPresentation = "MONOCHROME"
    ds.VolumetricProperties = "VOLUME"
    ds.VolumeBasedCalculationTechnique = "NONE"
    ds.ComplexImageComponent = "MAGNITUDE"
    ds.AcquisitionContrast = "T1"
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = rows
    ds.Columns = columns
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.NumberOfFrames = total
    ds.PixelData = pixels.tobytes()

    ds.DimensionOrganizationSequence = Sequence(
        [_item(((0x0020, 0x9164), "UI", "1.3.46.670589.11.99999.5.0.5"))]
    )
    ds.DimensionIndexSequence = Sequence(
        [
            _item(
                ((0x0020, 0x9164), "UI", "1.3.46.670589.11.99999.5.0.5"),
                ((0x0020, 0x9165), "AT", pointer),
            )
            for pointer in dimension_pointers
        ]
    )

    shared_frame_type = _item(
        ((0x0008, 0x9007), "CS", ["ORIGINAL", "PRIMARY", "T1", "NONE"]),
        ((0x0008, 0x9205), "CS", "MONOCHROME"),
        ((0x0008, 0x9206), "CS", "VOLUME"),
        ((0x0008, 0x9207), "CS", "NONE"),
        ((0x0008, 0x9208), "CS", "MAGNITUDE"),
        ((0x0008, 0x9209), "CS", "T1"),
    )
    ds.SharedFunctionalGroupsSequence = Sequence(
        [
            _item(
                (frame_type_sequence_tag, "SQ", Sequence([shared_frame_type])),
                ((0x0028, 0x9110), "SQ", Sequence([
                    _item(
                        ((0x0018, 0x0050), "DS", "5"),
                        ((0x0028, 0x0030), "DS", ["0.5", "0.5"]),
                    )
                ])),
            )
        ]
    )

    per_frame: list[Dataset] = []
    for frame_index, (stack, index, position) in enumerate(frames):
        content = _item(
            ((0x0020, 0x9056), "SH", stack.stack_id),
            ((0x0020, 0x9057), "UL", index + 1),
            ((0x0020, 0x9128), "UL", 1),
        )
        if dimension_values_by_frame and frame_index in dimension_values_by_frame:
            content.add_new(
                (0x0020, 0x9157),
                "UL",
                list(dimension_values_by_frame[frame_index]),
            )
        frame_item = _item(
                ((0x0020, 0x9111), "SQ", Sequence([content])),
                ((0x0020, 0x9113), "SQ", Sequence([
                    _item(((0x0020, 0x0032), "DS", list(position)))
                ])),
                ((0x0020, 0x9116), "SQ", Sequence([
                    _item(((0x0020, 0x0037), "DS", list(stack.orientation)))
                ])),
                ((0x0028, 0x9110), "SQ", Sequence([
                    _item(
                        ((0x0018, 0x0050), "DS", "5"),
                        ((0x0018, 0x0088), "DS", str(stack.spacing)),
                        ((0x0028, 0x0030), "DS", ["0.5", "0.5"]),
                    )
                ])),
                ((0x0028, 0x9132), "SQ", Sequence([
                    _item(
                        ((0x0028, 0x1050), "DS", str(1000 + frame_index)),
                        ((0x0028, 0x1051), "DS", str(2000 + frame_index)),
                    )
                ])),
                ((0x0028, 0x9145), "SQ", Sequence([
                    _item(
                        ((0x0028, 0x1052), "DS", "0"),
                        ((0x0028, 0x1053), "DS", "2.5"),
                        ((0x0028, 0x1054), "LO", "normalized"),
                    )
                ])),
            )
        if b_value_by_frame and frame_index in b_value_by_frame:
            frame_item.add_new(
                (0x0018, 0x9117),
                "SQ",
                Sequence(
                    [
                        _item(
                            (
                                (0x0018, 0x9087),
                                "FD",
                                float(b_value_by_frame[frame_index]),
                            )
                        )
                    ]
                ),
            )
        per_frame.append(frame_item)
    ds.PerFrameFunctionalGroupsSequence = Sequence(per_frame)

    ds.save_as(str(path), enforce_file_format=True)
    return {
        "pixels": pixels,
        "frames": frames,
        "path": str(path),
        "rows": rows,
        "columns": columns,
        "patient_name": patient_name,
        "patient_id": patient_id,
    }


@pytest.fixture
def enhanced_file(tmp_path):
    path = tmp_path / "enhanced.dcm"
    return build_enhanced_file(path)


@pytest.fixture
def enhanced_ct_file(tmp_path):
    path = tmp_path / "enhanced_ct.dcm"
    return build_enhanced_file(
        path,
        modality="CT",
        sop_class="1.2.840.10008.5.1.4.1.1.2.1",
        frame_type_sequence_tag=(0x0018, 0x9329),
    )
