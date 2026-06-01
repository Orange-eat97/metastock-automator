from __future__ import annotations

import queue
import sys
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from requestReceiver import ExploreRequest, parse_instruments_text
from phase2RequestReceiver import (
    AddExplorerRequest,
    parse_column_definitions_text,
)


class QueueWriter:
    """
    Redirects print/log output into a thread-safe queue.
    Tkinter will read the queue from the main UI thread.
    """

    def __init__(self, output_queue: queue.Queue[str]) -> None:
        self.output_queue = output_queue

    def write(self, text: str) -> None:
        if text:
            self.output_queue.put(text)

    def flush(self) -> None:
        pass


class GuiRequestReceiver:
    """
    Desktop UI for MetaStock automation.

    It does not click MetaStock directly.
    It only creates request objects and passes them to callbacks.

    Supported modes:
        - run existing explorer
        - add explorer only
        - add explorer and run
    """

    MODE_RUN = "run"
    MODE_ADD = "add"
    MODE_ADD_AND_RUN = "add-and-run"

    def __init__(
        self,
        run_callback,
        add_callback=None,
        add_and_run_callback=None,
    ) -> None:
        self.run_callback = run_callback
        self.add_callback = add_callback
        self.add_and_run_callback = add_and_run_callback

        self.output_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.root = tk.Tk()
        self.root.title("MetaStock Automator")
        self.root.geometry("860x700")
        self.root.minsize(760, 620)

        # Mode
        self.mode_var = tk.StringVar(value=self.MODE_RUN)

        # Shared / Phase 1 fields
        self.strategy_var = tk.StringVar(value="#Stoch and RSI")
        self.instruments_var = tk.StringVar(value="all")
        self.max_wait_var = tk.StringVar(value="300")

        # Phase 2 fields
        self.notes_var = tk.StringVar(value="")
        self.filter_code_file_var = tk.StringVar(value="")
        self.columns_file_var = tk.StringVar(value="")

        self.status_var = tk.StringVar(value="Ready")

        self._build_ui()
        self._on_mode_changed()
        self._poll_output_queue()

    def receive(self) -> None:
        self.root.mainloop()

    # ============================================================
    # UI
    # ============================================================

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        title = ttk.Label(
            main,
            text="MetaStock Automator",
            font=("Segoe UI", 16, "bold"),
        )
        title.pack(anchor="w", pady=(0, 12))

        # ========================================================
        # Mode selector
        # ========================================================

        mode_frame = ttk.LabelFrame(main, text="Mode", padding=10)
        mode_frame.pack(fill="x", pady=(0, 12))

        ttk.Radiobutton(
            mode_frame,
            text="Run existing explorer",
            variable=self.mode_var,
            value=self.MODE_RUN,
            command=self._on_mode_changed,
        ).pack(side="left", padx=(0, 16))

        ttk.Radiobutton(
            mode_frame,
            text="Add explorer only",
            variable=self.mode_var,
            value=self.MODE_ADD,
            command=self._on_mode_changed,
        ).pack(side="left", padx=(0, 16))

        ttk.Radiobutton(
            mode_frame,
            text="Add explorer and run",
            variable=self.mode_var,
            value=self.MODE_ADD_AND_RUN,
            command=self._on_mode_changed,
        ).pack(side="left")

        # ========================================================
        # Form
        # ========================================================

        form = ttk.Frame(main)
        form.pack(fill="x")

        ttk.Label(form, text="Explorer / strategy name").grid(
            row=0, column=0, sticky="w", pady=6
        )
        self.strategy_entry = ttk.Entry(form, textvariable=self.strategy_var)
        self.strategy_entry.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=6)

        ttk.Label(form, text="Instruments").grid(
            row=1, column=0, sticky="w", pady=6
        )
        self.instruments_entry = ttk.Entry(form, textvariable=self.instruments_var)
        self.instruments_entry.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=6)

        ttk.Label(form, text="Max wait seconds").grid(
            row=2, column=0, sticky="w", pady=6
        )
        self.max_wait_entry = ttk.Entry(form, textvariable=self.max_wait_var, width=12)
        self.max_wait_entry.grid(row=2, column=1, sticky="w", padx=(12, 0), pady=6)

        ttk.Label(form, text="Notes").grid(
            row=3, column=0, sticky="w", pady=6
        )
        self.notes_entry = ttk.Entry(form, textvariable=self.notes_var)
        self.notes_entry.grid(row=3, column=1, sticky="ew", padx=(12, 0), pady=6)

        ttk.Label(form, text="Filter code file").grid(
            row=4, column=0, sticky="w", pady=6
        )
        self.filter_file_entry = ttk.Entry(form, textvariable=self.filter_code_file_var)
        self.filter_file_entry.grid(row=4, column=1, sticky="ew", padx=(12, 0), pady=6)

        ttk.Label(form, text="Columns file").grid(
            row=5, column=0, sticky="w", pady=6
        )
        self.columns_file_entry = ttk.Entry(form, textvariable=self.columns_file_var)
        self.columns_file_entry.grid(row=5, column=1, sticky="ew", padx=(12, 0), pady=6)

        form.columnconfigure(1, weight=1)

        hint = ttk.Label(
            main,
            text=(
                "For add/add-and-run, enter file names only, e.g. "
                "'test explorer code.txt' and 'columns.txt'. "
                "The GUI searches current working directory."
            ),
            foreground="#555555",
            wraplength=780,
        )
        hint.pack(anchor="w", pady=(8, 12))

        # ========================================================
        # Buttons
        # ========================================================

        buttons = ttk.Frame(main)
        buttons.pack(fill="x", pady=(0, 10))

        self.run_button = ttk.Button(
            buttons,
            text="Start",
            command=self._on_start_clicked,
        )
        self.run_button.pack(side="left")

        self.clear_button = ttk.Button(
            buttons,
            text="Clear Log",
            command=self._clear_log,
        )
        self.clear_button.pack(side="left", padx=(8, 0))

        ttk.Label(main, textvariable=self.status_var).pack(anchor="w", pady=(0, 6))

        self.log_box = tk.Text(main, height=22, wrap="word")
        self.log_box.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(self.log_box, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

    def _on_mode_changed(self) -> None:
        mode = self.mode_var.get()

        is_add_mode = mode in {self.MODE_ADD, self.MODE_ADD_AND_RUN}

        # Phase 2 fields only matter when adding explorers.
        state = "normal" if is_add_mode else "disabled"

        self.notes_entry.configure(state=state)
        self.filter_file_entry.configure(state=state)
        self.columns_file_entry.configure(state=state)

        if mode == self.MODE_RUN:
            self.run_button.configure(text="Run Exploration")
        elif mode == self.MODE_ADD:
            self.run_button.configure(text="Add Explorer")
        else:
            self.run_button.configure(text="Add Explorer and Run")

    # ============================================================
    # REQUEST BUILDING
    # ============================================================

    def _on_start_clicked(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("MetaStock Automator", "Automation is already running.")
            return

        mode = self.mode_var.get()

        try:
            if mode == self.MODE_RUN:
                request = self._build_explore_request()
                callback = self.run_callback
                title = "Starting MetaStock exploration"

            elif mode == self.MODE_ADD:
                if self.add_callback is None:
                    messagebox.showerror(
                        "Unsupported mode",
                        "Add callback was not provided by automator.py.",
                    )
                    return

                request = self._build_add_explorer_request()
                callback = self.add_callback
                title = "Starting MetaStock explorer creation"

            elif mode == self.MODE_ADD_AND_RUN:
                if self.add_and_run_callback is None:
                    messagebox.showerror(
                        "Unsupported mode",
                        "Add-and-run callback was not provided by automator.py.",
                    )
                    return

                request = self._build_add_explorer_request()
                callback = self.add_and_run_callback
                title = "Starting MetaStock explorer creation and exploration"

            else:
                messagebox.showerror("Invalid mode", f"Unknown mode: {mode}")
                return

        except Exception as e:
            messagebox.showerror("Invalid input", str(e))
            return

        self._append_log(f"\n=== {title} ===\n")
        self._append_request_summary(mode, request)
        self._append_log("\n")

        self.status_var.set("Running...")
        self.run_button.configure(state="disabled")

        self.worker = threading.Thread(
            target=self._run_worker,
            args=(callback, request),
            daemon=True,
        )
        self.worker.start()

    def _build_explore_request(self) -> ExploreRequest:
        strategy = self.strategy_var.get().strip()
        instruments_text = self.instruments_var.get().strip()
        max_wait = self._parse_max_wait()

        if not strategy:
            raise ValueError("Please enter a strategy / explorer name.")

        instrument_names, select_all = parse_instruments_text(instruments_text)

        return ExploreRequest(
            strategy_name=strategy,
            instrument_names=instrument_names,
            select_all_instruments=select_all,
            max_execution_wait_sec=max_wait,
        )

    def _build_add_explorer_request(self) -> AddExplorerRequest:
        name = self.strategy_var.get().strip()
        notes = self.notes_var.get()
        instruments_text = self.instruments_var.get().strip()
        max_wait = self._parse_max_wait()

        if not name:
            raise ValueError("Please enter an explorer name.")

        filter_file_name = self.filter_code_file_var.get().strip()

        if not filter_file_name:
            raise ValueError("Please enter the filter code file name.")

        filter_path = self._resolve_user_file(filter_file_name)

        code_body = filter_path.read_text(encoding="utf-8")

        if not code_body.strip():
            raise ValueError(f"Filter code file is empty: {filter_path}")

        columns = []
        columns_file_name = self.columns_file_var.get().strip()

        if columns_file_name:
            columns_path = self._resolve_user_file(columns_file_name)
            columns_text = columns_path.read_text(encoding="utf-8")

            if not columns_text.strip():
                raise ValueError(f"Columns file is empty: {columns_path}")

            columns = parse_column_definitions_text(columns_text)

        instrument_names, select_all = parse_instruments_text(instruments_text)

        return AddExplorerRequest(
            name=name,
            notes=notes,
            code_body=code_body,
            columns=columns,

            # Phase 1-compatible fields
            strategy_name=name,
            instrument_names=instrument_names,
            select_all_instruments=select_all,
            max_execution_wait_sec=max_wait,
        )

    def _parse_max_wait(self) -> int:
        try:
            max_wait = int(self.max_wait_var.get().strip())
            if max_wait <= 0:
                raise ValueError
            return max_wait
        except ValueError:
            raise ValueError("Max wait must be a positive integer.")

    def _resolve_user_file(self, file_name: str) -> Path:
        """
        Resolve GUI filename input.

        Expected user input:
            test explorer code
            test explorer code.txt
            test cols
            test cols.txt

        Files are expected at project root, same level as main/.
        """
        raw = Path(file_name)

        if raw.is_absolute():
            candidates = [raw]
            if raw.suffix == "":
                candidates.append(raw.with_suffix(".txt"))

            for candidate in candidates:
                if candidate.exists():
                    return candidate

            raise FileNotFoundError(
                f"Could not find file: {file_name}\n"
                f"Tried:\n" + "\n".join(f"  {c}" for c in candidates)
            )

        main_dir = Path(__file__).resolve().parent
        project_root = main_dir.parent

        candidates = [project_root / raw]

        if raw.suffix == "":
            candidates.append(project_root / raw.with_suffix(".txt"))

        for candidate in candidates:
            if candidate.exists():
                return candidate

        raise FileNotFoundError(
            f"Could not find file: {file_name}\n"
            f"Expected location:\n"
            + "\n".join(f"  {c}" for c in candidates)
        )

    def _append_request_summary(self, mode: str, request) -> None:
        if mode == self.MODE_RUN:
            self._append_log(f"Strategy: {request.strategy_name}\n")
            self._append_log(
                f"Instruments: {'all' if request.select_all_instruments else request.instrument_names}\n"
            )
            self._append_log(f"Max wait: {request.max_execution_wait_sec}\n")
            return

        self._append_log(f"Explorer name: {request.name}\n")
        self._append_log(f"Notes: {request.notes}\n")
        self._append_log(f"Filter code length: {len(request.code_body)} chars\n")
        self._append_log(f"Columns: {len(request.columns)}\n")

        if request.columns:
            self._append_log(
                "Column slots: "
                + ", ".join(column.slot for column in request.columns)
                + "\n"
            )

        self._append_log(
            f"Instruments: {'all' if request.select_all_instruments else request.instrument_names}\n"
        )
        self._append_log(f"Max wait: {request.max_execution_wait_sec}\n")

    # ============================================================
    # WORKER / LOGGING
    # ============================================================

    def _run_worker(self, callback, request) -> None:
        old_stdout = sys.stdout
        old_stderr = sys.stderr

        sys.stdout = QueueWriter(self.output_queue)
        sys.stderr = QueueWriter(self.output_queue)

        try:
            callback(request)
            self.output_queue.put("\n=== Automation finished ===\n")
            self.output_queue.put("__STATUS_DONE__")
        except Exception:
            self.output_queue.put("\n=== Automation failed ===\n")
            self.output_queue.put(traceback.format_exc())
            self.output_queue.put("__STATUS_FAILED__")
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    def _poll_output_queue(self) -> None:
        try:
            while True:
                msg = self.output_queue.get_nowait()

                if msg == "__STATUS_DONE__":
                    self.status_var.set("Done")
                    self.run_button.configure(state="normal")
                    continue

                if msg == "__STATUS_FAILED__":
                    self.status_var.set("Failed")
                    self.run_button.configure(state="normal")
                    continue

                self._append_log(msg)
        except queue.Empty:
            pass

        self.root.after(100, self._poll_output_queue)

    def _append_log(self, text: str) -> None:
        self.log_box.insert("end", text)
        self.log_box.see("end")

    def _clear_log(self) -> None:
        self.log_box.delete("1.0", "end")