from __future__ import annotations

from pywinauto import Application
from pywinauto.base_wrapper import BaseWrapper

from ui_interacter.ui_core import log


class MetaStockApp:
    """
    Owns connection to the already-open MetaStock application.

    This class should not know anything about Explore Console,
    strategies, instruments, or execution progress.
    """

    def __init__(self, app_title_re: str = r".*MetaStock.*"):
        self.app_title_re = app_title_re

    def connect(self) -> BaseWrapper:
        log("Connecting to MetaStock...")

        app = Application(backend="uia").connect(
            title_re=self.app_title_re,
            timeout=15,
        )

        main = app.window(title_re=self.app_title_re)
        main.wait("exists visible", timeout=20)
        main.set_focus()

        log(f"Connected to window: {main.window_text()!r}")
        return main