# result_scraper.py

from __future__ import annotations

from asyncio import timeout
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from pywinauto.base_wrapper import BaseWrapper
from pywinauto.keyboard import send_keys

from ui_interacter.ui_core import (
    log,
    normalize_text,
    safe_descendants,
)


# ============================================================
# UIA NAME PATTERNS
# ============================================================

RESULTS_TAB_RE = re.compile(
    r"^Results\s*\(\s*(?P<count>\d+)\s*\)$",
    re.IGNORECASE,
)

CELL_NAME_RE = re.compile(
    r"^Row\s+(?P<row>\d+),\s*"
    r"Column\s+(?P<column>\d+):\s*"
    r"(?P<value>.*)$",
    re.IGNORECASE,
)

COLUMN_VALUE_HEADER_RE = re.compile(
    r"^ColumnValues\[(?P<index>\d+)\]$",
    re.IGNORECASE,
)


# ============================================================
# RESULT MODELS
# ============================================================


@dataclass(frozen=True)
class ExplorationResultRow:
    """
    One scraped MetaStock result row.

    values_by_column:
        Raw UIA column index -> displayed value.

    values_by_name:
        Human-readable field name -> displayed value.

    Example:

        values_by_column = {
            0: "A SONIC AEROSPACE ORD",
            1: "0.5500",
            2: "0.5300",
            11: "D_ASON.SI",
        }

        values_by_name = {
            "instrument_name": "A SONIC AEROSPACE ORD",
            "column_A": "0.5500",
            "column_B": "0.5300",
            "symbol": "D_ASON.SI",
        }
    """

    row_index: int
    values_by_column: dict[int, str]
    values_by_name: dict[str, str]


@dataclass(frozen=True)
class ExplorationResultSet:
    """
    Complete result returned by the UIA scraper.
    """

    expected_count: int
    headers: dict[int, str]
    rows: list[ExplorationResultRow] = field(
        default_factory=list
    )

    @property
    def matched_count(self) -> int:
        return len(self.rows)

    @property
    def has_matches(self) -> bool:
        return self.expected_count > 0

    def to_records(self) -> list[dict[str, Any]]:
        """
        Convert rows into a JSON-serializable representation.
        """
        records: list[dict[str, Any]] = []

        for row in self.rows:
            record: dict[str, Any] = {
                "row_index": row.row_index,
            }

            record.update(row.values_by_name)
            records.append(record)

        return records


# ============================================================
# RESULT SCRAPER
# ============================================================


