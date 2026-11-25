'''
   Copyright 2022-2026 Maksim Trushin  PET-Technology Podolsk
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


def run_gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    try:  # crisp text on Windows high-DPI displays
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001, S110 - not Windows, or old Windows
        pass

    root = tk.Tk()
    root.title("uncompressMRI %s" % __version__)
    root.geometry("860x640")
    root.minsize(760, 560)

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
    style.configure("TProgressbar", thickness=8)

    input_var = tk.StringVar()
    output_var = tk.StringVar()
    anon_var = tk.BooleanVar(value=False)
    private_var = tk.BooleanVar(value=False)
    progress_var = tk.DoubleVar(value=0.0)
    progress_text = tk.StringVar(value="")
    status_var = tk.StringVar(value="Выберите файл серии")

    messages: queue.Queue[tuple[str, object]] = queue.Queue()
    worker: dict[str, threading.Thread | None] = {"thread": None}

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
    ttk.Entry(source_box, textvariable=input_var).grid(row=0, column=1, sticky="ew")
    ttk.Button(source_box, text="Обзор…", command=lambda: choose_input()).grid(
        row=0, column=2, padx=(8, 0)
    )
    info_label = ttk.Label(source_box, text="", style="Subtitle.TLabel", justify="left")
    info_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

    output_box = ttk.LabelFrame(outer, text=" Папка результата ", padding=10)
    output_box.grid(row=2, column=0, sticky="ew", pady=(12, 0))
    output_box.columnconfigure(1, weight=1)
    ttk.Label(output_box, text="Папка").grid(row=0, column=0, sticky="w", padx=(0, 8))
    ttk.Entry(output_box, textvariable=output_var).grid(row=0, column=1, sticky="ew")
    ttk.Button(output_box, text="Обзор…", command=lambda: choose_output()).grid(
        row=0, column=2, padx=(8, 0)
    )
    ttk.Label(
        output_box,
        text="Пусто → <имя файла>_slices рядом с исходным файлом",
        style="Subtitle.TLabel",
    ).grid(row=1, column=1, columnspan=2, sticky="w", pady=(6, 0))

    options = ttk.Frame(outer)
    options.grid(row=3, column=0, sticky="w", pady=(12, 0))
    ttk.Checkbutton(
        options,
        text="Анонимизировать (ФИО/ID, новый Study UID)",
        variable=anon_var,
    ).pack(anchor="w")
    ttk.Checkbutton(
        options, text="Оставить приватные теги вендора", variable=private_var
    ).pack(anchor="w")

    actions = ttk.Frame(outer)
    actions.grid(row=4, column=0, sticky="ew", pady=(14, 0))
    actions.columnconfigure(2, weight=1)
    run_button = ttk.Button(actions, text="РАСПАКОВАТЬ", style="Primary.TButton")
    run_button.grid(row=0, column=0)
    open_button = ttk.Button(
        actions, text="Открыть папку", command=lambda: open_output(), state="disabled"
    )
    open_button.grid(row=0, column=1, padx=(8, 0))
    ttk.Label(actions, textvariable=progress_text, style="Subtitle.TLabel").grid(
        row=0, column=2, sticky="e"
    )

    progress = ttk.Progressbar(outer, variable=progress_var, maximum=100.0)
    progress.grid(row=5, column=0, sticky="ew", pady=(8, 0))

    log_frame = ttk.LabelFrame(outer, text=" Журнал ", padding=6)
    log_frame.grid(row=6, column=0, sticky="nsew", pady=(12, 0))
    log_frame.columnconfigure(0, weight=1)
    log_frame.rowconfigure(0, weight=1)
    log = tk.Text(
        log_frame,
        height=10,
        wrap="word",
        state="disabled",
        font="TkFixedFont",
        relief="flat",
        padx=6,
        pady=6,
    )
    log.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(log_frame, command=log.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    log.configure(yscrollcommand=scrollbar.set)

    status = ttk.Label(outer, textvariable=status_var, style="Status.TLabel")
    status.grid(row=7, column=0, sticky="w", pady=(10, 0))

    def append_log(text: str) -> None:
        log.configure(state="normal")
        log.insert("end", text.rstrip() + "\n")
        log.see("end")
        log.configure(state="disabled")

    def clear_log() -> None:
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.configure(state="disabled")

    def set_status(text: str, kind: str = "Idle") -> None:
        status.configure(style=_STATUS_STYLES.get(kind, "Status.TLabel"))
        status_var.set(text)

    def update_info(path: str) -> None:
        info_label.configure(text="Читаю заголовок…")

        def job() -> None:
            try:
                messages.put(("info", describe(path)))
            except Exception as exc:  # noqa: BLE001 - shown to the user
                messages.put(("info", "Не удалось прочитать заголовок: %s" % exc))

        threading.Thread(target=job, daemon=True).start()

    def choose_input() -> None:
        path = filedialog.askopenfilename(
            title="Выберите файл DICOM",
            filetypes=[("DICOM", "*.dcm *.DCM *.ima *.IMA"), ("Все файлы", "*")],
        )
        if not path:
            return
        input_var.set(path)
        output_var.set(os.path.splitext(path)[0] + "_slices")
        update_info(path)
        set_status("Файл выбран")

    def choose_output() -> None:
        path = filedialog.askdirectory(title="Выберите папку результата")
        if path:
            output_var.set(path)

    def open_output() -> None:
        path = output_var.get().strip().strip('"')
        if not path or not os.path.isdir(path):
            messagebox.showinfo("Папка не найдена", "Сначала выполните распаковку.")
            return
        try:
            _open_folder(path)
        except Exception as exc:  # noqa: BLE001 - system dependent
            messagebox.showerror("Не удалось открыть папку", str(exc))

    def start() -> None:
        if worker["thread"] is not None and worker["thread"].is_alive():
            return
        source = input_var.get().strip().strip('"')
        if not source:
            messagebox.showwarning("Нет файла", "Выберите файл серии.")
            return
        if not os.path.isfile(source):
            messagebox.showerror("Файл не найден", source)
            return
        target = output_var.get().strip().strip('"')
        if not target:
            target = os.path.splitext(source)[0] + "_slices"
            output_var.set(target)

        clear_log()
        progress_var.set(0.0)
        progress_text.set("")
        open_button.configure(state="disabled")
        run_button.configure(state="disabled")
        set_status("Распаковка…", "Busy")
        append_log("Источник: %s" % source)
        append_log("Результат: %s" % target)

        def on_progress(done: int, total: int) -> None:
            messages.put(("progress", (done, total)))

        def job() -> None:
            try:
                report = convert_file(
                    source,
                    target,
                    anonymize=anon_var.get(),
                    keep_private_tags=private_var.get(),
                    progress=on_progress,
                )
                messages.put(("ok", report))
            except ConversionError as exc:
                messages.put(("error", str(exc)))
            except Exception as exc:  # noqa: BLE001 - reported in the window
                messages.put(("error", "%s\n\n%s" % (exc, traceback.format_exc())))

        thread = threading.Thread(target=job, daemon=True)
        worker["thread"] = thread
        thread.start()

    def poll() -> None:
        try:
            kind, payload = messages.get_nowait()
        except queue.Empty:
            root.after(80, poll)
            return

        if kind == "info":
            info_label.configure(text=str(payload))
        elif kind == "progress":
            done, total = payload  # type: ignore[misc]
            progress_var.set(100.0 * done / total if total else 0.0)
            progress_text.set("%d / %d" % (done, total))
        elif kind == "ok":
            report = payload  # type: ConversionReport
            progress_var.set(100.0)
            append_log("")
            append_log(_summary(report))
            for warning in report.warnings:
                append_log("ВНИМАНИЕ: %s" % warning)
            run_button.configure(state="normal")
            open_button.configure(state="normal")
            set_status(
                "Готово: %d срез(ов) в %d сери(ях) → %s"
                % (report.frame_count, len(report.series), report.output_dir),
                "Ok",
            )
        else:
            append_log("ОШИБКА: %s" % payload)
            progress_var.set(0.0)
            progress_text.set("")
            run_button.configure(state="normal")
            set_status("Ошибка", "Error")
            messagebox.showerror("Не удалось распаковать", str(payload))

        root.after(80, poll)

    run_button.configure(command=start)
    root.bind("<Return>", lambda _event: start())
    root.bind("<Control-o>", lambda _event: choose_input())
    root.bind("<Escape>", lambda _event: root.destroy())
    root.after(80, poll)
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
