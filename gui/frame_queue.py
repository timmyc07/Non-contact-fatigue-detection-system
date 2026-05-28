"""低延遲影像佇列工具。"""

from __future__ import annotations

import queue
from typing import TypeVar

T = TypeVar("T")


def put_latest(q: "queue.Queue[T]", item: T) -> None:
    """放入最新項目；若佇列已滿，先丟棄最舊項目。"""
    try:
        q.put_nowait(item)
        return
    except queue.Full:
        pass

    try:
        q.get_nowait()
    except queue.Empty:
        pass

    try:
        q.put_nowait(item)
    except queue.Full:
        pass


def get_latest(q: "queue.Queue[T]", timeout: float) -> T:
    """取得一筆資料後清空滯留項目，只回傳最新項目。"""
    item = q.get(timeout=timeout)
    while True:
        try:
            item = q.get_nowait()
        except queue.Empty:
            return item
