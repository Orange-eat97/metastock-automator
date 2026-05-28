from __future__ import annotations

import time
from typing import Optional

from pywinauto.base_wrapper import BaseWrapper

from phase2RequestReceiver import ExplorerColumn
from ui_interacter.ui_core import log, normalize_text, safe_descendants, wait_until


class ColumnEditor:
    """
    Defines existing MetaStock exploration column tabs.

    UI assumption:
        Filter tab comes first.
        Column tabs A, B, C... come after Filter.
        UIA does not expose names A/B/C, so we use tab order.

    This class only edits the code box inside each column tab.
    """

    COLUMN_TAB_VM = "ExplorationTabColumnViewModel"
    FILTER_TAB_VM = "ExplorationTabFilterViewModel"

    def __init__(
        self,
        actions,
        tab_switch_delay: float = 0.35,
        code_box_timeout: int = 5,
    ) -> None:
        self.actions = actions
        self.tab_switch_delay = tab_switch_delay
        self.code_box_timeout = code_box_timeout

    def define_columns(
        self,
        editor: BaseWrapper,
        columns: list[ExplorerColumn],
    ) -> None:
        if not columns:
            log("No column definitions provided. Skipping column editing.")
            return

        log(f"Defining {len(columns)} exploration column(s)...")

        column_tabs = self._find_column_tabs(editor)

        if len(columns) > len(column_tabs):
            raise RuntimeError(
                f"Requested {len(columns)} columns, but only found {len(column_tabs)} column tabs."
            )

        for index, column in enumerate(columns):
            tab = column_tabs[index]

            log(f"Selecting column {column.slot} using tab index {index}...")
            self.actions.invoke_or_click(tab, f"column {column.slot} tab")

            time.sleep(self.tab_switch_delay)

            code_box = self._wait_for_column_code_box(editor)

            self.actions.paste_text(
                code_box,
                column.code_body,
                f"column {column.slot} code",
            )

        log("Finished defining columns.")

    # ============================================================
    # TAB DISCOVERY
    # ============================================================

    def _find_column_tabs(self, editor: BaseWrapper) -> list[BaseWrapper]:
        """
        Finds all column tabs by ViewModel name and sorts them spatially.

        We do not use visible labels A/B/C because Inspect does not expose them.
        """
        tabs: list[BaseWrapper] = []

        for tab in safe_descendants(editor, control_type="TabItem"):
            try:
                name = normalize_text(tab.element_info.name or "")
                text = normalize_text(tab.window_text())
                combined = f"{name} {text}"

                if self.COLUMN_TAB_VM not in combined:
                    continue

                if not tab.is_visible() or not tab.is_enabled():
                    continue

                r = tab.rectangle()

                # Reject garbage/invisible rectangles.
                if r.width() <= 10 or r.height() <= 10:
                    continue

                tabs.append(tab)
            except Exception:
                continue

        if not tabs:
            raise RuntimeError("Could not find any column tabs.")

        tabs.sort(key=lambda t: (t.rectangle().top, t.rectangle().left))

        log("Column tab candidates by spatial order:")
        for i, tab in enumerate(tabs):
            r = tab.rectangle()
            slot = chr(ord("A") + i)
            log(f"  {slot}: rect=({r.left},{r.top},{r.right},{r.bottom})")

        return tabs

    # ============================================================
    # CODE BOX DISCOVERY
    # ============================================================

    def _wait_for_column_code_box(self, editor: BaseWrapper) -> BaseWrapper:
        return wait_until(
            lambda: self._find_column_code_box(editor),
            timeout=self.code_box_timeout,
            interval=0.15,
            error_msg="Column code box did not become available",
        )

    def _find_column_code_box(self, editor: BaseWrapper) -> Optional[BaseWrapper]:
        """
        Finds the large writable code editor currently visible in the selected tab.

        Column and Filter both expose similar editor structures, but after selecting
        a column tab, the visible large Document should belong to that column.
        """
        document = self._find_large_visible_control(editor, "Document")

        if document is not None:
            r = document.rectangle()
            log(f"Found current column code box as Document: rect=({r.left},{r.top},{r.right},{r.bottom})")
            return document

        custom = self._find_large_visible_control(editor, "Custom")

        if custom is not None:
            r = custom.rectangle()
            log(f"Found current column code box as Custom: rect=({r.left},{r.top},{r.right},{r.bottom})")
            return custom

        return None

    def _find_large_visible_control(
        self,
        editor: BaseWrapper,
        control_type: str,
    ) -> Optional[BaseWrapper]:
        candidates: list[BaseWrapper] = []

        for ctrl in safe_descendants(editor, control_type=control_type):
            try:
                if not ctrl.is_visible() or not ctrl.is_enabled():
                    continue

                r = ctrl.rectangle()

                # Code editor is the large central box.
                if r.width() <= 500 or r.height() <= 200:
                    continue

                candidates.append(ctrl)
            except Exception:
                continue

        if not candidates:
            return None

        # Pick the largest visible code-like region.
        candidates.sort(
            key=lambda c: c.rectangle().width() * c.rectangle().height(),
            reverse=True,
        )

        return candidates[0]