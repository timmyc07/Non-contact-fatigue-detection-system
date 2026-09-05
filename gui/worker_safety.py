"""分析 worker 共用的 fail-closed 邊界。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar


_F = TypeVar("_F", bound=Callable[..., Any])


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
