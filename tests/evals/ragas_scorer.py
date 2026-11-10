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
from ragas import evaluate
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
        temperature=0.1,
        max_tokens=512,
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

        ctx = [
            c.get("content", "")
            for c in r.get("citations", [])
            if c.get("content")
        ]
        # RAGAS needs at least one context. If LLM cited nothing, use the response itself
        # (this yields low faithfulness honestly — that's the signal we want)
        if not ctx:
            ctx = [r["response"]]

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
    )

    df = ragas_result.to_pandas()

    metrics = {
        "faithfulness": float(df["faithfulness"].mean(skipna=True)),
        "answer_relevancy": float(df["answer_relevancy"].mean(skipna=True)),
        "context_precision": float(df["context_precision"].mean(skipna=True)),
    }
    metrics["citation_accuracy"] = _citation_accuracy(valid)
    metrics["count"] = len(df)

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
