"""分析 worker 共用的 fail-closed 邊界。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar


_F = TypeVar("_F", bound=Callable[..., Any])


class ConsecutiveFrameFailures:
    """與相機擷取相同，連續 30 次失敗後交由 fail-closed 邊界收尾。"""

    def __init__(self) -> None:
        self._count = 0

    def reset(self) -> None:
        self._count = 0

    def record(self, error: Exception) -> None:
        self._count += 1
        if self._count >= 30:
            raise RuntimeError(f"連續 30 次影格處理失敗：{error}") from error


def fail_closed_worker(label: str, logger: logging.Logger) -> Callable[[_F], _F]:
    """把未處理例外轉成 failed/finished，並保留原函式供 source guard 檢查。"""

    def decorate(func: _F) -> _F:
        @wraps(func)
        def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
            try:
                return func(self, *args, **kwargs)
            except Exception as exc:
                logger.exception("%s初始化或執行失敗", label)
                self.failed.emit(f"{label}失敗：{exc}")
                self.finished.emit()
                return None

        return wrapped  # type: ignore[return-value]

    return decorate
