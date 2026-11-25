"""Regenerate the images used in README.md (developer tool, not shipped).

Needs a real X display plus ImageMagick (``import``) and ffmpeg::

    python -m pip install pillow
    python tools/make_screenshots.py

Writes docs/gui-main.png, docs/gui-done.png, docs/gui-howto.png, docs/demo.gif.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dcm_magic import __version__  # noqa: E402
from main import UncompressApp, _center_window  # noqa: E402

DOCS = os.path.join(ROOT, "docs")
SAMPLE = os.path.join(ROOT, "IMG-0001-00001.dcm")
DEMO_DIR = "/tmp/MRI"
SAMPLE_COPY = os.path.join(DEMO_DIR, "IMG-0001-00001.dcm")
DEMO_OUT = os.path.join(DEMO_DIR, "slices")
RAW_VIDEO = "/tmp/opencode/uncompressMRI-demo.mkv"


def grab(root: tk.Tk, path: str) -> None:
    """Save the client area of *root* exactly as it is on screen."""
    subprocess.run(["import", "-window", str(root.winfo_id()), path], check=True)
    print("saved", os.path.relpath(path, ROOT), flush=True)


def widget_box(app: UncompressApp, widget) -> dict[str, int]:
    root = app.root
    return {
        "x": widget.winfo_rootx() - root.winfo_rootx(),
        "y": widget.winfo_rooty() - root.winfo_rooty(),
        "w": widget.winfo_width(),
        "h": widget.winfo_height(),
    }


def record(root: tk.Tk, path: str) -> subprocess.Popen:
    root.update_idletasks()
    rect = "%s+%d,%d" % (
        os.environ.get("DISPLAY", ":0"),
        root.winfo_rootx(),
        root.winfo_rooty(),
    )
    return subprocess.Popen(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "x11grab",
            "-framerate",
            "15",
            "-video_size",
            "%dx%d" % (root.winfo_width(), root.winfo_height()),
            "-i",
            rect,
            "-t",
            "25",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            path,
        ]
    )


def make_gif(video: str, out: str, width: int = 780, fps: int = 12) -> None:
    script = (
        "fps=%d,scale=%d:-1:flags=lanczos,split[a][b];"
        "[a]palettegen=max_colors=160[p];"
        "[b][p]paletteuse=dither=bayer:bayer_scale=3" % (fps, width)
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-vf", script,
         "-loop", "0", out],
        check=True,
    )
    print(
        "saved",
        os.path.relpath(out, ROOT),
        "(%.1f MB)" % (os.path.getsize(out) / 1e6),
        flush=True,
    )


def annotate(clean: str, out: str, targets: list[tuple[int, str, dict[str, int]]]) -> None:
    from PIL import Image, ImageDraw, ImageFont

    fonts = "/usr/share/fonts/truetype/dejavu/"
    bold = ImageFont.truetype(fonts + "DejaVuSans-Bold.ttf", 19)
    regular = ImageFont.truetype(fonts + "DejaVuSans.ttf", 17)
    title_font = ImageFont.truetype(fonts + "DejaVuSans-Bold.ttf", 24)

    shot = Image.open(clean).convert("RGB")
    shot_w, shot_h = shot.size
    left, top, gap = 350, 70, 28
    canvas = Image.new("RGB", (left + shot_w + gap, top + shot_h + gap), "#f6f8fa")
    draw = ImageDraw.Draw(canvas)

    draw.text((26, 22), "uncompressMRI %s — что нажимать" % __version__,
              fill="#1f2328", font=title_font)
    draw.rectangle([left + 4, top + 5, left + shot_w + 4, top + shot_h + 5],
                   fill="#d8dee4")
    canvas.paste(shot, (left, top))
    draw.rectangle([left - 1, top - 1, left + shot_w, top + shot_h], outline="#c6cdd5")

    previous = top - 100
    for number, label, target in targets:
        cy = top + target["y"] + target["h"] // 2
        text_y = max(top + 18, min(cy, top + shot_h - 22), previous + 72)
        text_y = min(text_y, top + shot_h - 22)
        previous = text_y
        draw.multiline_text((86, text_y), label, fill="#1f2328", font=regular,
                            anchor="lm", spacing=4)
        draw.ellipse([28, text_y - 16, 60, text_y + 16], fill="#0969da")
        draw.text((44, text_y), str(number), fill="white", font=bold, anchor="mm")

        end_x = left + 22
        draw.line([300, text_y, end_x - 14, cy], fill="#0969da", width=3)
        draw.polygon([(end_x, cy), (end_x - 16, cy - 8), (end_x - 16, cy + 8)],
                     fill="#0969da")

    canvas.save(out, optimize=True)
    print("saved", os.path.relpath(out, ROOT), flush=True)


def main() -> int:
    if not os.path.exists(SAMPLE):
        print("sample file not found:", SAMPLE)
        return 1
    os.makedirs(DOCS, exist_ok=True)
    os.makedirs(DEMO_OUT, exist_ok=True)
    shutil.copyfile(SAMPLE, SAMPLE_COPY)

    root = tk.Tk()
    root.title("uncompressMRI %s" % __version__)
    root.geometry("880x720")
    root.minsize(780, 620)
    root.attributes("-topmost", True)

    app = UncompressApp(root)
    root.after(80, app.poll)
    _center_window(root)

    state = {"step": "load"}
    recorder: dict[str, subprocess.Popen | None] = {"proc": None}

    def targets() -> list[tuple[int, str, dict[str, int]]]:
        return [
            (1, "Выберите файл\nсерии", widget_box(app, app.source_entry)),
            (2, "Проверьте папку\nрезультата", widget_box(app, app.output_entry)),
            (3, "Включите\nанонимизацию", widget_box(app, app.anon_check)),
            (4, "Нажмите\nРАСПАКОВАТЬ", widget_box(app, app.run_button)),
            (5, "Смотрите журнал\nи счётчик", widget_box(app, app.log)),
        ]

    def stop_recording() -> None:
        proc = recorder["proc"]
        if proc is not None and proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=30)
        if os.path.exists(RAW_VIDEO) and os.path.getsize(RAW_VIDEO) > 0:
            make_gif(RAW_VIDEO, os.path.join(DOCS, "demo.gif"))
            os.remove(RAW_VIDEO)
        grab(root, os.path.join(DOCS, "gui-done.png"))
        root.after(200, root.quit)

    def begin() -> None:
        app.start()
        state["step"] = "run"

    def tick() -> None:
        step = state["step"]
        info = app.info_label.cget("text")
        if step == "load" and info and "Читаю" not in info:
            clean = os.path.join(DOCS, "gui-main.png")
            grab(root, clean)
            annotate(clean, os.path.join(DOCS, "gui-howto.png"), targets())
            recorder["proc"] = record(root, RAW_VIDEO)
            state["step"] = "starting"
            root.after(700, begin)
        elif step == "run" and app.status_var.get().startswith("Готово"):
            state["step"] = "settle"
            root.after(1800, stop_recording)
        elif step == "error" and app.status_var.get() == "Ошибка":
            root.after(500, root.quit)
        root.after(100, tick)

    root.after(150, lambda: app.set_source(SAMPLE_COPY, DEMO_OUT))
    root.after(100, tick)
    root.mainloop()
    root.destroy()
    shutil.rmtree(DEMO_OUT, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
