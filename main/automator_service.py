from __future__ import annotations

import io
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from automator import run_add_and_run_request
from phase2RequestReceiver import AddExplorerRequest, ExplorerColumn


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
    columns: list[AutomatorExecutionColumn] = field(default_factory=list)
    instruments: list[str] | None = None
    select_all_instruments: bool = True
    max_execution_wait_sec: int = 300


@dataclass(frozen=True)
class AutomatorExecutionResult:
    succeeded: bool
    message: str
    started_at: str
    finished_at: str
    diagnostics: dict[str, Any] = field(default_factory=dict)


class MetaStockAutomatorService:
    """Stable workflow-level boundary around the existing Automator flow."""

    def __init__(
        self,
        runner: Callable[[AddExplorerRequest], Any] | None = None,
    ) -> None:
        self._runner = runner or run_add_and_run_request

    def run_explorer(
        self,
        request: AutomatorExecutionRequest,
    ) -> AutomatorExecutionResult:
        normalized = self._normalize_request(request)
        add_request = self._to_add_explorer_request(normalized)

        started_at = self._utc_now()
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()

        try:
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                workflow_result = self._runner(add_request)

            diagnostics: dict[str, Any] = {
                "explorer_id": normalized.explorer_id,
                "explorer_name": normalized.name,
                "stdout_text": stdout_buffer.getvalue(),
                "stderr_text": stderr_buffer.getvalue(),
            }

            # Preserve compatibility with old runners and test doubles that
            # return None instead of an ExplorationCaptureResult.
            if workflow_result is None:
                return AutomatorExecutionResult(
                    succeeded=True,
                    message=(
                        f"Explorer {normalized.name!r} was created and run "
                        "in MetaStock. No structured result was returned."
                    ),
                    started_at=started_at,
                    finished_at=self._utc_now(),
                    diagnostics=diagnostics,
                )

            if not hasattr(workflow_result, "to_dict"):
                raise TypeError(
                    "The MetaStock workflow returned an unsupported result type: "
                    f"{type(workflow_result).__name__}. "
                    "Expected an object with a to_dict() method."
                )

            exploration_result = ( workflow_result.to_agent_contract_dict() )
            diagnostics["exploration_result"] = ( exploration_result )

            outcome = exploration_result.get("outcome")
            matched_count = exploration_result.get("matched_count", 0)

            if outcome == "no_matches":
                message = (
                    f"Explorer {normalized.name!r} ran successfully but matched "
                    "no instruments. The Explorer should be revised."
                )

            elif outcome == "matches_found":
                clipboard_verification = (
                    exploration_result.get("clipboard_verification") or {}
                )

                if clipboard_verification.get("passed") is not True:
                    raise RuntimeError(
                        "MetaStock returned results, but clipboard verification "
                        "did not pass."
                    )

                message = (
                    f"Explorer {normalized.name!r} was created and run in "
                    f"MetaStock. Captured and verified {matched_count} "
                    "matched instruments."
                )

            else:
                raise RuntimeError(
                    "The MetaStock workflow returned an unknown outcome: "
                    f"{outcome!r}."
                )

            return AutomatorExecutionResult(
                succeeded=True,
                message=message,
                started_at=started_at,
                finished_at=self._utc_now(),
                diagnostics=diagnostics,
            )

        except Exception as exc:
            return AutomatorExecutionResult(
                succeeded=False,
                message=f"MetaStock execution failed: {exc}",
                started_at=started_at,
                finished_at=self._utc_now(),
                diagnostics={
                    "explorer_id": normalized.explorer_id,
                    "explorer_name": normalized.name,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "traceback": traceback.format_exc(),
                    "stdout_text": stdout_buffer.getvalue(),
                    "stderr_text": stderr_buffer.getvalue(),
                },
            )

    def _normalize_request(
        self,
        request: AutomatorExecutionRequest,
    ) -> AutomatorExecutionRequest:
        explorer_id = self._required_text(request.explorer_id, "explorer_id")
        name = self._required_text(request.name, "name")
        filter_code = self._required_text(request.filter_code, "filter_code")
        description = str(request.description or "")

        if request.max_execution_wait_sec <= 0:
            raise ValueError("max_execution_wait_sec must be positive.")

        columns: list[AutomatorExecutionColumn] = []
        for item in request.columns:
            letter = self._required_text(
                item.col_letter,
                "columns[].col_letter",
            ).upper()
            code = self._required_text(item.col_code, "columns[].col_code")

            if len(letter) != 1 or not letter.isalpha():
                raise ValueError(
                    "Each column letter must be one alphabetic character."
                )

            columns.append(
                AutomatorExecutionColumn(
                    col_letter=letter,
                    col_code=code,
                )
            )

        columns.sort(key=lambda column: column.col_letter)
        expected = [chr(ord("A") + index) for index in range(len(columns))]
        actual = [column.col_letter for column in columns]

        if actual != expected:
            raise ValueError(
                "Column letters must start at A and be continuous. "
                f"Expected {expected}, got {actual}."
            )

        if request.select_all_instruments:
            instruments = None
            select_all = True
        else:
            instruments = [
                self._required_text(value, "instruments[]")
                for value in (request.instruments or [])
            ]
            if not instruments:
                raise ValueError(
                    "At least one instrument is required when "
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
            select_all_instruments=select_all,
            max_execution_wait_sec=request.max_execution_wait_sec,
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
            instrument_names=request.instruments,
            select_all_instruments=request.select_all_instruments,
            max_execution_wait_sec=request.max_execution_wait_sec,
            run_after_add=True,
        )

    @staticmethod
    def _required_text(value: Any, field_name: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError(f"{field_name} is required.")
        return cleaned

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()
