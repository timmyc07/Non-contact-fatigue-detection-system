from __future__ import annotations

import re
import textwrap
from pathlib import Path

from matplotlib import font_manager
from matplotlib.axes import Axes
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "rppg_technical_report.md"
TARGET = ROOT / "docs" / "rppg_technical_report.pdf"


FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
]


def _font_properties(size: float) -> font_manager.FontProperties:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return font_manager.FontProperties(fname=path, size=size)
    return font_manager.FontProperties(size=size)


FONT_BODY = _font_properties(10.2)
FONT_SMALL = _font_properties(8.5)
FONT_H1 = _font_properties(18.0)
FONT_H2 = _font_properties(13.8)
FONT_H3 = _font_properties(11.8)


def _clean_inline(text: str) -> str:
    text = text.replace("`", "")
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1（\2）", text)
    return text


def _wrap(text: str, width: int) -> list[str]:
    if not text.strip():
        return [""]
    return textwrap.wrap(
        _clean_inline(text),
        width=width,
        break_long_words=False,
        replace_whitespace=False,
    ) or [""]


def _parse_markdown(md: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    in_code = False
    code_lines: list[str] = []
    para: list[str] = []

    def flush_para() -> None:
        nonlocal para
        if para:
            blocks.append(("p", " ".join(x.strip() for x in para)))
            para = []

    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                blocks.append(("code", "\n".join(code_lines)))
                code_lines = []
                in_code = False
            else:
                flush_para()
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line.strip():
            flush_para()
            continue
        if line.startswith("# "):
            flush_para()
            blocks.append(("h1", line[2:].strip()))
            continue
        if line.startswith("## "):
            flush_para()
            blocks.append(("h2", line[3:].strip()))
            continue
        if line.startswith("### "):
            flush_para()
            blocks.append(("h3", line[4:].strip()))
            continue
        if line.startswith("- "):
            flush_para()
            blocks.append(("li", line[2:].strip()))
            continue
        if re.match(r"^\d+\.\s+", line):
            flush_para()
            blocks.append(("li", re.sub(r"^\d+\.\s+", "", line).strip()))
            continue
        para.append(line)
    flush_para()
    return blocks


def _new_page(pdf: PdfPages, page_no: int) -> tuple[Figure, Axes, float]:
    fig = Figure(figsize=(8.27, 11.69))
    ax = fig.add_axes((0, 0, 1, 1))
    ax.axis("off")
    ax.text(
        0.5,
        0.025,
        f"rPPG 技術、演算法與系統運作說明 | {page_no}",
        ha="center",
        va="bottom",
        fontproperties=FONT_SMALL,
        color="#555555",
    )
    return fig, ax, 0.955


def _save_page(pdf: PdfPages, fig: Figure) -> None:
    pdf.savefig(fig)


def build_pdf() -> None:
    blocks = _parse_markdown(SOURCE.read_text(encoding="utf-8"))
    TARGET.parent.mkdir(parents=True, exist_ok=True)

    page_no = 1
    with PdfPages(TARGET) as pdf:
        fig, ax, y = _new_page(pdf, page_no)

        for kind, text in blocks:
            if kind == "h1":
                font = FONT_H1
                line_h = 0.030
                gap = 0.020
                width = 28
                color = "#111111"
            elif kind == "h2":
                font = FONT_H2
                line_h = 0.024
                gap = 0.014
                width = 34
                color = "#1f2937"
            elif kind == "h3":
                font = FONT_H3
                line_h = 0.021
                gap = 0.010
                width = 38
                color = "#334155"
            elif kind == "li":
                font = FONT_BODY
                line_h = 0.0185
                gap = 0.005
                width = 48
                color = "#111111"
                text = "• " + text
            elif kind == "code":
                font = FONT_SMALL
                line_h = 0.0165
                gap = 0.008
                width = 62
                color = "#334155"
            else:
                font = FONT_BODY
                line_h = 0.0185
                gap = 0.007
                width = 50
                color = "#111111"

            lines: list[str] = []
            for part in text.split("\n"):
                lines.extend(_wrap(part, width))
            needed = len(lines) * line_h + gap
            if y - needed < 0.065:
                _save_page(pdf, fig)
                page_no += 1
                fig, ax, y = _new_page(pdf, page_no)

            x = 0.085
            if kind == "li":
                x = 0.105
            elif kind == "code":
                x = 0.095
            for line in lines:
                ax.text(
                    x,
                    y,
                    line,
                    ha="left",
                    va="top",
                    fontproperties=font,
                    color=color,
                )
                y -= line_h
            y -= gap

        _save_page(pdf, fig)


if __name__ == "__main__":
    build_pdf()
