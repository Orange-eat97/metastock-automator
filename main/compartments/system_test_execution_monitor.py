from __future__ import annotations

import re
import time
from typing import Optional

from pywinauto.base_wrapper import BaseWrapper

from ui_interacter.ui_core import log, normalize_text
from ui_interacter.state_readers import (
    parse_fraction_from_any_text,
)


class SystemTestExecutionMonitor:
    """
    System Tester counterpart of ExecutionMonitor.

    It preserves the Explorer monitor sequence:
    - wait for the execution/status window;
    - collect visible progress text;
    - wait until completion or disappearance;
    - time out using the request's maximum wait.
    """

    def __init__(
        self,
        max_execution_wait_sec: int = 300,
        poll_interval: float = 0.35,
    ):
        self.max_execution_wait_sec = (
            max_execution_wait_sec
        )
        self.poll_interval = poll_interval

    def wait_for_window(
        self,
        main: BaseWrapper,
    ) -> BaseWrapper:
        log(
            "Waiting for System Tester Execution Status "
            "window inside MetaStock..."
        )

        deadline = time.time() + 60

        while time.time() < deadline:
            execution_window = (
                self.find_execution_window_inside_main(main)
            )

            if execution_window is not None:
                log(
                    "System Tester Execution Status window "
                    "found inside Main - MetaStock."
                )
                return execution_window

            time.sleep(0.25)

        raise RuntimeError(
            "Timed out waiting for System Tester Execution "
            "Status window inside Main - MetaStock."
        )

    def wait_done(
        self,
        execution_window: BaseWrapper,
    ) -> None:
        log("Waiting for system test to complete...")

        deadline = (
            time.time() + self.max_execution_wait_sec
        )
        last_status = None

        while time.time() < deadline:
            try:
                if not execution_window.exists(timeout=0.2):
                    log(
                        "Execution status window disappeared. "
                        "Assuming execution finished."
                    )
                    return
            except Exception:
                log(
                    "Execution status window is no longer "
                    "accessible. Assuming execution finished."
                )
                return

            texts = self.collect_all_visible_text(
                execution_window
            )

            progress_bits = []
            for text in texts:
                if (
                    "System Tester" in text
                    or "Elapsed" in text
                    or "Last" in text
                    or "Best" in text
                    or re.search(r"\d+\s*/\s*\d+", text)
                    or "%" in text
                ):
                    progress_bits.append(text)

            progress_status = " | ".join(progress_bits)

            if (
                progress_status
                and progress_status != last_status
            ):
                log(
                    f"Progress/status: {progress_status}"
                )
                last_status = progress_status

            if self.execution_progress_done(
                execution_window
            ):
                log("System test finished.")
                return

            time.sleep(self.poll_interval)

        raise TimeoutError(
            "System test did not complete within "
            f"{self.max_execution_wait_sec} seconds."
        )

    def find_execution_window_inside_main(
        self,
        main: BaseWrapper,
    ) -> Optional[BaseWrapper]:
        """
        Find System Tester Execution Status as a child/descendant of Main.
        """
        keyword = "system tester execution status"

        try:
            windows = main.descendants(
                control_type="Window"
            )
        except Exception:
            windows = []

        for window in windows:
            try:
                name = normalize_text(
                    window.element_info.name or ""
                )
                text = normalize_text(
                    window.window_text()
                )
                combined = f"{name} {text}".lower()

                if keyword in combined:
                    return window
            except Exception:
                continue

        return None

    def collect_all_visible_text(
        self,
        root: BaseWrapper,
    ) -> list[str]:
        """
        Collect visible text/name values from the status window.
        """
        values = []

        try:
            descendants = root.descendants()
        except Exception:
            descendants = []

        for element in descendants:
            try:
                text = normalize_text(
                    element.window_text()
                )
                if text:
                    values.append(text)
            except Exception:
                pass

            try:
                name = normalize_text(
                    element.element_info.name or ""
                )
                if name:
                    values.append(name)
            except Exception:
                pass

        seen = set()
        result = []

        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)

        return result

    def execution_progress_done(
        self,
        execution_window: BaseWrapper,
    ) -> bool:
        """
        The inspected status text exposes a current/total fraction such as
        ``3/778``. Completion is the same fraction with current == total.
        """
        texts = self.collect_all_visible_text(
            execution_window
        )

        fractions = []
        for text in texts:
            fraction = parse_fraction_from_any_text(text)
            if fraction is not None:
                fractions.append(fraction)

        return any(
            current == total and total > 0
            for current, total in fractions
        )
