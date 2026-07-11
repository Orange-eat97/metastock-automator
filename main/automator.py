from __future__ import annotations

from typing import Optional

import sys

from requestReceiver import CliRequestReceiver, ExploreRequest
from guiReceiver import GuiRequestReceiver

from phase2RequestReceiver import CliAddExplorerRequestReceiver, AddExplorerRequest
from compartments.explorer_creator import ExplorerCreator
from compartments.result_capture import (
    ClipboardResultVerifier,
    ExplorationResultCapture,
)
from compartments.result_scraper import (
    ExplorationResultScraper,
)

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

APP_TITLE_RE = r"^Main - MetaStock$"

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
        click_settle_delay=0.03,
        text_settle_delay=0.08,
        key_delay=0.01,
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

    result_scraper = ExplorationResultScraper(
        page_load_delay=0.35,
        max_stale_pages=4,
    )

    clipboard_verifier = ClipboardResultVerifier(
        actions=actions,
        clipboard_timeout=5.0,
        preserve_existing_clipboard=True,
    )

    result_capture = ExplorationResultCapture(
        scraper=result_scraper,
        verifier=clipboard_verifier,
    )

    return ExploreWorkflow(
        app=app,
        console=console,
        strategy_selector=strategy_selector,
        instrument_selector=instrument_selector,
        execution_monitor=execution_monitor,
        result_capture=result_capture,
    )


def run_request(request: ExploreRequest):
    workflow = build_workflow(
        max_execution_wait_sec=(
            request.max_execution_wait_sec
        ),
    )

    return workflow.run(request)


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


def run_add_and_wait_request(
    request: AddExplorerRequest,
):
    """
    Phase 2 split runner for the agent:

    1. create the Explorer in MetaStock;
    2. run the Explorer;
    3. wait until the Exploration Execution window has completed;
    4. leave the result window open for read_current_results().

    This function intentionally does not scrape, verify, or close the
    result window. That second step belongs to read_current_results().
    """
    run_add_request(request)

    workflow = build_workflow(
        max_execution_wait_sec=(
            request.max_execution_wait_sec
        ),
    )

    return workflow.run_until_results_ready(
        request
    )


def read_current_results(
    *,
    close_after_read: bool = True,
):
    """
    Read the currently open completed Exploration Execution window.

    Used by the agent-side read_metastock_explorer_results tool after
    run_add_and_wait_request() has completed.
    """
    workflow = build_workflow(
        max_execution_wait_sec=(
            MAX_EXECUTION_WAIT_SEC
        ),
    )

    main = workflow.app.connect()

    execution_window = (
        workflow.execution_monitor
        .find_execution_window_inside_main(main)
    )

    if execution_window is None:
        raise RuntimeError(
            "No open Exploration Execution result window was found. "
            "Run an Explorer first, wait until it completes, then read "
            "the results."
        )

    try:
        execution_window.set_focus()
    except Exception:
        pass

    result = workflow.result_capture.capture(
        execution_window
    )

    if close_after_read:
        results_window_closed = (
            workflow.execution_monitor
            .close_results_window(
                main=main,
                exec_win=execution_window,
            )
        )

        if not results_window_closed:
            raise RuntimeError(
                "The result was captured, but the Exploration Execution "
                "window could not be closed. The open window may block "
                "later MetaStock operations."
            )

    if result.outcome == "no_matches":
        log(
            "Exploration result read successfully with zero matches."
        )
    else:
        log(
            f"Read and verified {result.matched_count} "
            "MetaStock result rows."
        )

    return result


def run_add_and_run_request(
    request: AddExplorerRequest,
):
    """
    Backward-compatible combined runner.

    This preserves the older CLI/GUI behavior:
    create -> run -> capture -> verify -> close -> return result.
    """
    run_add_request(request)

    workflow = build_workflow(
        max_execution_wait_sec=(
            request.max_execution_wait_sec
        ),
    )

    return workflow.run(request)


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


def print_result_inspection(result) -> None:
    if result is None:
        log(
            "Workflow returned no structured exploration result."
        )
        return

    if not hasattr(result, "to_agent_contract_dict"):
        log(
            "Workflow returned an unsupported result type: "
            f"{type(result).__name__}"
        )
        return

    print(result.to_human_text())

    print("\n=== AGENT JSON CONTRACT ===")
    print(result.to_pretty_json())


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    # Preserve existing GUI behavior.
    # GUI currently runs Phase 1 only.
    if "--gui" in sys.argv:
        # Remove --gui so argparse will not see it later.
        sys.argv = [arg for arg in sys.argv if arg != "--gui"]

        receiver = GuiRequestReceiver(
            run_callback=run_request,
            add_callback=run_add_request,
            add_and_run_callback=run_add_and_run_request,
        )
        receiver.receive()
        return

    mode = pop_mode_from_argv()

    if mode == "run":
        receiver = CliRequestReceiver()
        request = receiver.receive()

        result = run_request(request)
        print_result_inspection(result)
        return

    if mode == "add":
        receiver = CliAddExplorerRequestReceiver()
        request = receiver.receive()
        run_add_request(request)
        return

    if mode == "add-and-run":
        receiver = CliAddExplorerRequestReceiver()
        request = receiver.receive()

        result = run_add_and_run_request(request)
        print_result_inspection(result)
        return

    raise ValueError(f"Unsupported automator mode: {mode!r}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FAILED: {e}")
        raise
