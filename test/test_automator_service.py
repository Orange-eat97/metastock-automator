from __future__ import annotations

from phase2RequestReceiver import AddExplorerRequest
from automator_service import (
    AutomatorExecutionColumn,
    AutomatorExecutionRequest,
    MetaStockAutomatorService,
)


def test_service_maps_request_and_calls_existing_workflow() -> None:
    captured: list[AddExplorerRequest] = []

    def fake_runner(request: AddExplorerRequest) -> None:
        captured.append(request)

    service = MetaStockAutomatorService(runner=fake_runner)
    result = service.run_explorer(
        AutomatorExecutionRequest(
            explorer_id="explorer-1",
            name="RSI Test",
            description="RSI below 30.",
            filter_code="RSI(14) < 30",
            columns=[
                AutomatorExecutionColumn(
                    col_letter="A",
                    col_code="RSI(14)",
                )
            ],
            select_all_instruments=True,
            max_execution_wait_sec=120,
        )
    )

    assert result.succeeded is True
    assert len(captured) == 1
    mapped = captured[0]
    assert mapped.name == "RSI Test"
    assert mapped.strategy_name == "RSI Test"
    assert mapped.notes == "RSI below 30."
    assert mapped.code_body == "RSI(14) < 30"
    assert mapped.select_all_instruments is True
    assert mapped.instrument_names is None
    assert mapped.max_execution_wait_sec == 120
    assert mapped.run_after_add is True
    assert mapped.columns[0].slot == "A"
    assert mapped.columns[0].code_body == "RSI(14)"


def test_service_returns_failed_result_when_workflow_raises() -> None:
    def failing_runner(request: AddExplorerRequest) -> None:
        raise RuntimeError("MetaStock is not open")

    service = MetaStockAutomatorService(runner=failing_runner)
    result = service.run_explorer(
        AutomatorExecutionRequest(
            explorer_id="explorer-1",
            name="RSI Test",
            description="",
            filter_code="RSI(14) < 30",
        )
    )

    assert result.succeeded is False
    assert "MetaStock is not open" in result.message
    assert result.diagnostics["error_type"] == "RuntimeError"
