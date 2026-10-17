"""Retain a synthetic multi-site GUI report for wording/layout QA, not science."""
import json
from pathlib import Path
import shutil
from test_gui_full_journey import GuiFullJourneyTests


def main():
    output = Path(__file__).resolve().parent / "runs/site-first-control-20261017_b/multisite-fixture"
    assert not output.exists()
    GuiFullJourneyTests.setUpClass()
    case = GuiFullJourneyTests("test_control_multisite_review_requires_exploratory_finalization")
    case.setUp()
    try:
        case.test_control_multisite_review_requires_exploratory_finalization()
        shutil.copytree(case.root / "multi-final", output)
        (output / "fixture_notice.json").write_text(json.dumps({
            "scope": "Synthetic workflow/report fixture; fictional remote evidence and simulated control result",
            "scientific_docking_searches": 0, "status": "passed",
            "not_a_scientific_control": True,
        }, indent=2) + "\n")
        print(str(output))
    finally:
        case.tearDown()


if __name__ == "__main__":
    main()
