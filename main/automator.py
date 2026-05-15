"""
MetaStock Phase 1 Explore Automation MVP

Workflow:
1. Connect to already-open MetaStock.
2. Open Explore Console.
3. Use SearchComboBox to search for target explorer strategy.
4. Select strategy using stable list-coordinate click + Selected:n repair.
5. Ensure Instruments are selected using InstrumentListTypesTVM tree item state.
6. Click Start Exploration.
7. Wait for Exploration Execution to complete.
8. Leave result window visible.

Assumptions:
- MetaStock is already open and logged in.
- Target custom list / dataset has already been added into the Explore Console.
- The target strategy can be found by searching in the Explore Console search box.
- The script does NOT open Custom List Manager.
- The script does NOT parse the result table yet.
"""

from __future__ import annotations

import re
import time
from typing import Optional

import pyperclip
from pywinauto import Application, Desktop, mouse
from pywinauto.base_wrapper import BaseWrapper
from pywinauto.keyboard import send_keys

from requestReceiver import CliRequestReceiver, ExploreRequest



# ============================================================
# USER CONFIG
# ============================================================

APP_TITLE_RE = r".*MetaStock.*"

MAX_EXECUTION_WAIT_SEC = 300
CLICK_EXIT_AFTER_DONE = False

# Timing config
SHORT_DELAY = 0.15
MEDIUM_DELAY = 0.35
LONG_DELAY = 0.75
EXPLORE_LOAD_TIMEOUT = 8
SEARCH_FILTER_TIMEOUT = 2
EXECUTION_POLL_INTERVAL = 0.35

# Fallback for Start button only. Keep False unless manually verified.
ALLOW_START_FALLBACK_CLICK = False
START_FALLBACK_ABSOLUTE_XY: Optional[tuple[int, int]] = None


# ============================================================
# GENERAL HELPERS
# ============================================================

def log(msg: str) -> None:
    print(f"[MetaStockBot] {msg}")


def normalize_text(s: str) -> str:
    return " ".join((s or "").strip().split())


def safe_descendants(root: BaseWrapper, **kwargs) -> list[BaseWrapper]:
    try:
        return root.descendants(**kwargs)
    except Exception:
        return []


