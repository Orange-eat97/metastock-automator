from __future__ import annotations

from typing import Optional

import sys

from requestReceiver import CliRequestReceiver, ExploreRequest
from guiReceiver import GuiRequestReceiver

from ui_interacter.ui_core import log
from ui_interacter.ui_actions import UiActions
from ui_interacter.explore_selectors import ExploreSelectors

from compartments.metastock_app import MetaStockApp
from compartments.explore_console import ExploreConsole
from compartments.strategy_selector import StrategySelector
from compartments.instrument_selector import InstrumentSelector
from compartments.execution_monitor import ExecutionMonitor
from compartments.explore_workflow import ExploreWorkflow


# ============================================================
# CONFIG
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
# COMPOSITION ROOT
# ============================================================

def build_workflow(max_execution_wait_sec: int) -> ExploreWorkflow:
    """
    Build and wire all Phase 1 components.

    This function is the composition root:
    it decides which concrete implementations the workflow uses.
    """
    actions = UiActions(
        short_delay=SHORT_DELAY,
        medium_delay=MEDIUM_DELAY,
    )

    selectors = ExploreSelectors()

    app = MetaStockApp(
        app_title_re=APP_TITLE_RE,
    )

    console = ExploreConsole(
        actions=actions,
        selectors=selectors,
        explore_load_timeout=EXPLORE_LOAD_TIMEOUT,
        allow_start_fallback_click=ALLOW_START_FALLBACK_CLICK,
        start_fallback_absolute_xy=START_FALLBACK_ABSOLUTE_XY,
    )

    strategy_selector = StrategySelector(
        actions=actions,
        selectors=selectors,
        search_filter_timeout=SEARCH_FILTER_TIMEOUT,
    )

    instrument_selector = InstrumentSelector(
        actions=actions,
        selectors=selectors,
        medium_delay=MEDIUM_DELAY,
    )

    execution_monitor = ExecutionMonitor(
        max_execution_wait_sec=max_execution_wait_sec,
        poll_interval=EXECUTION_POLL_INTERVAL,
    )

    return ExploreWorkflow(
        app=app,
        console=console,
        strategy_selector=strategy_selector,
        instrument_selector=instrument_selector,
        execution_monitor=execution_monitor,
    )


def run_request(request: ExploreRequest) -> None:
    workflow = build_workflow(
        max_execution_wait_sec=request.max_execution_wait_sec,
    )

    workflow.run(request)


def main() -> None:
    if "--gui" in sys.argv:
        # Remove --gui so argparse will not see it later.
        sys.argv = [arg for arg in sys.argv if arg != "--gui"]

        receiver = GuiRequestReceiver(run_callback=run_request)
        receiver.receive()
        return

    receiver = CliRequestReceiver()
    request = receiver.receive()
    run_request(request)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FAILED: {e}")
        raise
