"""v0.7 RAGAS scorer — compute metrics from eval results.

Usage:
    set -a; source .env.aws; set +a
    uv run python -m tests.evals.ragas_scorer

Reads latest tests/evals/results-*.json
Writes tests/evals/baseline.json
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pandas as pd
from datasets import Dataset
from langchain_aws import BedrockEmbeddings, ChatBedrockConverse
from ragas import RunConfig, evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    faithfulness,
)

from academic_ai.config import settings


def _judge_llm():

    profile = os.getenv("EVAL_JUDGE_PROFILE")  # unset in CI
    session_kwargs = {"region_name": settings.eval_judge_region}
    if profile:
        session_kwargs["profile_name"] = profile
    session = boto3.Session(**session_kwargs)
    ...
    chat = ChatBedrockConverse(
        model=settings.eval_judge_model,
        client=session.client("bedrock-runtime"),
        temperature=0.0,
        max_tokens=8192,
    )
    return LangchainLLMWrapper(chat)


def _judge_embeddings():

    profile = os.getenv("EVAL_JUDGE_PROFILE")
    session_kwargs = {"region_name": settings.eval_judge_region}
    if profile:
        session_kwargs["profile_name"] = profile
    session = boto3.Session(**session_kwargs)
    emb = BedrockEmbeddings(
        client=session.client("bedrock-runtime"),
        model_id="amazon.titan-embed-text-v2:0",
        model_kwargs={"dimensions": 1024, "normalize": True},
    )
    return LangchainEmbeddingsWrapper(emb)


def _build_dataset(results: list[dict]) -> tuple[Dataset, list[dict]]:
    """Build RAGAS dataset. Returns (dataset, valid_results)."""
    questions, answers, contexts, ground_truths = [], [], [], []
    valid = []

    for r in results:
        if "error" in r:
            continue
        if not r.get("response") or not r.get("ground_truth"):
            continue

        ctx = r.get("contexts") or []

        if not ctx:
            print(f"⚠️  SKIP {r['id']}: no retrieved contexts, cannot score faithfulness")
            continue

        questions.append(r["question"])
        answers.append(r["response"])
        contexts.append(ctx)
        ground_truths.append(r["ground_truth"])
        valid.append(r)

    return Dataset.from_dict({
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths,
    }), valid


def _citation_accuracy(results: list[dict]) -> float:
    """Custom: fraction of questions where cited pages overlap expected_pages."""
    scored = 0
    correct = 0
    for r in results:
        if r.get("category") in ("web", "refusal"):
            continue
        expected = set(r.get("expected_pages", []))
        cited = {
            c["page_number"]
            for c in r.get("citations", [])
            if c.get("source") == "document" and c.get("page_number")
        }
        scored += 1
        if expected & cited:
            correct += 1
    return correct / scored if scored else 0.0


def main():
    files = sorted(Path("tests/evals").glob("results-*.json"))
    if not files:
        print("ERROR: no results-*.json found. Run runner.py first.", file=sys.stderr)
        sys.exit(1)
    latest = files[-1]
    print(f"Loading: {latest}\n")

    results = json.loads(latest.read_text())
    dataset, valid = _build_dataset(results)
    print(f"Dataset: {len(dataset)} rows (skipped {len(results) - len(valid)} invalid)\n")

    print("Running RAGAS evaluation (~2-5 min)...")
    ragas_result = evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_relevancy, context_precision],
        llm=_judge_llm(),
        embeddings=_judge_embeddings(),
        raise_exceptions=False,
        run_config=RunConfig(
            timeout=300,
            max_retries=3,
            max_wait=60,
            max_workers=2
        ),
    )

    df = ragas_result.to_pandas()

    # --- Guard: every judged metric must have ≥80% non-NaN rows ---
    MIN_SCORED = 0.8
    tracked_metrics = ("faithfulness", "answer_relevancy", "context_precision")
    failed = []
    for m in tracked_metrics:
        nan_count = df[m].isna().sum()
        scored = len(df) - nan_count
        ratio = scored / len(df) if len(df) else 0.0
        print(f"Scored {m}: {scored}/{len(df)} ({ratio:.0%})")
        if ratio < MIN_SCORED:
            failed.append((m, nan_count, len(df), ratio))

    # Diagnostic: which rows have NaN, and on which metrics
    nan_rows = df[list(tracked_metrics)].isna().any(axis=1)
    if nan_rows.any():
        print(f"\n⚠️  {nan_rows.sum()} rows have NaN metrics:")
        for i, (_, row) in enumerate(df.iterrows()):
            if nan_rows.iloc[i]:
                qid = valid[i]["id"] if i < len(valid) else f"row-{i}"
                parts = [f"{m}={row[m]}" for m in tracked_metrics]
                print(f"  {qid}: {', '.join(parts)}")

    if failed:
        print(f"\nERROR: incomplete RAGAS scoring (need ≥{MIN_SCORED:.0%} per metric):",
              file=sys.stderr)
        for m, nan_count, total, ratio in failed:
            print(f"  {m}: {nan_count} of {total} NaN ({ratio:.0%} scored)",
                  file=sys.stderr)
        print("\nRefusing to write baseline.json — partial means against a full "
              "reference produce false regressions.", file=sys.stderr)
        sys.exit(1)

    # --- All metrics scored enough — compute aggregates ---
    metrics = {
        "faithfulness": float(df["faithfulness"].mean(skipna=True)),
        "answer_relevancy": float(df["answer_relevancy"].mean(skipna=True)),
        "context_precision": float(df["context_precision"].mean(skipna=True)),
    }
    metrics["citation_accuracy"] = _citation_accuracy(valid)
    metrics["count"] = len(df)

    nan_rows = df[df[["faithfulness", "answer_relevancy", "context_precision"]].isna().any(axis=1)]
    if not nan_rows.empty:
        print(f"\n⚠️  {len(nan_rows)} rows have NaN metrics:")
        for i, (_, row) in enumerate(df.iterrows()):
            if pd.isna(row["faithfulness"]) or pd.isna(row["answer_relevancy"]) or pd.isna(row["context_precision"]):
                qid = valid[i]["id"] if i < len(valid) else f"row-{i}"
                print(f"  {qid}: f={row['faithfulness']}, ar={row['answer_relevancy']}, cp={row['context_precision']}")

    baseline = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_results": str(latest),
        "metrics": metrics,
        "per_question": {
            valid[i]["id"]: {
                "faithfulness": float(row["faithfulness"]) if not pd.isna(row["faithfulness"]) else None,
                "answer_relevancy": float(row["answer_relevancy"]) if not pd.isna(row["answer_relevancy"]) else None,
                "context_precision": float(row["context_precision"]) if not pd.isna(row["context_precision"]) else None,
                "expected_pages": valid[i].get("expected_pages", []),
                "cited_pages": [
                    c["page_number"]
                    for c in valid[i].get("citations", [])
                    if c.get("source") == "document"
                ],
            }
            for i, (_, row) in enumerate(df.iterrows())
            if i < len(valid)
        },
    }

    out = Path(settings.eval_baseline_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(baseline, indent=2))

    print("\n=== BASELINE ===")
    for k, v in metrics.items():
        if isinstance(v, float):
            print(f"{k:<22} {v:.4f}")
        else:
            print(f"{k:<22} {v}")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
