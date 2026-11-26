from __future__ import annotations

import glob
import os
import pathlib

import numpy as np
import pydicom
import pytest
from conftest import (
    FRAME_OF_REFERENCE_UID,
    STUDY_UID,
    Stack,
    build_enhanced_file,
)

import dcm_magic
from dcm_magic import ConversionError, convert_file

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_all(directory):
    return [pydicom.dcmread(p) for p in sorted(glob.glob(os.path.join(directory, "*.dcm")))]


def test_splits_stacks_into_separate_series(tmp_path, enhanced_file):
    out = tmp_path / "out"
    report = convert_file(enhanced_file["path"], str(out))

    assert report.frame_count == 5
    assert len(report.series) == 2
    assert [s.frame_count for s in report.series] == [3, 2]
    assert len(report.output_files) == 5

    datasets = _read_all(str(out))
    assert len({ds.SeriesInstanceUID for ds in datasets}) == 2
    assert len({ds.SOPInstanceUID for ds in datasets}) == 5


def test_pixels_are_preserved_exactly(tmp_path, enhanced_file):
    out = tmp_path / "out"
    convert_file(enhanced_file["path"], str(out))
    pixels = enhanced_file["pixels"]

    for ds in _read_all(str(out)):
        # Match the source frame by its slice position.
        source_index = next(
            i
            for i, (_, _, position) in enumerate(enhanced_file["frames"])
            if np.allclose(
                [float(v) for v in ds.ImagePositionPatient], position, atol=1e-6
            )
        )
        np.testing.assert_array_equal(ds.pixel_array, pixels[source_index])


def test_study_and_geometry_are_consistent(tmp_path, enhanced_file):
    out = tmp_path / "out"
    convert_file(enhanced_file["path"], str(out))
    datasets = _read_all(str(out))

    # A new study UID: Eclipse refuses a second study with the UID of the
    # enhanced series that was already imported.
    study_uids = {str(ds.StudyInstanceUID) for ds in datasets}
    assert len(study_uids) == 1
    assert study_uids.pop() != STUDY_UID
    assert all(str(ds.FrameOfReferenceUID) != FRAME_OF_REFERENCE_UID for ds in datasets)
    assert len({str(ds.FrameOfReferenceUID) for ds in datasets}) == 1
    assert all(ds.SOPClassUID == dcm_magic.MR_IMAGE_STORAGE for ds in datasets)

    for ds in datasets:
        assert ds.Rows == enhanced_file["rows"]
        assert ds.Columns == enhanced_file["columns"]
        assert len(ds.ImagePositionPatient) == 3
        assert len(ds.ImageOrientationPatient) == 6
        assert ds.BitsAllocated == 16
        assert ds.BitsStored == 12
        assert ds.HighBit == 11
        assert ds.PixelRepresentation == 0
        assert ds.SamplesPerPixel == 1
        assert ds.PhotometricInterpretation == "MONOCHROME2"
        assert "NumberOfFrames" not in ds
        assert (0x5200, 0x9230) not in ds
        assert (0x5200, 0x9229) not in ds
        assert ds.file_meta.TransferSyntaxUID == dcm_magic.ExplicitVRLittleEndian
        assert len(ds.PixelData) == ds.Rows * ds.Columns * 2


def test_slice_location_matches_position(tmp_path, enhanced_file):
    out = tmp_path / "out"
    convert_file(enhanced_file["path"], str(out))

    for ds in _read_all(str(out)):
        position = np.asarray([float(v) for v in ds.ImagePositionPatient])
        orientation = [float(v) for v in ds.ImageOrientationPatient]
        normal = np.cross(orientation[:3], orientation[3:])
        normal /= np.linalg.norm(normal)
        assert float(ds.SliceLocation) == pytest.approx(float(position @ normal), abs=1e-5)


def test_instance_numbers_start_at_one_per_series(tmp_path, enhanced_file):
    out = tmp_path / "out"
    convert_file(enhanced_file["path"], str(out))
    datasets = _read_all(str(out))

    by_series: dict[str, list[pydicom.Dataset]] = {}
    for ds in datasets:
        by_series.setdefault(str(ds.SeriesInstanceUID), []).append(ds)
    for series in by_series.values():
        numbers = sorted(int(ds.InstanceNumber) for ds in series)
        assert numbers == list(range(1, len(series) + 1))


def test_patient_data_is_not_hardcoded(tmp_path, enhanced_file):
    """Regression: the old code overwrote PatientName with a fixed person."""
    out = tmp_path / "out"
    convert_file(enhanced_file["path"], str(out))

    for ds in _read_all(str(out)):
        assert str(ds.PatientName) == enhanced_file["patient_name"]
        assert str(ds.PatientID) == enhanced_file["patient_id"]


