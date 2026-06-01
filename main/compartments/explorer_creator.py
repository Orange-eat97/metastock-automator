from __future__ import annotations

import time
from typing import Optional

from pywinauto.base_wrapper import BaseWrapper

from phase2RequestReceiver import AddExplorerRequest
from compartments.column_editor import ColumnEditor
from ui_interacter.ui_core import (
    log,
    normalize_text,
    safe_descendants,
    wait_until,
)


class ExplorerCreator:
    """
    Phase 2 component.

    Responsibility:
        - click New Exploration
        - wait for Exploration Editor
        - fill Name
        - fill Notes
        - fill Filter code
        - optionally define column tabs A/B/C...
        - click Ok

    This class deliberately does not:
        - connect to MetaStock
        - open the Explore Console
        - run the exploration

    Those are handled by automator.py / workflow components.
    """

    def __init__(
        self,
        actions,
        selectors=None,
        editor_load_timeout: int = 8,
        save_timeout: int = 10,
        column_editor: ColumnEditor | None = None,
    ) -> None:
        self.actions = actions
        self.selectors = selectors
        self.editor_load_timeout = editor_load_timeout
        self.save_timeout = save_timeout
        self.column_editor = column_editor or ColumnEditor(actions=actions)

    # ============================================================
    # PUBLIC API
    # ============================================================

    def create(self, main_window: BaseWrapper, request: AddExplorerRequest) -> None:
        log(f"Creating new explorer: {request.name!r}")

        editor = self._open_new_exploration_editor(main_window)

        name_field = self._find_edit_after_label(
            editor=editor,
            label="Name:",
            ordinal_fallback=0,
        )

        notes_field = self._find_edit_after_label(
            editor=editor,
            label="Notes:",
            ordinal_fallback=1,
        )

        filter_code_editor = self._find_code_editor(editor)

        self.actions.paste_text(name_field, request.name, "explorer name")
        self.actions.paste_text(notes_field, request.notes, "explorer notes")
        self.actions.paste_text(
            filter_code_editor,
            request.code_body,
            "explorer filter code body",
        )

        if request.columns:
            self.column_editor.define_columns(editor, request.columns)

        self._save_editor(editor)

        log(f"Explorer created: {request.name!r}")

    # ============================================================
    # OPEN EDITOR
    # ============================================================

    def _open_new_exploration_editor(self, main_window: BaseWrapper) -> BaseWrapper:
        new_button = self._find_new_exploration_button(main_window)

        self.actions.invoke_or_click(
            new_button,
            "New Exploration button",
        )

        log("Waiting for Exploration Editor window...")

        def find_editor() -> Optional[BaseWrapper]:
            try:
                editor = main_window.child_window(
                    title="Exploration Editor",
                    control_type="Window",
                )

                if editor.exists(timeout=0.2):
                    return editor.wrapper_object()
            except Exception:
                pass

            for win in safe_descendants(main_window, control_type="Window"):
                try:
                    name = normalize_text(win.element_info.name or "")
                    text = normalize_text(win.window_text())

                    if name == "Exploration Editor" or text == "Exploration Editor":
                        return win
                except Exception:
                    continue

            return None

        editor = wait_until(
            find_editor,
            timeout=self.editor_load_timeout,
            interval=0.2,
            error_msg="Exploration Editor did not appear",
        )

        editor.set_focus()
        time.sleep(0.35)

        log("Exploration Editor opened.")
        return editor

    def _find_new_exploration_button(self, main_window: BaseWrapper) -> BaseWrapper:
        log("Searching for New Exploration button...")

        for button in safe_descendants(main_window, control_type="Button"):
            try:
                name = normalize_text(button.window_text())
                info_name = normalize_text(button.element_info.name or "")

                if name == "New Exploration" or info_name == "New Exploration":
                    log("Found New Exploration button.")
                    return button
            except Exception:
                continue

        raise RuntimeError("Could not find New Exploration button.")

    # ============================================================
    # NAME / NOTES FIELDS
    # ============================================================

    def _find_edit_after_label(
        self,
        editor: BaseWrapper,
        label: str,
        ordinal_fallback: int,
    ) -> BaseWrapper:
        """
        Finds fields using the inspected structure:

            Name:
                TextEdit
                    TextEdit

            Notes:
                TextEdit
                    TextEdit

        We first anchor by label, then choose the nearest following leaf Edit.

        If label matching fails, we fall back to sorted leaf edit order:
            ordinal 0 -> Name
            ordinal 1 -> Notes
        """
        edits = self._get_visible_leaf_edits(editor)

        if not edits:
            raise RuntimeError("Could not find any visible edit controls in Exploration Editor.")

        label_ctrl = self._find_label_text(editor, label)

        if label_ctrl is not None:
            label_rect = label_ctrl.rectangle()
            candidates = []

            for edit in edits:
                try:
                    edit_rect = edit.rectangle()

                    # The target field should be on the same row as the label
                    # or below it. Reject edits visually above the label.
                    if edit_rect.bottom < label_rect.top:
                        continue

                    vertical_distance = max(0, edit_rect.top - label_rect.top)
                    horizontal_distance = abs(edit_rect.left - label_rect.right)

                    candidates.append(
                        (
                            vertical_distance,
                            horizontal_distance,
                            edit_rect.top,
                            edit_rect.left,
                            edit,
                        )
                    )
                except Exception:
                    continue

            if candidates:
                candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
                chosen = candidates[0][4]
                r = chosen.rectangle()

                log(
                    f"Found field after {label!r}: "
                    f"rect=({r.left},{r.top},{r.right},{r.bottom})"
                )

                return chosen

        if len(edits) > ordinal_fallback:
            chosen = edits[ordinal_fallback]
            r = chosen.rectangle()

            log(
                f"Label lookup failed for {label!r}. "
                f"Using edit ordinal {ordinal_fallback}: "
                f"rect=({r.left},{r.top},{r.right},{r.bottom})"
            )

            return chosen

        raise RuntimeError(
            f"Could not find edit field for {label!r}. "
            f"Visible leaf edit count={len(edits)}"
        )

    def _get_visible_leaf_edits(self, editor: BaseWrapper) -> list[BaseWrapper]:
        """
        Gets only the inner editable TextEdit controls.

        WPF often exposes:
            Edit
                Edit

        We skip the outer edit if it has nested edit descendants.
        """
        edits: list[BaseWrapper] = []

        for edit in safe_descendants(editor, control_type="Edit"):
            try:
                if not edit.is_visible() or not edit.is_enabled():
                    continue

                r = edit.rectangle()

                if r.width() <= 20 or r.height() <= 8:
                    continue

                try:
                    nested_edits = edit.descendants(control_type="Edit")
                    if nested_edits:
                        continue
                except Exception:
                    pass

                edits.append(edit)
            except Exception:
                continue

        edits.sort(key=lambda e: (e.rectangle().top, e.rectangle().left))
        return edits

    def _find_label_text(self, editor: BaseWrapper, label: str) -> Optional[BaseWrapper]:
        target = normalize_text(label).lower()
        target_no_colon = target.rstrip(":")

        for text_ctrl in safe_descendants(editor, control_type="Text"):
            try:
                text = normalize_text(text_ctrl.window_text()).lower()
                name = normalize_text(text_ctrl.element_info.name or "").lower()

                values = {
                    text,
                    name,
                    text.rstrip(":"),
                    name.rstrip(":"),
                }

                if target in values or target_no_colon in values:
                    return text_ctrl
            except Exception:
                continue

        return None

    # ============================================================
    # FILTER CODE EDITOR
    # ============================================================

    def _find_code_editor(self, editor: BaseWrapper) -> BaseWrapper:
        """
        Finds the currently visible code editor.

        When called from create(), the selected tab should still be Filter,
        so this resolves the filter code editor.

        Earlier Inspect showed the code box as Document.
        The control tree also showed Code followed by an unnamed Custom.

        So we support both:
            1. large visible Document after Code:
            2. large visible Custom after Code:
        """
        log("Searching for Filter code editor...")

        code_label = self._find_label_text(editor, "Code:")

        document = self._find_large_control_after_label(
            editor=editor,
            control_type="Document",
            label_ctrl=code_label,
        )

        if document is not None:
            r = document.rectangle()
            log(f"Found Filter code editor as Document: rect=({r.left},{r.top},{r.right},{r.bottom})")
            return document

        custom = self._find_large_control_after_label(
            editor=editor,
            control_type="Custom",
            label_ctrl=code_label,
        )

        if custom is not None:
            r = custom.rectangle()
            log(f"Found Filter code editor as Custom: rect=({r.left},{r.top},{r.right},{r.bottom})")
            return custom

        raise RuntimeError("Could not find Filter code editor as Document or large Custom control.")

    def _find_large_control_after_label(
        self,
        editor: BaseWrapper,
        control_type: str,
        label_ctrl: Optional[BaseWrapper],
    ) -> Optional[BaseWrapper]:
        candidates: list[BaseWrapper] = []

        for ctrl in safe_descendants(editor, control_type=control_type):
            try:
                if not ctrl.is_visible() or not ctrl.is_enabled():
                    continue

                r = ctrl.rectangle()

                if r.width() <= 300 or r.height() <= 100:
                    continue

                if label_ctrl is not None:
                    label_rect = label_ctrl.rectangle()

                    if r.top < label_rect.top:
                        continue

                candidates.append(ctrl)
            except Exception:
                continue

        if not candidates:
            return None

        candidates.sort(key=lambda c: (c.rectangle().top, c.rectangle().left))
        return candidates[0]

    # ============================================================
    # SAVE
    # ============================================================

    def _save_editor(self, editor: BaseWrapper) -> None:
        ok_button = self._find_ok_button(editor)

        self.actions.invoke_or_click(
            ok_button,
            "Ok button",
        )

        log("Waiting for Exploration Editor to close...")

        def editor_closed() -> bool:
            try:
                return not editor.exists(timeout=0.2)
            except Exception:
                return True

        try:
            wait_until(
                editor_closed,
                timeout=self.save_timeout,
                interval=0.3,
                error_msg="Exploration Editor did not close after clicking Ok",
            )

            log("Editor closed. Save likely succeeded.")

        except Exception as e:
            self._print_editor_debug_text(editor)

            raise RuntimeError(
                "Save may have failed, or MetaStock may be showing a validation error. "
                "Check the Exploration Editor manually."
            ) from e

    def _find_ok_button(self, editor: BaseWrapper) -> BaseWrapper:
        log("Searching for Ok button...")

        try:
            ok = editor.child_window(
                auto_id="ButtonOk",
                control_type="Button",
            )

            if ok.exists(timeout=0.5):
                log("Found Ok button by AutomationId ButtonOk.")
                return ok.wrapper_object()
        except Exception:
            pass

        for button in safe_descendants(editor, control_type="Button"):
            try:
                name = normalize_text(button.window_text())
                info_name = normalize_text(button.element_info.name or "")
                auto_id = normalize_text(button.element_info.automation_id or "")

                if (
                    auto_id == "ButtonOk"
                    or name.lower() == "ok"
                    or info_name.lower() == "ok"
                ):
                    log("Found Ok button.")
                    return button
            except Exception:
                continue

        raise RuntimeError("Could not find Ok button.")

    # ============================================================
    # DEBUG
    # ============================================================

    def _print_editor_debug_text(self, editor: BaseWrapper) -> None:
        log("Visible Exploration Editor text/debug values:")

        shown = 0

        for ctrl in safe_descendants(editor):
            try:
                text = normalize_text(ctrl.window_text())
                name = normalize_text(ctrl.element_info.name or "")
                control_type = normalize_text(ctrl.element_info.control_type or "")
                class_name = normalize_text(ctrl.element_info.class_name or "")

                value = text or name

                if not value:
                    continue

                r = ctrl.rectangle()

                log(
                    f"  {control_type} class={class_name!r} "
                    f"value={value!r} rect=({r.left},{r.top},{r.right},{r.bottom})"
                )

                shown += 1

                if shown >= 80:
                    break
            except Exception:
                continue