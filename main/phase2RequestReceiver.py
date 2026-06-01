from __future__ import annotations

import re
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from requestReceiver import RequestReceiver, parse_instruments_text


@dataclass(frozen=True)
class ExplorerColumn:
    """
    One column definition.

    slot is user-facing only:
        A, B, C...

    Internally, automation uses column order:
        A = first column tab after Filter
        B = second column tab after Filter
    """
    slot: str
    code_body: str


@dataclass(frozen=True)
class AddExplorerRequest:
    """
    Phase 2 request model.

    Preserves Phase 1 exploration fields so the same object can later be used by:
        - add
        - add-and-run

    For a newly added explorer:
        strategy_name == name
    """

    # Phase 2 creation fields
    name: str
    notes: str
    code_body: str

    # Optional column definitions
    columns: list[ExplorerColumn] = field(default_factory=list)

    # Phase 1-compatible fields
    strategy_name: str = ""
    instrument_names: Optional[list[str]] = None
    select_all_instruments: bool = True
    max_execution_wait_sec: int = 300

    # Future integration control
    run_after_add: bool = False


def parse_column_definitions_text(text: str) -> list[ExplorerColumn]:
    """
    Parses one text file containing column definitions like:

        col A = CLOSE
        col B = VOLUME
        col C = Sum(((H=C) AND (V>Mov(V,256,S))),10)

    Important:
        We do NOT split by comma because MetaStock formulas contain commas.
        We split by markers like:
            col A =
            col B =
            col C =
    """
    raw = text or ""

    pattern = re.compile(
        r"(?im)\bcol\s+([A-Z])\s*=",
    )

    matches = list(pattern.finditer(raw))

    if not matches:
        raise ValueError(
            "No column definitions found. Expected format like: col A = CLOSE"
        )

    columns: list[ExplorerColumn] = []

    for i, match in enumerate(matches):
        slot = match.group(1).upper()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)

        code_body = raw[start:end].strip()

        # Allow users to write:
        #   col A = CLOSE,
        #   col B = VOLUME,
        # But do not remove commas inside formulas.
        if code_body.endswith(","):
            code_body = code_body[:-1].rstrip()

        if not code_body:
            raise ValueError(f"Column {slot} has empty code body.")

        columns.append(
            ExplorerColumn(
                slot=slot,
                code_body=code_body,
            )
        )

    # Sort by slot order A, B, C...
    columns.sort(key=lambda c: ord(c.slot) - ord("A"))

    # Safety check: our UI automation currently maps by order.
    # So we should avoid gaps like A, C without B.
    expected_slots = [chr(ord("A") + i) for i in range(len(columns))]
    actual_slots = [c.slot for c in columns]

    if actual_slots != expected_slots:
        raise ValueError(
            "Column slots must start from A and be continuous because UI automation "
            f"uses tab order. Expected {expected_slots}, got {actual_slots}."
        )

    return columns

class CliAddExplorerRequestReceiver(RequestReceiver):
    """
    Phase 2 CLI receiver.

    Examples:

        Add only:
            python automator.py add --name "#My Test" --notes "test" --code "C > Ref(C,-1)"

        Add with filter code file:
            python automator.py add --name "#My Test" --notes "test" --code-file "..\\test explorer code.txt"

        Add with column A:
            python automator.py add --name "#My Test" --code-file "..\\filter.txt" --column-code-file "..\\column_a.txt"

        Add with columns A and B:
            python automator.py add --name "#My Test" --code-file "..\\filter.txt" --column-code-file "..\\column_a.txt" --column-code-file "..\\column_b.txt"

        Add and run:
            python automator.py add-and-run --name "#My Test" --code-file "..\\filter.txt" --all-instruments
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

        parser.add_argument(
            "--columns-file",
            default=None,
            help=(
                "Path to one text file containing column definitions. "
                "Example format: col A = CLOSE, col B = VOLUME, col C = Mov(C,20,S)"
            ),
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
        # Parse optional column code files
        # ============================================================

        columns: list[ExplorerColumn] = []

        if args.columns_file:
            columns_path = Path(args.columns_file)

            if not columns_path.exists():
                raise FileNotFoundError(f"Columns file does not exist: {columns_path}")

            columns_text = columns_path.read_text(encoding="utf-8")

            if not columns_text.strip():
                raise ValueError(f"Columns file is empty: {columns_path}")

            columns = parse_column_definitions_text(columns_text)

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
            columns=columns,

            # Phase 1-compatible values
            strategy_name=name,
            instrument_names=instrument_names,
            select_all_instruments=select_all,
            max_execution_wait_sec=args.max_wait,

            # Future add-and-run switch
            run_after_add=args.run_after_add,
        )