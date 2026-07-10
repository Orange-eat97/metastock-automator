# strategy_selector.py

from __future__ import annotations

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
        Deterministic strategy-selection sequence:

        1. Clear old search.
        2. Reset Selected count to zero.
        3. Search for the target strategy.
        4. Require one unique filtered row.
        5. Select it.
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
            "Waiting for Explorer list to filter..."
        )

        self.wait_for_strategy_list_after_search(
            main
        )

        selected_before = get_selected_count(main)

        if selected_before != 0:
            raise RuntimeError(
                "Expected zero selected strategies before "
                "selecting the filtered target. "
                f"Actual selected count: {selected_before}"
            )

        self.click_strategy_checkbox(
            main,
            strategy_name,
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
        Establish the invariant Selected: 0 before applying the
        desired strategy search.

        The first Select all click may select everything when the
        checkbox is currently unchecked or indeterminate. A second
        click then clears everything. Each step is verified using
        the Selected:n state exposed by MetaStock.
        """
        search_box = (
            self.selectors.find_search_combobox(main)
        )

        current_search = (
            self.get_search_combobox_text(search_box)
        )

        # Clear an old filter first so Select all operates against
        # the complete Explorer list.
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
            checkbox = (
                self.selectors
                .find_strategy_select_all_checkbox(main)
            )

            self.actions.invoke_or_click(
                checkbox,
                label=(
                    "strategy Select all checkbox "
                    f"(reset attempt {attempt})"
                ),
            )

            try:
                wait_until_stable(
                    lambda: get_selected_count(main) == 0,
                    timeout=1.5,
                    interval=0.03,
                    stable_reads=2,
                    error_msg=(
                        "Selected strategy count did not "
                        "stabilize at zero"
                    ),
                )
            except RuntimeError:
                pass

            selected_after = get_selected_count(main)

            log(
                "Selected count after Select all click "
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
                    "Could not read Selected:n after clicking "
                    "the Select all checkbox."
                )

            log(
                "The first click did not clear the selection. "
                "It may have selected every strategy; clicking "
                "again to reach zero."
            )

        raise RuntimeError(
            "Could not reset selected strategies to zero "
            "after two Select all clicks."
        )