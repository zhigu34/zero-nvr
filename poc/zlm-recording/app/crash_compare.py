from __future__ import annotations

import json
from pathlib import Path


BASELINE = Path("/runtime/mp4-baseline-evidence.json")
FMP4 = Path("/runtime/fmp4-evidence.json")
OUT = Path("/runtime/mp4-vs-fmp4-comparison.json")


def main() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    fmp4 = json.loads(FMP4.read_text(encoding="utf-8"))

    baseline_all = bool(baseline.get("all_recovery_checks_passed"))
    fmp4_all = fmp4.get("result") == "PASS"

    result = {
        "ordinary_mp4_all_recovery_checks_passed": baseline_all,
        "fmp4_all_recovery_checks_passed": fmp4_all,
        "fmp4_materially_better_in_this_sigkill_test": fmp4_all and not baseline_all,
        "baseline": baseline,
        "fmp4": fmp4,
    }

    if not fmp4_all:
        result["result"] = "FAIL"
        result["reason"] = "fMP4 did not satisfy its recovery checks"
    elif baseline_all:
        result["result"] = "FAIL"
        result["reason"] = (
            "ordinary MP4 passed the same recovery checks; this test does not "
            "demonstrate a material fMP4 recovery advantage"
        )
    else:
        result["result"] = "PASS"

    OUT.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result["result"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
