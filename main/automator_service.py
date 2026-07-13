from __future__ import annotations

import io
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from automator import (
    create_explorer_request,
    read_current_results,
    run_selected_explorer_request,
    select_explorer_request,
)

from phase2RequestReceiver import (
    AddExplorerRequest,
    ExplorerColumn,
)


RESULT_SCHEMA_VERSION = "1.0"


# ============================================================
# EXECUTION CONTRACT
# ============================================================


@dataclass(frozen=True)
class AutomatorExecutionColumn:
    col_letter: str
    col_code: str


@dataclass(frozen=True)
class AutomatorExecutionRequest:
    explorer_id: str
    name: str
    description: str
    filter_code: str
    columns: list[AutomatorExecutionColumn] = field(
        default_factory=list
    )
    instruments: list[str] | None = None
    select_all_instruments: bool = True
    max_execution_wait_sec: int = 300


@dataclass(frozen=True)
class AutomatorExecutionResult:
    succeeded: bool
    message: str
    started_at: str
    finished_at: str
    result_available: bool = False
    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================
# RESULT-READING CONTRACT
# ============================================================


@dataclass(frozen=True)
class AutomatorClipboardVerification:
    passed: bool
    expected_count: int
    scraped_count: int
    clipboard_count: int
    missing_from_scrape: list[str] = field(
        default_factory=list
    )
    unexpected_in_scrape: list[str] = field(
        default_factory=list
    )
    clipboard_headers: list[str] = field(
        default_factory=list
    )

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> AutomatorClipboardVerification:
        return cls(
            passed=bool(payload.get("passed", False)),
            expected_count=int(
                payload.get("expected_count", 0)
            ),
            scraped_count=int(
                payload.get("scraped_count", 0)
            ),
            clipboard_count=int(
                payload.get("clipboard_count", 0)
            ),
            missing_from_scrape=[
                str(value)
                for value in (
                    payload.get(
                        "missing_from_scrape"
                    )
                    or []
                )
            ],
            unexpected_in_scrape=[
                str(value)
                for value in (
                    payload.get(
                        "unexpected_in_scrape"
                    )
                    or []
                )
            ],
            clipboard_headers=[
                str(value)
                for value in (
                    payload.get("clipboard_headers")
                    or []
                )
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "expected_count": self.expected_count,
            "scraped_count": self.scraped_count,
            "clipboard_count": self.clipboard_count,
            "missing_from_scrape": list(
                self.missing_from_scrape
            ),
            "unexpected_in_scrape": list(
                self.unexpected_in_scrape
            ),
            "clipboard_headers": list(
                self.clipboard_headers
            ),
        }


@dataclass(frozen=True)
class AutomatorResultRow:
    row_index: int
    instrument_name: str
    symbol: str | None
    column_values: dict[str, str] = field(
        default_factory=dict
    )

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> AutomatorResultRow:
        return cls(
            row_index=int(
                payload.get("row_index", 0)
            ),
            instrument_name=str(
                payload.get("instrument_name")
                or ""
            ),
            symbol=(
                str(payload["symbol"])
                if payload.get("symbol")
                is not None
                else None
            ),
            column_values={
                str(letter): str(value)
                for letter, value in (
                    payload.get("column_values")
                    or {}
                ).items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_index": self.row_index,
            "instrument_name": self.instrument_name,
            "symbol": self.symbol,
            "column_values": dict(
                self.column_values
            ),
        }


@dataclass(frozen=True)
class AutomatorExplorerResults:
    schema_version: str
    outcome: str
    expected_count: int
    matched_count: int
    has_matches: bool
    clipboard_verification: (
        AutomatorClipboardVerification | None
    ) = None
    rows: list[AutomatorResultRow] = field(
        default_factory=list
    )

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> AutomatorExplorerResults:
        schema_version = str(
            payload.get("schema_version") or ""
        )

        if schema_version != RESULT_SCHEMA_VERSION:
            raise ValueError(
                "Unsupported MetaStock result schema "
                f"version: {schema_version!r}. "
                f"Expected {RESULT_SCHEMA_VERSION!r}."
            )

        outcome = str(
            payload.get("outcome") or ""
        )

        if outcome not in {
            "matches_found",
            "no_matches",
        }:
            raise ValueError(
                "Unsupported MetaStock result outcome: "
                f"{outcome!r}."
            )

        rows = [
            AutomatorResultRow.from_dict(item)
            for item in (
                payload.get("rows") or []
            )
            if isinstance(item, dict)
        ]

        raw_verification = payload.get(
            "clipboard_verification"
        )
        verification = (
            AutomatorClipboardVerification
            .from_dict(raw_verification)
            if isinstance(
                raw_verification,
                dict,
            )
            else None
        )

        result = cls(
            schema_version=schema_version,
            outcome=outcome,
            expected_count=int(
                payload.get(
                    "expected_count",
                    0,
                )
            ),
            matched_count=int(
                payload.get(
                    "matched_count",
                    len(rows),
                )
            ),
            has_matches=bool(
                payload.get(
                    "has_matches",
                    bool(rows),
                )
            ),
            clipboard_verification=(
                verification
            ),
            rows=rows,
        )

        result.validate()
        return result

    def validate(self) -> None:
        if self.matched_count != len(self.rows):
            raise ValueError(
                "MetaStock matched_count does not "
                "equal the number of result rows: "
                f"{self.matched_count} != "
                f"{len(self.rows)}."
            )

        if self.outcome == "no_matches":
            if (
                self.expected_count != 0
                or self.matched_count != 0
                or self.rows
            ):
                raise ValueError(
                    "A no_matches result must have "
                    "zero expected and matched rows."
                )

            return

        if (
            self.expected_count
            != self.matched_count
        ):
            raise ValueError(
                "MetaStock result row count mismatch: "
                f"expected={self.expected_count}, "
                f"matched={self.matched_count}."
            )

        if (
            self.clipboard_verification is None
            or (
                self.clipboard_verification
                .passed
                is not True
            )
        ):
            raise ValueError(
                "A matches_found result must include "
                "a passed clipboard verification."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "outcome": self.outcome,
            "expected_count": (
                self.expected_count
            ),
            "matched_count": (
                self.matched_count
            ),
            "has_matches": self.has_matches,
            "clipboard_verification": (
                self.clipboard_verification
                .to_dict()
                if (
                    self.clipboard_verification
                    is not None
                )
                else None
            ),
            "rows": [
                row.to_dict()
                for row in self.rows
            ],
        }


@dataclass(frozen=True)
class AutomatorResultReadRequest:
    explorer_id: str | None = None
    close_after_read: bool = True


@dataclass(frozen=True)
class AutomatorResultReadResult:
    succeeded: bool
    message: str
    started_at: str
    finished_at: str
    explorer_id: str | None = None
    results: AutomatorExplorerResults | None = None
    diagnostics: dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================
# SINGLE PUBLIC AUTOMATOR SERVICE
# ============================================================


class MetaStockAutomatorService:
    """
    Stable workflow-level boundary for MetaStock automation.

    Public capabilities:

    - create_explorer():
      create an Explorer without selecting or running it;

    - select_explorer():
      select an existing Explorer and its instruments;

    - run_selected_explorer():
      run the currently selected Explorer and leave its completed
      result window ready for reading;

    - read_results():
      scrape, normalize, clipboard-verify, and optionally close
      the currently open result window.

    The legacy composite run_explorer() method remains present only
    as a disabled compatibility boundary.

    UIA wrappers, selectors, and clipboard implementation details
    stay behind this service.
    """

    def __init__(
        self,
        result_reader: (
            Callable[..., Any] | None
        ) = None,
    ) -> None:
        self._result_reader = (
            result_reader
            or read_current_results
        )
  
    def _call_execution_boundary(
        self,
        request: AutomatorExecutionRequest,
        *,
        boundary: str,
        runner: Callable[
            [AddExplorerRequest],
            Any,
        ],
        success_message: str,
        result_available: bool,
    ) -> AutomatorExecutionResult:
        """
        Execute one auditable MetaStock boundary.

        Each public method supplies exactly one deterministic runner:
        create, select, or run selected.
        """
        normalized = (
            self._normalize_execution_request(
                request
            )
        )
        add_request = (
            self._to_add_explorer_request(
                normalized
            )
        )

        started_at = self._utc_now()
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()

        try:
            with (
                redirect_stdout(stdout_buffer),
                redirect_stderr(stderr_buffer),
            ):
                runner(add_request)

            return AutomatorExecutionResult(
                succeeded=True,
                message=success_message.format(
                    explorer_name=normalized.name
                ),
                started_at=started_at,
                finished_at=self._utc_now(),
                result_available=result_available,
                diagnostics={
                    "boundary": boundary,
                    "explorer_id": (
                        normalized.explorer_id
                    ),
                    "explorer_name": (
                        normalized.name
                    ),
                    "result_available": (
                        result_available
                    ),
                    "stdout_text": (
                        stdout_buffer.getvalue()
                    ),
                    "stderr_text": (
                        stderr_buffer.getvalue()
                    ),
                },
            )

        except Exception as exc:
            return AutomatorExecutionResult(
                succeeded=False,
                message=(
                    f"{boundary} failed: {exc}"
                ),
                started_at=started_at,
                finished_at=self._utc_now(),
                result_available=False,
                diagnostics={
                    "boundary": boundary,
                    "explorer_id": (
                        normalized.explorer_id
                    ),
                    "explorer_name": (
                        normalized.name
                    ),
                    "result_available": False,
                    "error_type": (
                        type(exc).__name__
                    ),
                    "error_message": str(exc),
                    "traceback": (
                        traceback.format_exc()
                    ),
                    "stdout_text": (
                        stdout_buffer.getvalue()
                    ),
                    "stderr_text": (
                        stderr_buffer.getvalue()
                    ),
                },
            )


    def create_explorer(
        self,
        request: AutomatorExecutionRequest,
    ) -> AutomatorExecutionResult:
        return self._call_execution_boundary(
            request,
            boundary="create_explorer",
            runner=create_explorer_request,
            success_message=(
                "Explorer {explorer_name!r} was "
                "created in MetaStock. It was not "
                "selected or run."
            ),
            result_available=False,
        )


    def select_explorer(
        self,
        request: AutomatorExecutionRequest,
    ) -> AutomatorExecutionResult:
        return self._call_execution_boundary(
            request,
            boundary="select_explorer",
            runner=select_explorer_request,
            success_message=(
                "Explorer {explorer_name!r} and "
                "instruments were selected in "
                "MetaStock. Execution has not started."
            ),
            result_available=False,
        )


    def run_selected_explorer(
        self,
        request: AutomatorExecutionRequest,
    ) -> AutomatorExecutionResult:
        return self._call_execution_boundary(
            request,
            boundary="run_selected_explorer",
            runner=run_selected_explorer_request,
            success_message=(
                "The currently selected Explorer was "
                "run in MetaStock. Its completed "
                "results are ready to be read."
            ),
            result_available=True,
        )


    def run_explorer(
        self,
        request: AutomatorExecutionRequest,
    ) -> AutomatorExecutionResult:
        """
        The former composite create/select/run operation is deliberately
        disabled for agent use.
        """
        started_at = self._utc_now()

        return AutomatorExecutionResult(
            succeeded=False,
            message=(
                "Composite run_explorer() is disabled. "
                "Call create_explorer(), "
                "select_explorer(), and "
                "run_selected_explorer() as separate "
                "service methods."
            ),
            started_at=started_at,
            finished_at=self._utc_now(),
            result_available=False,
            diagnostics={
                "boundary": "run_explorer",
                "disabled_reason": (
                    "create/select/run must remain "
                    "separate"
                ),
            },
        )

    def read_results(
        self,
        request: AutomatorResultReadRequest,
    ) -> AutomatorResultReadResult:
        started_at = self._utc_now()
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()

        try:
            with (
                redirect_stdout(stdout_buffer),
                redirect_stderr(stderr_buffer),
            ):
                capture_result = (
                    self._result_reader(
                        close_after_read=(
                            request.close_after_read
                        ),
                    )
                )

            if not hasattr(
                capture_result,
                "to_agent_contract_dict",
            ):
                raise TypeError(
                    "The MetaStock result reader "
                    "returned an unsupported object: "
                    f"{type(capture_result).__name__}."
                )

            payload = (
                capture_result
                .to_agent_contract_dict()
            )
            results = (
                AutomatorExplorerResults
                .from_dict(payload)
            )

            if (
                results.outcome
                == "no_matches"
            ):
                message = (
                    "MetaStock results were read "
                    "successfully. The Explorer "
                    "matched no instruments."
                )
            else:
                message = (
                    "MetaStock results were read "
                    "and verified successfully: "
                    f"{results.matched_count} "
                    "matched instruments."
                )

            return AutomatorResultReadResult(
                succeeded=True,
                message=message,
                started_at=started_at,
                finished_at=self._utc_now(),
                explorer_id=request.explorer_id,
                results=results,
                diagnostics={
                    "close_after_read": (
                        request.close_after_read
                    ),
                    "stdout_text": (
                        stdout_buffer.getvalue()
                    ),
                    "stderr_text": (
                        stderr_buffer.getvalue()
                    ),
                },
            )

        except Exception as exc:
            return AutomatorResultReadResult(
                succeeded=False,
                message=(
                    "MetaStock result reading "
                    f"failed: {exc}"
                ),
                started_at=started_at,
                finished_at=self._utc_now(),
                explorer_id=request.explorer_id,
                results=None,
                diagnostics={
                    "close_after_read": (
                        request.close_after_read
                    ),
                    "error_type": (
                        type(exc).__name__
                    ),
                    "error_message": str(exc),
                    "traceback": (
                        traceback.format_exc()
                    ),
                    "stdout_text": (
                        stdout_buffer.getvalue()
                    ),
                    "stderr_text": (
                        stderr_buffer.getvalue()
                    ),
                },
            )

    def _normalize_execution_request(
        self,
        request: AutomatorExecutionRequest,
    ) -> AutomatorExecutionRequest:
        explorer_id = self._required_text(
            request.explorer_id,
            "explorer_id",
        )
        name = self._required_text(
            request.name,
            "name",
        )
        filter_code = self._required_text(
            request.filter_code,
            "filter_code",
        )
        description = str(
            request.description or ""
        )

        if request.max_execution_wait_sec <= 0:
            raise ValueError(
                "max_execution_wait_sec must "
                "be positive."
            )

        columns: list[
            AutomatorExecutionColumn
        ] = []

        for item in request.columns:
            letter = self._required_text(
                item.col_letter,
                "columns[].col_letter",
            ).upper()
            code = self._required_text(
                item.col_code,
                "columns[].col_code",
            )

            if (
                len(letter) != 1
                or not letter.isalpha()
            ):
                raise ValueError(
                    "Each column letter must be "
                    "one alphabetic character."
                )

            columns.append(
                AutomatorExecutionColumn(
                    col_letter=letter,
                    col_code=code,
                )
            )

        columns.sort(
            key=lambda column: (
                column.col_letter
            )
        )

        expected = [
            chr(ord("A") + index)
            for index in range(
                len(columns)
            )
        ]
        actual = [
            column.col_letter
            for column in columns
        ]

        if actual != expected:
            raise ValueError(
                "Column letters must start at A "
                "and be continuous. "
                f"Expected {expected}, "
                f"got {actual}."
            )

        if request.select_all_instruments:
            instruments = None
            select_all = True
        else:
            instruments = [
                self._required_text(
                    value,
                    "instruments[]",
                )
                for value in (
                    request.instruments or []
                )
            ]

            if not instruments:
                raise ValueError(
                    "At least one instrument is "
                    "required when "
                    "select_all_instruments is false."
                )

            select_all = False

        return AutomatorExecutionRequest(
            explorer_id=explorer_id,
            name=name,
            description=description,
            filter_code=filter_code,
            columns=columns,
            instruments=instruments,
            select_all_instruments=(
                select_all
            ),
            max_execution_wait_sec=(
                request.max_execution_wait_sec
            ),
        )

    def _to_add_explorer_request(
        self,
        request: AutomatorExecutionRequest,
    ) -> AddExplorerRequest:
        return AddExplorerRequest(
            name=request.name,
            notes=request.description,
            code_body=request.filter_code,
            columns=[
                ExplorerColumn(
                    slot=column.col_letter,
                    code_body=column.col_code,
                )
                for column in request.columns
            ],
            strategy_name=request.name,
            instrument_names=(
                request.instruments
            ),
            select_all_instruments=(
                request.select_all_instruments
            ),
            max_execution_wait_sec=(
                request.max_execution_wait_sec
            ),
            run_after_add=True,
        )

    @staticmethod
    def _required_text(
        value: Any,
        field_name: str,
    ) -> str:
        cleaned = str(value or "").strip()

        if not cleaned:
            raise ValueError(
                f"{field_name} is required."
            )

        return cleaned

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()