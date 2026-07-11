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

    The primitive UI boundaries are intentionally separate:

    - select_existing_explorer():
      open Explore, select one existing Explorer, select instruments.

    - run_selected_until_results_ready():
      assume the Explorer/instruments are already selected, click Start,
      wait for completion, and leave the result window open.

    Legacy combined helpers may call these two primitives, but agent-facing
    service methods must not hide create/select/run coupling inside one
    Automator service call.
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

    def select_existing_explorer(
        self,
        request: ExploreRequest,
    ) -> BaseWrapper:
        """
        Select an existing Explorer and instruments.

        This method does not create or run anything.
        """
        main = self.app.connect()
        self.console.open(main)
        self.strategy_selector.select(main, request.strategy_name)

        if request.select_all_instruments:
            self.instrument_selector.ensure_all_selected(main)
        else:
            self.instrument_selector.select_named(
                main,
                request.instrument_names or [],
            )

        log("Explorer and instruments selected. No execution has started.")
        return main

    def run_selected_until_results_ready(
        self,
        request: ExploreRequest,
    ) -> BaseWrapper:
        """
        Run the currently selected Explorer.

        This method assumes selection has already happened. It does not create
        or select an Explorer. It starts execution, waits for completion, and
        leaves the completed result window open.
        """
        main = self.app.connect()
        self.console.start(main)

        execution_window = self.execution_monitor.wait_for_window(main)
        self.execution_monitor.wait_done(execution_window)

        refreshed_execution_window = (
            self.execution_monitor.find_execution_window_inside_main(main)
        )
        if refreshed_execution_window is not None:
            execution_window = refreshed_execution_window

        try:
            execution_window.set_focus()
        except Exception:
            pass

        log(
            "Selected Explorer completed. Result window is ready "
            "for separate result reading."
        )
        return execution_window

    def run_until_results_ready(
        self,
        request: ExploreRequest,
    ) -> BaseWrapper:
        """
        Legacy convenience wrapper: select existing Explorer, then run it.

        Agent-facing services should call select_existing_explorer() and
        run_selected_until_results_ready() separately instead of using this
        wrapper.
        """
        self.select_existing_explorer(request)
        return self.run_selected_until_results_ready(request)

    def run(
        self,
        request: ExploreRequest,
    ) -> ExplorationCaptureResult:
        """
        Legacy combined CLI behavior:
        select -> run -> capture -> verify -> close -> return result.
        """
        execution_window = self.run_until_results_ready(request)
        main = self.app.connect()

        result = self.result_capture.capture(execution_window)

        results_window_closed = self.execution_monitor.close_results_window(
            main=main,
            exec_win=execution_window,
        )

        if not results_window_closed:
            raise RuntimeError(
                "The exploration completed and its result was captured, but "
                "the Exploration Execution window could not be closed. The "
                "open window may block later MetaStock operations."
            )

        if result.outcome == "no_matches":
            log(
                "Exploration completed successfully with zero matches. "
                "No result rows will be returned."
            )
        else:
            log(f"Captured and verified {result.matched_count} MetaStock result rows.")

        return result
