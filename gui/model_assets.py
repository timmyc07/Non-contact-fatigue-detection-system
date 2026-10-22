"""Face Landmarker 模型的固定來源與安全下載。"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import urllib.request
from pathlib import Path


log = logging.getLogger(__name__)
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"


def download_face_model(target: Path) -> Path:
    """校驗完整內容後才原子發布，失敗時保留既有模型。"""
    log.info("正在下載固定版本 Face Landmarker 模型：%s", MODEL_URL)
    with urllib.request.urlopen(MODEL_URL, timeout=30) as response:
        content = response.read(16 * 1024 * 1024)
    if hashlib.sha256(content).hexdigest() != MODEL_SHA256:
        raise ValueError(f"模型 SHA-256 不符，未寫入或覆寫檔案：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    log.info("Face Landmarker 模型已驗證並儲存：%s", target)
    return target
