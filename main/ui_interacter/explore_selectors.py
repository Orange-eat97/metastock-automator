# explore_selectors.py

from __future__ import annotations

from typing import Optional

from pywinauto import Desktop
from pywinauto.base_wrapper import BaseWrapper

from ui_interacter.ui_core import normalize_text, safe_descendants, log
from ui_interacter.state_readers import parse_selected_total_text


class ExploreSelectors:
    def find_text_control_fuzzy(
        self,
        root: BaseWrapper,
        target_text: str,
    ) -> Optional[BaseWrapper]:
        target = normalize_text(target_text).lower()

        for t in safe_descendants(root, control_type="Text"):
            try:
                txt = normalize_text(t.window_text())
                if not txt:
                    continue

                low = txt.lower()
                if target in low or low in target:
                    return t
            except Exception:
                continue

        return None

    def find_explore_caption(self, main: BaseWrapper) -> Optional[BaseWrapper]:
        log("Searching for Explore tab/caption...")

        search_roots = [main]

        try:
            search_roots.append(Desktop(backend="uia"))
        except Exception:
            pass

        for root in search_roots:
            try:
                elems = root.descendants()
            except Exception:
                elems = []

            for e in elems:
                try:
                    info = e.element_info
                    name = normalize_text(info.name or "")
                    class_name = normalize_text(info.class_name or "")
                    help_text = normalize_text(getattr(info, "help_text", "") or "")

                    if help_text.lower() == "explore":
                        log(f"Found Explore by HelpText. name={name!r}, class={class_name!r}")
                        return e

                    if name.lower() == "explore":
                        log(f"Found Explore by Name. class={class_name!r}")
                        return e

                    if class_name == "TabCaptionControl":
                        child_texts = [
                            normalize_text(c.window_text())
                            for c in e.descendants(control_type="Text")
                            if normalize_text(c.window_text())
                        ]

                        if "Explore" in child_texts:
                            log("Found Explore inside TabCaptionControl children.")
                            return e

                except Exception:
                    continue

        log("Could not find Explore through UIA tree.")
        return None

    def find_search_combobox(self, main: BaseWrapper) -> BaseWrapper:
        log("Searching for explorer SearchComboBox...")

        combos = safe_descendants(main, control_type="ComboBox")

        for combo in combos:
            try:
                info = combo.element_info
                name = normalize_text(info.name or "")
                auto_id = normalize_text(info.automation_id or "")
                class_name = normalize_text(info.class_name or "")
                text = normalize_text(combo.window_text())

                fields = " ".join([name, auto_id, class_name, text]).lower()

                if "searchcombobox" in fields or "search" in fields:
                    log(
                        f"Found SearchComboBox: "
                        f"name={name!r}, auto_id={auto_id!r}, "
                        f"class={class_name!r}, text={text!r}"
                    )
                    return combo
            except Exception:
                continue

        raise RuntimeError("Could not find SearchComboBox in Explore Console.")

    def find_strategy_list_view(self, main: BaseWrapper) -> BaseWrapper:
        log("Searching for strategy list view...")

        list_views = safe_descendants(main, control_type="List")
        candidates = []

        for lv in list_views:
            try:
                r = lv.rectangle()
                name = normalize_text(lv.element_info.name or "")
                text = normalize_text(lv.window_text())

                # Strategy list is large and on the left side.
                if r.width() > 250 and r.height() > 120 and r.left < 750:
                    candidates.append((r.top, r.left, lv, name, text, r))
            except Exception:
                continue

        if not candidates:
            raise RuntimeError("Could not find strategy list view.")

        candidates.sort(key=lambda x: (x[0], x[1]))

        chosen = candidates[0][2]
        r = chosen.rectangle()

        log(f"Using strategy list view rect=({r.left},{r.top},{r.right},{r.bottom})")
        return chosen

    def find_filtered_strategy_rows(self, main: BaseWrapper) -> list[BaseWrapper]:
        """
        Find strategy ListBoxItem rows after the search filter is applied.

        Inspect.exe showed each strategy result is exposed as:
            ControlType: ListItem
            ClassName: ListBoxItem
            Name: IMA.Presentation...ExplorationVM
            HelpText: strategy description/formula
            Children: none
            TogglePattern: unavailable

        The searched display name, e.g. '#Stoch and RSI', is not exposed as row text.
        """
        list_view = self.find_strategy_list_view(main)
        list_rect = list_view.rectangle()

        candidates: list[tuple[int, int, int, BaseWrapper, str]] = []

        try:
            descendants = list_view.descendants()
        except Exception:
            descendants = []

        for ctrl in descendants:
            try:
                info = ctrl.element_info
                r = ctrl.rectangle()

                control_type = normalize_text(info.control_type or "")
                class_name = normalize_text(info.class_name or "")
                name = normalize_text(info.name or "")
                help_text = normalize_text(getattr(info, "help_text", "") or "")

                is_strategy_item = (
                    control_type == "ListItem"
                    or class_name == "ListBoxItem"
                    or "ExplorationVM" in name
                )

                if not is_strategy_item:
                    continue

                # Must overlap the strategy list view.
                if r.right < list_rect.left or r.left > list_rect.right:
                    continue
                if r.bottom < list_rect.top or r.top > list_rect.bottom:
                    continue

                # Avoid invalid/tiny elements.
                if r.width() <= 20 or r.height() <= 8:
                    continue

                score = 0

                if control_type == "ListItem":
                    score += 30
                if class_name == "ListBoxItem":
                    score += 30
                if "ExplorationVM" in name:
                    score += 20
                if help_text:
                    score += 10

                # Prefer row-sized items.
                if 15 <= r.height() <= 80:
                    score += 10

                candidates.append((score, r.top, r.left, ctrl, help_text or name))

            except Exception:
                continue

        candidates.sort(key=lambda x: (-x[0], x[1], x[2]))

        rows = [ctrl for _, _, _, ctrl, _ in candidates]

        log(f"Filtered strategy ListBoxItem candidate count: {len(rows)}")

        for idx, (score, _, _, ctrl, desc) in enumerate(candidates[:10], start=1):
            r = ctrl.rectangle()
            log(
                f"  strategy candidate {idx}: "
                f"score={score}, rect=({r.left},{r.top},{r.right},{r.bottom}), "
                f"description/name={desc!r}"
            )

        return rows

    def find_unique_filtered_strategy_row(self, main: BaseWrapper) -> BaseWrapper:
        """
        Return the unique visible filtered strategy row.

        Safety rule:
        - 0 rows: fail
        - 1 row: use it
        - >1 rows: fail safely because the search term is not unique enough
        """
        rows = self.find_filtered_strategy_rows(main)

        if not rows:
            raise RuntimeError(
                "No strategy ListBoxItem row found after search filtering. "
                "The filtered list may not be loaded, or MetaStock did not expose the result row."
            )

        if len(rows) > 1:
            raise RuntimeError(
                f"Search result is ambiguous: found {len(rows)} strategy rows after filtering. "
                "Use a more unique strategy search string before allowing automated selection."
            )

        row = rows[0]
        r = row.rectangle()

        log(
            "Using unique filtered strategy row: "
            f"rect=({r.left},{r.top},{r.right},{r.bottom})"
        )

        return row

    def find_checkbox_in_row(self, row: BaseWrapper) -> Optional[BaseWrapper]:
        """
        Find a real CheckBox inside a row if UIA exposes one.

        For strategy rows this probably returns None because Inspect.exe showed
        ListBoxItem rows with no children and no TogglePattern. Still useful for
        any UIA-exposed checkbox row.
        """
        def is_checkbox(ctrl: BaseWrapper) -> bool:
            try:
                info = ctrl.element_info
                control_type = normalize_text(info.control_type or "")
                class_name = normalize_text(info.class_name or "")
                name = normalize_text(info.name or "")

                combined = f"{control_type} {class_name} {name}".lower()
                return "checkbox" in combined
            except Exception:
                return False

        try:
            for child in row.children():
                if is_checkbox(child):
                    return child
        except Exception:
            pass

        try:
            for child in row.descendants():
                if is_checkbox(child):
                    return child
        except Exception:
            pass

        return None

    def find_instruments_tree_item(self, main: BaseWrapper) -> BaseWrapper:
        log("Searching for Instruments tree item...")

        candidates = []

        for item in safe_descendants(main):
            try:
                info = item.element_info
                name = normalize_text(info.name or "")
                class_name = normalize_text(info.class_name or "")
                control_type = normalize_text(info.control_type or "")
                r = item.rectangle()

                combined = f"{name} {class_name} {control_type}"

                if "InstrumentListTypesTVM" not in combined:
                    continue

                if r.width() <= 50 or r.height() <= 10:
                    continue

                if r.left > 350:
                    continue

                child_texts = []
                try:
                    for child in item.children():
                        txt = normalize_text(child.window_text())
                        if txt:
                            child_texts.append(txt)

                        child_name = normalize_text(child.element_info.name or "")
                        if child_name:
                            child_texts.append(child_name)
                except Exception:
                    pass

                score = 0

                if "InstrumentListTypesTVM" in name:
                    score += 10
                if class_name == "TreeViewItem":
                    score += 5
                if "TreeItem" in control_type:
                    score += 5
                if any(t.lower() == "instruments" for t in child_texts):
                    score += 5
                if any(parse_selected_total_text(t) is not None for t in child_texts):
                    score += 5

                candidates.append(
                    (score, r.top, r.left, item, child_texts, r, name, class_name, control_type)
                )

            except Exception:
                continue

        if not candidates:
            raise RuntimeError("Could not find Instruments TreeViewItem.")

        candidates.sort(key=lambda x: (-x[0], x[1], x[2]))

        return candidates[0][3]

    def find_start_button(self, main: BaseWrapper) -> Optional[BaseWrapper]:
        possible_names = [
            "Start Exploration...",
            "Start Exploration",
            "Start",
            "Run Exploration",
            "Run",
            "Explore",
            "Exploration",
        ]

        buttons = safe_descendants(main, control_type="Button")

        for target in possible_names:
            for btn in buttons:
                try:
                    name = normalize_text(btn.window_text())
                    info_name = normalize_text(btn.element_info.name or "")
                except Exception:
                    continue

                if name.lower() == target.lower() or info_name.lower() == target.lower():
                    log(f"Found Start button by exact name: {name or info_name!r}")
                    return btn

        for btn in buttons:
            try:
                name = normalize_text(btn.window_text())
                info_name = normalize_text(btn.element_info.name or "")
                combined = f"{name} {info_name}".lower()
            except Exception:
                continue

            if "start" in combined and "exploration" in combined:
                log(f"Found Start button by fuzzy name: {name or info_name!r}")
                return btn

        return None