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

def wait_until_stable(
    condition_fn: Callable,
    timeout: float = 2.0,
    interval: float = 0.03,
    stable_reads: int = 2,
    error_msg: str = "Timed out",
):
    """
    Poll quickly and return after the condition is true for
    several consecutive reads.

    Consecutive reads prevent transient WPF/UIA states from
    being mistaken for a completed update.
    """
    deadline = time.monotonic() + timeout
    consecutive_successes = 0
    last_result = None
    last_error: Optional[Exception] = None

    while time.monotonic() < deadline:
        try:
            result = condition_fn()
            last_result = result

            if result:
                consecutive_successes += 1

                if consecutive_successes >= stable_reads:
                    return result
            else:
                consecutive_successes = 0

        except Exception as exc:
            last_error = exc
            consecutive_successes = 0

        time.sleep(interval)

    raise RuntimeError(
        f"{error_msg}. "
        f"Last result: {last_result!r}. "
        f"Last error: {last_error}"
    )