def rect_center(ctrl: BaseWrapper) -> tuple[int, int]:
    r = ctrl.rectangle()
    return ((r.left + r.right) // 2, (r.top + r.bottom) // 2)


def click_wrapper(ctrl: BaseWrapper, label: str = "control") -> None:
    x, y = rect_center(ctrl)
    log(f"Clicking {label} at ({x}, {y})")
    ctrl.click_input()


def wait_until(condition_fn, timeout=20, interval=0.1, error_msg="Timed out"):
    deadline = time.time() + timeout
    last_error = None

    while time.time() < deadline:
        try:
            result = condition_fn()
            if result:
                return result
        except Exception as e:
            last_error = e

        time.sleep(interval)

    raise RuntimeError(f"{error_msg}. Last error: {last_error}")


# ============================================================
# CONNECT / OPEN EXPLORE
# ============================================================

def connect_metastock() -> BaseWrapper:
    log("Connecting to MetaStock...")

    app = Application(backend="uia").connect(title_re=APP_TITLE_RE, timeout=15)
    main = app.window(title_re=APP_TITLE_RE)
    main.wait("exists visible", timeout=20)
    main.set_focus()

    log(f"Connected to window: {main.window_text()!r}")
    return main


def find_text_control_fuzzy(root: BaseWrapper, target_text: str) -> Optional[BaseWrapper]:
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


def find_explore_caption(main: BaseWrapper) -> Optional[BaseWrapper]:
    """
    Try to find the left-side Explore tab through UIA.

    If UIA cannot find it, open_explore_panel() uses a coordinate fallback.
    """
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
                    try:
                        child_texts = [
                            normalize_text(c.window_text())
                            for c in e.descendants(control_type="Text")
                            if normalize_text(c.window_text())
                        ]
                    except Exception:
                        child_texts = []

                    if "Explore" in child_texts:
                        log("Found Explore inside TabCaptionControl children.")
                        return e

            except Exception:
                continue

    log("Could not find Explore through UIA tree.")
    return None


def open_explore_panel(main: BaseWrapper) -> None:
    """
    Opens Explore Console.
    """
    explore = find_explore_caption(main)

    if explore is not None:
        click_wrapper(explore, "Explore tab/caption")
    else:
        r = main.rectangle()

        # Relative fallback for the vertical Explore tab.
        # Adjust y if your tab layout changes.
        x = r.left + 28
        y = r.top + 390

        log(f"Using fallback click for Explore tab at ({x}, {y}).")
        mouse.click(button="left", coords=(x, y))

    log("Waiting for Explore Console to load...")

    def loaded():
        for text in ["All Explorations", "New Exploration", "Start Exploration"]:
            if find_text_control_fuzzy(main, text) is not None:
                return True
        return False

    try:
        wait_until(
            loaded,
            timeout=EXPLORE_LOAD_TIMEOUT,
            interval=0.2,
            error_msg="Explore Console did not finish loading",
        )
        log("Explore Console loaded.")
    except Exception:
        log("Could not verify Explore Console by text, continuing anyway.")


# ============================================================
# STRATEGY SELECTION
# ============================================================

def find_search_combobox(main: BaseWrapper) -> BaseWrapper:
    """
    Find the explorer SearchComboBox.
    """
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


def set_search_text(search_box: BaseWrapper, text: str) -> None:
    """
    Clipboard paste is more reliable than typing special characters into WPF ComboBox.
    """
    log(f"Pasting into explorer search box: {text!r}")

    search_box.click_input()
    time.sleep(SHORT_DELAY)

    pyperclip.copy(text)

    send_keys("^a")
    time.sleep(0.05)
    send_keys("{BACKSPACE}")
    time.sleep(0.05)
    send_keys("^v")

    time.sleep(MEDIUM_DELAY)


def get_selected_count_text(main: BaseWrapper) -> Optional[str]:
    for t in safe_descendants(main, control_type="Text"):
        try:
            txt = normalize_text(t.window_text())
            if txt.startswith("Selected:"):
                return txt
        except Exception:
            pass
    return None


def parse_selected_count(text: Optional[str]) -> Optional[int]:
    """
    Parses:
        'Selected: 0'
        'Selected: 1'
    """
    if not text:
        return None

    m = re.search(r"Selected:\s*(\d+)", text)
    if not m:
        return None

    return int(m.group(1))


def find_strategy_list_view(main: BaseWrapper) -> BaseWrapper:
    """
    Find the left-side strategy list view under All Explorations.
    """
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

    log("Strategy list view candidates:")
    for top, left, lv, name, text, r in candidates[:3]:
        log(
            f"  rect=({r.left},{r.top},{r.right},{r.bottom}), "
            f"name={name!r}, text={text!r}"
        )

    chosen = candidates[0][2]
    r = chosen.rectangle()
    log(f"Using strategy list view rect=({r.left},{r.top},{r.right},{r.bottom})")
    return chosen


def wait_for_strategy_list_after_search(main: BaseWrapper) -> None:
    """
    Wait until the strategy list view is available after using the search box.
    """
    def ready():
        try:
            lv = find_strategy_list_view(main)
            r = lv.rectangle()
            return r.width() > 250 and r.height() > 100
        except Exception:
            return False

    wait_until(
        ready,
        timeout=SEARCH_FILTER_TIMEOUT,
        interval=0.15,
        error_msg="Strategy list did not become ready after search",
    )


def click_first_filtered_strategy_checkbox(main: BaseWrapper) -> None:
    """
    Click first visible strategy checkbox after search.

    Uses stable coordinate relative to strategy list view.
    """
    list_view = find_strategy_list_view(main)
    r = list_view.rectangle()

    # Known stable position:
    # strategy list rect ~= (86,196,599,508)
    # first checkbox center ~= (108,221)
    x = r.left + 22
    y = r.top + 25

    log(f"Clicking first filtered strategy checkbox at ({x}, {y})")
    mouse.click(button="left", coords=(x, y))
    time.sleep(MEDIUM_DELAY)


def get_search_combobox_text(search_box: BaseWrapper) -> str:
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


def strategy_search_matches(current_text: str, strategy_name: str) -> bool:
    """
    Returns True if the current search box already contains the target strategy search.
    """
    current = normalize_text(current_text).lower()
    target = normalize_text(strategy_name).lower()

    if not current:
        return False

    return current == target or target in current or current in target


def select_strategy_by_search_then_coordinate(main: BaseWrapper, strategy_name: str) -> None:
    """
    Stateful strategy selection.

    Improved order:
    1. Check current SearchComboBox before searching.
    2. If it already filters to the target and Selected:n > 0, do nothing.
    3. Otherwise search target and use selected-count repair.

    This avoids unnecessary uncheck-then-recheck when the correct strategy is
    already filtered and checked.
    """
    log(f"Selecting strategy through search + stateful coordinate click: {strategy_name!r}")

    search_box = find_search_combobox(main)
    current_search_text = get_search_combobox_text(search_box)
    selected_initial_text = get_selected_count_text(main)
    selected_initial = parse_selected_count(selected_initial_text)

    log(f"Current search box text: {current_search_text!r}")
    log(f"Initial selected count: {selected_initial_text!r}")

    # Case 1: search box already shows the target strategy.
    # If Selected:n > 0, the target filtered row is already checked.
    if strategy_search_matches(current_search_text, strategy_name):
        log("Search box already matches target strategy.")

        wait_for_strategy_list_after_search(main)

        if selected_initial is not None and selected_initial > 0:
            log("Target strategy appears already selected. Proceeding without clicking.")
            return

        if selected_initial == 0:
            log("Target strategy appears unselected. Clicking once...")
            click_first_filtered_strategy_checkbox(main)

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
    set_search_text(search_box, strategy_name)

    log("Waiting for explorer list to filter...")
    wait_for_strategy_list_after_search(main)

    selected_before_text = get_selected_count_text(main)
    selected_before = parse_selected_count(selected_before_text)

    log(f"Selected count before strategy click: {selected_before_text!r}")

    if selected_before is None:
        raise RuntimeError(
            "Could not read selected strategy count before clicking. "
            "Refusing to do stateless toggle."
        )

    click_first_filtered_strategy_checkbox(main)

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

        click_first_filtered_strategy_checkbox(main)

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


# ============================================================
# INSTRUMENT SELECTION
# ============================================================

def parse_selected_total_text(text: str) -> Optional[tuple[int, int]]:
    """
    Parses:
        '0 of 784' -> (0, 784)
        '784 of 784' -> (784, 784)
    """
    m = re.search(r"(\d+)\s+of\s+(\d+)", text or "")
    if not m:
        return None

    return int(m.group(1)), int(m.group(2))


def find_instruments_tree_item(main: BaseWrapper) -> BaseWrapper:
    """
    Find the left-side Instruments TreeViewItem.

    Inspect shows the row as:
        Name: IMA.Presentation.InstrumentTreeView.ViewModel.InstrumentListTypesTVM
        ControlType: TreeItem
        ClassName: TreeViewItem
        Children:
            button
            checkbox
            Instruments text
            0 of 784 text
            (784) text

    In pywinauto, child texts may not always be exposed, so this function
    first finds by the stable VM name, then uses geometry/children as secondary signals.
    """
    log("Searching for Instruments tree item...")

    candidates = []

    # Search all descendants, not only control_type='TreeItem',
    # because UIA / pywinauto sometimes reports WPF tree items inconsistently.
    for item in safe_descendants(main):
        try:
            info = item.element_info
            name = normalize_text(info.name or "")
            class_name = normalize_text(info.class_name or "")
            control_type = normalize_text(info.control_type or "")
            r = item.rectangle()

            combined = f"{name} {class_name} {control_type}"

            # Stable signal from Inspect output.
            if "InstrumentListTypesTVM" not in combined:
                continue

            # Avoid invisible garbage rectangles.
            if r.width() <= 50 or r.height() <= 10:
                continue

            # This row should be in the left Explore Console area.
            if r.left > 350:
                continue

            child_texts = []
            try:
                for child in item.children():
                    try:
                        txt = normalize_text(child.window_text())
                        if txt:
                            child_texts.append(txt)
                    except Exception:
                        pass

                    try:
                        child_name = normalize_text(child.element_info.name or "")
                        if child_name:
                            child_texts.append(child_name)
                    except Exception:
                        pass
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
        # Helpful debug output
        log("Could not find InstrumentListTypesTVM. Nearby tree-like items:")
        shown = 0
        for item in safe_descendants(main):
            try:
                info = item.element_info
                name = normalize_text(info.name or "")
                class_name = normalize_text(info.class_name or "")
                control_type = normalize_text(info.control_type or "")
                r = item.rectangle()

                if "Tree" in class_name or "Tree" in control_type or "Instrument" in name:
                    log(
                        f"  candidate name={name!r}, class={class_name!r}, "
                        f"type={control_type!r}, rect=({r.left},{r.top},{r.right},{r.bottom})"
                    )
                    shown += 1
                    if shown >= 20:
                        break
            except Exception:
                pass

        raise RuntimeError("Could not find Instruments TreeViewItem.")

    # Higher score first, then top-left ordering.
    candidates.sort(key=lambda x: (-x[0], x[1], x[2]))

    for score, _, _, _, child_texts, r, name, class_name, control_type in candidates[:5]:
        log(
            f"Instruments candidate score={score}, "
            f"name={name!r}, class={class_name!r}, type={control_type!r}, "
            f"rect=({r.left},{r.top},{r.right},{r.bottom}), children={child_texts}"
        )

    return candidates[0][3]


def get_instruments_selected_total(item: BaseWrapper) -> Optional[tuple[int, int]]:
    """
    Reads selected/total count from the Instruments row.

    Expected child text:
        '0 of 784'
        '784 of 784'
    """
    texts = []

    try:
        children = item.children()
    except Exception:
        children = []

    for child in children:
        try:
            txt = normalize_text(child.window_text())
            if txt:
                texts.append(txt)
        except Exception:
            pass

        try:
            name = normalize_text(child.element_info.name or "")
            if name:
                texts.append(name)
        except Exception:
            pass

    log(f"Instruments row child texts/names: {texts}")

    for t in texts:
        parsed = parse_selected_total_text(t)
        if parsed is not None:
            return parsed

    return None


def click_instruments_checkbox_from_tree_item(item: BaseWrapper) -> None:
    """
    Click the checkbox inside the Instruments TreeItem using row geometry.
    """
    r = item.rectangle()

    # Tuned rightward because previous click was slightly left of the box.
    x = r.left + 38
    y = (r.top + r.bottom) // 2

    log(
        f"Clicking Instruments checkbox using TreeItem rect="
        f"({r.left},{r.top},{r.right},{r.bottom}), point=({x},{y})"
    )

    mouse.click(button="left", coords=(x, y))
    time.sleep(MEDIUM_DELAY)



def ensure_instrument_checked(main: BaseWrapper) -> None:
    """
    Ensure Instruments is selected without unsafe stateless toggling.

    Handles three states:
        0 of 784      -> unchecked
        778 of 784    -> partially checked
        784 of 784    -> fully checked

    Important:
    In WPF tri-state checkbox behavior, clicking a partially checked parent
    may toggle it to unchecked first. If that happens, click again to move
    from unchecked to checked.
    """
    try:
        item = find_instruments_tree_item(main)

        before = get_instruments_selected_total(item)
        log(f"Instruments selected count before: {before}")

        if before is None:
            raise RuntimeError(
                "Could not read Instruments selected/total count. "
                "Refusing to toggle blindly."
            )

        selected, total = before

        if total <= 0:
            raise RuntimeError(f"Invalid Instruments total count: {before}")

        if selected > total:
            raise RuntimeError(f"Invalid Instruments selected/total count: {before}")

        if selected == total:
            log("Instruments already fully selected. Proceeding without clicking.")
            return

        # Case 1: completely unchecked.
        if selected == 0:
            log("Instruments fully unchecked. Clicking once to select all...")
            click_instruments_checkbox_from_tree_item(item)

            item = find_instruments_tree_item(main)
            after = get_instruments_selected_total(item)
            log(f"Instruments selected count after click: {after}")

            if after is None:
                raise RuntimeError(
                    "Clicked Instruments checkbox, but could not verify selected/total count."
                )

            selected_after, total_after = after

            if total_after > 0 and selected_after == total_after:
                log("Instruments is now fully selected.")
                return

            raise RuntimeError(
                f"Clicked unchecked Instruments, but it did not become fully selected. "
                f"Before={before}, After={after}"
            )

        # Case 2: partially checked.
        # Example: 778 of 784.
        #
        # In many WPF tri-state checkboxes:
        # partial -> unchecked -> checked
        #
        # So we may need two clicks.
        log(
            "Instruments is partially selected. "
            "Clicking once and checking whether it becomes full or unchecked..."
        )

        click_instruments_checkbox_from_tree_item(item)

        item = find_instruments_tree_item(main)
        after_first = get_instruments_selected_total(item)
        log(f"Instruments selected count after first partial-state click: {after_first}")

        if after_first is None:
            raise RuntimeError(
                "Clicked partially selected Instruments, but could not verify state after first click."
            )

        selected_first, total_first = after_first

        if total_first <= 0:
            raise RuntimeError(f"Invalid Instruments total after first click: {after_first}")

        if selected_first == total_first:
            log("Instruments is now fully selected.")
            return

        if selected_first == 0:
            log(
                "Partial-state click toggled Instruments to unchecked. "
                "Clicking once more to select all..."
            )

            click_instruments_checkbox_from_tree_item(item)

            item = find_instruments_tree_item(main)
            after_second = get_instruments_selected_total(item)
            log(f"Instruments selected count after second click: {after_second}")

            if after_second is None:
                raise RuntimeError(
                    "Clicked unchecked Instruments, but could not verify state after second click."
                )

            selected_second, total_second = after_second

            if total_second > 0 and selected_second == total_second:
                log("Instruments is now fully selected.")
                return

            raise RuntimeError(
                f"Second click did not fully select Instruments. "
                f"Before={before}, AfterFirst={after_first}, AfterSecond={after_second}"
            )

        # Still partial after one click.
        raise RuntimeError(
            f"Instruments remained partially selected after click. "
            f"Before={before}, AfterFirst={after_first}"
        )

    except Exception as e:
        raise RuntimeError(
            f"Failed to ensure Instruments is checked without toggling: {e}"
        )


def ensure_named_instruments_checked(
    main: BaseWrapper,
    instrument_names: list[str],
) -> None:
    """
    Placeholder for future multiple/named instrument selection.

    Current Phase 1 POI only supports the broad 'all instruments' selection
    through InstrumentListTypesTVM.

    Do not silently ignore named instruments, because that would make the CLI
    look more capable than the automation actually is.
    """
    raise NotImplementedError(
        "Named/multiple instrument selection is not implemented yet. "
        f"Requested instruments: {instrument_names}. "
        "Use --all-instruments for the current Phase 1 MVP."
    )


# ============================================================
# START EXPLORATION
# ============================================================

def find_start_button(main: BaseWrapper) -> Optional[BaseWrapper]:
    """
    Find Start Exploration button.
    """
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


def start_exploration(main: BaseWrapper) -> None:
    log("Searching for Start Exploration button...")

    btn = find_start_button(main)

    if btn is not None:
        click_wrapper(btn, "Start Exploration button")
        return

    if ALLOW_START_FALLBACK_CLICK and START_FALLBACK_ABSOLUTE_XY is not None:
        x, y = START_FALLBACK_ABSOLUTE_XY
        log(f"Using fallback Start Exploration click at ({x}, {y})")
        mouse.click(button="left", coords=(x, y))
        return

    raise RuntimeError(
        "Could not find Start Exploration button safely. "
        "Inspect the button name, or configure START_FALLBACK_ABSOLUTE_XY."
    )


# ============================================================
# EXECUTION WINDOW / WAIT
# ============================================================

def find_execution_window_inside_main(main: BaseWrapper) -> Optional[BaseWrapper]:
    """
    Find Exploration Execution as a child/descendant of Main - MetaStock.
    """
    keyword = "exploration execution"

    try:
        windows = main.descendants(control_type="Window")
    except Exception:
        windows = []

    for w in windows:
        try:
            name = normalize_text(w.element_info.name or "")
            text = normalize_text(w.window_text())
            combined = f"{name} {text}".lower()

            if keyword in combined:
                return w
        except Exception:
            continue

    return None


def wait_for_execution_window(main: BaseWrapper) -> BaseWrapper:
    log("Waiting for Exploration Execution window inside MetaStock...")

    deadline = time.time() + 60

    while time.time() < deadline:
        exec_win = find_execution_window_inside_main(main)

        if exec_win is not None:
            log("Exploration Execution window found inside Main - MetaStock.")
            return exec_win

        time.sleep(0.25)

    raise RuntimeError("Timed out waiting for Exploration Execution window inside Main - MetaStock.")


def collect_all_visible_text(root: BaseWrapper) -> list[str]:
    """
    Collect visible text/name values from the execution window.
    """
    values = []

    try:
        descendants = root.descendants()
    except Exception:
        descendants = []

    for e in descendants:
        try:
            txt = normalize_text(e.window_text())
            if txt:
                values.append(txt)
        except Exception:
            pass

        try:
            name = normalize_text(e.element_info.name or "")
            if name:
                values.append(name)
        except Exception:
            pass

    seen = set()
    result = []

    for v in values:
        if v not in seen:
            seen.add(v)
            result.append(v)

    return result


def parse_fraction_from_any_text(s: str) -> Optional[tuple[int, int]]:
    """
    Examples:
        '1/1' -> (1, 1)
        '778/778' -> (778, 778)
        '772/778' -> (772, 778)
    """
    m = re.search(r"(\d+)\s*/\s*(\d+)", s)
    if not m:
        return None

    return int(m.group(1)), int(m.group(2))


def execution_progress_done(exec_win: BaseWrapper) -> bool:
    """
    Completed window exposes:
        Exploration(s): 1/1
        Instrument(s): 778/778
    """
    texts = collect_all_visible_text(exec_win)

    fractions = []
    for t in texts:
        f = parse_fraction_from_any_text(t)
        if f is not None:
            fractions.append(f)

    exploration_complete = any(a == b == 1 for a, b in fractions)
    instrument_complete = any(a == b and b > 1 for a, b in fractions)

    if exploration_complete and instrument_complete:
        return True

    # Backup: Exit enabled and Cancel disabled.
    cancel_disabled = False
    exit_enabled = False

    try:
        cancel_btn = exec_win.child_window(title="Cancel", control_type="Button")
        if cancel_btn.exists(timeout=0.2) and not cancel_btn.is_enabled():
            cancel_disabled = True
    except Exception:
        pass

    try:
        exit_btn = exec_win.child_window(title="Exit", control_type="Button")
        if exit_btn.exists(timeout=0.2) and exit_btn.is_enabled():
            exit_enabled = True
    except Exception:
        pass

    return cancel_disabled and exit_enabled and exploration_complete


def wait_for_execution_done(exec_win: BaseWrapper) -> None:
    log("Waiting for exploration to complete...")

    deadline = time.time() + MAX_EXECUTION_WAIT_SEC
    last_status = None

    while time.time() < deadline:
        try:
            if not exec_win.exists(timeout=0.2):
                log("Execution window disappeared. Assuming execution finished.")
                return
        except Exception:
            log("Execution window no longer accessible. Assuming execution finished.")
            return

        texts = collect_all_visible_text(exec_win)

        progress_bits = []
        for t in texts:
            if (
                "Exploration" in t
                or "Instrument" in t
                or "Rejected" in t
                or re.search(r"\d+\s*/\s*\d+", t)
                or "%" in t
            ):
                progress_bits.append(t)

        progress_status = " | ".join(progress_bits)

        if progress_status and progress_status != last_status:
            log(f"Progress/status: {progress_status}")
            last_status = progress_status

        if execution_progress_done(exec_win):
            log("Exploration finished.")
            return

        time.sleep(EXECUTION_POLL_INTERVAL)

    raise TimeoutError(
        f"Exploration did not complete within {MAX_EXECUTION_WAIT_SEC} seconds."
    )


# ============================================================
# DEBUG HELPER
# ============================================================

def print_control_summary(main: BaseWrapper) -> None:
    print("\n========== TEXTS ==========")
    for t in safe_descendants(main, control_type="Text"):
        try:
            txt = normalize_text(t.window_text())
            if txt:
                r = t.rectangle()
                print(f"TEXT {txt!r} rect=({r.left},{r.top},{r.right},{r.bottom})")
        except Exception:
            pass

    print("\n========== TREE ITEMS ==========")
    for item in safe_descendants(main, control_type="TreeItem"):
        try:
            r = item.rectangle()
            name = normalize_text(item.element_info.name or "")
            texts = []
            for child in item.children():
                try:
                    txt = normalize_text(child.window_text())
                    if txt:
                        texts.append(txt)
                except Exception:
                    pass
            print(
                f"TREEITEM name={name!r}, children={texts}, "
                f"rect=({r.left},{r.top},{r.right},{r.bottom})"
            )
        except Exception:
            pass

    print("\n========== BUTTONS ==========")
    for b in safe_descendants(main, control_type="Button"):
        try:
            r = b.rectangle()
            name = normalize_text(b.element_info.name or "")
            text = normalize_text(b.window_text())
            print(
                f"BUTTON name={name!r}, text={text!r}, "
                f"rect=({r.left},{r.top},{r.right},{r.bottom})"
            )
        except Exception:
            pass

    print("\n========== COMBOBOXES ==========")
    for c in safe_descendants(main, control_type="ComboBox"):
        try:
            r = c.rectangle()
            name = normalize_text(c.element_info.name or "")
            text = normalize_text(c.window_text())
            cls = normalize_text(c.element_info.class_name or "")
            print(
                f"COMBO name={name!r}, text={text!r}, class={cls!r}, "
                f"rect=({r.left},{r.top},{r.right},{r.bottom})"
            )
        except Exception:
            pass

    print("\n========== LISTS ==========")
    for lv in safe_descendants(main, control_type="List"):
        try:
            r = lv.rectangle()
            name = normalize_text(lv.element_info.name or "")
            text = normalize_text(lv.window_text())
            print(
                f"LIST name={name!r}, text={text!r}, "
                f"rect=({r.left},{r.top},{r.right},{r.bottom})"
            )
        except Exception:
            pass


# ============================================================
# MAIN WORKFLOW
# ============================================================

def run_phase1_explore(request: ExploreRequest) -> None:
    global MAX_EXECUTION_WAIT_SEC

    MAX_EXECUTION_WAIT_SEC = request.max_execution_wait_sec

    main = connect_metastock()

    open_explore_panel(main)

    select_strategy_by_search_then_coordinate(main, request.strategy_name)

    if request.select_all_instruments:
        ensure_instrument_checked(main)
    else:
        ensure_named_instruments_checked(main, request.instrument_names or [])

    start_exploration(main)

    exec_win = wait_for_execution_window(main)
    wait_for_execution_done(exec_win)

    log("Done. MetaStock results should now be visible.")


def main() -> None:
    receiver = CliRequestReceiver()
    request = receiver.receive()
    run_phase1_explore(request)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FAILED: {e}")
        raise