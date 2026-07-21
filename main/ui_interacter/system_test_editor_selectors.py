from __future__ import annotations

from typing import Iterable

from pywinauto import Desktop
from pywinauto.base_wrapper import BaseWrapper

from ui_interacter.ui_core import normalize_text, safe_descendants


class SystemTestEditorSelectors:
    """Exact selectors from the supplied System Editor inspection results."""

    NAME_EDIT_ID = "11063"
    NOTES_EDIT_ID = "11067"
    LONG_ORDERS_ID = "11070"
    SHORT_ORDERS_ID = "11073"
    SINGLE_PORTFOLIO_ID = "11075"
    MULTIPLE_PORTFOLIO_ID = "11078"
    POSITION_LIMIT_CHECKBOX_ID = "11052"
    MAX_POSITIONS_EDIT_ID = "11014"

    TAB_CONTROL_ID = "12320"
    FORMULA_EDITOR_ID = "11081"
    OK_BUTTON_ID = "1"

    def find_editor(self, main: BaseWrapper) -> BaseWrapper:
        """Copy ExplorerCreator's window search, adapted to System Editor."""
        try:
            spec = main.child_window(
                title="System Editor",
                control_type="Window",
            )
            if spec.exists(timeout=0.2):
                return spec.wrapper_object()
        except Exception:
            pass

        for window in safe_descendants(main, control_type="Window"):
            try:
                name = normalize_text(
                    window.element_info.name
                    or window.window_text()
                    or ""
                )
                if name == "System Editor":
                    return window
            except Exception:
                continue

        # Inspect reports a Win32 #32770 dialog. Keep this exact fallback for
        # cases where the nested Win32 dialog is outside main.descendants().
        try:
            desktop = Desktop(backend="uia")
            spec = desktop.window(
                title="System Editor",
                class_name="#32770",
            )
            if spec.exists(timeout=0.2):
                return spec.wrapper_object()
        except Exception:
            pass

        raise RuntimeError("Could not find the System Editor dialog.")

    def find_by_auto_id(
        self,
        editor: BaseWrapper,
        auto_id: str,
        *,
        control_types: Iterable[str] = (),
    ) -> BaseWrapper:
        allowed_types = tuple(control_types)

        for control_type in allowed_types or (None,):
            try:
                kwargs = {"auto_id": auto_id}
                if control_type is not None:
                    kwargs["control_type"] = control_type

                spec = editor.child_window(**kwargs)
                if spec.exists(timeout=0.2):
                    return spec.wrapper_object()
            except Exception:
                pass

        # Match the working Explorer creator style: scan descendants broadly,
        # then inspect properties instead of assuming a filtered UIA subtree.
        for control in safe_descendants(editor):
            try:
                current_auto_id = normalize_text(
                    control.element_info.automation_id or ""
                )
                if current_auto_id != auto_id:
                    continue

                if allowed_types:
                    current_type = normalize_text(
                        control.element_info.control_type or ""
                    )
                    if current_type not in allowed_types:
                        continue

                return control
            except Exception:
                continue

        raise RuntimeError(
            f"Could not find System Editor control AutomationId={auto_id}."
        )

    def find_name_edit(self, editor: BaseWrapper) -> BaseWrapper:
        return self.find_by_auto_id(
            editor,
            self.NAME_EDIT_ID,
            control_types=("Edit",),
        )

    def find_notes_edit(self, editor: BaseWrapper) -> BaseWrapper:
        return self.find_by_auto_id(
            editor,
            self.NOTES_EDIT_ID,
            control_types=("Edit",),
        )

    def find_long_orders_radio(self, editor: BaseWrapper) -> BaseWrapper:
        return self.find_by_auto_id(editor, self.LONG_ORDERS_ID)

    def find_short_orders_radio(self, editor: BaseWrapper) -> BaseWrapper:
        return self.find_by_auto_id(editor, self.SHORT_ORDERS_ID)

    def find_single_portfolio_radio(
        self,
        editor: BaseWrapper,
    ) -> BaseWrapper:
        return self.find_by_auto_id(editor, self.SINGLE_PORTFOLIO_ID)

    def find_multiple_portfolio_radio(
        self,
        editor: BaseWrapper,
    ) -> BaseWrapper:
        return self.find_by_auto_id(editor, self.MULTIPLE_PORTFOLIO_ID)

    def find_position_limit_checkbox(
        self,
        editor: BaseWrapper,
    ) -> BaseWrapper:
        return self.find_by_auto_id(
            editor,
            self.POSITION_LIMIT_CHECKBOX_ID,
        )

    def find_max_positions_edit(
        self,
        editor: BaseWrapper,
    ) -> BaseWrapper:
        return self.find_by_auto_id(
            editor,
            self.MAX_POSITIONS_EDIT_ID,
            control_types=("Edit",),
        )

    def find_tab_item(
        self,
        editor: BaseWrapper,
        tab_name: str,
    ) -> BaseWrapper:
        """
        Inspect.exe:
        - exact Name: Buy Order / Sell Order;
        - ControlType: TabItem;
        - SelectionItemPattern available;
        - ancestor: System Editor.
        """
        target = normalize_text(tab_name)

        try:
            spec = editor.child_window(
                title=target,
                control_type="TabItem",
            )
            if spec.exists(timeout=0.2):
                return spec.wrapper_object()
        except Exception:
            pass

        for item in safe_descendants(editor, control_type="TabItem"):
            try:
                name = normalize_text(
                    item.element_info.name
                    or item.window_text()
                    or ""
                )
                if name == target:
                    return item
            except Exception:
                continue

        raise RuntimeError(f"Could not find System Editor tab {tab_name!r}.")

    def find_active_order_formula_editor(
        self,
        editor: BaseWrapper,
        tab_name: str,
    ) -> BaseWrapper:
        """
        Buy and Sell both expose:
        - AutomationId: 11081;
        - ControlType: Document;
        - ClassName: Edit.

        The wrapper must be reacquired after each tab switch because its native
        handle and RuntimeId change.
        """
        formula_editor = self.find_by_auto_id(
            editor,
            self.FORMULA_EDITOR_ID,
            control_types=("Document",),
        )

        class_name = normalize_text(
            formula_editor.element_info.class_name or ""
        )
        if class_name != "Edit":
            raise RuntimeError(
                "Formula editor AutomationId=11081 did not expose "
                f"ClassName='Edit' on tab {tab_name!r}."
            )
        if not formula_editor.is_visible():
            raise RuntimeError(
                f"Formula editor is not visible on tab {tab_name!r}."
            )
        if not formula_editor.is_enabled():
            raise RuntimeError(
                f"Formula editor is not enabled on tab {tab_name!r}."
            )

        return formula_editor

    def find_ok_button(self, editor: BaseWrapper) -> BaseWrapper:
        return self.find_by_auto_id(
            editor,
            self.OK_BUTTON_ID,
            control_types=("Button",),
        )