def test_keep_study_uid_opt_in(tmp_path, enhanced_file):
    out = tmp_path / "out"
    convert_file(enhanced_file["path"], str(out), keep_study_uid=True)
    datasets = _read_all(str(out))

    assert all(str(ds.StudyInstanceUID) == STUDY_UID for ds in datasets)
    assert all(str(ds.FrameOfReferenceUID) == FRAME_OF_REFERENCE_UID for ds in datasets)


def test_truncated_file_is_repaired(tmp_path, enhanced_file):
    truncated = tmp_path / "truncated.dcm"
    data = pathlib.Path(enhanced_file["path"]).read_bytes()
    truncated.write_bytes(data[:-8])  # strip the trailing pixel-data delimiter

    out = tmp_path / "out"
    report = convert_file(str(truncated), str(out))

    assert report.frame_count == len(enhanced_file["frames"])
    assert any("truncated" in warning.lower() for warning in report.warnings)


def test_anonymize(tmp_path, enhanced_file):
    out = tmp_path / "out"
    convert_file(enhanced_file["path"], str(out), anonymize=True)
    datasets = _read_all(str(out))

    for ds in datasets:
        assert str(ds.PatientName) == "ANONYMOUS"
        assert str(ds.PatientID) == "ANONYMOUS"
        assert str(ds.InstitutionName) == ""
        assert str(ds.PatientSex) == ""
        assert str(ds.AccessionNumber) == ""
        assert str(ds.StudyInstanceUID) != STUDY_UID


def test_private_tags_are_removed_by_default(tmp_path, enhanced_file):
    out = tmp_path / "out"
    convert_file(enhanced_file["path"], str(out))
    for ds in _read_all(str(out)):
        assert not [element for element in ds if element.tag.is_private]


def test_output_is_deterministic(tmp_path, enhanced_file):
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    first = convert_file(enhanced_file["path"], str(out1))
    second = convert_file(enhanced_file["path"], str(out2))

    assert [s.series_instance_uid for s in first.series] == [
        s.series_instance_uid for s in second.series
    ]
    assert [
        str(pydicom.dcmread(path).SOPInstanceUID) for path in first.output_files
    ] == [str(pydicom.dcmread(path).SOPInstanceUID) for path in second.output_files]


def test_single_frame_classic_file_is_passed_through(tmp_path):
    """A normal single-frame MR image must produce exactly one slice."""
    source = pydicom.dcmread(os.path.join(REPO_ROOT, "etalon.dcm"))
    path = tmp_path / "single.dcm"
    source.save_as(str(path), enforce_file_format=True)

    out = tmp_path / "out"
    report = convert_file(str(path), str(out))
    assert report.frame_count == 1
    (ds,) = _read_all(str(out))
    assert ds.SOPClassUID == dcm_magic.MR_IMAGE_STORAGE
    np.testing.assert_array_equal(ds.pixel_array, source.pixel_array)


def test_missing_file_raises():
    with pytest.raises(ConversionError):
        convert_file("/definitely/not/here.dcm")


def test_default_output_directory_is_next_to_input(tmp_path, enhanced_file):
    report = convert_file(enhanced_file["path"])
    expected = os.path.join(tmp_path, "enhanced_slices")
    assert report.output_dir == os.path.abspath(expected)
    assert os.path.isdir(expected)


def test_legacy_template_argument_is_ignored(tmp_path, enhanced_file, monkeypatch):
    monkeypatch.chdir(tmp_path)
    files = dcm_magic.shamanstvo(enhanced_file["path"], "etalonnoeMRI")
    assert len(files) == 5
    assert all(os.path.isabs(path) for path in files)


def test_progress_callback_reports_every_slice(tmp_path, enhanced_file):
    out = tmp_path / "out"
    seen = []

    report = convert_file(
        enhanced_file["path"],
        str(out),
        progress=lambda done, total: seen.append((done, total)),
    )

    assert report.frame_count == 5
    assert [done for done, _ in seen] == [1, 2, 3, 4, 5]
    assert all(total == report.frame_count for _, total in seen)


SAMPLE = os.path.join(REPO_ROOT, "IMG-0001-00001.dcm")


@pytest.mark.skipif(
    not os.path.exists(SAMPLE), reason="sample file not available"
)
def test_real_philips_sample(tmp_path):
    """End-to-end check on the repository sample (3 localizer stacks)."""
    source = pydicom.dcmread(SAMPLE)
    out = tmp_path / "out"
    report = convert_file(SAMPLE, str(out))

    assert report.frame_count == int(source.NumberOfFrames)
    assert len(report.series) == 3
    assert sorted(s.frame_count for s in report.series) == [1, 1, 3]

    positions = {
        i: tuple(round(float(v), 3) for v in item[0x0020, 0x9113].value[0][0x0020, 0x0032].value)
        for i, item in enumerate(source[0x5200, 0x9230].value)
    }
    for ds in _read_all(str(out)):
        key = tuple(round(float(v), 3) for v in ds.ImagePositionPatient)
        index = next(i for i, pos in positions.items() if pos == key)
        np.testing.assert_array_equal(ds.pixel_array, source.pixel_array[index])


