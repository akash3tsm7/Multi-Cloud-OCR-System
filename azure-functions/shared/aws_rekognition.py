"""
aws_rekognition.py
AWS Rekognition detect_text wrapper.
Best for general images and photos with overlaid text.
"""

import os
import logging
import boto3

logger = logging.getLogger(__name__)

_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _get_client():
    return boto3.client(
        "rekognition",
        region_name=_AWS_REGION,
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )


def detect_text(image_bytes: bytes) -> str:
    """
    Run AWS Rekognition detect_text on raw image bytes.

    Args:
        image_bytes: Raw image data (JPEG/PNG, max 5MB for bytes API).

    Returns:
        Extracted text as a newline-joined string (LINE detections only).

    Raises:
        RuntimeError: If Rekognition call fails.
    """
    client = _get_client()

    try:
        response = client.detect_text(Image={"Bytes": image_bytes})
    except Exception as exc:
        raise RuntimeError(f"Rekognition detect_text failed: {exc}") from exc

    detections = response.get("TextDetections", [])
    # Filter to LINE level only (avoid duplicating WORD entries)
    lines = [
        d["DetectedText"]
        for d in detections
        if d["Type"] == "LINE" and d["Confidence"] >= 70.0
    ]

    logger.info(f"[Rekognition] Detected {len(lines)} lines (confidence >= 70%).")
    return "\n".join(lines)


def detect_text_from_s3(bucket: str, key: str) -> str:
    """
    Run Rekognition detect_text on an S3 object (avoids 5MB byte limit).

    Args:
        bucket: S3 bucket name.
        key: S3 object key.

    Returns:
        Extracted text as a newline-joined string.
    """
    client = _get_client()

    try:
        response = client.detect_text(
            Image={"S3Object": {"Bucket": bucket, "Name": key}}
        )
    except Exception as exc:
        raise RuntimeError(f"Rekognition detect_text (S3) failed: {exc}") from exc

    detections = response.get("TextDetections", [])
    lines = [
        d["DetectedText"]
        for d in detections
        if d["Type"] == "LINE" and d["Confidence"] >= 70.0
    ]

    logger.info(f"[Rekognition-S3] Detected {len(lines)} lines: s3://{bucket}/{key}")
    return "\n".join(lines)
