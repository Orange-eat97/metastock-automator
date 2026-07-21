from __future__ import annotations

import ctypes
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

from pywinauto.base_wrapper import BaseWrapper

from ui_interacter.ui_core import log


VK_R = 0x52
VK_ESCAPE = 0x1B
VK_LBUTTON = 0x01

_user32 = ctypes.windll.user32


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


@dataclass(frozen=True)
class CalibratedPoint:
    """
    A point stored relative to the MetaStock window.

    normalized_x / normalized_y allow the point to follow window-size
    changes when the overall layout scales consistently.
    """

    name: str
    absolute_x: int
    absolute_y: int
    window_relative_x: int
    window_relative_y: int
    normalized_x: float
    normalized_y: float


@dataclass(frozen=True)
class CalibrationProfile:
    profile_version: str
    profile_name: str
    window_title: str
    window_width: int
    window_height: int
    dpi: Optional[int]
    created_at_epoch: float
    points: dict[str, CalibratedPoint]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["points"] = {
            name: asdict(point)
            for name, point in self.points.items()
        }
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> "CalibrationProfile":
        points = {
            str(name): CalibratedPoint(**point_payload)
            for name, point_payload in (
                payload.get("points") or {}
            ).items()
        }

        return cls(
            profile_version=str(
                payload.get("profile_version") or "1.0"
            ),
            profile_name=str(
                payload.get("profile_name") or "default"
            ),
            window_title=str(
                payload.get("window_title") or ""
            ),
            window_width=int(
                payload.get("window_width") or 0
            ),
            window_height=int(
                payload.get("window_height") or 0
            ),
            dpi=(
                int(payload["dpi"])
                if payload.get("dpi") is not None
                else None
            ),
            created_at_epoch=float(
                payload.get("created_at_epoch") or 0.0
            ),
            points=points,
        )


