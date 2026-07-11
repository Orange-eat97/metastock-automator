from __future__ import annotations

import csv
import io
import re
import time
import json
import re
from typing import Any
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pyperclip
from pywinauto.base_wrapper import BaseWrapper

from compartments.result_scraper import (
    ExplorationResultRow,
    ExplorationResultScraper,
    ExplorationResultSet,
)
from ui_interacter.ui_actions import UiActions
from ui_interacter.ui_core import log, normalize_text, safe_descendants


COPY_BUTTON_AUTOMATION_ID = "BarButtonItemLinkCopyList"

INSTRUMENT_HEADER_NAMES = {
    "instrument",
    "instrument name",
    "instrumentname",
    "security",
    "security name",
    "securityname",
    "stock",
    "stock name",
    "stockname",
}


# ============================================================
# RESULT MODELS
# ============================================================


@dataclass(frozen=True)
class ClipboardVerification:
    passed: bool
    expected_count: int
    scraped_count: int
    clipboard_count: int
    missing_from_scrape: list[str] = field(default_factory=list)
    unexpected_in_scrape: list[str] = field(default_factory=list)
    clipboard_headers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "expected_count": self.expected_count,
            "scraped_count": self.scraped_count,
            "clipboard_count": self.clipboard_count,
            "missing_from_scrape": list(self.missing_from_scrape),
            "unexpected_in_scrape": list(self.unexpected_in_scrape),
            "clipboard_headers": list(self.clipboard_headers),
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> ClipboardVerification:
        return cls(
            passed=bool(payload.get("passed", False)),
            expected_count=int(payload.get("expected_count", 0)),
            scraped_count=int(payload.get("scraped_count", 0)),
            clipboard_count=int(payload.get("clipboard_count", 0)),
            missing_from_scrape=list(
                payload.get("missing_from_scrape") or []
            ),
            unexpected_in_scrape=list(
                payload.get("unexpected_in_scrape") or []
            ),
            clipboard_headers=list(
                payload.get("clipboard_headers") or []
            ),
        )


