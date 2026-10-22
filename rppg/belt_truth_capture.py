"""belt-truth 同步錄製（P6b-4）：離線驗證 rPPG ROI 權重候選的錄製格式與 I/O。

背景（見 CLAUDE.md「心跳帶」段、docs/2026-07-04-p6b-handoff.md 第 101-104 行）：
P6a/P6b 已建立「有護欄自適應」基礎層（``rppg.adaptive_calibration.RppgParamAbEvaluator``
以心跳帶真值對現行 vs 候選 ROI 權重的 rPPG BPM 做 A/B），但 live 自適應迴圈需要心跳帶
硬體才能端到端驗證。開 live 前的阻塞項：無法在**沒有硬體連線的情況下**，把「同一段
訊號」用不同 ROI 權重重算 BPM 再對心跳帶真值算誤差——因為沒有一個「同步錄下 per-ROI
RGB 均值 + 心跳帶 BPM」的錄製檔案格式。本模組只做這件事：定義格式、寫入、讀回。

設計原則（唯讀觀察，零touch 既有數值路徑）：
- 本模組**不**計算/修改任何 rPPG 數值。它只在既有 ``RppgEngine.push_roi_means()``
  呼叫點旁路「抄一份」已經算好的 per-ROI RGB 均值到磁碟，並附上呼叫端提供的
  belt BPM 快照（可能是 ``None``，例如心跳帶未連線/資料停滯）。
- 錄製**預設關閉**（``worker._belt_truth_capture is None``）。關閉時 worker 逐幀迴圈
  的行為與現況逐位元相同——見 ``rppg/rppg_worker.py`` 的 ``_maybe_capture_belt_truth``
  與 ``gui/combined_worker.py`` 的同名方法，兩者在 writer=None 時立即 return，
  不額外配置、不呼叫本模組任何函式。

格式（JSONL，一行一筆，選型理由見任務回報「設計選擇說明」）：
    {"t": <float, 秒>,
     "roi_means": {"forehead": [r, g, b], "L_cheek": [...], "R_cheek": [...], "glabella": [...]},
     "belt_bpm": <float 或 null>}

執行緒安全假設：:class:`BeltTruthCaptureWriter` 由 GUI 主執行緒建構（開檔），
之後把參照透過 pending-flag 模式（見 ``set_belt_truth_capture``）交給 worker 執行緒
呼叫 :meth:`BeltTruthCaptureWriter.record`；GUI 主執行緒隨時可能呼叫 :meth:`close`
（例如使用者關閉心跳帶校準）。這與現有 ``set_candidate_roi_weights`` 的單一參照
賦值模式相同——CPython GIL 下參照讀寫具原子性，不需額外鎖。``record`` 對「檔案已
被另一執行緒關閉」這個競態做防禦：捕捉寫入失敗並記 log、不丟例外，避免錄製功能
的邊界競態影響主要疲勞/rPPG 判斷路徑。
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from gui.runtime_paths import data_path

logger = logging.getLogger(__name__)

CAPTURE_FORMAT_VERSION = 1

# 錄製檔預設輸出根目錄（沿用 scripts/video_replay.py 的 recordings/ 慣例）。
DEFAULT_CAPTURE_DIR = data_path("recordings", "belt_truth_capture")


@dataclass(frozen=True)
class BeltTruthCaptureRecord:
    """capture 檔單筆記錄（讀回後的型別化表示）。

    ``roi_means``：``{roi_name: (r, g, b)}``，鍵通常對應
    :data:`rppg.rppg_worker.ROI_SPECS` 的 4 個 ROI 名稱，但讀取端不強制檢查——
    容忍未來 ROI 集合變動。``belt_bpm``：``None`` 表示錄製當下沒有可用的心跳帶
    真值（未連線、資料停滯、或尚未收到樣本）。
    """

    t: float
    roi_means: dict[str, tuple[float, float, float]]
    belt_bpm: Optional[float] = None


class BeltTruthCaptureWriter:
    """Append-only JSONL writer：把 per-ROI RGB 均值與心跳帶 BPM 對齊寫檔。

    ``belt_bpm_provider``：呼叫端（通常是 ``gui.belt_runtime.BeltRuntime``）提供的
    無參數 callable，每筆記錄呼叫一次取得「當下」心跳帶 BPM 快照。provider 例外、
    回傳 ``None``、或回傳非有限數值，一律記為 ``belt_bpm=None``（不中斷錄製、
    不丟例外）——offline 驗證腳本本就要能處理缺值。
    """

    def __init__(
        self,
        path: str | Path,
        belt_bpm_provider: Optional[Callable[[], Optional[float]]] = None,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._provider = belt_bpm_provider
        self._fh = open(self._path, "a", encoding="utf-8", newline="")
        self._count = 0
        self._closed = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def record_count(self) -> int:
        return self._count

    def _sample_belt_bpm(self) -> Optional[float]:
        if self._provider is None:
            return None
        try:
            value = self._provider()
        except Exception:
            logger.exception("belt_bpm_provider 呼叫失敗，本筆記錄 belt_bpm=None")
            return None
        if value is None:
            return None
        try:
            fv = float(value)
        except (TypeError, ValueError):
            return None
        if fv != fv or fv in (float("inf"), float("-inf")):  # NaN/Inf 防護
            return None
        return fv

    def record(self, t: float, roi_means: Mapping[str, Sequence[float]]) -> None:
        """寫入一筆記錄；唯讀觀察 ``roi_means``，不修改呼叫端傳入的物件。

        寫入失敗（例如另一執行緒已呼叫 :meth:`close`）不丟例外，只記 log 並跳過
        本筆——錄製為選配的離線驗證輔助功能，不應影響即時疲勞/rPPG 判斷路徑。
        """
        if self._closed:
            return
        try:
            payload = {
                "t": float(t),
                "roi_means": {
                    str(name): [float(rgb[0]), float(rgb[1]), float(rgb[2])]
                    for name, rgb in roi_means.items()
                },
                "belt_bpm": self._sample_belt_bpm(),
            }
            line = json.dumps(payload, ensure_ascii=False)
            self._fh.write(line + "\n")
            self._fh.flush()
        except (ValueError, OSError):
            logger.warning("belt-truth capture 寫入失敗（檔案可能已關閉），略過本筆")
            return
        self._count += 1

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._fh.close()
        except OSError:
            logger.warning("belt-truth capture 檔案關閉失敗", exc_info=True)

    def __enter__(self) -> "BeltTruthCaptureWriter":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def default_capture_path(base_dir: Optional[str | Path] = None) -> Path:
    """回傳一個帶時間戳的新 capture 檔路徑（自動建立父目錄）。"""
    root = Path(base_dir) if base_dir is not None else DEFAULT_CAPTURE_DIR
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return root / f"belt_truth_{stamp}.jsonl"


def load_belt_truth_capture(path: str | Path) -> list[BeltTruthCaptureRecord]:
    """讀回 capture 檔為 :class:`BeltTruthCaptureRecord` 清單。

    可行動錯誤：檔案不存在時丟 ``FileNotFoundError``（附路徑）。單行 JSON 解析
    失敗或欄位缺失/型別錯誤時記 warning 並略過該行，不中斷整體讀取（容忍寫入
    途中被中斷造成的末行截斷）。回傳清單本身可能為空——由呼叫端（例如
    ``scripts/rppg_param_replay.py``）決定空清單是否視為錯誤並提出可行動訊息。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"belt-truth capture 檔不存在：{p}。請確認已勾選「心跳帶真值校準」且"
            "在 config/hr_belt.json 設定 capture_enabled: true 後錄製過一段。"
        )
    records: list[BeltTruthCaptureRecord] = []
    with open(p, "r", encoding="utf-8") as fh:
        for lineno, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("belt-truth capture %s 第 %d 行 JSON 解析失敗，略過", p, lineno)
                continue
            if not isinstance(obj, dict):
                logger.warning("belt-truth capture %s 第 %d 行非 JSON object，略過", p, lineno)
                continue
            try:
                t = float(obj["t"])
                roi_means_raw = obj["roi_means"]
                if not isinstance(roi_means_raw, Mapping):
                    raise ValueError("roi_means 必須是 object")
                roi_means = {
                    str(name): (float(v[0]), float(v[1]), float(v[2]))
                    for name, v in roi_means_raw.items()
                }
                belt_bpm_raw = obj.get("belt_bpm")
                belt_bpm = float(belt_bpm_raw) if belt_bpm_raw is not None else None
                values = [t, *(v for rgb in roi_means.values() for v in rgb)]
                if belt_bpm is not None:
                    values.append(belt_bpm)
                if not all(math.isfinite(value) for value in values):
                    raise ValueError("capture 數值必須有限")
            except (KeyError, TypeError, ValueError, IndexError):
                logger.warning(
                    "belt-truth capture %s 第 %d 行欄位缺失或型別錯誤，略過", p, lineno
                )
                continue
            records.append(BeltTruthCaptureRecord(t=t, roi_means=roi_means, belt_bpm=belt_bpm))
    return records


__all__ = [
    "CAPTURE_FORMAT_VERSION",
    "DEFAULT_CAPTURE_DIR",
    "BeltTruthCaptureRecord",
    "BeltTruthCaptureWriter",
    "default_capture_path",
    "load_belt_truth_capture",
]
