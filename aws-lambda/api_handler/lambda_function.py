"""
aws-lambda/api_handler/lambda_function.py
AWS Lambda — REST API Handler (behind API Gateway)

Routes:
  POST /ocr
    Body: { "image_base64": "<b64>", "s3_key": "filename.ext" }  ← direct upload from UI
      OR: { "s3_key": "image.jpg" }  ← existing S3 object
    → On-demand OCR. Returns extracted text.

  GET /result/{key}
    → Fetches stored OCR result from the output bucket.
"""

import os
import json
import logging
import time
import base64
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

INPUT_BUCKET  = os.environ.get("AWS_S3_INPUT_BUCKET",  "ocr-input-bucket")
OUTPUT_BUCKET = os.environ.get("AWS_S3_OUTPUT_BUCKET", "ocr-output-bucket")
AWS_REGION    = os.environ.get("OCR_REGION", os.environ.get("AWS_REGION", "us-east-1"))

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,x-api-key,x-functions-key",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def lambda_handler(event, context):
    """API Gateway proxy integration handler."""
    method = event.get("httpMethod", "GET").upper()
    path   = event.get("path", "/")
    path_params = event.get("pathParameters") or {}

    logger.info(f"[APIHandler] {method} {path}")

    # ── CORS preflight ───────────────────────────────────────────────────────
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    # ── GET /result/{key} ────────────────────────────────────────────────────
    if method == "GET" and "key" in path_params:
        return _get_result(path_params["key"])

    # ── POST /ocr ────────────────────────────────────────────────────────────
    if method == "POST":
        try:
            body = json.loads(event.get("body") or "{}")
        except (json.JSONDecodeError, TypeError):
            return _response(400, {"error": "Request body must be valid JSON."})

        image_b64 = body.get("image_base64")
        s3_key    = body.get("s3_key", "upload.jpg")

        # ── Path A: direct base64 upload from browser UI ──────────────────
        if image_b64:
            return _run_ocr_from_b64(image_b64, s3_key)

        # ── Path B: existing S3 object ────────────────────────────────────
        if s3_key:
            return _run_ocr_from_s3(s3_key)

        return _response(400, {"error": "Missing 'image_base64' or 's3_key' in request body."})

    return _response(405, {"error": f"Method '{method}' not allowed."})


# ── Direct base64 upload ──────────────────────────────────────────────────────

def _run_ocr_from_b64(image_b64: str, s3_key: str) -> dict:
    """Decode base64 image, upload to S3, then run OCR."""
    start = time.monotonic()
    s3 = boto3.client("s3", region_name=AWS_REGION)

    # Decode
    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception as exc:
        return _response(400, {"error": f"Invalid base64 data: {exc}"})

    # Upload to input bucket (Rekognition/Textract need S3 objects)
    try:
        s3.put_object(Bucket=INPUT_BUCKET, Key=s3_key, Body=image_bytes)
        logger.info(f"[APIHandler] Uploaded {len(image_bytes)} bytes → s3://{INPUT_BUCKET}/{s3_key}")
    except Exception as exc:
        return _response(502, {"error": f"Failed to upload to S3: {exc}"})

    # Run OCR
    try:
        text, provider = _extract_text(INPUT_BUCKET, s3_key, image_bytes)
    except Exception as exc:
        return _response(502, {"error": f"OCR failed: {exc}"})

    # Save result
    result_key = f"{s3_key}.txt"
    try:
        s3.put_object(Bucket=OUTPUT_BUCKET, Key=result_key,
                      Body=text.encode("utf-8"), ContentType="text/plain")
    except Exception as exc:
        logger.warning(f"Could not save result: {exc}")

    return _response(200, {
        "s3_key":     s3_key,
        "provider":   provider,
        "latency_ms": round((time.monotonic() - start) * 1000, 2),
        "text":       text,
    })


# ── Existing S3 object ────────────────────────────────────────────────────────

def _run_ocr_from_s3(s3_key: str) -> dict:
    """On-demand OCR from an already-uploaded S3 object."""
    start = time.monotonic()
    s3 = boto3.client("s3", region_name=AWS_REGION)

    try:
        obj = s3.get_object(Bucket=INPUT_BUCKET, Key=s3_key)
        image_bytes = obj["Body"].read()
    except ClientError:
        return _response(404, {"error": f"Image '{s3_key}' not found in '{INPUT_BUCKET}'."})

    try:
        text, provider = _extract_text(INPUT_BUCKET, s3_key, image_bytes)
    except Exception as exc:
        return _response(502, {"error": f"OCR failed: {exc}"})

    result_key = f"{s3_key}.txt"
    s3.put_object(Bucket=OUTPUT_BUCKET, Key=result_key,
                  Body=text.encode("utf-8"), ContentType="text/plain")

    return _response(200, {
        "s3_key":     s3_key,
        "provider":   provider,
        "latency_ms": round((time.monotonic() - start) * 1000, 2),
        "text":       text,
    })


# ── Fetch stored result ───────────────────────────────────────────────────────

def _get_result(key: str) -> dict:
    s3 = boto3.client("s3", region_name=AWS_REGION)
    result_key = f"{key}.txt"
    try:
        obj = s3.get_object(Bucket=OUTPUT_BUCKET, Key=result_key)
        text = obj["Body"].read().decode("utf-8")
        return _response(200, {"key": key, "text": text})
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NoSuchKey":
            return _response(404, {"error": f"Result for '{key}' not found. POST /ocr first."})
        return _response(502, {"error": str(exc)})


# ── OCR dispatch ──────────────────────────────────────────────────────────────

def _extract_text(bucket: str, key: str, image_bytes: bytes) -> tuple[str, str]:
    """Choose Rekognition or Textract based on filename, return (text, provider)."""
    name_lower = key.lower()
    is_doc = "_doc_" in name_lower or name_lower.endswith(".pdf")

    if is_doc:
        text = _textract(bucket, key)
        return text, "aws_textract"
    else:
        text = _rekognition(bucket, key)
        return text, "aws_rekognition"


def _rekognition(bucket: str, key: str) -> str:
    client = boto3.client("rekognition", region_name=AWS_REGION)
    response = client.detect_text(
        Image={"S3Object": {"Bucket": bucket, "Name": key}}
    )
    lines = [
        d["DetectedText"]
        for d in response.get("TextDetections", [])
        if d["Type"] == "LINE" and d["Confidence"] >= 70.0
    ]
    return "\n".join(lines)


def _textract(bucket: str, key: str) -> str:
    client = boto3.client("textract", region_name=AWS_REGION)
    try:
        response = client.detect_document_text(
            Document={"S3Object": {"Bucket": bucket, "Name": key}}
        )
        lines = [
            b["Text"]
            for b in response.get("Blocks", [])
            if b["BlockType"] == "LINE" and b.get("Confidence", 0) >= 70.0
        ]
        return "\n".join(lines)
    except client.exceptions.UnsupportedDocumentException as exc:
        raise RuntimeError(f"Unsupported document format: {exc}") from exc
    except Exception as exc:
        if "SubscriptionRequiredException" in str(type(exc).__name__) or "SubscriptionRequired" in str(exc):
            logger.warning("Textract not subscribed — falling back to Rekognition")
            return _rekognition(bucket, key)
        raise


# ── HTTP response helper ──────────────────────────────────────────────────────

def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }
