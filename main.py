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
import logging
import os
import queue
import subprocess
import sys
import threading
import traceback
from collections.abc import Sequence

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


class UncompressApp:
    """The main window.

    A class rather than a closure so tools (screenshots, docs) and tests can
    build the window and drive it without faking mouse clicks.
    """

    def __init__(self, root) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        self._tk = tk
        self._filedialog = filedialog
        self._messagebox = messagebox
        self.root = root
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self._worker: threading.Thread | None = None

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
        self.status_var = tk.StringVar(value="Выберите файл серии")

        outer = ttk.Frame(root, padding=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(6, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        ttk.Label(header, text="Распаковка enhanced MRI", style="Title.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            header,
            text="Multi-frame DICOM → посрезовые файлы для Eclipse / Aria",
            style="Subtitle.TLabel",
        ).pack(anchor="w")

        source_box = ttk.LabelFrame(outer, text=" Исходный файл ", padding=10)
        source_box.grid(row=1, column=0, sticky="ew")
        source_box.columnconfigure(1, weight=1)
        ttk.Label(source_box, text="Файл серии").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.source_entry = ttk.Entry(source_box, textvariable=self.input_var)
        self.source_entry.grid(row=0, column=1, sticky="ew")
        self.source_button = ttk.Button(
            source_box, text="Обзор…", command=self.choose_input
        )
        self.source_button.grid(row=0, column=2, padx=(8, 0))
        self.info_label = ttk.Label(
            source_box, text="", style="Subtitle.TLabel", justify="left"
        )
        self.info_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        output_box = ttk.LabelFrame(outer, text=" Папка результата ", padding=10)
        output_box.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        output_box.columnconfigure(1, weight=1)
        ttk.Label(output_box, text="Папка").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.output_entry = ttk.Entry(output_box, textvariable=self.output_var)
        self.output_entry.grid(row=0, column=1, sticky="ew")
        self.output_button = ttk.Button(
            output_box, text="Обзор…", command=self.choose_output
        )
        self.output_button.grid(row=0, column=2, padx=(8, 0))
        ttk.Label(
            output_box,
            text="Пусто → <имя файла>_slices рядом с исходным файлом",
            style="Subtitle.TLabel",
        ).grid(row=1, column=1, columnspan=2, sticky="w", pady=(6, 0))

        options = ttk.Frame(outer)
        options.grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.anon_check = ttk.Checkbutton(
            options,
            text="Анонимизировать (ФИО/ID, новый Study UID)",
            variable=self.anon_var,
        )
        self.anon_check.pack(anchor="w")
        self.private_check = ttk.Checkbutton(
            options, text="Оставить приватные теги вендора", variable=self.private_var
        )
        self.private_check.pack(anchor="w")

        actions = ttk.Frame(outer)
        actions.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        actions.columnconfigure(2, weight=1)
        self.run_button = ttk.Button(
            actions, text="РАСПАКОВАТЬ", style="Primary.TButton", command=self.start
        )
        self.run_button.grid(row=0, column=0)
        self.open_button = ttk.Button(
            actions, text="Открыть папку", command=self.open_output, state="disabled"
        )
        self.open_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(actions, textvariable=self.progress_text, style="Subtitle.TLabel").grid(
            row=0, column=2, sticky="e"
        )

        self.progress_bar = ttk.Progressbar(
            outer, variable=self.progress_var, maximum=100.0
        )
        self.progress_bar.grid(row=5, column=0, sticky="ew", pady=(8, 0))

        log_frame = ttk.LabelFrame(outer, text=" Журнал ", padding=6)
        log_frame.grid(row=6, column=0, sticky="nsew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(
            log_frame,
            height=10,
            wrap="word",
            state="disabled",
            font="TkFixedFont",
            relief="flat",
            padx=6,
            pady=6,
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

        self.status_label = ttk.Label(
            outer, textvariable=self.status_var, style="Status.TLabel"
        )
        self.status_label.grid(row=7, column=0, sticky="w", pady=(10, 0))

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

    def set_status(self, text: str, kind: str = "Idle") -> None:
        self.status_label.configure(style=_STATUS_STYLES.get(kind, "Status.TLabel"))
        self.status_var.set(text)

    def set_source(self, path: str, output: str | None = None) -> None:
        """Fill in the file fields and refresh the header information."""
        self.input_var.set(path)
        self.output_var.set(output or os.path.splitext(path)[0] + "_slices")
        self.update_info(path)
        self.set_status("Файл выбран")

    def update_info(self, path: str) -> None:
        self.info_label.configure(text="Читаю заголовок…")

        def job() -> None:
            try:
                self.messages.put(("info", describe(path, compact=True)))
            except Exception as exc:  # noqa: BLE001 - shown to the user
                self.messages.put(("info", "Не удалось прочитать заголовок: %s" % exc))

        threading.Thread(target=job, daemon=True).start()

    # -- actions ----------------------------------------------------------

    def choose_input(self) -> None:
        path = self._filedialog.askopenfilename(
            title="Выберите файл DICOM",
            filetypes=[("DICOM", "*.dcm *.DCM *.ima *.IMA"), ("Все файлы", "*")],
        )
        if path:
            self.set_source(path)

    def choose_output(self) -> None:
        path = self._filedialog.askdirectory(title="Выберите папку результата")
        if path:
            self.output_var.set(path)

    def open_output(self) -> None:
        path = self.output_var.get().strip().strip('"')
        if not path or not os.path.isdir(path):
            self._messagebox.showinfo("Папка не найдена", "Сначала выполните распаковку.")
            return
        try:
            _open_folder(path)
        except Exception as exc:  # noqa: BLE001 - system dependent
            self._messagebox.showerror("Не удалось открыть папку", str(exc))

    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        source = self.input_var.get().strip().strip('"')
        if not source:
            self._messagebox.showwarning("Нет файла", "Выберите файл серии.")
            return
        if not os.path.isfile(source):
            self._messagebox.showerror("Файл не найден", source)
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
        self.progress_var.set(0.0)
        self.progress_text.set("")
        self.open_button.configure(state="disabled")
        self.run_button.configure(state="disabled")
        self.set_status("Распаковка…", "Busy")
        self.append_log("Источник: %s" % source)
        self.append_log("Результат: %s" % target)

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
                self.append_log("ВНИМАНИЕ: %s" % warning)
            self.run_button.configure(state="normal")
            self.open_button.configure(state="normal")
            self.set_status(
                "Готово: %d срез(ов) в %d сери(ях) → %s"
                % (report.frame_count, len(report.series), report.output_dir),
                "Ok",
            )
        else:
            self.append_log("ОШИБКА: %s" % payload)
            self.progress_var.set(0.0)
            self.progress_text.set("")
            self.run_button.configure(state="normal")
            self.set_status("Ошибка", "Error")
            self._messagebox.showerror("Не удалось распаковать", str(payload))

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
    root.geometry("880x720")
    root.minsize(780, 620)

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
