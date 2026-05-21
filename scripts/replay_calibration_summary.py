from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def summarize(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    def one(sql: str):
        cur.execute(sql)
        row = cur.fetchone()
        return row[0] if row else None

    total = one("SELECT COUNT(*) FROM metrics") or 0
    avg_quality = one("SELECT AVG(rppg_quality_score) FROM metrics") or 0.0
    avg_fat_quality = one("SELECT AVG(fatigue_quality_score) FROM metrics") or 0.0
    avg_sqi = one("SELECT AVG(sqi) FROM metrics") or 0.0
    avg_bpm = one("SELECT AVG(bpm) FROM metrics WHERE bpm > 0") or 0.0
    low_quality = one("SELECT COUNT(*) FROM metrics WHERE rppg_quality_score < 0.4") or 0
    high_art = one("SELECT COUNT(*) FROM metrics WHERE ibi_artifact_ratio > 0.35") or 0
    poor_roi = one("SELECT COUNT(*) FROM metrics WHERE rppg_roi_valid_count < 3") or 0

    print(f"資料庫: {db_path}")
    print(f"總筆數: {int(total)}")
    print(f"平均 rPPG quality_score: {float(avg_quality):.3f}")
    print(f"平均 fatigue quality_score: {float(avg_fat_quality):.3f}")
    print(f"平均 SQI: {float(avg_sqi):.3f}")
    print(f"平均 BPM: {float(avg_bpm):.2f}")
    print(f"rPPG 低品質筆數 (<0.4): {int(low_quality)}")
    print(f"高 artifact 筆數 (>0.35): {int(high_art)}")
    print(f"ROI 可用數不足筆數 (<3): {int(poor_roi)}")

    print("\nROI 權重平均:")
    for col in (
        "rppg_roi_weight_forehead",
        "rppg_roi_weight_l_cheek",
        "rppg_roi_weight_r_cheek",
        "rppg_roi_weight_glabella",
    ):
        val = one(f"SELECT AVG({col}) FROM metrics") or 0.0
        print(f"  {col}: {float(val):.3f}")

    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="彙整錄製資料中的 MediaPipe / rPPG 校準品質資訊")
    ap.add_argument("db_path", type=Path, help="metrics_*.db 路徑")
    args = ap.parse_args()
    summarize(args.db_path)


if __name__ == "__main__":
    main()
