from __future__ import annotations

import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import ttk, messagebox

from requestReceiver import ExploreRequest, parse_instruments_text


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
    Simple desktop UI for MetaStock Explore automation.

    It does not click MetaStock directly.
    It only creates ExploreRequest and passes it to run_callback.
    """

    def __init__(self, run_callback) -> None:
        self.run_callback = run_callback
        self.output_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.root = tk.Tk()
        self.root.title("Automator")
        self.root.geometry("760x520")
        self.root.minsize(680, 460)

        self.strategy_var = tk.StringVar(value="#Stoch and RSI")
        self.instruments_var = tk.StringVar(value="all")
        self.max_wait_var = tk.StringVar(value="300")
        self.status_var = tk.StringVar(value="Ready")

        self._build_ui()
        self._poll_output_queue()

    def receive(self) -> None:
        self.root.mainloop()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        title = ttk.Label(
            main,
            text="Explore Automator",
            font=("Segoe UI", 16, "bold"),
        )
        title.pack(anchor="w", pady=(0, 12))

        form = ttk.Frame(main)
        form.pack(fill="x")

        ttk.Label(form, text="Strategy keyword").grid(row=0, column=0, sticky="w", pady=6)
        strategy_entry = ttk.Entry(form, textvariable=self.strategy_var)
        strategy_entry.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=6)

        ttk.Label(form, text="Instruments").grid(row=1, column=0, sticky="w", pady=6)
        instruments_entry = ttk.Entry(form, textvariable=self.instruments_var)
        instruments_entry.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=6)

        ttk.Label(form, text="Max wait seconds").grid(row=2, column=0, sticky="w", pady=6)
        max_wait_entry = ttk.Entry(form, textvariable=self.max_wait_var, width=12)
        max_wait_entry.grid(row=2, column=1, sticky="w", padx=(12, 0), pady=6)

        form.columnconfigure(1, weight=1)

        hint = ttk.Label(
            main,
            text=(
                "Use instruments = all to match: "
                'python automator.py --strategy "#Stoch and RSI" --all-instruments'
            ),
            foreground="#555555",
        )
        hint.pack(anchor="w", pady=(4, 12))

        buttons = ttk.Frame(main)
        buttons.pack(fill="x", pady=(0, 10))

        self.run_button = ttk.Button(
            buttons,
            text="Run Exploration",
            command=self._on_run_clicked,
        )
        self.run_button.pack(side="left")

        self.clear_button = ttk.Button(
            buttons,
            text="Clear Log",
            command=self._clear_log,
        )
        self.clear_button.pack(side="left", padx=(8, 0))

        ttk.Label(main, textvariable=self.status_var).pack(anchor="w", pady=(0, 6))

        self.log_box = tk.Text(main, height=18, wrap="word")
        self.log_box.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(self.log_box, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

    def _on_run_clicked(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("MetaStock Automator", "Automation is already running.")
            return

        strategy = self.strategy_var.get().strip()
        instruments_text = self.instruments_var.get().strip()

        if not strategy:
            messagebox.showerror("Missing strategy", "Please enter a strategy keyword.")
            return

        try:
            max_wait = int(self.max_wait_var.get().strip())
            if max_wait <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid max wait", "Max wait must be a positive integer.")
            return

        instrument_names, select_all = parse_instruments_text(instruments_text)

        request = ExploreRequest(
            strategy_name=strategy,
            instrument_names=instrument_names,
            select_all_instruments=select_all,
            max_execution_wait_sec=max_wait,
        )

        self._append_log("\n=== Starting MetaStock automation ===\n")
        self._append_log(f"Strategy: {request.strategy_name}\n")
        self._append_log(
            f"Instruments: {'all' if request.select_all_instruments else request.instrument_names}\n\n"
        )

        self.status_var.set("Running...")
        self.run_button.configure(state="disabled")

        self.worker = threading.Thread(
            target=self._run_worker,
            args=(request,),
            daemon=True,
        )
        self.worker.start()

    def _run_worker(self, request: ExploreRequest) -> None:
        old_stdout = sys.stdout
        old_stderr = sys.stderr

        sys.stdout = QueueWriter(self.output_queue)
        sys.stderr = QueueWriter(self.output_queue)

        try:
            self.run_callback(request)
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