from __future__ import annotations

import argparse
from pathlib import Path

from latestLlmResultReceiver import (
    DEFAULT_LLM_RESULTS_PATH,
    describe_request,
    load_latest_llm_add_explorer_request,
)


def _resolve_add_and_run_callback():
    """
    Tries to import the existing add-and-run callback from automator.py.

    If your automator.py uses a different function name, update the candidates below.

    Common expected names:
        add_and_run_request
        run_add_and_run_request
        add_and_run
    """
    import automator

    candidates = [
        "add_and_run_request",
        "run_add_and_run_request",
        "add_and_run",
        "run_add_explorer_and_explore",
    ]

    for name in candidates:
        fn = getattr(automator, name, None)
        if callable(fn):
            print(f"[LatestLLM] Using automator callback: automator.{name}")
            return fn

    available = [
        name
        for name in dir(automator)
        if not name.startswith("_") and callable(getattr(automator, name))
    ]

    raise RuntimeError(
        "Could not find an add-and-run callback in automator.py.\n"
        "Please open automator.py and check the function passed into "
        "GuiRequestReceiver(add_and_run_callback=...).\n\n"
        f"Tried: {candidates}\n\n"
        f"Callable names found in automator.py:\n{available}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create and run the newest LLM-generated MetaStock Explorer."
    )

    parser.add_argument(
        "--excel-path",
        default=str(DEFAULT_LLM_RESULTS_PATH),
        help="Path to the LLM results Excel file.",
    )

    parser.add_argument(
        "--instruments",
        default="all",
        help=(
            "Instrument search string. Use 'all' for all instruments. "
            "Comma-separated names are supported by the existing parser, e.g. "
            "'SGX,NASDAQ'."
        ),
    )

    parser.add_argument(
        "--max-wait",
        type=int,
        default=300,
        help="Maximum seconds to wait for exploration execution.",
    )

    parser.add_argument(
        "--allow-invalid",
        action="store_true",
        help="Allow loading the latest row even if validation_passed is false.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print the request. Do not open/click MetaStock.",
    )

    args = parser.parse_args()

    request = load_latest_llm_add_explorer_request(
        excel_path=Path(args.excel_path),
        instruments_text=args.instruments,
        max_wait=args.max_wait,
        require_validation_passed=not args.allow_invalid,
    )

    print(describe_request(request))

    if args.dry_run:
        print("[LatestLLM] Dry run complete. MetaStock automation was not started.")
        return

    callback = _resolve_add_and_run_callback()
    callback(request)


if __name__ == "__main__":
    main()