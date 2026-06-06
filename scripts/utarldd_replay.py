from __future__ import annotations

import argparse
from pathlib import Path

from gui.utarldd_replay import run_replay_batch


def _split_csv(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    out: list[str] = []
    for value in values:
        out.extend(part.strip() for part in value.split(",") if part.strip())
    return out or None


def main() -> None:
    parser = argparse.ArgumentParser(description="批次回放 UTA-RLDD 影片並輸出 SQLite/CSV 指標。")
    parser.add_argument("dataset_root", type=Path, help="UTA-RLDD fold 目錄，例如 %%USERPROFILE%%\\Downloads\\Fold1_part1")
    parser.add_argument("--output-dir", type=Path, help="輸出目錄；預設為 recordings/utarldd_runs/<timestamp>")
    parser.add_argument("--max-videos", type=int, default=0, help="最多處理影片數，0 代表不限制")
    parser.add_argument("--max-frames", type=int, default=0, help="每支影片最多處理幀數，0 代表全幀")
    parser.add_argument("--subject", action="append", help="只處理指定受試者，可重複或用逗號分隔，例如 01,02")
    parser.add_argument("--label", action="append", help="只處理指定 label，可重複或用逗號分隔，例如 0,5,10")
    parser.add_argument("--jobs", type=int, default=1, help="平行處理影片數，建議 2-4；預設 1")
    parser.add_argument("--write-annotated-video", action="store_true", help="額外輸出標註後 mp4，預設關閉")
    args = parser.parse_args()

    def progress(event: str, current: int, total: int, summary) -> None:
        if event == "video_start":
            print(f"[{current}/{total}] 開始處理影片")
        elif event == "video_done" and summary is not None:
            print(
                f"[{current}/{total}] 完成 subject={summary.subject} label={summary.label} "
                f"frames={summary.frames} face_rate={summary.face_rate:.3f} status={summary.status}"
            )
        elif event == "frame" and summary is not None and total > 0:
            print(
                f"  frame {current}/{total} subject={summary.subject} label={summary.label}",
                end="\r",
            )

    result = run_replay_batch(
        args.dataset_root,
        output_dir=args.output_dir,
        max_videos=max(0, args.max_videos),
        max_frames=max(0, args.max_frames),
        subjects=_split_csv(args.subject),
        labels=_split_csv(args.label),
        write_annotated_video=bool(args.write_annotated_video),
        jobs=max(1, args.jobs),
        progress_cb=progress,
    )
    print()
    print(f"輸出目錄: {result.output_dir}")
    print(f"好讀摘要 CSV: {result.summary_csv}")
    print(f"完整欄位 CSV: {result.full_summary_csv}")
    print(f"Manifest: {result.manifest_path}")
    print(f"影片總數: {result.videos_total}, 完成: {result.videos_done}, 失敗: {result.videos_failed}")


if __name__ == "__main__":
    main()
