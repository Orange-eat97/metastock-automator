# state_readers.py

from __future__ import annotations

import re
from typing import Optional
from pywinauto.base_wrapper import BaseWrapper

from ui_interacter.ui_core import normalize_text, safe_descendants, log


def parse_selected_count(text: Optional[str]) -> Optional[int]:
    if not text:
        return None

    m = re.search(r"Selected:\s*(\d+)", text)
    if not m:
        return None

    return int(m.group(1))


def get_selected_count_text(main: BaseWrapper) -> Optional[str]:
    for t in safe_descendants(main, control_type="Text"):
        try:
            txt = normalize_text(t.window_text())
            if txt.startswith("Selected:"):
                return txt
        except Exception:
            pass
    return None


def get_selected_count(main: BaseWrapper) -> Optional[int]:
    return parse_selected_count(get_selected_count_text(main))


def parse_selected_total_text(text: str) -> Optional[tuple[int, int]]:
    m = re.search(r"(\d+)\s+of\s+(\d+)", text or "")
    if not m:
        return None

    return int(m.group(1)), int(m.group(2))


def get_instruments_selected_total(item: BaseWrapper) -> Optional[tuple[int, int]]:
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


def parse_fraction_from_any_text(s: str) -> Optional[tuple[int, int]]:
    m = re.search(r"(\d+)\s*/\s*(\d+)", s)
    if not m:
        return None

    return int(m.group(1)), int(m.group(2))