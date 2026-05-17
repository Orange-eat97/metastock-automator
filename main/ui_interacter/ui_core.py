# ui_core.py

from __future__ import annotations

import time
from typing import Callable, Optional
from pywinauto.base_wrapper import BaseWrapper


def log(msg: str) -> None:
    print(f"[MetaStockBot] {msg}")


def normalize_text(s: str) -> str:
    return " ".join((s or "").strip().split())


def safe_descendants(root: BaseWrapper, **kwargs) -> list[BaseWrapper]:
    try:
        return root.descendants(**kwargs)
    except Exception:
        return []


def rect_center(ctrl: BaseWrapper) -> tuple[int, int]:
    r = ctrl.rectangle()
    return ((r.left + r.right) // 2, (r.top + r.bottom) // 2)


def wait_until(
    condition_fn: Callable,
    timeout: float = 20,
    interval: float = 0.1,
    error_msg: str = "Timed out",
):
    deadline = time.time() + timeout
    last_error: Optional[Exception] = None

    while time.time() < deadline:
        try:
            result = condition_fn()
            if result:
                return result
        except Exception as e:
            last_error = e

        time.sleep(interval)

    raise RuntimeError(f"{error_msg}. Last error: {last_error}")