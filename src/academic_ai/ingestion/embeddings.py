import json
import logging

import boto3

from academic_ai.config import settings

log = logging.getLogger(__name__)

_client = None


def _bedrock_client():
    """REAL AWS Bedrock. NEVER point this at LocalStack — stub vectors break search."""
    global _client
    if _client is None:
        session = (
            boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
            if settings.aws_profile
            else boto3.Session(region_name=settings.aws_region)
        )
        _client = session.client("bedrock-runtime")
        log.info("bedrock-runtime client created (region=%s, profile=%s)",
                 settings.aws_region, settings.aws_profile)
    return _client


def embed(text: str) -> list[float]:
    """Titan v2 — 1024-dim unit-normalized vector. Returns Python list."""
    resp = _bedrock_client().invoke_model(
        modelId=settings.embedding_model_id,
        body=json.dumps({
            "inputText": text,
            "dimensions": settings.embedding_dimensions,
            "normalize": True,
        }),
    )
    return json.loads(resp["body"].read())["embedding"]