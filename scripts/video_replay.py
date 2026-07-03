"""通用影片回放：把任意影片檔或影片資料夾當離線鏡頭，餵進疲勞/rPPG 引擎。

與 scripts/utarldd_replay.py 的差異：這裡不要求 UTA-RLDD 目錄/檔名結構
（0.mov/5.mov/10.mov），適用任意單一影片檔或不含官方 label 的資料夾。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from gui.video_replay import run_replay_batch


def main() -> None:
    parser = argparse.ArgumentParser(description="批次回放任意影片並輸出 SQLite/CSV 指標。")
    parser.add_argument(
        "dataset_root",
        type=Path,
        help="單一影片檔或任意影片資料夾，例如 %%USERPROFILE%%\\Videos\\clip.mp4 或 %%USERPROFILE%%\\Videos\\clips",
    )
    parser.add_argument("--output-dir", type=Path, help="輸出目錄；預設為 recordings/replay_runs/<timestamp>")
    parser.add_argument("--max-videos", type=int, default=0, help="最多處理影片數，0 代表不限制")
    parser.add_argument("--max-frames", type=int, default=0, help="每支影片最多處理幀數，0 代表全幀")
    parser.add_argument("--jobs", type=int, default=1, help="平行處理影片數，建議 2-4；預設 1")
    parser.add_argument(
        "--write-annotated-video",
        action="store_true",
        help="額外輸出標註後 mp4，預設關閉；jobs > 1 時會自動停用以降低多進程資源壓力",
    )
    args = parser.parse_args()

    def progress(event: str, current: int, total: int, summary) -> None:
        if event == "video_start":
            print(f"[{current}/{total}] 開始處理影片")
        elif event == "video_done" and summary is not None:
            print(
                f"[{current}/{total}] 完成 subject={summary.subject} "
                f"frames={summary.frames} face_rate={summary.face_rate:.3f} status={summary.status}"
            )
        elif event == "frame" and summary is not None and total > 0:
            print(
                f"  frame {current}/{total} subject={summary.subject}",
                end="\r",
            )

    result = run_replay_batch(
        args.dataset_root,
        output_dir=args.output_dir,
        max_videos=max(0, args.max_videos),
        max_frames=max(0, args.max_frames),
        write_annotated_video=bool(args.write_annotated_video),
        jobs=max(1, args.jobs),
        progress_cb=progress,
        labeled=False,
    )
    print()
    print(f"輸出目錄: {result.output_dir}")
    print(f"好讀摘要 CSV: {result.summary_csv}")
    print(f"完整欄位 CSV: {result.full_summary_csv}")
    print(f"可視化 HTML 報表: {result.visual_report_html}")
    print("（無 label，略過驗證報表）")
    print(f"Manifest: {result.manifest_path}")
    print(f"影片總數: {result.videos_total}, 完成: {result.videos_done}, 失敗: {result.videos_failed}")


if __name__ == "__main__":
    main()
