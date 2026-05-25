from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def summarize(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(metrics)")
    columns = {str(row[1]) for row in cur.fetchall()}

    def one(sql: str):
        cur.execute(sql)
        row = cur.fetchone()
        return row[0] if row else None

    def avg_col(name: str, where: str = "") -> float:
        if name not in columns:
            return 0.0
        suffix = f" {where}" if where else ""
        return float(one(f"SELECT AVG({name}) FROM metrics{suffix}") or 0.0)

    def count_where(name: str, expr: str) -> int:
        if name not in columns:
            return 0
        return int(one(f"SELECT COUNT(*) FROM metrics WHERE {expr}") or 0)

    total = one("SELECT COUNT(*) FROM metrics") or 0
    avg_quality = avg_col("rppg_quality_score")
    avg_fat_quality = avg_col("fatigue_quality_score")
    avg_sqi = avg_col("sqi")
    avg_bpm = avg_col("bpm", "WHERE bpm > 0")
    avg_jitter = avg_col("rppg_landmark_jitter_norm")
    avg_roi_area_stability = avg_col("rppg_roi_area_stability")
    low_quality = count_where("rppg_quality_score", "rppg_quality_score < 0.4")
    high_art = count_where("ibi_artifact_ratio", "ibi_artifact_ratio > 0.35")
    poor_roi = count_where("rppg_roi_valid_count", "rppg_roi_valid_count < 3")

    print(f"資料庫: {db_path}")
    print(f"總筆數: {int(total)}")
    print(f"平均 rPPG quality_score: {float(avg_quality):.3f}")
    print(f"平均 fatigue quality_score: {float(avg_fat_quality):.3f}")
    print(f"平均 SQI: {float(avg_sqi):.3f}")
    print(f"平均 BPM: {float(avg_bpm):.2f}")
    print(f"平均 landmark jitter: {float(avg_jitter):.4f}")
    print(f"平均 ROI 面積穩定度: {float(avg_roi_area_stability):.3f}")
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
        val = avg_col(col)
        print(f"  {col}: {float(val):.3f}")

    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="彙整錄製資料中的 MediaPipe / rPPG 校準品質資訊")
    ap.add_argument("db_path", type=Path, help="metrics_*.db 路徑")
    args = ap.parse_args()
    summarize(args.db_path)


if __name__ == "__main__":
    main()