def test_multiple_stacks_with_same_orientation_are_kept_apart(tmp_path):
    stacks = [
        Stack("1", (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 10.0), (0.0, 0.0, 1.0), 2),
        Stack("2", (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), (0.0, 0.0, -10.0), (0.0, 0.0, 1.0), 2),
    ]
    path = tmp_path / "two_stacks.dcm"
    build_enhanced_file(path, stacks=stacks)

    report = convert_file(str(path), str(tmp_path / "out"))
    assert len(report.series) == 2
    assert [s.frame_count for s in report.series] == [2, 2]


def test_diffusion_b_values_become_separate_series(tmp_path):
    stack = Stack("1", (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 2)
    path = tmp_path / "dwi.dcm"
    # Frame 0/1 -> b=0, frame 2/3 -> b=1000
    build_enhanced_file(
        path,
        stacks=[stack, Stack("1", stack.orientation, (0.0, 0.0, 10.0), stack.normal, 2)],
        b_value_by_frame={0: 0.0, 1: 0.0, 2: 1000.0, 3: 1000.0},
    )

    report = convert_file(str(path), str(tmp_path / "out"))
    assert len(report.series) == 2
    assert sorted(s.frame_count for s in report.series) == [2, 2]
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_sop_uids_are_unique_across_studies(tmp_path, enhanced_file):
    default_out = tmp_path / "default"
    keep_out = tmp_path / "keep"
    convert_file(enhanced_file["path"], str(default_out))
    convert_file(enhanced_file["path"], str(keep_out), keep_study_uid=True)

    default_sops = {str(ds.SOPInstanceUID) for ds in _read_all(str(default_out))}
    keep_sops = {str(ds.SOPInstanceUID) for ds in _read_all(str(keep_out))}
    assert not default_sops & keep_sops


def test_enhanced_ct_is_written_as_ct_image_storage(tmp_path, enhanced_ct_file):
    out = tmp_path / "out"
    report = convert_file(enhanced_ct_file["path"], str(out))

    assert report.frame_count == 5
    assert len(report.series) == 2
    for ds in _read_all(str(out)):
        assert ds.SOPClassUID == dcm_magic.CT_IMAGE_STORAGE
        assert ds.Modality == "CT"
        assert "NumberOfFrames" not in ds
        assert (0x5200, 0x9230) not in ds
        assert (0x5200, 0x9229) not in ds


def test_ct_couch_angles_are_optional(tmp_path, enhanced_ct_file):
    source = pydicom.dcmread(enhanced_ct_file["path"])
    source.PatientSupportAngle = 15.0
    source.TableTopPitchAngle = 2.0
    source.TableTopRollAngle = -1.0
    source.save_as(enhanced_ct_file["path"], enforce_file_format=True)

    default_out = tmp_path / "default"
    convert_file(enhanced_ct_file["path"], str(default_out))
    default_ds = _read_all(str(default_out))[0]
    assert float(default_ds.PatientSupportAngle) == pytest.approx(15.0)
    assert float(default_ds.TableTopPitchAngle) == pytest.approx(2.0)

    zero_out = tmp_path / "zero"
    report = convert_file(
        enhanced_ct_file["path"], str(zero_out), zero_couch_angles=True
    )
    zero_ds = _read_all(str(zero_out))[0]
    assert float(zero_ds.PatientSupportAngle) == 0.0
    assert float(zero_ds.TableTopPitchAngle) == 0.0
    assert float(zero_ds.TableTopRollAngle) == 0.0
    assert any("TPS harmonization" in warning for warning in report.warnings)


def test_harmonize_fills_missing_tps_tags(tmp_path, enhanced_file):
    source = pydicom.dcmread(enhanced_file["path"])
    for keyword in (
        "AccessionNumber",
        "StudyID",
        "ReferringPhysicianName",
        "ImageType",
        "MRAcquisitionType",
        "EchoTime",
    ):
        if keyword in source:
            del source[keyword]
    source.save_as(enhanced_file["path"], enforce_file_format=True)

    out = tmp_path / "out"
    report = convert_file(enhanced_file["path"], str(out))
    ds = _read_all(str(out))[0]

    assert str(ds.AccessionNumber) == "000000"
    assert str(ds.StudyID) == "1"
    assert str(ds.ReferringPhysicianName) == "UNKNOWN"
    assert list(ds.ImageType)[:2] == ["ORIGINAL", "PRIMARY"]
    assert str(ds.MRAcquisitionType) == "2D"
    assert any("TPS harmonization" in warning for warning in report.warnings)


def test_harmonize_can_be_disabled(tmp_path, enhanced_file):
    source = pydicom.dcmread(enhanced_file["path"])
    del source.AccessionNumber
    source.save_as(enhanced_file["path"], enforce_file_format=True)

    out = tmp_path / "out"
    convert_file(enhanced_file["path"], str(out), harmonize=False)
    ds = _read_all(str(out))[0]
    assert "AccessionNumber" not in ds


def test_harmonize_normalizes_ascii_utf8_to_latin1(tmp_path, enhanced_file):
    source = pydicom.dcmread(enhanced_file["path"])
    source.SpecificCharacterSet = "ISO_IR 192"
    source.save_as(enhanced_file["path"], enforce_file_format=True)

    out = tmp_path / "out"
    convert_file(enhanced_file["path"], str(out))
    ds = _read_all(str(out))[0]
    assert ds.SpecificCharacterSet == "ISO_IR 100"


def test_harmonize_preserves_cyrillic_as_utf8(tmp_path):
    path = tmp_path / "cyrillic.dcm"
    build_enhanced_file(
        path,
        stacks=[
            Stack(
                "1",
                (1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                (0.0, 0.0, 0.0),
                (0.0, 0.0, 1.0),
                2,
            )
        ],
        patient_name="Иванов^Иван",
        specific_character_set="ISO_IR 144",
    )
    source = pydicom.dcmread(path)
    source.SeriesDescription = "Т2_аксиал"
    source.save_as(path, enforce_file_format=True)

    out = tmp_path / "out"
    convert_file(str(path), str(out))
    ds = _read_all(str(out))[0]
    assert ds.SpecificCharacterSet == "ISO_IR 192"
    assert str(ds.PatientName) == "Иванов^Иван"
    assert str(ds.SeriesDescription) == "Т2_аксиал"


def test_spatial_dimensions_do_not_split_one_volume(tmp_path):
    stack = Stack(
        "1",
        (1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
        3,
    )
    path = tmp_path / "spatial_dimensions.dcm"
    build_enhanced_file(
        path,
        stacks=[stack],
        dimension_pointers=(
            (0x0020, 0x0032),  # Image Position Patient
            (0x0020, 0x0013),  # Instance Number
            (0x0018, 0x9074),  # Frame Acquisition DateTime
        ),
        dimension_values_by_frame={0: (1, 1, 1), 1: (2, 2, 2), 2: (3, 3, 3)},
    )

    report = convert_file(str(path), str(tmp_path / "out"))
    assert len(report.series) == 1
    assert report.frame_count == 3


def test_contrast_dimension_still_splits_series(tmp_path):
    stack = Stack(
        "1",
        (1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
        3,
    )
    path = tmp_path / "echo_dimension.dcm"
    build_enhanced_file(
        path,
        stacks=[stack],
        dimension_pointers=((0x0018, 0x9082),),  # Effective Echo Time
        dimension_values_by_frame={0: (10,), 1: (10,), 2: (20,)},
    )

    report = convert_file(str(path), str(tmp_path / "out"))
    assert len(report.series) == 2
    assert [series.frame_count for series in report.series] == [2, 1]


def test_classic_ct_stays_ct_on_second_pass(tmp_path, enhanced_ct_file):
    first = tmp_path / "first"
    report = convert_file(enhanced_ct_file["path"], str(first))

    second = tmp_path / "second"
    report2 = convert_file(report.output_files[0], str(second))
    ds = _read_all(str(second))[0]
    assert report2.frame_count == 1
    assert ds.SOPClassUID == dcm_magic.CT_IMAGE_STORAGE
    assert ds.Modality == "CT"


def test_force_16bit_widens_8bit_grayscale(tmp_path, enhanced_file):
    source = pydicom.dcmread(enhanced_file["path"])
    small = (source.pixel_array % 256).astype(np.uint8)
    source.BitsAllocated = 8
    source.BitsStored = 8
    source.HighBit = 7
    source.PixelRepresentation = 0
    source.PixelData = small.tobytes()
    source.save_as(enhanced_file["path"], enforce_file_format=True)

    out = tmp_path / "out"
    convert_file(enhanced_file["path"], str(out), force_16bit=True)
    for ds in _read_all(str(out)):
        assert int(ds.BitsAllocated) == 16
        assert int(ds.BitsStored) == 16
        assert int(ds.HighBit) == 15
        assert ds.pixel_array.dtype == np.uint16
