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
    Receives user intent and converts it into a validated ExploreRequest.

    It should not know how to click MetaStock.
    It should not know UIA selectors.
    It should not parse strategy formulas.
    """

    def receive(self) -> ExploreRequest:
        raise NotImplementedError


def parse_instruments_text(instruments_text: Optional[str]) -> tuple[Optional[list[str]], bool]:
    """
    Converts a UI/CLI instruments string into:
        (instrument_names, select_all_instruments)

    Current supported behavior:
        "", "all", "*" -> all instruments

    Future behavior:
        "SGX"
        "SGX, NASDAQ"
        "AAPL, MSFT"
    """
    raw = (instruments_text or "").strip()

    if not raw or raw.lower() in {"all", "all-instruments", "*"}:
        return None, True

    names = [part.strip() for part in raw.split(",") if part.strip()]

    if not names:
        return None, True

    return names, False


class CliRequestReceiver(RequestReceiver):
    def receive(self) -> ExploreRequest:
        parser = argparse.ArgumentParser(
            description="Run MetaStock Phase 1 Explore automation."
        )

        parser.add_argument(
            "--strategy",
            required=True,
            help="Explorer strategy keyword/name to search and select.",
        )

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

        args = parser.parse_args()

        if args.all_instruments:
            instrument_names = None
            select_all = True
        elif args.instrument:
            instrument_names = args.instrument
            select_all = False
        else:
            instrument_names, select_all = parse_instruments_text(args.instruments)

        return ExploreRequest(
            strategy_name=args.strategy,
            instrument_names=instrument_names,
            select_all_instruments=select_all,
            max_execution_wait_sec=args.max_wait,
        )