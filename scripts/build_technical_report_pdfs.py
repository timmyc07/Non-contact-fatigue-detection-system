from __future__ import annotations

import argparse
import re
import textwrap
from pathlib import Path

from matplotlib import font_manager
from matplotlib.axes import Axes
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure


ROOT = Path(__file__).resolve().parents[1]

REPORTS = {
    "overview": {
        "source": ROOT / "docs" / "system_overview_technical_report.md",
        "target": ROOT / "docs" / "system_overview_technical_report.pdf",
        "footer": "系統總技術報告書",
    },
    "rppg": {
        "source": ROOT / "docs" / "rppg_technical_report_v2.md",
        "target": ROOT / "docs" / "rppg_technical_report_v2.pdf",
        "footer": "rPPG 系統技術報告書",
    },
    "mediapipe-fatigue": {
        "source": ROOT / "docs" / "mediapipe_fatigue_technical_report.md",
        "target": ROOT / "docs" / "mediapipe_fatigue_technical_report.pdf",
        "footer": "MediaPipe 疲勞偵測系統技術報告書",
    },
}

FONT_CANDIDATES = [
    "C:/Windows/Fonts/msjh.ttc",
    "C:/Windows/Fonts/mingliu.ttc",
    "C:/Windows/Fonts/simsun.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
]


def _font_properties(size: float) -> font_manager.FontProperties:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return font_manager.FontProperties(fname=path, size=size)
    return font_manager.FontProperties(size=size)


FONT_BODY = _font_properties(10.0)
FONT_SMALL = _font_properties(8.2)
FONT_H1 = _font_properties(18.0)
FONT_H2 = _font_properties(13.5)
FONT_H3 = _font_properties(11.5)
FONT_CODE = _font_properties(8.4)


def _clean_inline(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1 (\2)", text)
    return text


def _wrap(text: str, width: int, *, break_long_words: bool = False) -> list[str]:
    if not text.strip():
        return [""]
    return textwrap.wrap(
        _clean_inline(text),
        width=width,
        break_long_words=break_long_words,
        break_on_hyphens=break_long_words,
        replace_whitespace=False,
    ) or [""]


def _parse_markdown(md: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    in_code = False
    in_refs = False
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
            heading = line[3:].strip()
            in_refs = heading.startswith("參考資料")
            blocks.append(("h2", heading))
            continue
        if line.startswith("### "):
            flush_para()
            blocks.append(("h3", line[4:].strip()))
            continue
        if line.startswith("|"):
            flush_para()
            blocks.append(("code", line))
            continue
        if in_refs and re.match(r"^\d+\.\s+", line):
            flush_para()
            blocks.append(("ref_title", re.sub(r"^\d+\.\s+", "", line).strip()))
            continue
        if in_refs and line.strip().startswith("http"):
            flush_para()
            blocks.append(("ref_url", line.strip()))
            continue
        if in_refs and line.strip().startswith("本系統參考技術"):
            flush_para()
            blocks.append(("ref_note", line.strip()))
            continue
        if line.startswith("- "):
            flush_para()
            blocks.append(("li", line[2:].strip()))
            continue
        if re.match(r"^\d+\.\s+", line):
            flush_para()
            blocks.append(("li", re.sub(r"^\d+\.\s+", "", line).strip()))
            continue
        if re.match(r"^\s{2,}\S", raw):
            flush_para()
            blocks.append(("p", line.strip()))
            continue
        para.append(line)
    flush_para()
    return blocks


def _new_page(pdf: PdfPages, page_no: int, footer: str) -> tuple[Figure, Axes, float]:
    fig = Figure(figsize=(8.27, 11.69))
    ax = fig.add_axes((0, 0, 1, 1))
    ax.axis("off")
    ax.text(
        0.5,
        0.025,
        f"{footer} | {page_no}",
        ha="center",
        va="bottom",
        fontproperties=FONT_SMALL,
        color="#555555",
    )
    return fig, ax, 0.955


def _block_style(kind: str) -> tuple[font_manager.FontProperties, float, float, int, str, float, bool]:
    if kind == "h1":
        return FONT_H1, 0.031, 0.020, 25, "#111111", 0.085, False
    if kind == "h2":
        return FONT_H2, 0.024, 0.017, 31, "#1f2937", 0.085, False
    if kind == "h3":
        return FONT_H3, 0.021, 0.012, 35, "#334155", 0.085, False
    if kind == "li":
        return FONT_BODY, 0.019, 0.007, 43, "#111111", 0.105, True
    if kind == "code":
        return FONT_CODE, 0.0165, 0.010, 60, "#334155", 0.095, True
    if kind == "ref_title":
        return FONT_BODY, 0.019, 0.004, 43, "#111111", 0.095, True
    if kind == "ref_url":
        return FONT_SMALL, 0.0165, 0.006, 62, "#374151", 0.095, True
    if kind == "ref_note":
        return FONT_BODY, 0.0188, 0.019, 45, "#111111", 0.095, True
    return FONT_BODY, 0.019, 0.009, 45, "#111111", 0.085, True


def build_pdf(source: Path, target: Path, footer: str) -> None:
    blocks = _parse_markdown(source.read_text(encoding="utf-8"))
    target.parent.mkdir(parents=True, exist_ok=True)

    page_no = 1
    with PdfPages(target) as pdf:
        fig, ax, y = _new_page(pdf, page_no, footer)

        for kind, text in blocks:
            font, line_h, gap, width, color, x, break_long_words = _block_style(kind)
            if kind == "li":
                text = "• " + text
            elif kind == "ref_title":
                text = "• " + text

            lines: list[str] = []
            for part in text.split("\n"):
                lines.extend(_wrap(part, width, break_long_words=break_long_words))
            needed = len(lines) * line_h + gap
            if y - needed < 0.065:
                pdf.savefig(fig)
                page_no += 1
                fig, ax, y = _new_page(pdf, page_no, footer)

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

        pdf.savefig(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build technical report PDFs.")
    parser.add_argument(
        "reports",
        nargs="*",
        help=f"Reports to build. Defaults to all. Choices: {', '.join(sorted(REPORTS))}.",
    )
    args = parser.parse_args()

    selected = args.reports or sorted(REPORTS)
    for name in selected:
        if name not in REPORTS:
            parser.error(f"unknown report {name!r}; choose from {', '.join(sorted(REPORTS))}")
        cfg = REPORTS[name]
        build_pdf(cfg["source"], cfg["target"], cfg["footer"])
        print(f"wrote {cfg['target']}")


if __name__ == "__main__":
    main()
