# ui_actions.py

from __future__ import annotations

import time
import pyperclip
from pywinauto import mouse
from pywinauto.base_wrapper import BaseWrapper
from pywinauto.keyboard import send_keys

from ui_interacter.ui_core import log, rect_center


class UiActions:
    def __init__(self, short_delay: float = 0.15, medium_delay: float = 0.35):
        self.short_delay = short_delay
        self.medium_delay = medium_delay

    def click_control(self, ctrl: BaseWrapper, label: str = "control") -> None:
        x, y = rect_center(ctrl)
        log(f"Clicking {label} at ({x}, {y})")
        ctrl.click_input()

    def invoke_or_click(self, ctrl: BaseWrapper, label: str = "control") -> None:
        """
        Prefer UIA InvokePattern when available.
        Fall back to physical click.
        """
        try:
            log(f"Invoking {label}")
            ctrl.invoke()
            time.sleep(self.medium_delay)
            return
        except Exception:
            pass

        self.click_control(ctrl, label)
        time.sleep(self.medium_delay)

    def click_point(self, x: int, y: int, label: str = "point") -> None:
        log(f"Clicking {label} at ({x}, {y})")
        mouse.click(button="left", coords=(x, y))
        time.sleep(self.medium_delay)

    def paste_text(self, ctrl: BaseWrapper, text: str, label: str = "text field") -> None:
        log(f"Pasting into {label}: {text!r}")

        ctrl.click_input()
        time.sleep(self.short_delay)

        pyperclip.copy(text)
        send_keys("^a")
        time.sleep(0.05)
        send_keys("{BACKSPACE}")
        time.sleep(0.05)
        send_keys("^v")

        time.sleep(self.medium_delay)

    def click_checkbox_in_row(
        self,
        row: BaseWrapper,
        label: str,
        x_offset: int = 22,
    ) -> None:
        """
        Controlled fallback.

        This is still coordinate-based, but it is now isolated.
        Business logic should call this only after failing to find a real checkbox control.
        """
        r = row.rectangle()
        x = r.left + x_offset
        y = (r.top + r.bottom) // 2

        log(
            f"Fallback clicking checkbox in {label} row using rect="
            f"({r.left},{r.top},{r.right},{r.bottom}), point=({x},{y})"
        )

        mouse.click(button="left", coords=(x, y))
        time.sleep(self.medium_delay)