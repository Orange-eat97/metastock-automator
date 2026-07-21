from __future__ import annotations

import argparse

from compartments.metastock_app import MetaStockApp
from ui_interacter.coordinate_calibration import (
    CalibrationWizard,
)


APP_TITLE_RE = r"^Main - MetaStock$"


EXPLORE_ANCHORS = [
    (
        "explore_tab",
        "Click the middle of the word 'Explore' "
        "on the left-side MetaStock navigation.",
    ),
    (
        "strategy_checkbox",
        "Open the Explore Console and filter to one "
        "Explorer. Click the target strategy checkbox area.",
    ),
    (
        "instruments_checkbox",
        "Click the checkbox area of the main "
        "'Instruments' tree row.",
    ),
    (
        "start_exploration",
        "Click the middle of the 'Start Exploration' button.",
    ),
]


SYSTEM_TEST_ANCHORS = [
    (
        "system_test_tab",
        "Click the middle of the word 'SystemTest' "
        "on the left-side MetaStock navigation.",
    ),
    (
        "system_test_checkbox",
        "Open the System Tester Console and filter to one "
        "System Test. Click the target system-test checkbox area.",
    ),
    (
        "start_system_test",
        "Click the middle of the 'Start System Test' button.",
    ),
]


ANCHORS_BY_MODE = {
    "explore": EXPLORE_ANCHORS,
    "system-test": SYSTEM_TEST_ANCHORS,
    "all": EXPLORE_ANCHORS + SYSTEM_TEST_ANCHORS,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Interactively record MetaStock coordinate "
            "fallback points."
        )
    )
    parser.add_argument(
        "--profile",
        default="default",
        help=(
            "Calibration profile name, for example "
            "'t490-main-display'."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=sorted(ANCHORS_BY_MODE),
        default="explore",
        help=(
            "Which fallback points to record. Use 'all' when "
            "the same profile should support both Explorer and "
            "System Tester automation."
        ),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    app = MetaStockApp(
        app_title_re=APP_TITLE_RE
    )
    main_window = app.connect()

    print(
        "Prepare MetaStock in the exact layout used "
        "for automation before continuing."
    )
    print(
        "Do not resize or move MetaStock during "
        "this calibration run."
    )
    print(
        "For each point: press R to arm, click the "
        "target, then press R again to accept."
    )

    CalibrationWizard().run(
        main=main_window,
        profile_name=args.profile,
        anchors=ANCHORS_BY_MODE[args.mode],
    )

    print()
    print(
        "Calibration complete. Profile saved under "
        "main/calibration_profiles/."
    )
    print(
        "Use it in PowerShell with: "
        "$env:METASTOCK_CALIBRATION_PROFILE = "
        f"'{args.profile}'"
    )


if __name__ == "__main__":
    main()
