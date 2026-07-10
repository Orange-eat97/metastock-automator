from __future__ import annotations

import re
import time
from typing import Optional

from pywinauto.base_wrapper import BaseWrapper

from ui_interacter.ui_core import log, normalize_text
from ui_interacter.state_readers import parse_fraction_from_any_text


class ExecutionMonitor:
    """
    Owns Exploration Execution window detection and progress waiting.
    """

    def __init__(
        self,
        max_execution_wait_sec: int = 300,
        poll_interval: float = 0.35,
    ):
        self.max_execution_wait_sec = max_execution_wait_sec
        self.poll_interval = poll_interval

    def wait_for_window(self, main: BaseWrapper) -> BaseWrapper:
        log("Waiting for Exploration Execution window inside MetaStock...")

        deadline = time.time() + 60

        while time.time() < deadline:
            exec_win = self.find_execution_window_inside_main(main)

            if exec_win is not None:
                log("Exploration Execution window found inside Main - MetaStock.")
                return exec_win

            time.sleep(0.25)

        raise RuntimeError("Timed out waiting for Exploration Execution window inside Main - MetaStock.")

    def wait_done(self, exec_win: BaseWrapper) -> None:
        log("Waiting for exploration to complete...")

        deadline = time.time() + self.max_execution_wait_sec
        last_status = None

        while time.time() < deadline:
            try:
                if not exec_win.exists(timeout=0.2):
                    log("Execution window disappeared. Assuming execution finished.")
                    return
            except Exception:
                log("Execution window no longer accessible. Assuming execution finished.")
                return

            texts = self.collect_all_visible_text(exec_win)

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

            if self.execution_progress_done(exec_win):
                log("Exploration finished.")
                return

            time.sleep(self.poll_interval)

        raise TimeoutError(
            f"Exploration did not complete within {self.max_execution_wait_sec} seconds."
        )

    def find_execution_window_inside_main(
        self,
        main: BaseWrapper,
    ) -> Optional[BaseWrapper]:
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

    def collect_all_visible_text(self, root: BaseWrapper) -> list[str]:
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
    
    def find_exit_button(
        self,
        exec_win: BaseWrapper,
    ) -> Optional[BaseWrapper]:
        """
        Find the Exit button in the Exploration Execution window.
        """
        try:
            buttons = exec_win.descendants(
                control_type="Button"
            )
        except Exception:
            buttons = []

        for button in buttons:
            try:
                name = normalize_text(
                    button.element_info.name or ""
                )
                text = normalize_text(
                    button.window_text() or ""
                )

                if (
                    name.casefold() == "exit"
                    or text.casefold() == "exit"
                ):
                    return button

            except Exception:
                continue

        return None


    def close_results_window(
        self,
        main: BaseWrapper,
        exec_win: BaseWrapper,
        timeout: float = 2.0,
        poll_interval: float = 0.03,
    ) -> bool:
        """
        Click Exit after result scraping has completed.

        Returns True when the Exploration Execution window closes.
        Returns False when cleanup fails, without discarding already
        scraped result data.
        """
        log(
            "Closing Exploration Execution results window..."
        )

        # Refresh the wrapper because result scraping may have caused
        # WPF controls to be recreated.
        current_exec_win = (
            self.find_execution_window_inside_main(main)
            or exec_win
        )

        exit_button = self.find_exit_button(
            current_exec_win
        )

        if exit_button is None:
            log(
                "Warning: could not find the Exit button "
                "after result scraping."
            )
            return False

        try:
            if not exit_button.is_enabled():
                log(
                    "Warning: Exploration Execution Exit "
                    "button is disabled."
                )
                return False
        except Exception:
            pass

        try:
            log("Invoking Exploration Execution Exit button.")
            exit_button.invoke()

        except Exception:
            try:
                log(
                    "Invoke failed; clicking Exploration "
                    "Execution Exit button."
                )
                exit_button.click_input()

            except Exception as exc:
                log(
                    "Warning: could not activate the "
                    f"Exit button: {exc}"
                )
                return False

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            remaining_window = (
                self.find_execution_window_inside_main(
                    main
                )
            )

            if remaining_window is None:
                log(
                    "Exploration Execution results "
                    "window closed."
                )
                return True

            try:
                if not remaining_window.is_visible():
                    log(
                        "Exploration Execution results "
                        "window is no longer visible."
                    )
                    return True
            except Exception:
                pass

            time.sleep(poll_interval)

        log(
            "Warning: Exit was activated, but the "
            "Exploration Execution window remained open."
        )

        return False

    def execution_progress_done(self, exec_win: BaseWrapper) -> bool:
        """
        Completed window exposes:
            Exploration(s): 1/1
            Instrument(s): 778/778
        """
        texts = self.collect_all_visible_text(exec_win)

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