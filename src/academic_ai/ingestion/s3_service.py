import boto3

from academic_ai.config import settings


def _s3():
    if settings.s3_endpoint_url:
        # Localstack — any credentials accepted, profile ignored
        return boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.aws_region,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
    # Real AWS — use profile if set
    session = (
        boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
        if settings.aws_profile
        else boto3.Session(region_name=settings.aws_region)
    )
    return session.client("s3")


def upload_pdf(key: str, body: bytes) -> None:
    _s3().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=body,
        ContentType="application/pdf",
    )


def download_pdf(key: str) -> bytes:
    return _s3().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()