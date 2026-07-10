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


class ExploreWorkflow:
    """
    High-level MetaStock Explore workflow.

    Story order:
    1. connect
    2. open Explore
    3. select strategy
    4. select instruments
    5. start exploration
    6. wait for execution
    7. scrape result rows
    8. verify scraped instruments against MetaStock Copy output
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

    def run(
        self,
        request: ExploreRequest,
    ) -> ExplorationCaptureResult:
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
            self.execution_monitor.wait_for_window(main)
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

        result = self.result_capture.capture(
            execution_window
        )

        self.execution_monitor.close_results_window(
            main=main,
            exec_win=execution_window,
        )


        if result.outcome == "no_matches":
            log(
                "Exploration completed successfully but returned "
                "zero matches. Explorer revision is required."
            )
        else:
            log(
                f"Captured and verified {result.matched_count} "
                "MetaStock result rows."
            )

        return result