from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui.utarldd_replay import write_visual_report_html_from_csv


def _default_output(summary_csv: Path) -> Path:
    stem = summary_csv.stem
    if stem.startswith("utarldd_summary_"):
        suffix = stem.removeprefix("utarldd_summary_")
        return summary_csv.with_name(f"utarldd_visual_report_{suffix}.html")
    return summary_csv.with_suffix(".html")


def main() -> None:
    parser = argparse.ArgumentParser(description="將 UTA-RLDD summary CSV 轉成單檔 HTML 可視化報表。")
    parser.add_argument("summary_csv", type=Path, help="utarldd_summary_<timestamp>.csv 路徑")
    parser.add_argument("--output", type=Path, help="輸出 HTML 路徑；預設與 summary CSV 同資料夾")
    args = parser.parse_args()

    summary_csv = Path(args.summary_csv)
    output = Path(args.output) if args.output else _default_output(summary_csv)
    write_visual_report_html_from_csv(summary_csv, output)
    print(f"可視化 HTML 報表: {output}")


if __name__ == "__main__":
    main()
