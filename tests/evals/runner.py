"""v0.7 eval runner — capture /agent responses for RAGAS scoring.

Usage:
    set -a; source .env.aws; set +a
    uv run python -m tests.evals.runner

Outputs:
    tests/evals/results-YYYYMMDD-HHMMSS.json
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx
import yaml

from academic_ai.config import settings


def _api_base() -> str:
    return os.getenv("EVAL_API_BASE") or settings.eval_api_base or settings.api_base_url


def _credentials() -> tuple[str, str]:
    email = os.getenv("EVAL_USER_EMAIL") or settings.eval_user_email
    password = os.getenv("EVAL_USER_PASSWORD") or settings.eval_user_password
    if not email or not password:
        print("ERROR: EVAL_USER_EMAIL / EVAL_USER_PASSWORD not set", file=sys.stderr)
        sys.exit(1)
    return email, password


async def login(client: httpx.AsyncClient, api_base: str) -> str:
    email, password = _credentials()
    resp = await client.post(
        f"{api_base}/auth/login",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    return resp.json()["id_token"]


async def run_question(client, token, api_base, q):
    resp = await client.post(
        f"{api_base}/agent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "message": q["question"],
            "workspace_id": q.get("workspace_id") or None,
        },
    )
    resp.raise_for_status()
    return resp.json()


async def main():
    api_base = _api_base()
    print(f"API base: {api_base}\n")

    dataset_path = Path(settings.eval_dataset_path)
    if not dataset_path.exists():
        print(f"ERROR: {dataset_path} not found", file=sys.stderr)
        sys.exit(1)

    questions = yaml.safe_load(dataset_path.read_text())
    print(f"Loaded {len(questions)} questions\n")

    async with httpx.AsyncClient(timeout=90) as client:
        token = await login(client, api_base)
        print(f"JWT acquired: {token[:20]}...\n")

        results = []
        for i, q in enumerate(questions, 1):
            print(f"[{i}/{len(questions)}] {q['id']}: {q['question'][:60]}")
            try:
                r = await run_question(client, token, api_base, q)
                results.append({
                    "id": q["id"],
                    "question": q["question"],
                    "category": q["category"],
                    "ground_truth": q["ground_truth"],
                    "expected_pages": q.get("expected_pages", []),
                    "response": r["response"],
                    "tool_calls": r["tool_calls"],
                    "citations": r["citations"],
                    "conversation_id": r["conversation_id"],
                    "contexts": r.get("contexts") or [c.get("content") for c in r["citations"] if c.get("content")],
                })
                tools = [t["tool"] for t in r["tool_calls"]]
                print(f"  tools={tools} citations={len(r['citations'])}")
            except Exception as e:
                print(f"  ERROR: {e}")
                results.append({"id": q["id"], "question": q["question"], "error": str(e)})

    out = Path(f"tests/evals/results-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nSaved: {out}")

    ok = sum(1 for r in results if "error" not in r)
    print(f"Succeeded: {ok}/{len(results)}")


if __name__ == "__main__":
    asyncio.run(main())
