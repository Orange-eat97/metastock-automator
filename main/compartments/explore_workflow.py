from __future__ import annotations

from requestReceiver import ExploreRequest

from ui_interacter.ui_core import log
from compartments.metastock_app import MetaStockApp
from compartments.explore_console import ExploreConsole
from compartments.strategy_selector import StrategySelector
from compartments.instrument_selector import InstrumentSelector
from compartments.execution_monitor import ExecutionMonitor


class ExploreWorkflow:
    """
    High-level orchestrator for Phase 1 Explore automation.

    This class should express the story order only:
    1. connect
    2. open Explore
    3. select strategy
    4. select instruments
    5. start exploration
    6. wait for execution done
    """

    def __init__(
        self,
        app: MetaStockApp,
        console: ExploreConsole,
        strategy_selector: StrategySelector,
        instrument_selector: InstrumentSelector,
        execution_monitor: ExecutionMonitor,
    ):
        self.app = app
        self.console = console
        self.strategy_selector = strategy_selector
        self.instrument_selector = instrument_selector
        self.execution_monitor = execution_monitor

    def run(self, request: ExploreRequest) -> None:
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

        self.console.start(main)

        exec_win = self.execution_monitor.wait_for_window(main)
        self.execution_monitor.wait_done(exec_win)

        log("Done. MetaStock results should now be visible.")