"""Tiny translation table for the window.

Plain dictionaries, no external dependencies: the GUI is built with ``ttk``
only, and the flag switcher is drawn on a ``Canvas``.
"""

from __future__ import annotations

LANGUAGES = ("ru", "en")
DEFAULT = "ru"

STRINGS: dict[str, dict[str, str]] = {
    "ru": {
        "title": "Распаковка enhanced MRI",
        "subtitle": "Multi-frame DICOM → посрезовые файлы для Eclipse / Aria",
        "source_box": " Исходный файл ",
        "series_file": "Файл серии",
        "browse": "Обзор…",
        "output_box": " Папка результата ",
        "folder": "Папка",
        "output_hint": "Пусто → <имя файла>_slices рядом с исходным файлом",
        "anon": "Анонимизировать (ФИО/ID, новый Study UID)",
        "keep_private": "Оставить приватные теги вендора",
        "unpack": "РАСПАКОВАТЬ",
        "open_folder": "Открыть папку",
        "log": " Журнал ",
        "preview": " Предпросмотр ",
        "preview_empty": "Срезов пока нет\nраспакуйте файл",
        "preview_error": "Не удалось показать срез:\n%(error)s",
        "status_idle": "Выберите файл серии",
        "status_selected": "Файл выбран",
        "status_busy": "Распаковка…",
        "status_done": "Готово: %(frames)d срез(ов) в %(series)d сери(ях) → %(path)s",
        "status_error": "Ошибка",
        "reading": "Читаю заголовок…",
        "read_failed": "Не удалось прочитать заголовок: %(error)s",
        "log_source": "Источник: %(path)s",
        "log_output": "Результат: %(path)s",
        "log_warning": "ВНИМАНИЕ: %(text)s",
        "log_error": "ОШИБКА: %(text)s",
        "dialog_open": "Выберите файл DICOM",
        "dialog_out": "Выберите папку результата",
        "all_files": "Все файлы",
        "folder_missing": "Папка не найдена",
        "folder_missing_text": "Сначала выполните распаковку.",
        "open_failed": "Не удалось открыть папку",
        "no_file": "Нет файла",
        "no_file_text": "Выберите файл серии.",
        "file_missing": "Файл не найден",
        "error_title": "Не удалось распаковать",
        "frames_n": "кадров: %(n)d",
        "bits_n": "%(n)d бит",
        "flag_ru": "Русский",
        "flag_en": "English",
    },
    "en": {
        "title": "Enhanced MRI unpacker",
        "subtitle": "Multi-frame DICOM → slice-by-slice files for Eclipse / Aria",
        "source_box": " Source file ",
        "series_file": "Series file",
        "browse": "Browse…",
        "output_box": " Output folder ",
        "folder": "Folder",
        "output_hint": "Empty → <file name>_slices next to the source file",
        "anon": "Anonymize (name/ID, new Study UID)",
        "keep_private": "Keep vendor private tags",
        "unpack": "UNPACK",
        "open_folder": "Open folder",
        "log": " Log ",
        "preview": " Preview ",
        "preview_empty": "No slices yet\nunpack a file",
        "preview_error": "Cannot render the slice:\n%(error)s",
        "status_idle": "Choose a series file",
        "status_selected": "File selected",
        "status_busy": "Unpacking…",
        "status_done": "Done: %(frames)d slice(s) in %(series)d series → %(path)s",
        "status_error": "Error",
        "reading": "Reading header…",
        "read_failed": "Cannot read the header: %(error)s",
        "log_source": "Source: %(path)s",
        "log_output": "Output: %(path)s",
        "log_warning": "WARNING: %(text)s",
        "log_error": "ERROR: %(text)s",
        "dialog_open": "Choose a DICOM file",
        "dialog_out": "Choose the output folder",
        "all_files": "All files",
        "folder_missing": "Folder not found",
        "folder_missing_text": "Run the unpacking first.",
        "open_failed": "Cannot open the folder",
        "no_file": "No file",
        "no_file_text": "Choose a series file.",
        "file_missing": "File not found",
        "error_title": "Unpacking failed",
        "frames_n": "frames: %(n)d",
        "bits_n": "%(n)d bit",
        "flag_ru": "Russian",
        "flag_en": "English",
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    """Return *key* in *lang*, falling back to the default language."""
    table = STRINGS.get(lang) or STRINGS[DEFAULT]
    text = table.get(key) or STRINGS[DEFAULT].get(key) or key
    return text % kwargs if kwargs else text