@dataclass(frozen=True)
class ExplorationCaptureResult:
    """
    Final result produced after:

    1. scraping the MetaStock virtualized result grid;
    2. copying the complete MetaStock result list;
    3. verifying the scraped instrument names against the clipboard.
    """

    outcome: str
    expected_count: int
    headers: dict[int, str] = field(default_factory=dict)
    rows: list[ExplorationResultRow] = field(default_factory=list)
    clipboard_verification: ClipboardVerification | None = None

    @property
    def matched_count(self) -> int:
        return len(self.rows)

    @property
    def has_matches(self) -> bool:
        return self.expected_count > 0

    @property
    def requires_agent_action(self) -> bool:
        """
        A zero-match exploration is a valid completed execution.

        The automator reports the outcome but does not instruct the
        agent to revise, retry, or take another action.
        """
        return False

    @property
    def recommended_next_action(self) -> str | None:
        """
        The automator returns observed execution results only.

        Deciding whether to revise an Explorer belongs to the agent
        or calling application.
        """
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "expected_count": self.expected_count,
            "matched_count": self.matched_count,
            "has_matches": self.has_matches,
            "requires_agent_action": self.requires_agent_action,
            "recommended_next_action": self.recommended_next_action,
            "headers": {
                str(column_index): header
                for column_index, header in self.headers.items()
            },
            "rows": [
                {
                    "row_index": row.row_index,
                    "values_by_column": {
                        str(column_index): value
                        for column_index, value
                        in row.values_by_column.items()
                    },
                    "values_by_name": dict(row.values_by_name),
                }
                for row in self.rows
            ],
            "clipboard_verification": (
                self.clipboard_verification.to_dict()
                if self.clipboard_verification is not None
                else None
            ),
        }

    @classmethod
    def no_matches(cls) -> ExplorationCaptureResult:
        return cls(
            outcome="no_matches",
            expected_count=0,
            headers={},
            rows=[],
            clipboard_verification=None,
        )

    @classmethod
    def matches_found(
        cls,
        *,
        scraped_results: ExplorationResultSet,
        verification: ClipboardVerification,
    ) -> ExplorationCaptureResult:
        return cls(
            outcome="matches_found",
            expected_count=scraped_results.expected_count,
            headers=scraped_results.headers,
            rows=scraped_results.rows,
            clipboard_verification=verification,
        )

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> ExplorationCaptureResult:
        headers = {
            int(column_index): str(header)
            for column_index, header
            in (payload.get("headers") or {}).items()
        }

        rows: list[ExplorationResultRow] = []

        for raw_row in payload.get("rows") or []:
            values_by_column = {
                int(column_index): str(value)
                for column_index, value
                in (
                    raw_row.get("values_by_column") or {}
                ).items()
            }

            values_by_name = {
                str(name): str(value)
                for name, value
                in (
                    raw_row.get("values_by_name") or {}
                ).items()
            }

            rows.append(
                ExplorationResultRow(
                    row_index=int(raw_row["row_index"]),
                    values_by_column=values_by_column,
                    values_by_name=values_by_name,
                )
            )

        raw_verification = payload.get(
            "clipboard_verification"
        )

        verification = (
            ClipboardVerification.from_dict(
                raw_verification
            )
            if raw_verification
            else None
        )

        return cls(
            outcome=str(payload.get("outcome", "")),
            expected_count=int(
                payload.get("expected_count", 0)
            ),
            headers=headers,
            rows=rows,
            clipboard_verification=verification,
        )
    
    def to_agent_contract_dict(self) -> dict[str, Any]:
        """
        Stable result contract for the future agent/tool boundary.

        This intentionally exposes business-level fields:
        - instrument name
        - symbol
        - Explorer column values

        It does not expose pywinauto wrappers or UIA implementation details.
        """
        return {
            "schema_version": "1.0",
            "outcome": self.outcome,
            "expected_count": self.expected_count,
            "matched_count": self.matched_count,
            "has_matches": self.has_matches,
            "requires_agent_action": self.requires_agent_action,
            "recommended_next_action": self.recommended_next_action,
            "clipboard_verification": (
                self.clipboard_verification.to_dict()
                if self.clipboard_verification is not None
                else None
            ),
            "rows": [
                self._row_to_agent_contract(row)
                for row in sorted(
                    self.rows,
                    key=lambda item: item.row_index,
                )
            ],
        }


    def _row_to_agent_contract(
        self,
        row: ExplorationResultRow,
    ) -> dict[str, Any]:
        values_by_name = {
            str(name): str(value)
            for name, value in row.values_by_name.items()
        }

        values_by_column = {
            int(column_index): str(value)
            for column_index, value
            in row.values_by_column.items()
        }

        instrument_name = normalize_text(
            values_by_name.get("instrument_name", "")
        )

        if not instrument_name:
            instrument_name = normalize_text(
                values_by_column.get(0, "")
            )

        symbol = normalize_text(
            values_by_name.get("symbol", "")
        )

        # Resolve Symbol through the header map when it is not already
        # available in values_by_name.
        if not symbol:
            for column_index, header in self.headers.items():
                normalized_header = re.sub(
                    r"[^a-z0-9]+",
                    "",
                    str(header).casefold(),
                )

                if normalized_header == "symbol":
                    symbol = normalize_text(
                        values_by_column.get(
                            int(column_index),
                            "",
                        )
                    )
                    break

        column_values: dict[str, str] = {}

        # Preferred source: named values such as column_A.
        for name, value in values_by_name.items():
            match = re.fullmatch(
                r"(?:column[_\s-]*)?([A-J])",
                name.strip(),
                re.IGNORECASE,
            )

            if match:
                column_values[
                    match.group(1).upper()
                ] = value

        # Resolve through scraper headers when required.
        for column_index, header in self.headers.items():
            match = re.fullmatch(
                r"(?:column[_\s-]*)?([A-J])",
                str(header).strip(),
                re.IGNORECASE,
            )

            if not match:
                continue

            value = values_by_column.get(
                int(column_index)
            )

            if value is not None:
                column_values.setdefault(
                    match.group(1).upper(),
                    value,
                )

        # Final fallback for the observed MetaStock layout:
        # UIA columns 1..10 correspond to Explorer A..J.
        if not column_values:
            for column_index in range(1, 11):
                if column_index not in values_by_column:
                    continue

                column_letter = chr(
                    ord("A") + column_index - 1
                )

                column_values[column_letter] = (
                    values_by_column[column_index]
                )

        return {
            "row_index": row.row_index,
            "instrument_name": instrument_name,
            "symbol": symbol or None,
            "column_values": dict(
                sorted(column_values.items())
            ),
        }


    def to_pretty_json(self) -> str:
        """
        Human-readable JSON using the same structure that will later
        be returned to the agent.
        """
        return json.dumps(
            self.to_agent_contract_dict(),
            indent=2,
            ensure_ascii=False,
        )


    def to_human_text(self) -> str:
        """
        Compact terminal representation of every scraped result.
        """
        payload = self.to_agent_contract_dict()

        lines = [
            "",
            "=" * 72,
            "METASTOCK SCRAPED RESULT",
            "=" * 72,
            f"Outcome:        {payload['outcome']}",
            f"Expected rows:  {payload['expected_count']}",
            f"Scraped rows:   {payload['matched_count']}",
        ]

        verification = payload.get(
            "clipboard_verification"
        )

        if verification is not None:
            lines.extend(
                [
                    (
                        "Clipboard rows: "
                        f"{verification.get('clipboard_count')}"
                    ),
                    (
                        "Verified:       "
                        f"{verification.get('passed')}"
                    ),
                ]
            )

        lines.append("")
        lines.append("ROWS")
        lines.append("-" * 72)

        for row in payload["rows"]:
            column_text = "; ".join(
                f"{letter}={value}"
                for letter, value
                in row["column_values"].items()
            )

            lines.append(
                f"[{row['row_index']:>3}] "
                f"{row.get('symbol') or '<no symbol>'} | "
                f"{row['instrument_name']} | "
                f"{column_text}"
            )

        return "\n".join(lines)


