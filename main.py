'''
   Copyright 2022-2026 Maksim Trushin
   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at
       http://www.apache.org/licenses/LICENSE-2.0
   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

Unpack a compressed / enhanced multi-frame MRI series into single-frame
DICOM slices that Eclipse / Aria can import.

Run without arguments to open the window, or from a terminal:

    python main.py IMG-0001-00001.dcm
    python main.py IMG-0001-00001.dcm -o out --anon
'''

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import traceback
from collections.abc import Sequence

import i18n
import preview
from dcm_magic import (
    ConversionError,
    ConversionReport,
    __version__,
    convert_file,
    describe,
)


def _summary(report: ConversionReport) -> str:
    lines = [
        "%s -> %s" % (os.path.basename(report.source), report.output_dir),
        "  slices: %d in %d series" % (report.frame_count, len(report.series)),
    ]
    for series in report.series:
        lines.append(
            "  series %d '%s': %d slice(s)"
            % (series.series_number, series.description, series.frame_count)
        )
    for warning in report.warnings:
        lines.append("  warning: %s" % warning)
    return "\n".join(lines)


def run_cli(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uncompress-mri",
        description=(
            "Convert an enhanced (multi-frame) DICOM MRI series into "
            "single-frame slices for Eclipse / Aria."
        ),
    )
    parser.add_argument("files", nargs="+", help="input .dcm file(s)")
    parser.add_argument(
        "-o",
        "--out",
        help="output directory (default: <file>_slices next to the input)",
    )
    parser.add_argument(
        "--anon",
        action="store_true",
        help="remove patient identifiers and regenerate the study UID",
    )
    parser.add_argument(
        "--keep-study-uid",
        action="store_true",
        help="reuse the source Study Instance UID (Eclipse may refuse a study "
        "that was already imported)",
    )
    parser.add_argument(
        "--keep-private",
        action="store_true",
        help="keep vendor private tags in the output",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="fail instead of overwriting existing output files",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="only print errors")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(message)s",
    )

    failed = 0
    multiple = len(args.files) > 1
    for path in args.files:
        try:
            target = args.out
            if target is not None and multiple:
                stem, _ = os.path.splitext(os.path.basename(path))
                target = os.path.join(target, stem)
            report = convert_file(
                path,
                target,
                anonymize=args.anon,
                keep_study_uid=args.keep_study_uid,
                keep_private_tags=args.keep_private,
                overwrite=not args.no_overwrite,
            )
            if not args.quiet:
                print(_summary(report))
        except ConversionError as exc:
            failed += 1
            print("ERROR: %s" % exc, file=sys.stderr)
        except Exception:  # noqa: BLE001 - keep converting the other files
            failed += 1
            traceback.print_exc()
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

_STATUS_STYLES = {
    "Idle": "Status.TLabel",
    "Busy": "Busy.TLabel",
    "Ok": "Ok.TLabel",
    "Error": "Error.TLabel",
}