class CalibrationStore:
    def __init__(
        self,
        directory: str | Path | None = None,
    ) -> None:
        self.directory = Path(
            directory
            or Path(__file__).resolve().parents[1]
            / "calibration_profiles"
        )

    def profile_path(self, profile_name: str) -> Path:
        safe_name = "".join(
            char
            if char.isalnum() or char in {"-", "_"}
            else "_"
            for char in profile_name.strip()
        )

        if not safe_name:
            safe_name = "default"

        return self.directory / f"{safe_name}.json"

    def save(self, profile: CalibrationProfile) -> Path:
        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )
        path = self.profile_path(
            profile.profile_name
        )
        path.write_text(
            json.dumps(
                profile.to_dict(),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def load(
        self,
        profile_name: str,
    ) -> CalibrationProfile:
        path = self.profile_path(profile_name)

        if not path.exists():
            raise FileNotFoundError(
                f"Calibration profile does not exist: {path}"
            )

        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
        return CalibrationProfile.from_dict(payload)


class InteractiveCoordinateRecorder:
    """
    Windows-only interactive coordinate recorder.

    Per anchor:
      1. press R once to arm;
      2. click the intended point;
      3. press R again to accept and finish that anchor.

    The most recent click before the second R is used. ESC cancels.
    Polling GetAsyncKeyState avoids adding keyboard/mouse hook packages.
    """

    def __init__(
        self,
        *,
        poll_interval: float = 0.02,
    ) -> None:
        self.poll_interval = poll_interval

    def capture_anchor(
        self,
        *,
        anchor_name: str,
        instruction: str,
    ) -> tuple[int, int]:
        print()
        print("=" * 68)
        print(f"CALIBRATION: {anchor_name}")
        print(instruction)
        print()
        print("1. Press R once to arm coordinate recording.")
        print("2. Click the requested point.")
        print("3. Press R again to accept this calibration point.")
        print("Press ESC at any time to cancel.")
        print("=" * 68)

        self._wait_for_key_press(
            VK_R,
            action="arm coordinate recording",
        )

        print(
            f"[Calibration] Recording armed for {anchor_name!r}. "
            "Click the target point, then press R."
        )

        latest_click: Optional[tuple[int, int]] = None

        r_was_down = self._is_key_down(VK_R)
        mouse_was_down = self._is_key_down(
            VK_LBUTTON
        )

        while True:
            if self._is_key_down(VK_ESCAPE):
                self._wait_for_key_release(
                    VK_ESCAPE
                )
                raise KeyboardInterrupt(
                    "Calibration cancelled by user."
                )

            r_is_down = self._is_key_down(VK_R)
            mouse_is_down = self._is_key_down(
                VK_LBUTTON
            )

            if mouse_is_down and not mouse_was_down:
                latest_click = self._cursor_position()
                print(
                    "[Calibration] Click captured at "
                    f"{latest_click}. Click again to replace it, "
                    "or press R to accept."
                )

            if r_is_down and not r_was_down:
                if latest_click is None:
                    print(
                        "[Calibration] No click has been "
                        "captured yet. Click the target first."
                    )
                else:
                    self._wait_for_key_release(VK_R)
                    print(
                        "[Calibration] Accepted "
                        f"{anchor_name!r} at {latest_click}."
                    )
                    return latest_click

            r_was_down = r_is_down
            mouse_was_down = mouse_is_down
            time.sleep(self.poll_interval)

    def _wait_for_key_press(
        self,
        virtual_key: int,
        *,
        action: str,
    ) -> None:
        previous = self._is_key_down(
            virtual_key
        )

        while True:
            if self._is_key_down(VK_ESCAPE):
                self._wait_for_key_release(
                    VK_ESCAPE
                )
                raise KeyboardInterrupt(
                    "Calibration cancelled by user."
                )

            current = self._is_key_down(
                virtual_key
            )

            if current and not previous:
                self._wait_for_key_release(
                    virtual_key
                )
                return

            previous = current
            time.sleep(self.poll_interval)

    def _wait_for_key_release(
        self,
        virtual_key: int,
    ) -> None:
        while self._is_key_down(virtual_key):
            time.sleep(self.poll_interval)

    @staticmethod
    def _is_key_down(
        virtual_key: int,
    ) -> bool:
        return bool(
            _user32.GetAsyncKeyState(
                virtual_key
            )
            & 0x8000
        )

    @staticmethod
    def _cursor_position() -> tuple[int, int]:
        point = POINT()

        if not _user32.GetCursorPos(
            ctypes.byref(point)
        ):
            raise RuntimeError(
                "Windows GetCursorPos failed."
            )

        return int(point.x), int(point.y)


class CalibrationWizard:
    def __init__(
        self,
        *,
        store: CalibrationStore | None = None,
        recorder: InteractiveCoordinateRecorder
        | None = None,
    ) -> None:
        self.store = store or CalibrationStore()
        self.recorder = (
            recorder
            or InteractiveCoordinateRecorder()
        )

    def run(
        self,
        *,
        main: BaseWrapper,
        profile_name: str,
        anchors: Iterable[
            tuple[str, str]
        ],
    ) -> CalibrationProfile:
        rect = main.rectangle()

        if rect.width() <= 0 or rect.height() <= 0:
            raise RuntimeError(
                "MetaStock window has invalid bounds."
            )

        points: dict[
            str,
            CalibratedPoint,
        ] = {}

        for anchor_name, instruction in anchors:
            x, y = self.recorder.capture_anchor(
                anchor_name=anchor_name,
                instruction=instruction,
            )

            if not (
                rect.left <= x <= rect.right
                and rect.top <= y <= rect.bottom
            ):
                raise RuntimeError(
                    f"Captured point {anchor_name!r} "
                    f"({x}, {y}) is outside the "
                    "MetaStock window."
                )

            relative_x = x - rect.left
            relative_y = y - rect.top

            points[anchor_name] = CalibratedPoint(
                name=anchor_name,
                absolute_x=x,
                absolute_y=y,
                window_relative_x=relative_x,
                window_relative_y=relative_y,
                normalized_x=(
                    relative_x / rect.width()
                ),
                normalized_y=(
                    relative_y / rect.height()
                ),
            )

        # Preserve anchors that are already present in the same profile.
        # This lets users calibrate Explore and System Tester points in
        # separate runs without losing the other workflow's anchors.
        try:
            existing_profile = self.store.load(profile_name)
            merged_points = dict(existing_profile.points)
            merged_points.update(points)
            points = merged_points
        except FileNotFoundError:
            pass

        profile = CalibrationProfile(
            profile_version="1.0",
            profile_name=profile_name,
            window_title=main.window_text(),
            window_width=rect.width(),
            window_height=rect.height(),
            dpi=self._read_window_dpi(main),
            created_at_epoch=time.time(),
            points=points,
        )

        path = self.store.save(profile)

        log(
            "Calibration profile saved: "
            f"{path}"
        )
        return profile

    @staticmethod
    def _read_window_dpi(
        main: BaseWrapper,
    ) -> Optional[int]:
        try:
            hwnd = int(main.handle)
            get_dpi_for_window = (
                _user32.GetDpiForWindow
            )
            return int(
                get_dpi_for_window(hwnd)
            )
        except Exception:
            return None


class CoordinateMapper:
    """
    Resolve named calibration points against the current MetaStock window.
    """

    def __init__(
        self,
        profile: CalibrationProfile,
        *,
        max_size_change_ratio: float = 0.08,
    ) -> None:
        self.profile = profile
        self.max_size_change_ratio = (
            max_size_change_ratio
        )

    def resolve(
        self,
        *,
        main: BaseWrapper,
        point_name: str,
        require_matching_window: bool = True,
    ) -> tuple[int, int]:
        point = self.profile.points.get(
            point_name
        )

        if point is None:
            raise KeyError(
                "Calibration point is missing: "
                f"{point_name!r}"
            )

        rect = main.rectangle()

        if require_matching_window:
            self.validate_window(main)

        x = rect.left + round(
            point.normalized_x * rect.width()
        )
        y = rect.top + round(
            point.normalized_y * rect.height()
        )

        return int(x), int(y)

    def validate_window(
        self,
        main: BaseWrapper,
    ) -> None:
        rect = main.rectangle()

        width_ratio = self._difference_ratio(
            rect.width(),
            self.profile.window_width,
        )
        height_ratio = self._difference_ratio(
            rect.height(),
            self.profile.window_height,
        )

        if (
            width_ratio
            > self.max_size_change_ratio
            or height_ratio
            > self.max_size_change_ratio
        ):
            raise RuntimeError(
                "MetaStock window size changed beyond "
                "the calibrated tolerance. Re-run "
                "coordinate calibration. "
                f"Calibrated="
                f"{self.profile.window_width}x"
                f"{self.profile.window_height}, "
                f"Current={rect.width()}x"
                f"{rect.height()}."
            )

    @staticmethod
    def _difference_ratio(
        current: int,
        reference: int,
    ) -> float:
        if reference <= 0:
            return 1.0

        return abs(
            current - reference
        ) / reference
