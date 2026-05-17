from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from pywinauto.base_wrapper import BaseWrapper

from ui_interacter.ui_actions import UiActions
from ui_interacter.explore_selectors import ExploreSelectors
from ui_interacter.ui_core import log, normalize_text
from ui_interacter.state_readers import get_instruments_selected_total


@dataclass(frozen=True)
class InstrumentState:
    row: BaseWrapper
    checkbox: Optional[BaseWrapper]
    toggle_state: Optional[int]
    count: Optional[tuple[int, int]]

    @property
    def count_is_full(self) -> bool:
        if self.count is None:
            return False
        selected, total = self.count
        return total > 0 and selected == total

    @property
    def count_is_unchecked(self) -> bool:
        if self.count is None:
            return False
        selected, total = self.count
        return total > 0 and selected == 0

    @property
    def count_is_partial(self) -> bool:
        if self.count is None:
            return False
        selected, total = self.count
        return total > 0 and 0 < selected < total

    @property
    def toggle_is_checked(self) -> bool:
        return self.toggle_state == 1

    @property
    def toggle_is_unchecked(self) -> bool:
        return self.toggle_state == 0

    @property
    def toggle_is_partial(self) -> bool:
        return self.toggle_state == 2

    @property
    def definitely_full(self) -> bool:
        """
        Important safety rule:
        If either reliable signal says fully selected, do not click.

        This prevents:
            already checked -> accidental uncheck -> recheck
        """
        return self.toggle_is_checked or self.count_is_full

    @property
    def definitely_unchecked(self) -> bool:
        """
        Only treat as unchecked if no signal says full.
        """
        if self.definitely_full:
            return False

        if self.toggle_is_unchecked:
            return True

        if self.toggle_state is None and self.count_is_unchecked:
            return True

        return False

    @property
    def definitely_partial(self) -> bool:
        """
        Only treat as partial if no signal says full.
        """
        if self.definitely_full:
            return False

        if self.toggle_is_partial:
            return True

        if self.toggle_state is None and self.count_is_partial:
            return True

        return False


