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