from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from requestReceiver import RequestReceiver, parse_instruments_text


@dataclass(frozen=True)
class AddExplorerRequest:
    """
    Phase 2 request model.

    Preserves Phase 1 exploration fields so the same object can later be used by:
        - add
        - add-and-run
        - run existing explorer

    For a newly added explorer:
        strategy_name == name
    """

    # Phase 2 creation fields
    name: str
    notes: str
    code_body: str

    # Phase 1-compatible fields
    strategy_name: str
    instrument_names: Optional[list[str]] = None
    select_all_instruments: bool = True
    max_execution_wait_sec: int = 300

    # Future integration control
    run_after_add: bool = False


class CliAddExplorerRequestReceiver(RequestReceiver):
    """
    Temporary Phase 2 CLI receiver.

    It extends Phase 1's request logic instead of replacing it.

    Examples:

        Add only:
            python phase2_add_explorer.py --name "#My Test" --notes "test" --code "C > Ref(C,-1)"

        Add with Phase 1 all-instruments logic:
            python phase2_add_explorer.py --name "#My Test" --code-file explorer_code.txt --all-instruments

        Add with specific instruments:
            python phase2_add_explorer.py --name "#My Test" --code-file explorer_code.txt --instrument SGX --instrument NASDAQ

        Add with comma-separated instruments:
            python phase2_add_explorer.py --name "#My Test" --code-file explorer_code.txt --instruments "SGX,NASDAQ"
    """

    def receive(self) -> AddExplorerRequest:
        parser = argparse.ArgumentParser(
            description="Create a new MetaStock explorer from CLI input."
        )

        # ============================================================
        # Phase 2 explorer creation args
        # ============================================================

        parser.add_argument(
            "--name",
            required=True,
            help="Explorer name to create. This also becomes the Phase 1 strategy_name.",
        )

        parser.add_argument(
            "--notes",
            default="",
            help="Explorer notes / description.",
        )

        code_group = parser.add_mutually_exclusive_group(required=True)

        code_group.add_argument(
            "--code",
            help="Explorer filter code body.",
        )

        code_group.add_argument(
            "--code-file",
            help="Path to a text file containing the explorer filter code body.",
        )

        # ============================================================
        # Phase 1 exploration args — preserved from requestReceiver.py
        # ============================================================

        parser.add_argument(
            "--instruments",
            default=None,
            help=(
                "Instrument search string. Use 'all' for all instruments. "
                "Future support: comma-separated names such as 'SGX,NASDAQ'."
            ),
        )

        parser.add_argument(
            "--instrument",
            action="append",
            default=None,
            help=(
                "Instrument/custom list/exchange name to select. "
                "Can be passed multiple times. Kept for compatibility."
            ),
        )

        parser.add_argument(
            "--all-instruments",
            action="store_true",
            help="Select all instruments.",
        )

        parser.add_argument(
            "--max-wait",
            type=int,
            default=300,
            help="Maximum seconds to wait for exploration execution.",
        )

        # ============================================================
        # Future integration option
        # ============================================================

        parser.add_argument(
            "--run-after-add",
            action="store_true",
            help="Create this explorer and then run it using Phase 1 workflow.",
        )

        args = parser.parse_args()

        # ============================================================
        # Validate Phase 2 fields
        # ============================================================

        name = (args.name or "").strip()
        notes = args.notes or ""

        if not name:
            raise ValueError("Explorer name cannot be empty.")

        if args.code_file:
            code_path = Path(args.code_file)

            if not code_path.exists():
                raise FileNotFoundError(f"Code file does not exist: {code_path}")

            code_body = code_path.read_text(encoding="utf-8")
        else:
            code_body = args.code or ""

        if not code_body.strip():
            raise ValueError("Explorer code body cannot be empty.")

        # ============================================================
        # Preserve Phase 1 instrument-selection logic exactly
        # ============================================================

        if args.all_instruments:
            instrument_names = None
            select_all = True
        elif args.instrument:
            instrument_names = args.instrument
            select_all = False
        else:
            instrument_names, select_all = parse_instruments_text(args.instruments)

        if args.max_wait <= 0:
            raise ValueError("--max-wait must be positive.")

        return AddExplorerRequest(
            name=name,
            notes=notes,
            code_body=code_body,

            # Phase 1-compatible values
            strategy_name=name,
            instrument_names=instrument_names,
            select_all_instruments=select_all,
            max_execution_wait_sec=args.max_wait,

            # Future add-and-run switch
            run_after_add=args.run_after_add,
        )