class ResultVerificationError(RuntimeError):
    def __init__(
        self,
        verification: ClipboardVerification,
    ) -> None:
        self.verification = verification

        super().__init__(
            "MetaStock result verification failed. "
            f"Expected={verification.expected_count}, "
            f"scraped={verification.scraped_count}, "
            f"clipboard={verification.clipboard_count}, "
            f"missing_from_scrape="
            f"{verification.missing_from_scrape}, "
            f"unexpected_in_scrape="
            f"{verification.unexpected_in_scrape}"
        )


# ============================================================
# CLIPBOARD VERIFIER
# ============================================================


class ClipboardResultVerifier:
    """
    Uses MetaStock's Copy button as the ground truth for the
    complete instrument list.

    The UIA scraper is responsible for collecting column values.
    This verifier checks that the UIA scraper captured every
    instrument exposed by MetaStock.
    """

    def __init__(
        self,
        actions: UiActions,
        clipboard_timeout: float = 5.0,
        preserve_existing_clipboard: bool = True,
    ) -> None:
        self.actions = actions
        self.clipboard_timeout = clipboard_timeout
        self.preserve_existing_clipboard = (
            preserve_existing_clipboard
        )

    @staticmethod
    def _normalize_symbol(value: str) -> str:
        return normalize_text(value).casefold()

    def verify(
        self,
        *,
        execution_window: BaseWrapper,
        scraped_results: ExplorationResultSet,
    ) -> ClipboardVerification:
        expected_count = scraped_results.expected_count

        if expected_count == 0:
            return ClipboardVerification(
                passed=True,
                expected_count=0,
                scraped_count=0,
                clipboard_count=0,
            )

        existing_clipboard = self._read_clipboard_safely()

        try:
            self._clear_clipboard()

            copy_button = self._find_copy_button(
                execution_window
            )

            self.actions.invoke_or_click(
                copy_button,
                "Copy list to Clipboard",
            )

            clipboard_text = self._wait_for_clipboard_text()

            clipboard_symbols = self._parse_clipboard_symbols(
                clipboard_text=clipboard_text,
            )

        finally:
            if self.preserve_existing_clipboard:
                self._restore_clipboard_safely(
                    existing_clipboard
                )

        scraped_symbols = self._extract_scraped_symbols(
            scraped_results
        )

        clipboard_counter = Counter(
            self._normalize_symbol(symbol)
            for symbol in clipboard_symbols
        )

        scraped_counter = Counter(
            self._normalize_symbol(symbol)
            for symbol in scraped_symbols
        )

        missing_counter = (
            clipboard_counter - scraped_counter
        )

        unexpected_counter = (
            scraped_counter - clipboard_counter
        )

        missing_from_scrape = self._expand_counter(
            missing_counter
        )

        unexpected_in_scrape = self._expand_counter(
            unexpected_counter
        )

        passed = (
            len(scraped_symbols) == expected_count
            and len(clipboard_symbols) == expected_count
            and not missing_from_scrape
            and not unexpected_in_scrape
        )

        verification = ClipboardVerification(
            passed=passed,
            expected_count=expected_count,
            scraped_count=len(scraped_symbols),
            clipboard_count=len(clipboard_symbols),
            missing_from_scrape=missing_from_scrape,
            unexpected_in_scrape=unexpected_in_scrape,
            clipboard_headers=[],
        )

        if passed:
            log(
                "Clipboard verification passed: "
                f"{expected_count} symbols matched."
            )
        else:
            log(
                "Clipboard verification failed: "
                f"expected={expected_count}, "
                f"scraped={len(scraped_symbols)}, "
                f"clipboard={len(clipboard_symbols)}, "
                f"missing={missing_from_scrape}, "
                f"unexpected={unexpected_in_scrape}"
            )

        return verification

    # ========================================================
    # COPY BUTTON
    # ========================================================

    def _find_copy_button(
        self,
        execution_window: BaseWrapper,
    ) -> BaseWrapper:
        fallback_candidates: list[BaseWrapper] = []

        buttons = safe_descendants(
            execution_window,
            control_type="Button",
        )

        for button in buttons:
            try:
                info = button.element_info

                automation_id = normalize_text(
                    info.automation_id or ""
                )

                name = normalize_text(
                    info.name or ""
                )

                help_text = normalize_text(
                    getattr(info, "help_text", "") or ""
                )

                if (
                    automation_id
                    == COPY_BUTTON_AUTOMATION_ID
                ):
                    log(
                        "Found MetaStock Copy button by "
                        f"AutomationId="
                        f"{COPY_BUTTON_AUTOMATION_ID!r}."
                    )
                    return button

                if (
                    name.casefold() == "copy"
                    or help_text.casefold()
                    == "copy list to clipboard"
                ):
                    fallback_candidates.append(button)

            except Exception:
                continue

        if len(fallback_candidates) == 1:
            log(
                "Found MetaStock Copy button through "
                "name/help-text fallback."
            )
            return fallback_candidates[0]

        if len(fallback_candidates) > 1:
            raise RuntimeError(
                "The stable MetaStock Copy selector failed, "
                "and multiple fallback Copy buttons were found."
            )

        raise RuntimeError(
            "Could not find the MetaStock Copy button. "
            f"Expected AutomationId "
            f"{COPY_BUTTON_AUTOMATION_ID!r}."
        )

    # ========================================================
    # SCRAPED INSTRUMENT EXTRACTION
    # ========================================================

    def _extract_scraped_symbols(
        self,
        scraped_results: ExplorationResultSet,
    ) -> list[str]:
        symbol_column_index: int | None = None

        for column_index, header_name in (
            scraped_results.headers.items()
        ):
            normalized_header = self._normalize_header(
                str(header_name)
            )

            if normalized_header == "symbol":
                symbol_column_index = column_index
                break

        if symbol_column_index is None:
            raise RuntimeError(
                "Could not identify the Symbol column in the "
                "scraped MetaStock results. "
                f"Headers={scraped_results.headers}"
            )

        symbols: list[str] = []

        for row in scraped_results.rows:
            symbol = normalize_text(
                row.values_by_column.get(
                    symbol_column_index,
                    "",
                )
            )

            if not symbol:
                symbol = normalize_text(
                    row.values_by_name.get(
                        "symbol",
                        "",
                    )
                )

            if not symbol:
                raise RuntimeError(
                    "A scraped result row is missing its symbol. "
                    f"row_index={row.row_index}, "
                    f"symbol_column_index={symbol_column_index}, "
                    f"values_by_column={row.values_by_column}, "
                    f"values_by_name={row.values_by_name}"
                )

            symbols.append(symbol)

        return symbols

    # ========================================================
    # CLIPBOARD PARSING
    # ========================================================

    def _parse_clipboard_symbols(
        self,
        *,
        clipboard_text: str,
    ) -> list[str]:
        """
        MetaStock Copy currently returns one comma-separated list:

            D_ASON.SI, D_ADSA.SI, D_AJJM.SI

        Newlines are also accepted in case MetaStock changes the
        clipboard formatting.
        """
        cleaned_text = (
            clipboard_text
            .replace("\x00", "")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .strip()
        )

        if not cleaned_text:
            raise RuntimeError(
                "MetaStock Copy returned an empty clipboard."
            )

        raw_items = re.split(
            r"[\n,]+",
            cleaned_text,
        )

        symbols = [
            normalize_text(item)
            for item in raw_items
            if normalize_text(item)
        ]

        if not symbols:
            raise RuntimeError(
                "Could not extract symbols from the MetaStock "
                f"clipboard. Clipboard={cleaned_text[:500]!r}"
            )

        log(
            f"Parsed {len(symbols)} symbols from "
            "the MetaStock clipboard."
        )

        return symbols

    # ========================================================
    # CLIPBOARD ACCESS
    # ========================================================

    def _clear_clipboard(self) -> None:
        last_error: Exception | None = None

        for _ in range(5):
            try:
                pyperclip.copy("")
                return
            except Exception as exc:
                last_error = exc
                time.sleep(0.1)

        raise RuntimeError(
            "Could not clear the Windows clipboard. "
            f"Last error: {last_error}"
        )

    def _wait_for_clipboard_text(self) -> str:
        deadline = time.time() + self.clipboard_timeout
        last_error: Exception | None = None

        while time.time() < deadline:
            try:
                clipboard_text = pyperclip.paste()

                if (
                    isinstance(clipboard_text, str)
                    and clipboard_text.strip()
                ):
                    return clipboard_text

            except Exception as exc:
                last_error = exc

            time.sleep(0.1)

        raise RuntimeError(
            "MetaStock Copy was invoked, but no clipboard "
            "text appeared within "
            f"{self.clipboard_timeout} seconds. "
            f"Last clipboard error: {last_error}"
        )

    @staticmethod
    def _read_clipboard_safely() -> str | None:
        try:
            value = pyperclip.paste()

            if isinstance(value, str):
                return value

        except Exception:
            pass

        return None

    @staticmethod
    def _restore_clipboard_safely(
        previous_value: str | None,
    ) -> None:
        if previous_value is None:
            return

        try:
            pyperclip.copy(previous_value)
        except Exception as exc:
            log(
                "Warning: could not restore the previous "
                f"clipboard contents: {exc}"
            )

    # ========================================================
    # NORMALIZATION
    # ========================================================

    @staticmethod
    def _normalize_header(value: str) -> str:
        return re.sub(
            r"[^a-z0-9]+",
            "",
            value.casefold(),
        )

    @staticmethod
    def _normalize_instrument_name(
        value: str,
    ) -> str:
        return normalize_text(value).casefold()

    @staticmethod
    def _expand_counter(
        counter: Counter[str],
    ) -> list[str]:
        expanded: list[str] = []

        for value, count in sorted(counter.items()):
            expanded.extend([value] * count)

        return expanded


