from __future__ import annotations

from automator_service import (
    AutomatorExecutionRequest,
    AutomatorResultReadRequest,
    MetaStockAutomatorService,
)


class FakeCaptureResult:
    def __init__(self, payload):
        self.payload = payload

    def to_agent_contract_dict(self):
        return self.payload


def verified_payload():
    return {
        "schema_version": "1.0",
        "outcome": "matches_found",
        "expected_count": 1,
        "matched_count": 1,
        "has_matches": True,
        "clipboard_verification": {
            "passed": True,
            "expected_count": 1,
            "scraped_count": 1,
            "clipboard_count": 1,
            "missing_from_scrape": [],
            "unexpected_in_scrape": [],
            "clipboard_headers": [],
        },
        "rows": [
            {
                "row_index": 0,
                "instrument_name": (
                    "A SONIC AEROSPACE ORD"
                ),
                "symbol": "D_ASON.SI",
                "column_values": {
                    "A": "0.5500",
                    "B": "0.5300",
                },
            }
        ],
    }


def test_one_service_runs_and_reads_results() -> None:
    run_calls = []
    read_calls = []

    def fake_runner(request):
        run_calls.append(request)

    def fake_reader(*, close_after_read):
        read_calls.append(close_after_read)
        return FakeCaptureResult(
            verified_payload()
        )

    service = MetaStockAutomatorService(
        runner=fake_runner,
        result_reader=fake_reader,
    )

    run_result = service.run_explorer(
        AutomatorExecutionRequest(
            explorer_id="explorer-1",
            name="RSI Test",
            description="",
            filter_code="RSI(14) < 30",
        )
    )

    assert run_result.succeeded is True
    assert (
        run_result.result_available
        is True
    )
    assert len(run_calls) == 1

    read_result = service.read_results(
        AutomatorResultReadRequest(
            explorer_id="explorer-1",
            close_after_read=True,
        )
    )

    assert read_result.succeeded is True
    assert read_result.results is not None
    assert (
        read_result.results.matched_count
        == 1
    )
    assert (
        read_result.results.rows[0].symbol
        == "D_ASON.SI"
    )
    assert read_calls == [True]


def test_bad_verification_returns_failure() -> None:
    payload = verified_payload()
    payload[
        "clipboard_verification"
    ]["passed"] = False

    def fake_reader(*, close_after_read):
        return FakeCaptureResult(payload)

    service = MetaStockAutomatorService(
        runner=lambda request: None,
        result_reader=fake_reader,
    )

    result = service.read_results(
        AutomatorResultReadRequest()
    )

    assert result.succeeded is False
    assert result.results is None
    assert (
        result.diagnostics["error_type"]
        == "ValueError"
    )
