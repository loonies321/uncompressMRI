from __future__ import annotations

import dcm_magic
import i18n


def test_both_languages_define_the_same_keys():
    assert set(i18n.STRINGS["ru"]) == set(i18n.STRINGS["en"])


def test_unknown_language_falls_back_to_russian():
    assert i18n.t("de", "title") == i18n.STRINGS["ru"]["title"]


def test_unknown_key_is_returned_as_is():
    assert i18n.t("en", "no_such_key") == "no_such_key"


def test_placeholders_are_substituted():
    text = i18n.t("en", "status_done", frames=5, series=3, path="/tmp/out")
    assert "5 slice(s)" in text
    assert "3 series" in text
    assert "/tmp/out" in text


def test_describe_speaks_both_languages(enhanced_file):
    assert "кадров" in dcm_magic.describe(enhanced_file["path"], compact=True)
    english = dcm_magic.describe(enhanced_file["path"], compact=True, lang="en")
    assert "frames:" in english
    assert "бит" not in english
