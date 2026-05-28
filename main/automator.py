from __future__ import annotations

from typing import Optional

import sys

from requestReceiver import CliRequestReceiver, ExploreRequest
from guiReceiver import GuiRequestReceiver

from phase2RequestReceiver import CliAddExplorerRequestReceiver, AddExplorerRequest
from compartments.explorer_creator import ExplorerCreator

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
# SHARED COMPOSITION
# ============================================================

def build_shared_components():
    """
    Build shared low-level components used by Phase 1 and Phase 2.

    This avoids duplicating:
        - UiActions
        - ExploreSelectors
        - MetaStockApp
        - ExploreConsole
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

    return actions, selectors, app, console


# ============================================================
# PHASE 1 COMPOSITION ROOT
# ============================================================

def build_workflow(max_execution_wait_sec: int) -> ExploreWorkflow:
    """
    Build and wire all Phase 1 components.

    Preserved from the original automator.py.
    """
    actions, selectors, app, console = build_shared_components()

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
    """
    Phase 1 runner.

    Preserved so GUI mode and old CLI behavior continue to work.
    """
    workflow = build_workflow(
        max_execution_wait_sec=request.max_execution_wait_sec,
    )

    workflow.run(request)


# ============================================================
# PHASE 2 COMPOSITION / RUNNERS
# ============================================================

def run_add_request(request: AddExplorerRequest) -> None:
    """
    Phase 2 runner:
        connect -> open Explore Console -> create explorer

    Does not run exploration.
    """
    actions, selectors, app, console = build_shared_components()

    creator = ExplorerCreator(
        actions=actions,
        selectors=selectors,
    )

    main_window = app.connect()
    console.open(main_window)
    creator.create(main_window, request)


def run_add_and_run_request(request: AddExplorerRequest) -> None:
    """
    Integrated Phase 2 + Phase 1 runner:
        add explorer -> run newly added explorer

    This depends on phase2RequestReceiver setting:
        request.strategy_name = request.name

    So Phase 1 can receive the Phase 2 request object.
    """
    run_add_request(request)

    workflow = build_workflow(
        max_execution_wait_sec=request.max_execution_wait_sec,
    )

    workflow.run(request)


# ============================================================
# CLI MODE ROUTER
# ============================================================

def pop_mode_from_argv() -> str:
    """
    Supports both old and new CLI styles.

    Old Phase 1 style, still valid:
        python automator.py --strategy "#Stoch and RSI" --all-instruments

    New explicit Phase 1:
        python automator.py run --strategy "#Stoch and RSI" --all-instruments

    Phase 2 add only:
        python automator.py add --name "#My Test" --code-file "..\\test explorer code.txt"

    Phase 2 add then run:
        python automator.py add-and-run --name "#My Test" --code-file "..\\test explorer code.txt" --all-instruments
    """
    if len(sys.argv) <= 1:
        return "run"

    first_arg = sys.argv[1].strip().lower()

    if first_arg in {"run", "add", "add-and-run"}:
        # Remove the mode token so the existing argparse receivers
        # can parse the remaining arguments normally.
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        return first_arg

    # Backward compatibility:
    # if first arg is --strategy, --gui, etc., use old Phase 1 behavior.
    return "run"


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    # Preserve existing GUI behavior.
    # GUI currently runs Phase 1 only.
    if "--gui" in sys.argv:
        # Remove --gui so argparse will not see it later.
        sys.argv = [arg for arg in sys.argv if arg != "--gui"]

        receiver = GuiRequestReceiver(run_callback=run_request)
        receiver.receive()
        return

    mode = pop_mode_from_argv()

    if mode == "run":
        receiver = CliRequestReceiver()
        request = receiver.receive()
        run_request(request)
        return

    if mode == "add":
        receiver = CliAddExplorerRequestReceiver()
        request = receiver.receive()
        run_add_request(request)
        return

    if mode == "add-and-run":
        receiver = CliAddExplorerRequestReceiver()
        request = receiver.receive()
        run_add_and_run_request(request)
        return

    raise ValueError(f"Unsupported automator mode: {mode!r}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FAILED: {e}")
        raise