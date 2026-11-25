"""Verify slices written by the frozen Windows executable.

Used by the GitHub Actions smoke test, not by pytest.
"""

from __future__ import annotations

import argparse
import glob
import os

import pydicom

MR_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.4"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument("--series", type=int, default=1)
    args = parser.parse_args()

    paths = sorted(glob.glob(os.path.join(args.directory, "*.dcm")))
    if len(paths) != args.frames:
        print("expected %d slices, found %d" % (args.frames, len(paths)))
        return 1

    datasets = [pydicom.dcmread(path) for path in paths]
    series = {str(ds.SeriesInstanceUID) for ds in datasets}
    if len(series) != args.series:
        print("expected %d series, found %d" % (args.series, len(series)))
        return 1

    for path, ds in zip(paths, datasets):
        if str(ds.SOPClassUID) != MR_IMAGE_STORAGE:
            print("%s: unexpected SOP class %s" % (path, ds.SOPClassUID))
            return 1
        if len(ds.PixelData) != int(ds.Rows) * int(ds.Columns) * (
            int(ds.BitsAllocated) // 8
        ):
            print("%s: pixel data length does not match Rows/Columns" % path)
            return 1
        if "ImagePositionPatient" not in ds:
            print("%s: no ImagePositionPatient" % path)
            return 1

    print("OK: %d slices, %d series" % (len(paths), len(series)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