class InstrumentSelector:
    """
    Owns instrument selection.

    Current supported behavior:
    - ensure the broad Instruments parent row is fully selected.

    Safety principle:
    - Never click if checkbox/count already indicates selected.
    - Never click if state is unknown.
    """

    def __init__(
        self,
        actions: UiActions,
        selectors: ExploreSelectors,
        medium_delay: float = 0.35,
    ):
        self.actions = actions
        self.selectors = selectors
        self.medium_delay = medium_delay

    # ============================================================
    # PUBLIC API
    # ============================================================

    def ensure_all_selected(self, main: BaseWrapper) -> None:
        """
        Ensure Instruments is selected.

        Fixed behavior:
        - If already selected, do nothing.
        - If unchecked, click once and verify.
        - If partial, click and verify; if it becomes unchecked, click once more.
        - If state cannot be read, refuse to toggle blindly.
        """
        try:
            before = self.read_state(main)

            log(f"Instruments checkbox toggle state before: {before.toggle_state}")
            log(f"Instruments selected count before: {before.count}")

            # Critical guard.
            if before.definitely_full:
                log("Instruments already fully selected. Proceeding without clicking.")
                return

            if before.definitely_unchecked:
                log("Instruments is unchecked. Clicking once to select all...")
                self.click_instruments_checkbox(before)

                after = self.read_state(main)
                log(f"Instruments checkbox toggle state after click: {after.toggle_state}")
                log(f"Instruments selected count after click: {after.count}")

                if after.definitely_full:
                    log("Instruments is now fully selected.")
                    return

                raise RuntimeError(
                    "Clicked unchecked Instruments, but it did not become fully selected. "
                    f"BeforeToggle={before.toggle_state}, BeforeCount={before.count}, "
                    f"AfterToggle={after.toggle_state}, AfterCount={after.count}"
                )

            if before.definitely_partial:
                log(
                    "Instruments is partially selected. "
                    "Clicking once and re-scanning state..."
                )

                self.click_instruments_checkbox(before)

                after_first = self.read_state(main)
                log(f"Instruments toggle state after first partial click: {after_first.toggle_state}")
                log(f"Instruments selected count after first partial click: {after_first.count}")

                if after_first.definitely_full:
                    log("Instruments is now fully selected.")
                    return

                if after_first.definitely_unchecked:
                    log(
                        "Partial-state click changed Instruments to unchecked. "
                        "Clicking once more to select all..."
                    )

                    self.click_instruments_checkbox(after_first)

                    after_second = self.read_state(main)
                    log(f"Instruments toggle state after second click: {after_second.toggle_state}")
                    log(f"Instruments selected count after second click: {after_second.count}")

                    if after_second.definitely_full:
                        log("Instruments is now fully selected.")
                        return

                    raise RuntimeError(
                        "Second click did not fully select Instruments. "
                        f"BeforeToggle={before.toggle_state}, BeforeCount={before.count}, "
                        f"AfterFirstToggle={after_first.toggle_state}, AfterFirstCount={after_first.count}, "
                        f"AfterSecondToggle={after_second.toggle_state}, AfterSecondCount={after_second.count}"
                    )

                raise RuntimeError(
                    "Instruments remained not fully selected after partial-state click. "
                    f"BeforeToggle={before.toggle_state}, BeforeCount={before.count}, "
                    f"AfterFirstToggle={after_first.toggle_state}, AfterFirstCount={after_first.count}"
                )

            raise RuntimeError(
                "Could not determine Instruments state safely. "
                "Refusing to toggle blindly. "
                f"ToggleState={before.toggle_state}, Count={before.count}"
            )

        except Exception as e:
            raise RuntimeError(
                f"Failed to ensure Instruments is checked without blind toggling: {e}"
            )

    def select_named(
        self,
        main: BaseWrapper,
        instrument_names: list[str],
    ) -> None:
        raise NotImplementedError(
            "Named/multiple instrument selection is not implemented yet. "
            f"Requested instruments: {instrument_names}. "
            "Use --all-instruments for the current Phase 1 MVP."
        )

    # ============================================================
    # STATE READING
    # ============================================================

    def read_state(self, main: BaseWrapper) -> InstrumentState:
        """
        Always re-find the row before reading state.

        This matters because WPF rows can refresh after clicks.
        """
        item = self.selectors.find_instruments_tree_item(main)
        checkbox = self.find_checkbox_inside_row(item)
        toggle_state = (
            self.get_checkbox_toggle_state(checkbox)
            if checkbox is not None
            else None
        )
        count = get_instruments_selected_total(item)

        self.validate_count(count)

        return InstrumentState(
            row=item,
            checkbox=checkbox,
            toggle_state=toggle_state,
            count=count,
        )

    def validate_count(self, count: Optional[tuple[int, int]]) -> None:
        if count is None:
            return

        selected, total = count

        if total <= 0:
            raise RuntimeError(f"Invalid Instruments total count: {count}")

        if selected < 0:
            raise RuntimeError(f"Invalid Instruments selected count: {count}")

        if selected > total:
            raise RuntimeError(f"Invalid Instruments selected/total count: {count}")

    def find_checkbox_inside_row(self, row: BaseWrapper) -> Optional[BaseWrapper]:
        """
        Find a real CheckBox child inside a row, if UIA exposes it.
        """
        try:
            for child in row.children():
                try:
                    info = child.element_info
                    control_type = normalize_text(info.control_type or "")
                    class_name = normalize_text(info.class_name or "")

                    if control_type == "CheckBox" or "CheckBox" in class_name:
                        return child
                except Exception:
                    continue
        except Exception:
            pass

        try:
            for child in row.descendants():
                try:
                    info = child.element_info
                    control_type = normalize_text(info.control_type or "")
                    class_name = normalize_text(info.class_name or "")

                    if control_type == "CheckBox" or "CheckBox" in class_name:
                        return child
                except Exception:
                    continue
        except Exception:
            pass

        return None

    def get_checkbox_toggle_state(self, checkbox: BaseWrapper) -> Optional[int]:
        """
        UIA ToggleState:
            0 = Off
            1 = On
            2 = Indeterminate / Partial

        Returns None if pywinauto cannot read the state.
        """
        if checkbox is None:
            return None

        try:
            pattern = checkbox.iface_toggle
            return int(pattern.CurrentToggleState)
        except Exception:
            pass

        try:
            return int(checkbox.get_toggle_state())
        except Exception:
            pass

        try:
            legacy = checkbox.legacy_properties()
            state = str(legacy.get("State", "")).lower()

            # Important:
            # Check "unchecked" before "checked", because "unchecked"
            # contains the substring "checked".
            if "unchecked" in state:
                return 0

            if "mixed" in state or "indeterminate" in state or "partial" in state:
                return 2

            if "checked" in state:
                return 1
        except Exception:
            pass

        return None

    # ============================================================
    # CLICKING
    # ============================================================

    def click_instruments_checkbox(self, state: InstrumentState) -> None:
        """
        Prefer real checkbox click.
        Fall back to row-relative coordinate click only if checkbox is not exposed.
        """
        if state.checkbox is not None:
            log(
                "Clicking real Instruments checkbox. "
                f"ToggleState before click: {state.toggle_state}"
            )
            self.actions.click_control(state.checkbox, "Instruments checkbox")
            time.sleep(self.medium_delay)
            return

        log("Could not find real Instruments checkbox. Using row-relative fallback click.")
        self.actions.click_checkbox_in_row(
            state.row,
            label="Instruments",
            x_offset=38,
        )