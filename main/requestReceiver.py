from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import argparse

@dataclass(frozen=True)
class ExploreRequest:
    strategy_name: str
    instrument_names: Optional[list[str]] = None
    select_all_instruments: bool = True
    max_execution_wait_sec: int = 300

class RequestReceiver:
    """
    Receives user intent from CLI/config/defaults and converts it into
    a validated ExploreRequest.

    It should not know how to click MetaStock.
    It should not know UIA selectors.
    It should not parse strategy formulas.
    """

    def receive(self) -> ExploreRequest:
        raise NotImplementedError
    
class CliRequestReceiver(RequestReceiver):
    def receive(self) -> ExploreRequest:
        parser = argparse.ArgumentParser(
            description="Run MetaStock Phase 1 Explore automation."
        )

        parser.add_argument(
            "--strategy",
            required=True,
            help="Explorer strategy name to search and select.",
        )

        parser.add_argument(
            "--instrument",
            action="append",
            default=None,
            help=(
                "Instrument/custom list/exchange name to select. "
                "Can be passed multiple times."
            ),
        )

        parser.add_argument(
            "--all-instruments",
            action="store_true",
            help="Select all instruments. Mutually exclusive with --instrument.",
        )

        parser.add_argument(
            "--max-wait",
            type=int,
            default=300,
            help="Maximum seconds to wait for exploration execution.",
        )

        args = parser.parse_args()

        if args.instrument and args.all_instruments:
            raise ValueError(
                "Use either --instrument or --all-instruments, not both."
            )

        select_all = args.all_instruments or not args.instrument

        return ExploreRequest(
            strategy_name=args.strategy,
            instrument_names=args.instrument,
            select_all_instruments=select_all,
            max_execution_wait_sec=args.max_wait,
        )