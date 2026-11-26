# Как участвовать в uncompressMRI

Спасибо, что хотите помочь. Проект маленький и практичный: главная цель — чтобы медицинский физик открыл exe, получил корректные срезы и импортировал их в Eclipse / Aria / Monaco без сюрпризов.

## Коротко

| Что | Куда |
|---|---|
| Ошибка | [Bug report](.github/ISSUE_TEMPLATE/bug_report.yml) |
| Идея или улучшение | [Feature request](.github/ISSUE_TEMPLATE/feature_request.yml) |
| Pull request | ветка от `main`, тесты обязательны |
| Уязвимость | [SECURITY.md](SECURITY.md), **не** публичный issue |
| Данные пациентов | **никуда**: ни в issue, ни в PR, ни в комментарии |

## Прежде чем открыть issue

1. Проверьте [README](README.md), раздел «Если что-то пошло не так».
2. Поищите похожие issue.
3. Подготовьте:
   - версию: `uncompressMRI.exe --version` или `python main.py --version`;
   - ОС и разрядность;
   - как запускаете: exe, CLI или GUI из исходников;
   - что за файл: enhanced multi-frame, обычный single-frame, несколько файлов;
   - шаги, ожидаемое и фактическое поведение;
   - журнал или текст ошибки без персональных данных.

**Не прикладывайте реальные DICOM-файлы пациентов.** Для примеров используйте синтетические файлы или обезличьте их через `--anon`, а потом проверьте глазами. Если файл нужен для разбора, сначала согласуйте безопасный канал с мейнтейнером.

## Разработка

### Требования

- Python 3.9+;
- Windows 10/11 x64 — основная платформа для exe;
- Linux/macOS — для CLI и тестов; GUI требует `tkinter` (`python3-tk` в Debian/Ubuntu);
- `pydicom`, `numpy` — runtime-зависимости.

### Установка

```bash
git clone https://github.com/loonies321/uncompressMRI.git
cd uncompressMRI
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements-dev.txt
```

### Запуск

```bash
python main.py                    # GUI
python main.py --help             # CLI
python main.py IMG-0001-00001.dcm -o out
python main.py IMG-0001-00001.dcm -o out --anon
```

### Тесты

```bash
python -m pytest tests -q
```

Сейчас в наборе 28 тестов: конвертация enhanced-серий, геометрия кадров, UID, восстановление обрезанного пиксельного потока (Siemens), предпросмотр, паритет RU/EN. Новую логику в `dcm_magic.py` добавляйте вместе с тестом.

## Ограничения проекта

Это не пожелания, а причина, по которой проект существует:

1. **GUI — только стандартная библиотека.** `tkinter` / `ttk`, без PyQt, PySide и других тяжёлых фреймворков.
2. **Exe остаётся лёгким.** Ориентир — около 25 МБ. Новые runtime-зависимости обсуждаются заранее; exe не должен требовать Visual C++ runtime.
3. **Никакой телеметрии и сети.** Инструмент работает офлайн; проверки обновлений нет.
4. **Двуязычный интерфейс.** Новые строки добавляются в `i18n.py` сразу для RU и EN; тест `test_i18n` проверяет паритет.
5. **Корректная геометрия важнее скорости.** `ImagePositionPatient`, `ImageOrientationPatient`, `PixelSpacing`, `SliceLocation`, номера срезов и UID — не «средние по больнице».
6. **UID по умолчанию новые.** `--keep-study-uid` — осознанный opt-in, потому что Eclipse может отказаться импортировать исследование с уже занятым Study Instance UID.

## Стиль кода

- PEP 8, отступ 4 пробела, `snake_case`, понятные имена.
- Аннотации типов приветствуются там, где они помогают, но не вместо читаемости.
- Логика DICOM — в `dcm_magic.py`, без зависимости от GUI; предпросмотр — в `preview.py`.
- Ошибки пользователю — человеческим языком, без стектрейсов в окне; технические детали — в журнал.
- Не добавляйте «магические» глобальные состояния: приложение должно оставаться тестируемым.
- Форматтер не навязан; главное — не ломать существующий стиль файла.

## Тестовые DICOM-файлы

В репозитории лежат `etalon.dcm` и `IMG-0001-00001.dcm` — синтетические/обезличенные примеры для тестов. Не заменяйте их реальными исследованиями. Если нужен новый кейс, приложите описание тегов и происхождение файла.

## Pull request

1. Сделайте fork и ветку от `main`: `fix/...`, `feat/...`, `docs/...`.
2. Внесите изменение минимального размера.
3. Добавьте или обновите тесты.
4. Обновите README / README.en.md, если меняется поведение или CLI.
5. Проверьте, что `python -m pytest tests -q` проходит.
6. Заполните шаблон PR: что, зачем, как проверяли, влияние на размер exe.

PR без тестов на новую логику может быть отклонён или отправлен на доработку. Если не уверены, откройте issue и обсудите дизайн до кода.

## Коммиты

Короткое повелительное наклонение, одна мысль на коммит:

```
mr: preserve per-frame pixel spacing
cli: add --keep-private
docs: explain Eclipse "already imported"
```

Префиксы не обязательны, но полезны: `mr`, `cli`, `gui`, `docs`, `tests`, `build`.

## Релизы

Релизы делает мейнтейнер: тег `v*` запускает GitHub Actions, тесты, сборку Windows exe и smoke-тест. В release notes указывается SHA-256 файла. Не создавайте теги и релизы в fork без согласования.

## Лицензия вклада

Отправляя PR, вы соглашаетесь, что ваш вклад распространяется под [Apache License 2.0](LICENCE.txt). CLA не требуется, но авторство коммитов сохраняется.

---

## English summary

- Use issues for bugs and feature requests; use [SECURITY.md](SECURITY.md) for vulnerabilities.
- Never attach real patient DICOM data. Use synthetic or anonymized files only.
- GUI must stay stdlib-only (`tkinter`/`ttk`); keep the Windows exe around 25 MB and free of a Visual C++ runtime dependency.
- Run `python -m pytest tests -q`; add tests for new `dcm_magic.py` logic.
- Update both RU and EN strings in `i18n.py` and the matching README.
- Contributions are accepted under Apache-2.0; no CLA.
