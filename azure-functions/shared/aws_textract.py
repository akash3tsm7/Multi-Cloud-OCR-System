"""
aws_textract.py
AWS Textract analyze_document wrapper.
Best for documents, forms, and multi-column text layouts.
"""

import os
import logging
import boto3

logger = logging.getLogger(__name__)

_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _get_client():
    return boto3.client(
        "textract",
        region_name=_AWS_REGION,
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )


def analyze_document(image_bytes: bytes) -> str:
    """
    Run AWS Textract DetectDocumentText on raw image bytes.

    Args:
        image_bytes: Raw image data (JPEG/PNG, max 5MB).

    Returns:
        Extracted text as a newline-joined string (LINE blocks only).

    Raises:
        RuntimeError: If Textract call fails.
    """
    client = _get_client()

    try:
        response = client.detect_document_text(Document={"Bytes": image_bytes})
    except Exception as exc:
        raise RuntimeError(f"Textract detect_document_text failed: {exc}") from exc

    blocks = response.get("Blocks", [])
    lines = [
        b["Text"]
        for b in blocks
        if b["BlockType"] == "LINE" and b.get("Confidence", 0) >= 70.0
    ]

    logger.info(f"[Textract] Extracted {len(lines)} LINE blocks.")
    return "\n".join(lines)


def analyze_document_from_s3(bucket: str, key: str) -> str:
    """
    Run Textract DetectDocumentText on an S3 object (avoids 5MB byte limit).

    Args:
        bucket: S3 bucket name.
        key: S3 object key.

    Returns:
        Extracted text as a newline-joined string.
    """
    client = _get_client()

    try:
        response = client.detect_document_text(
            Document={"S3Object": {"Bucket": bucket, "Name": key}}
        )
    except Exception as exc:
        raise RuntimeError(f"Textract (S3) failed: {exc}") from exc

    blocks = response.get("Blocks", [])
    lines = [
        b["Text"]
        for b in blocks
        if b["BlockType"] == "LINE" and b.get("Confidence", 0) >= 70.0
    ]

    logger.info(f"[Textract-S3] Extracted {len(lines)} lines: s3://{bucket}/{key}")
    return "\n".join(lines)