def _open_folder(path: str) -> None:
    """Open *path* in the system file manager."""
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _center_window(window) -> None:
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    x = max(0, (window.winfo_screenwidth() - width) // 2)
    y = max(0, (window.winfo_screenheight() - height) // 3)
    window.geometry("+%d+%d" % (x, y))


class FlagSwitcher:
    """Two clickable flags that switch the interface language.

    The flags are painted on a ``Canvas``: no image files, no extra packages
    and nothing to bundle into the Windows .exe.
    """

    WIDTH = 32
    HEIGHT = 20
    ACTIVE = "#0969da"
    INACTIVE = "#c6cdd5"

    def __init__(self, master, on_change, lang=i18n.DEFAULT, tk=None) -> None:
        self._on_change = on_change
        self._lang = lang
        self._holders = {}
        self.frame = tk.Frame(master)
        for code, painter in (("ru", self._paint_ru), ("en", self._paint_en)):
            holder = tk.Frame(self.frame, bg=self.INACTIVE, padx=2, pady=2)
            canvas = tk.Canvas(
                holder,
                width=self.WIDTH,
                height=self.HEIGHT,
                highlightthickness=0,
                bd=0,
                cursor="hand2",
            )
            painter(canvas)
            canvas.pack()
            for widget in (holder, canvas):
                widget.bind("<Button-1>", lambda _event, c=code: self._choose(c))
            holder.pack(side="left", padx=(0, 6))
            self._holders[code] = holder
        self.set_lang(lang)

    def _paint_ru(self, canvas) -> None:
        band = self.HEIGHT / 3
        for index, color in enumerate(("#ffffff", "#0039a6", "#d52b1e")):
            canvas.create_rectangle(
                0,
                index * band,
                self.WIDTH,
                (index + 1) * band,
                fill=color,
                outline=color,
            )

    def _paint_en(self, canvas) -> None:
        width, height = self.WIDTH, self.HEIGHT
        canvas.create_rectangle(0, 0, width, height, fill="#012169", outline="#012169")
        for color, line_width in (("#ffffff", 6), ("#c8102e", 2)):
            canvas.create_line(0, 0, width, height, fill=color, width=line_width)
            canvas.create_line(0, height, width, 0, fill=color, width=line_width)
        for color, line_width in (("#ffffff", 10), ("#c8102e", 6)):
            canvas.create_line(
                width / 2, 0, width / 2, height, fill=color, width=line_width
            )
            canvas.create_line(
                0, height / 2, width, height / 2, fill=color, width=line_width
            )

    def _choose(self, code) -> None:
        if code != self._lang:
            self.set_lang(code)
            self._on_change(code)

    def set_lang(self, code) -> None:
        self._lang = code
        for key, holder in self._holders.items():
            holder.configure(bg=self.ACTIVE if key == code else self.INACTIVE)

    @property
    def lang(self):
        return self._lang


class UncompressApp:
    """The main window.

    A class rather than a closure so tools (screenshots, docs) and tests can
    build the window and drive it without faking mouse clicks.
    """

    def __init__(self, root, lang: str | None = None) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        self._tk = tk
        self._filedialog = filedialog
        self._messagebox = messagebox
        self.root = root
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self.lang = i18n.DEFAULT

        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("TkDefaultFont", 15, "bold"))
        style.configure("Subtitle.TLabel", foreground="#666666")
        style.configure("Status.TLabel", foreground="#444444")
        style.configure("Busy.TLabel", foreground="#1a4f8a")
        style.configure("Ok.TLabel", foreground="#146c2e")
        style.configure("Error.TLabel", foreground="#a4262c")
        style.configure(
            "Primary.TButton", font=("TkDefaultFont", 11, "bold"), padding=(22, 8)
        )
        style.configure("TLabelframe.Label", font=("TkDefaultFont", 9, "bold"))
        style.configure(
            "TProgressbar",
            thickness=10,
            troughcolor="#e6e8eb",
            background="#2da44e",
            bordercolor="#d0d7de",
            lightcolor="#2da44e",
            darkcolor="#2da44e",
        )

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.anon_var = tk.BooleanVar(value=False)
        self.private_var = tk.BooleanVar(value=False)
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_text = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")
        self._status_key = "status_idle"
        self._status_kind = "Idle"
        self._status_args: dict[str, object] = {}

        outer = ttk.Frame(root, padding=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(6, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.columnconfigure(0, weight=1)
        self.title_label = ttk.Label(header, text="", style="Title.TLabel")
        self.title_label.grid(row=0, column=0, sticky="w")
        self.subtitle_label = ttk.Label(header, text="", style="Subtitle.TLabel")
        self.subtitle_label.grid(row=1, column=0, sticky="w")

        initial_lang = lang if lang in i18n.LANGUAGES else self._load_lang()
        self.flags = FlagSwitcher(header, self.set_language, initial_lang, tk=tk)
        self.flags.frame.grid(row=0, column=1, rowspan=2, sticky="ne")

        self.source_box = ttk.LabelFrame(outer, text="", padding=10)
        self.source_box.grid(row=1, column=0, sticky="ew")
        self.source_box.columnconfigure(1, weight=1)
        self.source_label = ttk.Label(self.source_box, text="")
        self.source_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.source_entry = ttk.Entry(self.source_box, textvariable=self.input_var)
        self.source_entry.grid(row=0, column=1, sticky="ew")
        self.source_button = ttk.Button(
            self.source_box, text="", command=self.choose_input
        )
        self.source_button.grid(row=0, column=2, padx=(8, 0))
        self.info_label = ttk.Label(
            self.source_box, text="", style="Subtitle.TLabel", justify="left"
        )
        self.info_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self.output_box = ttk.LabelFrame(outer, text="", padding=10)
        self.output_box.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.output_box.columnconfigure(1, weight=1)
        self.output_label = ttk.Label(self.output_box, text="")
        self.output_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.output_entry = ttk.Entry(self.output_box, textvariable=self.output_var)
        self.output_entry.grid(row=0, column=1, sticky="ew")
        self.output_button = ttk.Button(
            self.output_box, text="", command=self.choose_output
        )
        self.output_button.grid(row=0, column=2, padx=(8, 0))
        self.output_hint = ttk.Label(
            self.output_box, text="", style="Subtitle.TLabel"
        )
        self.output_hint.grid(row=1, column=1, columnspan=2, sticky="w", pady=(6, 0))

        options = ttk.Frame(outer)
        options.grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.anon_check = ttk.Checkbutton(
            options, text="", variable=self.anon_var
        )
        self.anon_check.pack(anchor="w")
        self.private_check = ttk.Checkbutton(
            options, text="", variable=self.private_var
        )
        self.private_check.pack(anchor="w")

        actions = ttk.Frame(outer)
        actions.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        actions.columnconfigure(2, weight=1)
        self.run_button = ttk.Button(
            actions, text="", style="Primary.TButton", command=self.start
        )
        self.run_button.grid(row=0, column=0)
        self.open_button = ttk.Button(
            actions, text="", command=self.open_output, state="disabled"
        )
        self.open_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(
            actions, textvariable=self.progress_text, style="Subtitle.TLabel"
        ).grid(row=0, column=2, sticky="e")

        self.progress_bar = ttk.Progressbar(
            outer, variable=self.progress_var, maximum=100.0
        )
        self.progress_bar.grid(row=5, column=0, sticky="ew", pady=(8, 0))

        body = ttk.Frame(outer)
        body.grid(row=6, column=0, sticky="nsew", pady=(12, 0))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.log_frame = ttk.LabelFrame(body, text="", padding=6)
        self.log_frame.grid(row=0, column=0, sticky="nsew")
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(
            self.log_frame,
            height=8,
            wrap="word",
            state="disabled",
            font="TkFixedFont",
            relief="flat",
            padx=6,
            pady=6,
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self.log_frame, command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

        self.preview_frame = ttk.LabelFrame(body, text="", padding=6)
        self.preview_frame.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.preview_frame.columnconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(
            self.preview_frame,
            width=preview.MAX_SIZE,
            height=preview.MAX_SIZE,
            highlightthickness=0,
            bd=0,
            bg="#101418",
        )
        self.preview_canvas.grid(row=0, column=0)
        center = preview.MAX_SIZE // 2
        self._preview_image = self.preview_canvas.create_image(
            center, center, anchor="center"
        )
        self._preview_text = self.preview_canvas.create_text(
            center,
            center,
            text="",
            width=preview.MAX_SIZE - 40,
            fill="#8b949e",
            justify="center",
            font=("TkDefaultFont", 10),
        )
        self.preview_scale = ttk.Scale(
            self.preview_frame,
            from_=0,
            to=0,
            orient="horizontal",
            state="disabled",
            command=self._on_preview_scale,
        )
        self.preview_scale.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.preview_counter = ttk.Label(
            # A space keeps the row from collapsing before the first slice.
            self.preview_frame,
            text=" ",
            style="Subtitle.TLabel",
        )
        self.preview_counter.grid(row=2, column=0, sticky="w", pady=(4, 0))
        self._preview_paths: list[str] = []
        self._preview_cache: dict[int, bytes] = {}
        self._preview_index = 0
        self._preview_job = None
        self._preview_photo = None

        self.status_label = ttk.Label(
            outer, textvariable=self.status_var, style="Status.TLabel"
        )
        self.status_label.grid(row=7, column=0, sticky="w", pady=(10, 0))

        self.clear_preview()
        self._apply_lang(initial_lang)

    # -- language ---------------------------------------------------------

    def t(self, key: str, **kwargs) -> str:
        return i18n.t(self.lang, key, **kwargs)

    def set_language(self, code: str, persist: bool = True) -> None:
        """Switch the whole window to *code* and remember the choice."""
        self._apply_lang(code)
        if persist:
            self._save_lang(self.lang)

    def _apply_lang(self, code: str) -> None:
        if code not in i18n.LANGUAGES:
            code = i18n.DEFAULT
        self.lang = code
        self.flags.set_lang(code)
        self.title_label.configure(text=self.t("title"))
        self.subtitle_label.configure(text=self.t("subtitle"))
        self.source_box.configure(text=self.t("source_box"))
        self.source_label.configure(text=self.t("series_file"))
        self.source_button.configure(text=self.t("browse"))
        self.output_box.configure(text=self.t("output_box"))
        self.output_label.configure(text=self.t("folder"))
        self.output_button.configure(text=self.t("browse"))
        self.output_hint.configure(text=self.t("output_hint"))
        self.anon_check.configure(text=self.t("anon"))
        self.private_check.configure(text=self.t("keep_private"))
        self.run_button.configure(text=self.t("unpack"))
        self.open_button.configure(text=self.t("open_folder"))
        self.log_frame.configure(text=self.t("log"))
        self.preview_frame.configure(text=self.t("preview"))
        if not self._preview_paths:
            self.preview_canvas.itemconfigure(
                self._preview_text, text=self.t("preview_empty")
            )
        self._render_status()
        path = self.input_var.get().strip().strip('"')
        if path and os.path.isfile(path):
            self.update_info(path)

    @staticmethod
    def _config_path() -> str:
        base = os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
        return os.path.join(base, "uncompressMRI", "config.json")

    def _load_lang(self) -> str:
        try:
            with open(self._config_path(), encoding="utf-8") as handle:
                code = str(json.load(handle).get("lang", ""))
        except (OSError, ValueError):
            return i18n.DEFAULT
        return code if code in i18n.LANGUAGES else i18n.DEFAULT

    def _save_lang(self, code: str) -> None:
        try:
            path = self._config_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"lang": code}, handle)
        except OSError:
            pass

    # -- helpers ----------------------------------------------------------

    def append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def set_status(self, key: str, kind: str = "Idle", **kwargs) -> None:
        self._status_key = key
        self._status_kind = kind
        self._status_args = kwargs
        self._render_status()

    def _render_status(self) -> None:
        self.status_label.configure(
            style=_STATUS_STYLES.get(self._status_kind, "Status.TLabel")
        )
        self.status_var.set(self.t(self._status_key, **self._status_args))

    def set_source(self, path: str, output: str | None = None) -> None:
        """Fill in the file fields and refresh the header information."""
        self.input_var.set(path)
        self.output_var.set(output or os.path.splitext(path)[0] + "_slices")
        self.update_info(path)
        self.set_status("status_selected")

    def update_info(self, path: str) -> None:
        self.info_label.configure(text=self.t("reading"))
        lang = self.lang

        def job() -> None:
            try:
                self.messages.put(("info", describe(path, compact=True, lang=lang)))
            except Exception as exc:  # noqa: BLE001 - shown to the user
                self.messages.put(("info", i18n.t(lang, "read_failed", error=exc)))

        threading.Thread(target=job, daemon=True).start()

    # -- preview ----------------------------------------------------------

    def _cancel_preview_job(self) -> None:
        if self._preview_job is not None:
            self.root.after_cancel(self._preview_job)
            self._preview_job = None

    def clear_preview(self, message: str | None = None) -> None:
        self._cancel_preview_job()
        self._preview_paths = []
        self._preview_cache.clear()
        self._preview_photo = None
        self._preview_index = 0
        self.preview_scale.configure(to=0, state="disabled")
        self.preview_scale.set(0)
        self.preview_counter.configure(text=" ")
        self.preview_canvas.itemconfigure(self._preview_image, image="")
        text = message if message is not None else self.t("preview_empty")
        self.preview_canvas.itemconfigure(self._preview_text, text=text)

    def set_preview(self, paths: list[str], index: int = 0) -> None:
        self._cancel_preview_job()
        self._preview_paths = list(paths)
        self._preview_cache.clear()
        if not self._preview_paths:
            self.clear_preview()
            return
        self.preview_scale.configure(to=len(self._preview_paths) - 1, state="normal")
        self.preview_scale.set(index)
        self._show_preview(index)

    def _on_preview_scale(self, value) -> None:
        self._cancel_preview_job()
        self._preview_job = self.root.after(
            40, lambda: self._show_preview(int(float(value)))
        )

    def _show_preview(self, index: int) -> None:
        self._preview_job = None
        if not self._preview_paths:
            return
        index = max(0, min(index, len(self._preview_paths) - 1))
        self._preview_index = index
        total = len(self._preview_paths)
        ppm = self._preview_cache.get(index)
        if ppm is None:
            try:
                # One slice only: a 1 GB study is never loaded into memory.
                ppm = preview.render_ppm(self._preview_paths[index])
            except Exception as exc:  # noqa: BLE001 - shown inside the canvas
                self._preview_photo = None
                self.preview_canvas.itemconfigure(self._preview_image, image="")
                self.preview_canvas.itemconfigure(
                    self._preview_text,
                    text=self.t("preview_error", error=str(exc)[:80]),
                )
                self.preview_counter.configure(text="%d / %d" % (index + 1, total))
                return
            if len(self._preview_cache) >= 8:
                self._preview_cache.pop(next(iter(self._preview_cache)))
            self._preview_cache[index] = ppm
        try:
            self._preview_photo = self._tk.PhotoImage(data=ppm)
        except Exception:  # noqa: BLE001 - Tk build without PPM support
            return
        self.preview_canvas.itemconfigure(
            self._preview_image, image=self._preview_photo
        )
        self.preview_canvas.itemconfigure(self._preview_text, text="")
        self.preview_counter.configure(text="%d / %d" % (index + 1, total))

    # -- actions ----------------------------------------------------------

    def choose_input(self) -> None:
        path = self._filedialog.askopenfilename(
            title=self.t("dialog_open"),
            filetypes=[
                ("DICOM", "*.dcm *.DCM *.ima *.IMA"),
                (self.t("all_files"), "*"),
            ],
        )
        if path:
            self.set_source(path)

    def choose_output(self) -> None:
        path = self._filedialog.askdirectory(title=self.t("dialog_out"))
        if path:
            self.output_var.set(path)

    def open_output(self) -> None:
        path = self.output_var.get().strip().strip('"')
        if not path or not os.path.isdir(path):
            self._messagebox.showinfo(
                self.t("folder_missing"), self.t("folder_missing_text")
            )
            return
        try:
            _open_folder(path)
        except Exception as exc:  # noqa: BLE001 - system dependent
            self._messagebox.showerror(self.t("open_failed"), str(exc))

    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        source = self.input_var.get().strip().strip('"')
        if not source:
            self._messagebox.showwarning(self.t("no_file"), self.t("no_file_text"))
            return
        if not os.path.isfile(source):
            self._messagebox.showerror(self.t("file_missing"), source)
            return
        target = self.output_var.get().strip().strip('"')
        if not target:
            target = os.path.splitext(source)[0] + "_slices"
            self.output_var.set(target)

        # Read the widgets here, on the main thread: Tk variables must not be
        # touched from the worker thread that does the conversion.
        anonymize = self.anon_var.get()
        keep_private = self.private_var.get()

        self.clear_log()
        self.clear_preview()
        self.progress_var.set(0.0)
        self.progress_text.set("")
        self.open_button.configure(state="disabled")
        self.run_button.configure(state="disabled")
        self.set_status("status_busy", "Busy")
        self.append_log(self.t("log_source", path=source))
        self.append_log(self.t("log_output", path=target))

        def on_progress(done: int, total: int) -> None:
            self.messages.put(("progress", (done, total)))

        def job() -> None:
            try:
                report = convert_file(
                    source,
                    target,
                    anonymize=anonymize,
                    keep_private_tags=keep_private,
                    progress=on_progress,
                )
                self.messages.put(("ok", report))
            except ConversionError as exc:
                self.messages.put(("error", str(exc)))
            except Exception as exc:  # noqa: BLE001 - reported in the window
                self.messages.put(("error", "%s\n\n%s" % (exc, traceback.format_exc())))

        self._worker = threading.Thread(target=job, daemon=True)
        self._worker.start()

    def poll(self) -> None:
        try:
            kind, payload = self.messages.get_nowait()
        except queue.Empty:
            self.root.after(80, self.poll)
            return

        if kind == "info":
            self.info_label.configure(text=str(payload))
        elif kind == "progress":
            done, total = payload  # type: ignore[misc]
            self.progress_var.set(100.0 * done / total if total else 0.0)
            self.progress_text.set("%d / %d" % (done, total))
        elif kind == "ok":
            report = payload  # type: ConversionReport
            self.progress_var.set(100.0)
            self.append_log("")
            self.append_log(_summary(report))
            for warning in report.warnings:
                self.append_log(self.t("log_warning", text=warning))
            self.run_button.configure(state="normal")
            self.open_button.configure(state="normal")
            self.set_preview(report.output_files)
            self.set_status(
                "status_done",
                "Ok",
                frames=report.frame_count,
                series=len(report.series),
                path=report.output_dir,
            )
        else:
            self.append_log(self.t("log_error", text=payload))
            self.progress_var.set(0.0)
            self.progress_text.set("")
            self.run_button.configure(state="normal")
            self.set_status("status_error", "Error")
            self._messagebox.showerror(self.t("error_title"), str(payload))

        self.root.after(80, self.poll)


def run_gui() -> int:
    import tkinter as tk

    try:  # crisp text on Windows high-DPI displays
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001, S110 - not Windows, or old Windows
        pass

    root = tk.Tk()
    root.title("uncompressMRI %s" % __version__)
    root.geometry("1080x840")
    root.minsize(980, 820)

    app = UncompressApp(root)
    root.bind("<Return>", lambda _event: app.start())
    root.bind("<Control-o>", lambda _event: app.choose_input())
    root.bind("<Escape>", lambda _event: root.destroy())
    root.after(80, app.poll)
    _center_window(root)
    root.mainloop()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    # In a PyInstaller --windowed build sys.stdout/stderr are None, which
    # breaks print() and logging. Send them to os.devnull instead.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115 - lives for the process
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115 - lives for the process

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        return run_cli(argv)
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
