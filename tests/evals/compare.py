"""Compare current baseline to a reference baseline (regression check).

Usage:
    uv run python -m tests.evals.compare

Reads:
    tests/evals/baseline.json       ← latest run (written by ragas_scorer)
    tests/evals/baseline.reference.json  ← committed reference (baseline at tag)

Exit code:
    0  if all metrics within threshold
    1  if any metric regressed > threshold
"""
import json
import sys
from pathlib import Path

from academic_ai.config import settings

METRICS = ["faithfulness", "answer_relevancy", "context_precision", "citation_accuracy"]


def load(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text())


def main():
    baseline_path = Path(settings.eval_baseline_path)
    reference_path = Path("tests/evals/baseline.reference.json")

    if not baseline_path.exists():
        print(f"ERROR: {baseline_path} not found — run ragas_scorer first", file=sys.stderr)
        sys.exit(1)

    if not reference_path.exists():
        print(f"ERROR: {reference_path} missing — commit a reference before running CI",
              file=sys.stderr)
        sys.exit(1)

    current = load(baseline_path)
    reference = load(reference_path)
    threshold = settings.eval_regression_threshold

    print(f"Reference: {reference['generated_at']}")
    print(f"Current:   {current['generated_at']}")
    print(f"Threshold: {threshold} (fail if metric drops more than this)")
    print()

    header = f"{'metric':<22} {'reference':>10} {'current':>10} {'delta':>10} {'status':>10}"
    print(header)
    print("-" * len(header))

    failed = False
    for metric in METRICS:
        ref_val = reference["metrics"].get(metric)
        cur_val = current["metrics"].get(metric)

        if ref_val is None or cur_val is None:
            print(f"{metric:<22} {'N/A':>10} {'N/A':>10} {'N/A':>10} {'SKIP':>10}")
            continue

        delta = cur_val - ref_val
        regressed = delta < -threshold
        status = "REGRESSED" if regressed else "ok"

        print(f"{metric:<22} {ref_val:>10.4f} {cur_val:>10.4f} {delta:>+10.4f} {status:>10}")
        if regressed:
            failed = True

    print()
    if failed:
        print(f"❌ REGRESSION DETECTED — one or more metrics dropped > {threshold}")
        print("Fix the regression or update baseline.reference.json if intentional")
        sys.exit(1)
    else:
        print("✅ All metrics within threshold")
        sys.exit(0)


if __name__ == "__main__":
    main()
