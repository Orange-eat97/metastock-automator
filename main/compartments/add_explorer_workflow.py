from __future__ import annotations

from pywinauto.base_wrapper import BaseWrapper

from phase2RequestReceiver import AddExplorerRequest
from compartments.explorer_creator import ExplorerCreator


class AddExplorerWorkflow:
    """
    Phase 2 workflow.

    Responsibility:
        - connect/open Explore Console is handled by automator composition
        - create explorer through ExplorerCreator

    It does not run exploration.
    """

    def __init__(
        self,
        app,
        console,
        explorer_creator: ExplorerCreator,
    ) -> None:
        self.app = app
        self.console = console
        self.explorer_creator = explorer_creator

    def run(self, request: AddExplorerRequest) -> BaseWrapper:
        main_window = self.app.connect()
        self.console.open(main_window)
        self.explorer_creator.create(main_window, request)
        return main_window