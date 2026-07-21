from __future__ import annotations

from typing import Optional

from pywinauto.base_wrapper import BaseWrapper

from ui_interacter.ui_actions import UiActions
from ui_interacter.explore_selectors import ExploreSelectors
from ui_interacter.ui_core import log, wait_until


class ExploreConsole:
    """
    Owns Explore Console-level actions:
    - open Explore panel
    - click Start Exploration

    This class should not contain strategy-selection or instrument-selection
    state machines.
    """

    def __init__(
        self,
        actions: UiActions,
        selectors: ExploreSelectors,
        explore_load_timeout: float = 8,
        allow_start_fallback_click: bool = False,
        start_fallback_absolute_xy: Optional[tuple[int, int]] = None,
    ):
        self.actions = actions
        self.selectors = selectors
        self.explore_load_timeout = explore_load_timeout
        self.allow_start_fallback_click = allow_start_fallback_click
        self.start_fallback_absolute_xy = start_fallback_absolute_xy

    def open(self, main: BaseWrapper) -> None:
        """
        Opens Explore Console.

        Uses UIA locator first. If that fails, uses the existing relative
        fallback click for the vertical Explore tab.
        """
        explore = self.selectors.find_explore_caption(main)

        if explore is not None:
            self.actions.click_control(explore, "Explore tab/caption")
        else:
            r = main.rectangle()

            # Existing relative fallback for the vertical Explore tab.
            # Still isolated here so it is not scattered across workflow logic.
            x = r.left + 28
            y = r.top + 390

            self.actions.click_point(
                x,
                y,
                "Explore tab fallback",
                main=main,
                calibration_point_name="explore_tab",
            )

        log("Waiting for Explore Console to load...")

        def loaded():
            for text in ["All Explorations", "New Exploration", "Start Exploration"]:
                if self.selectors.find_text_control_fuzzy(main, text) is not None:
                    return True
            return False

        try:
            wait_until(
                loaded,
                timeout=self.explore_load_timeout,
                interval=0.2,
                error_msg="Explore Console did not finish loading",
            )
            log("Explore Console loaded.")
        except Exception:
            log("Could not verify Explore Console by text, continuing anyway.")

    def start(self, main: BaseWrapper) -> None:
        """
        Click Start Exploration.
        """
        log("Searching for Start Exploration button...")

        btn = self.selectors.find_start_button(main)

        if btn is not None:
            self.actions.click_control(btn, "Start Exploration button")
            return

        if self.allow_start_fallback_click and self.start_fallback_absolute_xy is not None:
            x, y = self.start_fallback_absolute_xy
            self.actions.click_point(
                x,
                y,
                "Start Exploration fallback",
                main=main,
                calibration_point_name="start_exploration",
            )
            return

        raise RuntimeError(
            "Could not find Start Exploration button safely. "
            "Inspect the button name, or configure start_fallback_absolute_xy."
        )