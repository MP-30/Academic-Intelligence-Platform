import logging

import boto3

from academic_ai.config import settings

log = logging.getLogger(__name__)

_client = None


def _sqs():
    """SQS client. LocalStack in dev, real AWS in prod."""
    global _client
    if _client is not None:
        return _client

    if settings.sqs_endpoint_url:
        # LocalStack — fake creds, endpoint override
        _client = boto3.client(
            "sqs",
            endpoint_url=settings.sqs_endpoint_url,
            region_name=settings.aws_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
    else:
        # Real AWS — use profile if configured
        session = (
            boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
            if settings.aws_profile
            else boto3.Session(region_name=settings.aws_region)
        )
        _client = session.client("sqs")

    log.info("sqs client created (endpoint=%s, region=%s)",
             settings.sqs_endpoint_url or "aws", settings.aws_region)
    return _client


def get_queue_url() -> str:
    """The queue URL from .env, or discover it by name."""
    if settings.sqs_queue_url:
        return settings.sqs_queue_url
    return _sqs().get_queue_url(QueueName=settings.sqs_queue_name)["QueueUrl"]