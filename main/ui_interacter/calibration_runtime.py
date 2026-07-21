from __future__ import annotations

import os
from typing import Optional

from ui_interacter.coordinate_calibration import (
    CalibrationStore,
    CoordinateMapper,
)
from ui_interacter.ui_core import log


def load_coordinate_mapper_from_env(
) -> Optional[CoordinateMapper]:
    """
    Enable calibrated fallbacks by setting:

        METASTOCK_CALIBRATION_PROFILE=t490-main-display

    If the variable is absent, existing UIA and row-relative
    fallback behavior remains unchanged.
    """
    profile_name = (
        os.getenv(
            "METASTOCK_CALIBRATION_PROFILE"
        )
        or ""
    ).strip()

    if not profile_name:
        return None

    profile = CalibrationStore().load(
        profile_name
    )
    log(
        "Loaded MetaStock calibration profile: "
        f"{profile_name!r}"
    )
    return CoordinateMapper(profile)
