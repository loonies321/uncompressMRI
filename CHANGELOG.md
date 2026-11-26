# Changelog

## 2.4.0 — 2026-11-26

### Added

- Enhanced CT (`Enhanced CT Image Storage`) support; classic single-frame CT is
  now preserved as `CT Image Storage` instead of being relabelled as MR.
- Conservative TPS harmonization: missing Type 1/2 attributes are filled with
  explicit placeholders, and `SpecificCharacterSet` is normalized to Latin-1
  for ASCII or UTF-8 for Cyrillic. Disable with `--no-harmonize`.
- Optional `--zero-couch-angles` for CT (off by default; changes geometry).
- Optional `--force-16bit` for 8-bit grayscale sources.
- Optional `--verify` for a full re-read of every written file. The fast
  in-memory validation is always enabled.
- GUI checkbox “Harmonize tags for TPS” (enabled by default).
- Regression tests for CT output, harmonization, charset handling, single-
  valued `DimensionIndexValues`, spatial Dimension Index over-splitting, and
  `--force-16bit` widening.

### Fixed

- A single-valued `DimensionIndexValues` value could be ignored because
  pydicom returns a scalar instead of a list for VM 1.
- Spatial / instance / timestamp Dimension Index pointers no longer split one
  3D volume into one series per slice. Only a small allowlist of
  contrast/physics dimensions is used for grouping.

### Performance

- Replaced deep copies of the full Enhanced dataset with shallow element-dict
  copies; per-frame functional groups are no longer copied just to be removed.
- Removed the unconditional re-read of every output file; validation now uses
  the in-memory datasets.
- On a synthetic 800-frame 256×256 file: about 2.5 s (~320 frames/s) versus
  about 3.6 s in 2.3.1 on the same test machine (~30% faster).

### Documentation

- README (RU/EN), GUI screenshots, social preview and issue template updated
  for MR/CT support and version 2.4.0.
- Added `THIRD_PARTY_NOTICES.md` for the MIT-licensed portions adapted from
  DICOM_TPS_Harmonizer.
