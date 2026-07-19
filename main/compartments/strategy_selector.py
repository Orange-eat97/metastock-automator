# strategy_selector.py

from __future__ import annotations

import time

from pywinauto.base_wrapper import BaseWrapper

from ui_interacter.ui_actions import UiActions
from ui_interacter.explore_selectors import ExploreSelectors
from ui_interacter.ui_core import (
    log,
    normalize_text,
    wait_until,
    wait_until_stable,
)
from ui_interacter.state_readers import (
    get_selected_count,
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
        # MetaStock updates its WPF filtered list asynchronously.
        # Two seconds was too aggressive on packaged beta runs.
        self.search_filter_timeout = max(
            float(search_filter_timeout),
            5.0,
        )

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
        
    def strategy_search_matches(
        self,
        current_text: str,
        strategy_name: str,
    ) -> bool:
        current = normalize_text(
            current_text
        ).casefold()
        target = normalize_text(
            strategy_name
        ).casefold()

        if not current:
            return False

        return (
            current == target
            or target in current
            or current in target
        )

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
        row: BaseWrapper | None = None,
    ) -> None:
        """
        Click the checkbox area for the unique filtered strategy row.

        We do not match strategy_name against row text because Inspect.exe showed
        the searched display name is not exposed in UIA. The row exposes:
        - generic ExplorationVM name
        - HelpText strategy description

        If no real checkbox is exposed, click relative to the discovered ListBoxItem row.
        """
        if row is None:
            rows = self.selectors.find_filtered_strategy_rows(
                main
            )

            if not rows:
                raise RuntimeError(
                    "No Explorer row was returned by the "
                    "MetaStock search."
                )

            row = rows[0]

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
        Deterministic strategy-selection sequence:

        1. Clear old search.
        2. Reset Selected count to zero.
        3. Search for the target strategy.
        4. Wait for at least one stable filtered row.
        5. Select the first returned row.
        6. Require Selected count to become exactly one.
        """
        log(
            "Selecting strategy with clean-state workflow: "
            f"{strategy_name!r}"
        )

        self.clear_all_selected_strategies(
            main
        )

        search_box = (
            self.selectors.find_search_combobox(main)
        )

        self.actions.paste_text(
            search_box,
            strategy_name,
            label="explorer search box",
        )

        log(
            "Waiting for MetaStock Explorer search results..."
        )

        def first_filtered_target_ready():
            try:
                rows = (
                    self.selectors
                    .find_filtered_strategy_rows(main)
                )

                if rows:
                    return (
                        "row",
                        rows[0],
                    )

                checkbox = (
                    self.selectors
                    .find_first_filtered_strategy_checkbox(
                        main
                    )
                )

                if checkbox is not None:
                    return (
                        "checkbox",
                        checkbox,
                    )

                return None

            except Exception:
                return None

        # Require several successful reads so the WPF result has
        # materialized. Always select the first visible result row.
        filtered_target = wait_until_stable(
            first_filtered_target_ready,
            timeout=self.search_filter_timeout,
            interval=0.10,
            stable_reads=3,
            error_msg=(
                "No Explorer row or checkbox appeared "
                "after searching"
            ),
        )

        # Let the checkbox hit target settle after the last list update.
        time.sleep(0.25)

        selected_before = get_selected_count(main)

        if selected_before != 0:
            raise RuntimeError(
                "Expected zero selected strategies before "
                "selecting the filtered target. "
                f"Actual selected count: {selected_before}"
            )

        target_type, target_control = (
            filtered_target
        )

        if target_type == "checkbox":
            log(
                "Explorer row was not exposed as a "
                "ListBoxItem; clicking its first visible "
                "checkbox directly."
            )

            self.actions.click_control(
                target_control,
                label=(
                    "first filtered Explorer checkbox"
                ),
            )

        else:
            self.click_strategy_checkbox(
                main,
                strategy_name,
                row=target_control,
            )

        wait_until_stable(
            lambda: get_selected_count(main) == 1,
            timeout=1.5,
            interval=0.03,
            stable_reads=2,
            error_msg=(
                "Selected strategy count did not "
                "stabilize at one"
            ),
        )

        selected_after = get_selected_count(main)

        if selected_after != 1:
            raise RuntimeError(
                "Target Explorer selection could not be verified. "
                f"Expected Selected: 1, actual={selected_after}"
            )

        log(
            f"Strategy selected successfully: "
            f"{strategy_name!r}"
        )

    def clear_all_selected_strategies(
        self,
        main: BaseWrapper,
    ) -> None:
        """
        Establish Selected: 0 before searching.

        Uses TogglePattern directly and waits only for the selected
        count to change. This avoids spending 1.5 seconds waiting
        for zero when the first toggle has selected every Explorer.
        """
        search_box = (
            self.selectors.find_search_combobox(main)
        )

        current_search = (
            self.get_search_combobox_text(search_box)
        )

        if current_search:
            log(
                "Clearing previous Explorer search before "
                "resetting strategy selection."
            )

            self.actions.paste_text(
                search_box,
                "",
                label="clear explorer search box",
            )

            self.wait_for_strategy_list_after_search(
                main
            )

        selected_count = get_selected_count(main)

        if selected_count is None:
            raise RuntimeError(
                "Could not read Selected:n before clearing "
                "strategy selections."
            )

        if selected_count == 0:
            log(
                "Strategy selected count is already zero."
            )
            return

        log(
            "Resetting selected strategies. "
            f"Current selected count: {selected_count}"
        )

        for attempt in range(1, 3):
            selected_before = get_selected_count(main)

            if selected_before is None:
                raise RuntimeError(
                    "Could not read Selected:n before "
                    "toggling Select all."
                )

            checkbox = (
                self.selectors
                .find_strategy_select_all_checkbox(main)
            )

            log(
                "Toggling strategy Select all checkbox "
                f"(attempt {attempt})."
            )

            try:
                # Inspect.exe confirmed TogglePattern is available.
                checkbox.toggle()

            except Exception:
                # Keep physical click only as a fallback.
                self.actions.click_control(
                    checkbox,
                    label=(
                        "strategy Select all checkbox "
                        f"(attempt {attempt})"
                    ),
                )

            # Wait only until the selected count changes.
            # Do not wait specifically for zero on the first click,
            # because the first click may select every Explorer.
            try:
                wait_until(
                    lambda: (
                        get_selected_count(main) is not None
                        and get_selected_count(main)
                        != selected_before
                    ),
                    timeout=0.75,
                    interval=0.03,
                    error_msg=(
                        "Selected count did not change after "
                        "toggling Select all"
                    ),
                )
            except RuntimeError:
                # Inspect the final state below. A delayed or
                # unchanged UIA read should not immediately fail.
                pass

            selected_after = get_selected_count(main)

            log(
                "Selected count after Select all toggle "
                f"{attempt}: {selected_after}"
            )

            if selected_after == 0:
                log(
                    "All previous strategy selections "
                    "have been cleared."
                )
                return

            if selected_after is None:
                raise RuntimeError(
                    "Could not read Selected:n after "
                    "toggling Select all."
                )

        raise RuntimeError(
            "Could not reset selected strategies to zero "
            "after two Select all toggles."
        )
    