from __future__ import annotations

from requestReceiver import ExploreRequest

from ui_interacter.ui_core import log
from compartments.metastock_app import MetaStockApp
from compartments.explore_console import ExploreConsole
from compartments.strategy_selector import StrategySelector
from compartments.instrument_selector import InstrumentSelector
from compartments.execution_monitor import ExecutionMonitor
from compartments.result_capture import (
    ExplorationCaptureResult,
    ExplorationResultCapture,
)

from pywinauto.base_wrapper import BaseWrapper


class ExploreWorkflow:
    """
    High-level MetaStock Explore workflow.

    Two execution shapes are intentionally supported:

    - run():
      old combined CLI behavior: run, capture, verify, close, return result.

    - run_until_results_ready():
      agent split behavior: run and leave completed results window open.
      A later read_current_results() call captures/verifies/persists.
    """

    def __init__(
        self,
        app: MetaStockApp,
        console: ExploreConsole,
        strategy_selector: StrategySelector,
        instrument_selector: InstrumentSelector,
        execution_monitor: ExecutionMonitor,
        result_capture: ExplorationResultCapture,
    ) -> None:
        self.app = app
        self.console = console
        self.strategy_selector = strategy_selector
        self.instrument_selector = instrument_selector
        self.execution_monitor = execution_monitor
        self.result_capture = result_capture

    def run_until_results_ready(
        self,
        request: ExploreRequest,
    ) -> BaseWrapper:
        """
        Run an Explorer and wait until the Exploration Execution window
        is complete, but do not scrape or close it.

        This is the split workflow required by the agent:
        run_explorer_in_metastock first, read_metastock_explorer_results
        second.
        """
        main = self.app.connect()

        self.console.open(main)

        self.strategy_selector.select(
            main,
            request.strategy_name,
        )

        if request.select_all_instruments:
            self.instrument_selector.ensure_all_selected(main)
        else:
            self.instrument_selector.select_named(
                main,
                request.instrument_names or [],
            )

        self.console.start(main)

        execution_window = (
            self.execution_monitor
            .wait_for_window(main)
        )

        self.execution_monitor.wait_done(
            execution_window
        )

        refreshed_execution_window = (
            self.execution_monitor
            .find_execution_window_inside_main(main)
        )

        if refreshed_execution_window is not None:
            execution_window = refreshed_execution_window

        try:
            execution_window.set_focus()
        except Exception:
            pass

        log(
            "Exploration completed. Result window is ready "
            "for separate result reading."
        )

        return execution_window

    def run(
        self,
        request: ExploreRequest,
    ) -> ExplorationCaptureResult:
        execution_window = (
            self.run_until_results_ready(
                request
            )
        )

        main = self.app.connect()

        result = self.result_capture.capture(
            execution_window
        )

        results_window_closed = (
            self.execution_monitor
            .close_results_window(
                main=main,
                exec_win=execution_window,
            )
        )

        if not results_window_closed:
            raise RuntimeError(
                "The exploration completed and its result was "
                "captured, but the Exploration Execution window "
                "could not be closed. The open window may block "
                "later MetaStock operations."
            )

        if result.outcome == "no_matches":
            log(
                "Exploration completed successfully with zero "
                "matches. No result rows will be returned."
            )
        else:
            log(
                f"Captured and verified {result.matched_count} "
                "MetaStock result rows."
            )

        return result