# ============================================================
# CAPTURE COORDINATOR
# ============================================================


class ExplorationResultCapture:
    """
    Coordinates result scraping and clipboard verification.

    It deliberately does not:
    - implement UIA grid paging;
    - parse UIA result cells;
    - persist results;
    - access Supabase;
    - call the RAG service.

    Those responsibilities belong to:
    - ExplorationResultScraper;
    - the application persistence layer.
    """

    def __init__(
        self,
        scraper: ExplorationResultScraper,
        verifier: ClipboardResultVerifier,
    ) -> None:
        self.scraper = scraper
        self.verifier = verifier

    def capture(
        self,
        execution_window: BaseWrapper,
    ) -> ExplorationCaptureResult:
        scraped_results = self.scraper.scrape(
            execution_window
        )

        if not scraped_results.has_matches:
            log(
                "Exploration completed successfully but "
                "returned zero matches."
            )

            return ExplorationCaptureResult.no_matches()

        verification = self.verifier.verify(
            execution_window=execution_window,
            scraped_results=scraped_results,
        )

        if not verification.passed:
            raise ResultVerificationError(
                verification
            )

        log(
            "MetaStock result capture completed: "
            f"{scraped_results.matched_count} rows were "
            "scraped and verified."
        )

        return ExplorationCaptureResult.matches_found(
            scraped_results=scraped_results,
            verification=verification,
        )