# strategy_selector.py

from __future__ import annotations

from pywinauto.base_wrapper import BaseWrapper

from ui_interacter.ui_actions import UiActions
from ui_interacter.explore_selectors import ExploreSelectors
from ui_interacter.ui_core import log, normalize_text, wait_until
from ui_interacter.state_readers import (
    get_selected_count_text,
    parse_selected_count,
)


class StrategySelector:
    """
    Owns strategy selection.

    This class contains the strategy-selection state machine:
    - read current search box
    - search target strategy if needed
    - locate the unique filtered strategy row
    - click the row's checkbox area
    - verify using Selected:n
    - repair if the click accidentally untoggled an already-selected strategy
    """

    def __init__(
        self,
        actions: UiActions,
        selectors: ExploreSelectors,
        search_filter_timeout: float = 2,
    ):
        self.actions = actions
        self.selectors = selectors
        self.search_filter_timeout = search_filter_timeout

    def select(self, main: BaseWrapper, strategy_name: str) -> None:
        self.select_by_search(main, strategy_name)

    def get_search_combobox_text(self, search_box: BaseWrapper) -> str:
        """
        Read current SearchComboBox text.
        """
        try:
            return normalize_text(search_box.window_text())
        except Exception:
            pass

        try:
            return normalize_text(search_box.element_info.name or "")
        except Exception:
            return ""

    def strategy_search_matches(self, current_text: str, strategy_name: str) -> bool:
        """
        Returns True if the current search box already contains the target strategy search.
        """
        current = normalize_text(current_text).lower()
        target = normalize_text(strategy_name).lower()

        if not current:
            return False

        return current == target or target in current or current in target

    def wait_for_strategy_list_after_search(self, main: BaseWrapper) -> None:
        """
        Wait until the strategy list view is available after using the search box.
        """
        def ready():
            try:
                lv = self.selectors.find_strategy_list_view(main)
                r = lv.rectangle()
                return r.width() > 250 and r.height() > 100
            except Exception:
                return False

        wait_until(
            ready,
            timeout=self.search_filter_timeout,
            interval=0.15,
            error_msg="Strategy list did not become ready after search",
        )

    def click_strategy_checkbox(
        self,
        main: BaseWrapper,
        strategy_name: str,
    ) -> None:
        """
        Click the checkbox area for the unique filtered strategy row.

        We do not match strategy_name against row text because Inspect.exe showed
        the searched display name is not exposed in UIA. The row exposes:
        - generic ExplorationVM name
        - HelpText strategy description

        If no real checkbox is exposed, click relative to the discovered ListBoxItem row.
        """
        row = self.selectors.find_unique_filtered_strategy_row(main)
        checkbox = self.selectors.find_checkbox_in_row(row)

        if checkbox is not None:
            log(f"Clicking real checkbox for strategy {strategy_name!r}.")
            self.actions.click_control(
                checkbox,
                f"strategy checkbox: {strategy_name}",
            )
            return

        r = row.rectangle()
        log(
            f"Strategy row found but checkbox is not exposed through UIA. "
            f"Using row-relative checkbox click. "
            f"Row rect=({r.left},{r.top},{r.right},{r.bottom})"
        )

        # Inspect row example:
        # row rect={l:91 t:201 r:400 b:249}
        # old working checkbox point around x=108, y=221
        # offset ~= 17, so use 20.
        self.actions.click_checkbox_in_row(
            row,
            label=f"strategy {strategy_name!r}",
            x_offset=20,
        )

    def select_by_search(
        self,
        main: BaseWrapper,
        strategy_name: str,
    ) -> None:
        """
        Stateful strategy selection.

        Behavior:
        1. Check current SearchComboBox before searching.
        2. If already filtered to target and Selected:n > 0, do nothing.
        3. Otherwise search target and use selected-count repair.
        """
        log(f"Selecting strategy through search + row/control checkbox click: {strategy_name!r}")

        search_box = self.selectors.find_search_combobox(main)
        current_search_text = self.get_search_combobox_text(search_box)

        selected_initial_text = get_selected_count_text(main)
        selected_initial = parse_selected_count(selected_initial_text)

        log(f"Current search box text: {current_search_text!r}")
        log(f"Initial selected count: {selected_initial_text!r}")

        # Case 1: search box already shows the target strategy.
        if self.strategy_search_matches(current_search_text, strategy_name):
            log("Search box already matches target strategy.")

            self.wait_for_strategy_list_after_search(main)

            if selected_initial is not None and selected_initial > 0:
                log("Target strategy appears already selected. Proceeding without clicking.")
                return

            if selected_initial == 0:
                log("Target strategy appears unselected. Clicking once...")
                self.click_strategy_checkbox(main, strategy_name)

                selected_after_text = get_selected_count_text(main)
                selected_after = parse_selected_count(selected_after_text)

                log(f"Selected count after strategy click: {selected_after_text!r}")

                if selected_after is not None and selected_after > 0:
                    log("Strategy is now selected.")
                    return

                raise RuntimeError(
                    f"Clicked target strategy but selected count did not increase. "
                    f"Before={selected_initial_text!r}, After={selected_after_text!r}"
                )

        # Case 2: search box is different. Search first, then use repair logic.
        self.actions.paste_text(search_box, strategy_name, label="explorer search box")

        log("Waiting for explorer list to filter...")
        self.wait_for_strategy_list_after_search(main)

        selected_before_text = get_selected_count_text(main)
        selected_before = parse_selected_count(selected_before_text)

        log(f"Selected count before strategy click: {selected_before_text!r}")

        if selected_before is None:
            raise RuntimeError(
                "Could not read selected strategy count before clicking. "
                "Refusing to do stateless toggle."
            )

        self.click_strategy_checkbox(main, strategy_name)

        selected_after_text = get_selected_count_text(main)
        selected_after = parse_selected_count(selected_after_text)

        log(f"Selected count after strategy click: {selected_after_text!r}")

        if selected_after is None:
            raise RuntimeError(
                "Could not read selected strategy count after clicking. "
                "Cannot verify strategy state."
            )

        if selected_after > selected_before:
            log("Strategy was unchecked before; now checked. Good.")
            return

        if selected_after < selected_before:
            log(
                "Strategy was already checked; first click unchecked it. "
                "Clicking again to restore checked state..."
            )

            self.click_strategy_checkbox(main, strategy_name)

            selected_restore_text = get_selected_count_text(main)
            selected_restore = parse_selected_count(selected_restore_text)

            log(f"Selected count after restore click: {selected_restore_text!r}")

            if selected_restore == selected_before:
                log("Strategy restored to checked state. Good.")
                return

            raise RuntimeError(
                "Tried to restore already-checked strategy, but selected count did not return "
                f"to original value. Before={selected_before}, after_restore={selected_restore}"
            )

        raise RuntimeError(
            "Strategy click did not change selected count. "
            "Either the click missed, the list did not filter correctly, or UI did not refresh."
        )