class ExplorationResultScraper:
    """
    Scrape MetaStock's virtualized WPF result DataGrid.

    MetaStock does not expose every result row at once. Only rows
    currently materialized in the visible DataGrid viewport appear
    in the UIA tree.

    The scraper therefore:

    1. waits for Results (N) to be published through UIA;
    2. waits for the lower result DataGrid;
    3. moves to the first result row;
    4. collects currently materialized cells;
    5. pages through the grid;
    6. merges cells by row and column index;
    7. verifies that every expected row was collected.

    Fixed long delays are avoided. State is polled at short
    intervals and each wait returns as soon as the UI is ready.
    """

    def __init__(
        self,
        page_load_delay: float = 0.03,
        max_stale_pages: int = 4,
        result_ready_timeout: float = 3.0,
        page_change_timeout: float = 0.5,
        poll_interval: float = 0.04,
    ) -> None:
        # Backward compatibility:
        # older composition code may still pass page_load_delay=0.35.
        # Cap it so an old value does not reintroduce long waits.
        self.event_dispatch_delay = min(
            max(page_load_delay, 0.01),
            0.05,
        )

        self.max_stale_pages = max_stale_pages
        self.result_ready_timeout = result_ready_timeout
        self.page_change_timeout = page_change_timeout
        self.poll_interval = poll_interval

    # ========================================================
    # PUBLIC ENTRY POINT
    # ========================================================

    def scrape(
        self,
        execution_window: BaseWrapper,
    ) -> ExplorationResultSet:
        """
        Scrape all rows from the completed Exploration Execution
        window.
        """
        expected_count = self._wait_for_result_count(
            execution_window=execution_window,
            timeout=self.result_ready_timeout,
            poll_interval=self.poll_interval,
        )

        log(
            "MetaStock result count detected: "
            f"{expected_count}"
        )

        if expected_count == 0:
            return ExplorationResultSet(
                expected_count=0,
                headers={},
                rows=[],
            )

        grid = self._wait_for_results_grid(
            execution_window=execution_window,
            expected_count=expected_count,
            timeout=self.result_ready_timeout,
            poll_interval=self.poll_interval,
        )

        headers = self._read_headers(grid)

        log(f"Result headers: {headers}")

        # row index -> column index -> displayed value
        collected: dict[int, dict[int, str]] = {}

        self._focus_grid(grid)
        self._move_to_first_row(grid)

        expected_row_indices = set(
            range(expected_count)
        )

        stale_pages = 0

        # Generous safety bound. The normal Page Down path moves one
        # viewport at a time. The fallback path may move one row at a time.
        maximum_iterations = max(
            expected_count * 3,
            150,
        )

        for page_number in range(maximum_iterations):
            self._collect_materialized_cells(
                grid=grid,
                collected=collected,
            )

            collected_indices = set(collected)

            cell_count = sum(
                len(values)
                for values in collected.values()
            )

            visible_rows = self._visible_row_indices(
                grid
            )

            if visible_rows:
                visible_range = (
                    f"{min(visible_rows)}-"
                    f"{max(visible_rows)}"
                )
            else:
                visible_range = "<none>"

            log(
                f"Result scrape page {page_number + 1}: "
                f"rows={len(collected_indices)}/"
                f"{expected_count}, "
                f"cells={cell_count}, "
                f"visible={visible_range}"
            )

            if expected_row_indices.issubset(
                collected_indices
            ):
                break

            moved = self._page_down(grid)

            if moved:
                stale_pages = 0
                continue

            stale_pages += 1

            log(
                "Result grid did not move. "
                f"Unchanged attempts="
                f"{stale_pages}/{self.max_stale_pages}"
            )

            if stale_pages >= self.max_stale_pages:
                log(
                    "Result paging stopped because neither "
                    "Page Down nor the one-row fallback moved "
                    "the result grid."
                )
                break

        # Final Ctrl+End attempt for the last partially visible
        # group of rows.
        if not expected_row_indices.issubset(
            set(collected)
        ):
            before_rows = self._visible_row_indices(
                grid
            )

            self._focus_grid(grid)

            send_keys(
                "^{END}",
                pause=0.01,
            )

            self._wait_for_grid_change(
                grid=grid,
                previous_rows=before_rows,
                timeout=self.page_change_timeout,
            )

            self._collect_materialized_cells(
                grid=grid,
                collected=collected,
            )

        missing_rows = sorted(
            expected_row_indices - set(collected)
        )

        if missing_rows:
            raise RuntimeError(
                "Could not scrape every MetaStock result row. "
                f"Expected={expected_count}, "
                f"collected={len(collected)}, "
                f"missing_rows={missing_rows}"
            )

        rows = self._build_rows(
            collected=collected,
            headers=headers,
        )

        return ExplorationResultSet(
            expected_count=expected_count,
            headers=headers,
            rows=rows,
        )

    # ========================================================
    # RESULT SURFACE DISCOVERY
    # ========================================================

    def _wait_for_result_count(
        self,
        *,
        execution_window: BaseWrapper,
        timeout: float,
        poll_interval: float,
    ) -> int:
        """
        Wait until MetaStock publishes a UIA name such as:

            Results (77)

        WPF can paint this caption before it publishes the
        corresponding UIA element, so a single descendant scan
        is not reliable.
        """
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            try:
                # Fast path: actual tab items.
                tab_items = (
                    execution_window.descendants(
                        control_type="TabItem"
                    )
                )

                count = (
                    self._read_result_count_from_controls(
                        tab_items
                    )
                )

                if count is not None:
                    log(
                        "Results tab published through UIA: "
                        f"Results ({count})"
                    )
                    return count

                # WPF fallback:
                # during a tree refresh, the caption may briefly
                # appear under a different control type.
                all_controls = (
                    execution_window.descendants()
                )

                count = (
                    self._read_result_count_from_controls(
                        all_controls
                    )
                )

                if count is not None:
                    log(
                        "Results count found through UIA "
                        f"fallback: Results ({count})"
                    )
                    return count

            except Exception as exc:
                last_error = exc

            time.sleep(poll_interval)

        self._log_result_surface_snapshot(
            execution_window
        )

        raise RuntimeError(
            "MetaStock completed visually, but no Results (N) "
            "control appeared through UIA within "
            f"{timeout:.1f} seconds. "
            f"Last UIA error: {last_error}"
        )

    def _read_result_count_from_controls(
        self,
        controls: list[BaseWrapper],
    ) -> Optional[int]:
        for control in controls:
            for text in self._control_text_candidates(
                control
            ):
                match = RESULTS_TAB_RE.fullmatch(
                    text
                )

                if match is not None:
                    return int(
                        match.group("count")
                    )

        return None

    def _wait_for_results_grid(
        self,
        *,
        execution_window: BaseWrapper,
        expected_count: int,
        timeout: float,
        poll_interval: float,
    ) -> BaseWrapper:
        """
        Locate the lower Explorer result grid.

        The Exploration Execution window contains more than one
        DataGrid. The result grid is identified by headers such as:

            InstrumentName
            ColumnValues[0]
            ColumnValues[1]
            Symbol
        """
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            try:
                controls = (
                    execution_window.descendants()
                )

                candidates: list[
                    tuple[int, int, BaseWrapper]
                ] = []

                for control in controls:
                    try:
                        info = control.element_info

                        control_type = normalize_text(
                            info.control_type or ""
                        )

                        class_name = normalize_text(
                            info.class_name or ""
                        )

                        combined = (
                            f"{control_type} "
                            f"{class_name}"
                        ).casefold()

                        if (
                            control_type != "DataGrid"
                            and "datagrid" not in combined
                        ):
                            continue

                        try:
                            descendants = (
                                control.descendants()
                            )
                        except Exception:
                            descendants = []

                        header_score = 0
                        visible_cell_count = 0

                        for descendant in descendants:
                            parsed = self._extract_cell(
                                descendant
                            )

                            if parsed is not None:
                                visible_cell_count += 1

                            try:
                                descendant_info = (
                                    descendant.element_info
                                )

                                descendant_type = (
                                    normalize_text(
                                        descendant_info
                                        .control_type
                                        or ""
                                    )
                                )

                                descendant_name = (
                                    normalize_text(
                                        descendant_info.name
                                        or ""
                                    )
                                )

                                if (
                                    descendant_type
                                    != "HeaderItem"
                                ):
                                    continue

                                if (
                                    descendant_name
                                    == "InstrumentName"
                                ):
                                    header_score += 100

                                elif COLUMN_VALUE_HEADER_RE.fullmatch(
                                    descendant_name
                                ):
                                    header_score += 20

                                elif (
                                    descendant_name
                                    == "Symbol"
                                ):
                                    header_score += 20

                            except Exception:
                                continue

                        candidates.append(
                            (
                                header_score,
                                visible_cell_count,
                                control,
                            )
                        )

                    except Exception:
                        continue

                candidates.sort(
                    key=lambda item: (
                        item[0],
                        item[1],
                    ),
                    reverse=True,
                )

                if candidates:
                    (
                        header_score,
                        visible_cell_count,
                        result_grid,
                    ) = candidates[0]

                    # InstrumentName provides a strong distinction
                    # from the upper execution summary grid.
                    if (
                        header_score >= 100
                        and visible_cell_count > 0
                    ):
                        log(
                            "Result DataGrid ready: "
                            f"header_score={header_score}, "
                            f"visible_cells="
                            f"{visible_cell_count}, "
                            f"expected_rows={expected_count}"
                        )

                        return result_grid

            except Exception as exc:
                last_error = exc

            time.sleep(poll_interval)

        self._log_result_surface_snapshot(
            execution_window
        )

        raise RuntimeError(
            "Results (N) was available, but the lower "
            "MetaStock result DataGrid did not become ready "
            f"within {timeout:.1f} seconds. "
            f"Expected rows={expected_count}. "
            f"Last UIA error: {last_error}"
        )

    # ========================================================
    # HEADER READING
    # ========================================================

    def _read_headers(
        self,
        grid: BaseWrapper,
    ) -> dict[int, str]:
        """
        Observed MetaStock column mapping:

            UIA column 0
                InstrumentName

            UIA column 1
                ColumnValues[0] / Explorer Column A

            UIA column 2
                ColumnValues[1] / Explorer Column B

            ...

            UIA column 10
                ColumnValues[9] / Explorer Column J

            final UIA column
                Symbol
        """
        headers: dict[int, str] = {}

        maximum_explorer_column_index = -1
        symbol_header_found = False

        for control in safe_descendants(grid):
            try:
                info = control.element_info

                control_type = normalize_text(
                    info.control_type or ""
                )

                if control_type != "HeaderItem":
                    continue

                technical_name = normalize_text(
                    info.name or ""
                )

                if technical_name == "InstrumentName":
                    headers[0] = "instrument_name"
                    continue

                column_match = (
                    COLUMN_VALUE_HEADER_RE.fullmatch(
                        technical_name
                    )
                )

                if column_match is not None:
                    zero_based_index = int(
                        column_match.group("index")
                    )

                    # UIA column 0 is InstrumentName, so Explorer
                    # column A begins at UIA column 1.
                    uia_column_index = (
                        zero_based_index + 1
                    )

                    display_name = (
                        self._find_header_display_name(
                            control
                        )
                    )

                    if not display_name:
                        display_name = chr(
                            ord("A")
                            + zero_based_index
                        )

                    headers[uia_column_index] = (
                        f"column_{display_name}"
                    )

                    maximum_explorer_column_index = max(
                        maximum_explorer_column_index,
                        zero_based_index,
                    )

                    continue

                if technical_name == "Symbol":
                    symbol_header_found = True

            except Exception:
                continue

        if 0 not in headers:
            headers[0] = "instrument_name"

        if symbol_header_found:
            # Instrument occupies column 0.
            # Explorer A starts at column 1.
            # Symbol follows the last ColumnValues[n] field.
            symbol_column_index = (
                maximum_explorer_column_index + 2
            )

            headers[symbol_column_index] = "symbol"

        return headers

    def _find_header_display_name(
        self,
        header: BaseWrapper,
    ) -> Optional[str]:
        """
        A technical header such as ColumnValues[0] may contain
        a Text child named A.
        """
        for child in safe_descendants(header):
            try:
                info = child.element_info

                control_type = normalize_text(
                    info.control_type or ""
                )

                if control_type != "Text":
                    continue

                for value in (
                    self._control_text_candidates(
                        child
                    )
                ):
                    if value:
                        return value

            except Exception:
                continue

        return None

    # ========================================================
    # CELL COLLECTION
    # ========================================================

    def _collect_materialized_cells(
        self,
        *,
        grid: BaseWrapper,
        collected: dict[int, dict[int, str]],
    ) -> None:
        """
        Add every currently materialized cell to the collected
        row/column map.
        """
        try:
            descendants = grid.descendants()
        except Exception:
            descendants = []

        for control in descendants:
            parsed = self._extract_cell(
                control
            )

            if parsed is None:
                continue

            row_index, column_index, value = parsed

            collected.setdefault(
                row_index,
                {},
            )

            collected[row_index][column_index] = value

    def _extract_cell(
        self,
        control: BaseWrapper,
    ) -> Optional[tuple[int, int, str]]:
        """
        Parse UIA names such as:

            Row 40, Column 0: SOUTHERN ARCHIPELAGO ORD
            Row 40, Column 1: 0.5500
            Row 40, Column 11: D_SOUE.SI
        """
        for candidate in (
            self._control_text_candidates(control)
        ):
            match = CELL_NAME_RE.fullmatch(
                candidate
            )

            if match is None:
                continue

            return (
                int(match.group("row")),
                int(match.group("column")),
                match.group("value").strip(),
            )

        return None

    # ========================================================
    # KEYBOARD FOCUS AND VIRTUALIZED PAGING
    # ========================================================

    def _focus_grid(
        self,
        grid: BaseWrapper,
    ) -> None:
        """
        Prefer focusing a materialized result cell.

        MetaStock result cells are keyboard-focusable, while the
        WPF DataGrid wrapper does not always retain keyboard focus.
        """
        cells: list[
            tuple[int, int, BaseWrapper]
        ] = []

        try:
            descendants = grid.descendants()
        except Exception:
            descendants = []

        for control in descendants:
            parsed = self._extract_cell(
                control
            )

            if parsed is None:
                continue

            row_index, column_index, _ = parsed

            cells.append(
                (
                    row_index,
                    column_index,
                    control,
                )
            )

        cells.sort(
            key=lambda item: (
                item[0],
                item[1],
            )
        )

        for _, _, cell in cells:
            try:
                cell.set_focus()

                time.sleep(
                    self.event_dispatch_delay
                )

                return

            except Exception:
                continue

        try:
            grid.set_focus()

            time.sleep(
                self.event_dispatch_delay
            )

            return

        except Exception:
            pass

        try:
            grid.click_input()

            time.sleep(
                self.event_dispatch_delay
            )

            return

        except Exception as exc:
            raise RuntimeError(
                "Could not focus the MetaStock result grid "
                "or a materialized result cell: "
                f"{exc}"
            ) from exc

    def _move_to_first_row(
        self,
        grid: BaseWrapper,
    ) -> None:
        """
        Move the virtualized result grid to row zero.
        """
        self._focus_grid(grid)

        send_keys(
            "^{HOME}",
            pause=0.01,
        )

        deadline = (
            time.monotonic()
            + self.page_change_timeout
        )

        while time.monotonic() < deadline:
            rows = self._visible_row_indices(
                grid
            )

            if rows and min(rows) == 0:
                return

            time.sleep(0.03)

    def _page_down(
        self,
        grid: BaseWrapper,
    ) -> bool:
        """
        Advance the virtualized result grid.

        Important:
        Do not call _focus_grid() before every Page Down. That method
        focuses the first visible cell and resets keyboard navigation.

        The existing keyboard focus is preserved for the normal path.
        If Page Down fails, focus the bottom visible row and move down
        one row to force WPF virtualization.
        """
        before_rows = self._visible_row_indices(
            grid
        )

        if not before_rows:
            return False

        # Normal path: preserve the current focused cell.
        send_keys(
            "{PGDN}",
            pause=0.01,
        )

        if self._wait_for_grid_change(
            grid=grid,
            previous_rows=before_rows,
            timeout=self.page_change_timeout,
        ):
            return True

        # Fallback:
        # MetaStock occasionally ignores Page Down even though a result
        # cell previously had keyboard focus. Focus the last visible row
        # and press Down once to materialize the next row.
        bottom_cell = self._find_bottom_visible_cell(
            grid
        )

        if bottom_cell is None:
            return False

        try:
            bottom_cell.set_focus()
            time.sleep(self.event_dispatch_delay)
        except Exception:
            try:
                bottom_cell.click_input()
                time.sleep(self.event_dispatch_delay)
            except Exception:
                return False

        fallback_before_rows = (
            self._visible_row_indices(grid)
        )

        send_keys(
            "{DOWN}",
            pause=0.01,
        )

        return self._wait_for_grid_change(
            grid=grid,
            previous_rows=fallback_before_rows,
            timeout=self.page_change_timeout,
        )

    def _find_bottom_visible_cell(
        self,
        grid: BaseWrapper,
    ) -> Optional[BaseWrapper]:
        """
        Find a cell in the last currently materialized row.

        Prefer column 0 because the instrument-name cell is known to
        be keyboard-focusable.
        """
        cells: list[
            tuple[int, int, BaseWrapper]
        ] = []

        try:
            descendants = grid.descendants()
        except Exception:
            descendants = []

        for control in descendants:
            parsed = self._extract_cell(
                control
            )

            if parsed is None:
                continue

            row_index, column_index, _ = parsed

            cells.append(
                (
                    row_index,
                    column_index,
                    control,
                )
            )

        if not cells:
            return None

        bottom_row_index = max(
            row_index
            for row_index, _, _ in cells
        )

        bottom_row_cells = [
            (
                column_index,
                control,
            )
            for row_index, column_index, control
            in cells
            if row_index == bottom_row_index
        ]

        # Prefer the instrument-name cell in column 0.
        for column_index, control in bottom_row_cells:
            if column_index == 0:
                return control

        bottom_row_cells.sort(
            key=lambda item: item[0]
        )

        return bottom_row_cells[0][1]

    def _visible_row_indices(
        self,
        grid: BaseWrapper,
    ) -> set[int]:
        """
        Return the row indices currently materialized in UIA.
        """
        row_indices: set[int] = set()

        try:
            descendants = grid.descendants()
        except Exception:
            return row_indices

        for control in descendants:
            parsed = self._extract_cell(
                control
            )

            if parsed is None:
                continue

            row_index, _, _ = parsed
            row_indices.add(row_index)

        return row_indices

    def _wait_for_grid_change(
        self,
        *,
        grid: BaseWrapper,
        previous_rows: set[int],
        timeout: float,
    ) -> bool:
        """
        Return True as soon as WPF publishes a different visible row set.

        Return False when the viewport does not change before timeout.
        """
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            current_rows = (
                self._visible_row_indices(grid)
            )

            if (
                current_rows
                and current_rows != previous_rows
            ):
                return True

            time.sleep(0.03)

        return False
    
    # ========================================================
    # ROW CONSTRUCTION
    # ========================================================

    def _build_rows(
        self,
        *,
        collected: dict[int, dict[int, str]],
        headers: dict[int, str],
    ) -> list[ExplorationResultRow]:
        rows: list[ExplorationResultRow] = []

        for row_index in sorted(collected):
            values_by_column = dict(
                sorted(
                    collected[row_index].items()
                )
            )

            values_by_name: dict[str, str] = {}

            for (
                column_index,
                value,
            ) in values_by_column.items():
                header = headers.get(
                    column_index,
                    f"column_index_{column_index}",
                )

                values_by_name[header] = value

            rows.append(
                ExplorationResultRow(
                    row_index=row_index,
                    values_by_column=(
                        values_by_column
                    ),
                    values_by_name=values_by_name,
                )
            )

        return rows

    # ========================================================
    # GENERAL HELPERS
    # ========================================================

    @staticmethod
    def _control_text_candidates(
        control: BaseWrapper,
    ) -> list[str]:
        """
        Return every useful accessible text representation for
        a control.
        """
        values: list[str] = []

        try:
            name = normalize_text(
                control.element_info.name or ""
            )

            if name:
                values.append(name)

        except Exception:
            pass

        try:
            text = normalize_text(
                control.window_text() or ""
            )

            if text and text not in values:
                values.append(text)

        except Exception:
            pass

        return values

    def _log_result_surface_snapshot(
        self,
        execution_window: BaseWrapper,
    ) -> None:
        """
        Print result-related UIA controls when discovery fails.
        """
        log(
            "UIA result-surface diagnostic snapshot:"
        )

        try:
            controls = (
                execution_window.descendants()
            )
        except Exception as exc:
            log(
                "  Could not enumerate descendants: "
                f"{exc}"
            )
            return

        logged = 0

        for control in controls:
            try:
                info = control.element_info

                control_type = normalize_text(
                    info.control_type or ""
                )

                name = normalize_text(
                    info.name or ""
                )

                text = normalize_text(
                    control.window_text() or ""
                )

                class_name = normalize_text(
                    info.class_name or ""
                )

                searchable = (
                    f"{control_type} "
                    f"{name} "
                    f"{text} "
                    f"{class_name}"
                ).casefold()

                if not any(
                    token in searchable
                    for token in (
                        "result",
                        "datagrid",
                        "instrumentname",
                        "columnvalues",
                    )
                ):
                    continue

                log(
                    "  "
                    f"type={control_type!r}, "
                    f"name={name!r}, "
                    f"text={text!r}, "
                    f"class={class_name!r}"
                )

                logged += 1

                if logged >= 40:
                    log(
                        "  Diagnostic output truncated "
                        "after 40 controls."
                    )
                    break

            except Exception:
                continue

        if logged == 0:
            log(
                "  No result-related controls are "
                "currently exposed through UIA."
            )