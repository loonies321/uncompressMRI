# uncompressMRI

**Режет «сжатую» multi-frame МРТ-серию на обычные посрезовые DICOM-файлы,
которые импортируются в Eclipse / Aria.**

**Русский** · 🇬🇧 [English version](README.en.md)

[![Release](https://img.shields.io/github/v/release/loonies321/uncompressMRI?style=flat-square)](https://github.com/loonies321/uncompressMRI/releases/latest)
[![Windows build](https://github.com/loonies321/uncompressMRI/actions/workflows/build-windows-exe.yml/badge.svg)](https://github.com/loonies321/uncompressMRI/actions/workflows/build-windows-exe.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square)](LICENCE.txt)

![Как пользоваться: пять шагов](docs/gui-howto.png)

**[Скачать uncompressMRI.exe](https://github.com/loonies321/uncompressMRI/releases/latest)** —
Windows x64, ~25 МБ, Python не нужен.
Или [запустить из исходников](#из-исходников).

---

## Зачем это

Аппарат (например, Philips) может записать всю серию одним файлом —
`Enhanced MR Image Storage`, внутри которого лежат десятки кадров.
Eclipse и Aria такие файлы не принимают: им нужен набор обычных
`MR Image Storage`, по файлу на срез.

uncompressMRI разбирает multi-frame файл обратно на срезы, сохраняя
геометрию каждого кадра, а не «среднюю по больнице»:

| | |
|---|---|
| **Было** | 1 файл, 5 кадров, 3 стека, геометрия спрятана в per-frame functional groups |
| **Стало** | 5 файлов, 3 серии; у каждого среза свои `ImagePositionPatient`, `SliceLocation`, `InstanceNumber` |

## Три шага

1. **Выберите файл серии** — кнопка «Обзор…» или вставьте путь в поле.
   Под заголовком сразу появится, что внутри: SOP-класс, число кадров,
   матрица, описание серии. Если написано `Enhanced MR Image Storage` —
   файл тот самый.
2. **Проверьте папку результата** — по умолчанию `<имя файла>_slices`
   рядом с исходником.
3. **Нажмите `РАСПАКОВАТЬ`** — прогресс-бар покажет `записано / всего`,
   журнал — итог по сериям, кнопка «Открыть папку» откроет результат.

Горячие клавиши: `Enter` — распаковать, `Ctrl+O` — выбрать файл,
`Esc` — закрыть.

![Демонстрация работы](docs/demo.gif)

## Что получится в папке

```text
IMG-0001-00001_slices/
├── IM_101_0001.dcm   ← серия 101, срез 1
├── IM_101_0002.dcm
├── IM_101_0003.dcm
├── IM_102_0001.dcm   ← серия 102, другой стек
└── IM_103_0001.dcm   ← серия 103, локалайзер в другой плоскости
```

Имя файла: `IM_<номер серии>_<номер среза>.dcm`. У каждой серии свой
`SeriesInstanceUID`, поэтому в TPS серии не перемешаются, даже если лежат
в одной папке.

| Поле | Что с ним происходит |
|---|---|
| `SOPInstanceUID` | новый, детерминированный: повторный запуск даёт те же значения |
| `SeriesInstanceUID` | новый на каждую серию |
| `StudyInstanceUID` | **сохраняется** — срезы попадают в то же исследование |
| `FrameOfReferenceUID` | **сохраняется** — геометрия остаётся привязанной |
| `ImagePositionPatient`, `SliceLocation` | из per-frame functional groups **каждого** кадра |
| `Rows`, `Columns`, `BitsStored` | из источника, 12 бит в 16 остаются 12 битами |
| Приватные теги вендора | удаляются, можно оставить флагом `--keep-private` |
| `PatientName`, `PatientID` | из источника, либо обезличиваются флагом `--anon` |

## Импорт в Eclipse / Aria

1. Импорт DICOM → указать папку `*_slices` **целиком** (не отдельный файл).
2. Убедиться, что подтянулось исследование с тем же `StudyInstanceUID`,
   что у исходной серии.
3. Если из одного файла получилось несколько серий — это нормально:
   локалайзеры и разные стеки лежат отдельными сериями.

## Командная строка

```bash
python main.py IMG-0001-00001.dcm                 # рядом появится IMG-0001-00001_slices/
python main.py IMG-0001-00001.dcm -o /data/slices
python main.py IMG-0001-00001.dcm --anon          # обезличить
python main.py ./dicoms/*.dcm -o /data/out        # несколько файлов
```

| Ключ | Что делает |
|---|---|
| `-o`, `--output` | папка результата (по умолчанию `<имя>_slices`) |
| `--anon` | убрать ФИО/ID и перегенерировать Study UID |
| `--keep-private` | оставить приватные теги вендора |
| `--no-overwrite` | не перезаписывать существующие файлы |
| `-q` | тихий режим |
| `--version` | версия |

## Как это работает

```mermaid
flowchart LR
    A["Enhanced MR<br/>1 файл, N кадров"] --> B["Разбор кадров<br/>позиция · ориентация<br/>толщина · окно"]
    B --> C{"Группировка<br/>стек · эхо<br/>b-value · время"}
    C --> D["Серия 101<br/>срезы 1…k"]
    C --> E["Серия 102<br/>срезы 1…m"]
    C --> F["Серия 103<br/>локалайзеры"]
    D --> G["Eclipse / Aria"]
    E --> G
    F --> G
```

1. Пиксели декодируются `pydicom` (для JPEG/JPEG-2000 нужен `pylibjpeg` или `python-gdcm`).
2. Из `Per-Frame Functional Groups` каждого кадра достаются позиция,
   ориентация, `PixelSpacing`, `SliceThickness`, окно, `RescaleSlope/Intercept`.
   Если per-frame данных нет — берутся `Shared Functional Groups`, затем
   значения верхнего уровня.
3. Кадры группируются в серии по `StackID`, ориентации, `FrameType`,
   номеру эха, b-value и значениям `Dimension Index` (кроме позиции в стеке).
4. Каждый срез пишется как обычный `MR Image Storage` (explicit VR little endian)
   с пересчитанным `SliceLocation` (`IPP · normal`) и своим `InstanceNumber`.
5. Результат проверяется: длина `PixelData` = `Rows × Columns × 2`,
   позиции срезов уникальны.

<details>
<summary>Что было сломано в версии 1.x (поэтому конвертер переписан)</summary>

| Было | Стало |
|---|---|
| Путь `etalonnoeMRI\file` — работало только в Windows | `os.path.join`, Linux/macOS/Windows |
| Все кадры сваливались в одну серию | группировка по стеку / эху / b-value / времени |
| Ориентация и позиция брались из 0-го кадра | геометрия из per-frame functional groups каждого кадра |
| `SliceLocation` оставался от эталона у всех срезов | пересчитывается как `IPP · normal` |
| `Rows/Columns` подменялись, `BitsStored` терялся | размер и битность из источника |
| `ndarray.tostring()` — удалён в NumPy 2.x | `tobytes()` |
| Мёртвая функция `write_dicom` | удалена |
| Нужна была папка `etalonnoeMRI` с чужим срезом | срезы строятся из исходного файла |
| Вывод в текущую папку как `after0.dcm` | в `<имя>_slices/`, имена `IM_<серия>_<номер>.dcm` |

</details>

## Тесты и сборка

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q      # 17 тестов
```

Тесты строят синтетический enhanced-файл (Philips-подобная структура,
2 стека, 12-битные пиксели) и проверяют разбиение на серии, побитовое
совпадение пикселей, геометрию, UID, обезличивание, прогресс и отсутствие
захардкоженных данных пациента. Отдельный тест прогоняет реальный пример
`IMG-0001-00001.dcm`.

Windows-сборка автоматическая: тег `v*` поднимает GitHub Actions, который
прогоняет тесты, собирает exe через PyInstaller, **запускает уже собранный
файл на реальной Windows** (enhanced-файл → 5 срезов / 3 серии, одиночный
срез → 1 файл) и прикрепляет его к релизу.

Даже картинки в этом README сделаны не руками: `tools/make_screenshots.py`
поднимает настоящее окно, прогоняет конвертацию и снимает скриншоты и GIF
(`ImageMagick` + `ffmpeg`).

### Из исходников

```bash
git clone https://github.com/loonies321/uncompressMRI.git
cd uncompressMRI
python -m pip install -r requirements.txt
python main.py                     # окно
python main.py file.dcm -o out     # консоль
```

Нужен Python 3.9+ (проверено на 3.11).

### Собрать exe локально (Windows)

```bat
python -m pip install -r requirements-dev.txt pyinstaller
build_exe.bat
```

Результат: `dist\uncompressMRI.exe`. Кросс-компиляции нет: PyInstaller
собирает только под ту ОС, где запущен.

## Ограничения

* Цветные enhanced-MR (`Enhanced MR Color Image Storage`) не поддерживаются.
* Сжатые JPEG/JPEG-2000 файлы требуют `pylibjpeg` или `python-gdcm`.
* Если позиции нет ни в per-frame, ни в shared, ни в top-level тегах,
  срезы восстанавливаются по толщине — программа предупредит, результат
  нужно проверить глазами.
* DWI с несколькими направлениями градиента группируется по b-value,
  направления отдельными сериями не разделяются.

## Если что-то пошло не так

**Windows пишет «Windows защитила ваш компьютер».** exe не подписан
платным сертификатом: «Подробнее» → «Выполнить в любом случае». SHA-256
файла указан в описании релиза — можно сверить.

**В Eclipse не появились срезы.** Импортировать нужно папку `*_slices`
целиком и выбрать то же исследование (`StudyInstanceUID`).

**«Файл не является DICOM».** Файл может быть сжат JPEG/JPEG-2000 —
поставьте `pylibjpeg` (из исходников) или пришлите файл, добавлю поддержку.

**Из одного файла вышло несколько серий.** Так и должно быть: в исходнике
несколько стеков (например, локалайзеры в трёх плоскостях).

**В результате не то ФИО.** Оно берётся из исходного файла, ничего не
подставляется. Для обезличивания — `--anon` или галочка в окне.

## Лицензия

Apache License 2.0 — см. [LICENCE.txt](LICENCE.txt).

`инструкция.pdf` в репозитории описывает версию 1.x (с папкой
`etalonnoeMRI`) и устарела — актуальна эта README.

---

## English summary

Full English README: **[README.en.md](README.en.md)**.

`uncompressMRI` converts **enhanced (multi-frame) MRI DICOM** (Philips
`Enhanced MR Image Storage`) into plain **single-frame `MR Image Storage`**
slices that Varian **Eclipse** / **Aria** and other treatment planning
systems (Oncentra, Monaco, RayStation) can import.

It is a DICOM splitter/converter for radiotherapy: per-frame geometry
(position, orientation, spacing, thickness), series splitting by
stack/echo/b-value, deterministic UIDs, preserved `StudyInstanceUID`,
anonymization, Windows `.exe`, CLI and GUI.

<sub>dicom · dicom converter · dicom splitter · enhanced MR · multi-frame ·
MRI · radiotherapy · radiation oncology · medical physics · treatment planning
system · Varian Eclipse · Varian Aria · Philips · pydicom · Python</sub>
