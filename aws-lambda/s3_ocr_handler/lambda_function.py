"""
aws-lambda/s3_ocr_handler/lambda_function.py
AWS Lambda — S3 Event Trigger

Triggered automatically when an image is uploaded to 'ocr-input-bucket'.
Runs OCR via Rekognition (general images) or Textract (documents),
saves result to 'ocr-output-bucket', and optionally mirrors to Azure Blob.
"""

import os
import json
import time
import logging
import urllib.parse
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

INPUT_BUCKET = os.environ.get("AWS_S3_INPUT_BUCKET", "ocr-input-bucket")
OUTPUT_BUCKET = os.environ.get("AWS_S3_OUTPUT_BUCKET", "ocr-output-bucket")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def lambda_handler(event, context):
    """
    Entry point for S3 ObjectCreated event.
    Processes each uploaded image through OCR.
    """
    results = []

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        size = record["s3"]["object"].get("size", 0)

        logger.info(f"[S3OCRHandler] Processing: s3://{bucket}/{key} ({size} bytes)")

        result = _process_image(bucket, key, size)
        results.append(result)

    return {
        "statusCode": 200,
        "body": json.dumps({"processed": len(results), "results": results})
    }


def _process_image(bucket: str, key: str, size: int) -> dict:
    """Download image from S3, run OCR, save result."""
    start = time.monotonic()
    result = {"key": key, "provider": None, "char_count": 0, "error": None}

    try:
        # Download image from S3
        s3 = boto3.client("s3", region_name=AWS_REGION)
        response = s3.get_object(Bucket=bucket, Key=key)
        image_bytes = response["Body"].read()

        # Route: Textract for documents, Rekognition for general images
        is_document = _is_document(key)
        provider = "aws_textract" if is_document else "aws_rekognition"
        text = _run_ocr(provider, bucket, key, image_bytes)

        result["provider"] = provider
        result["char_count"] = len(text)

        # Save result to output bucket
        output_key = f"{key}.txt"
        s3.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=output_key,
            Body=text.encode("utf-8"),
            ContentType="text/plain",
        )

        # Save metadata
        metadata = {
            "filename": key,
            "provider": provider,
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
            "char_count": len(text),
            "line_count": text.count("\n") + 1,
        }
        s3.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=f"{key}.meta.json",
            Body=json.dumps(metadata, indent=2).encode("utf-8"),
            ContentType="application/json",
        )

        logger.info(f"[S3OCRHandler] Done: {key} → {len(text)} chars via {provider}")

    except Exception as exc:
        logger.error(f"[S3OCRHandler] Error processing {key}: {exc}")
        result["error"] = str(exc)
        # Save error to output bucket
        try:
            s3 = boto3.client("s3", region_name=AWS_REGION)
            s3.put_object(
                Bucket=OUTPUT_BUCKET,
                Key=f"{key}.error.json",
                Body=json.dumps({"key": key, "error": str(exc)}).encode("utf-8"),
                ContentType="application/json",
            )
        except Exception:
            pass

    return result


def _is_document(key: str) -> bool:
    """Returns True if the key hints at a document (use Textract)."""
    name = key.lower()
    return "_doc_" in name or name.endswith(".pdf")


def _run_ocr(provider: str, bucket: str, key: str, image_bytes: bytes) -> str:
    """Run the chosen OCR provider and return extracted text."""
    region = AWS_REGION

    if provider == "aws_rekognition":
        client = boto3.client("rekognition", region_name=region)
        response = client.detect_text(
            Image={"S3Object": {"Bucket": bucket, "Name": key}}
        )
        detections = response.get("TextDetections", [])
        lines = [
            d["DetectedText"]
            for d in detections
            if d["Type"] == "LINE" and d["Confidence"] >= 70.0
        ]
        return "\n".join(lines)

    elif provider == "aws_textract":
        client = boto3.client("textract", region_name=region)
        response = client.detect_document_text(
            Document={"S3Object": {"Bucket": bucket, "Name": key}}
        )
        blocks = response.get("Blocks", [])
        lines = [
            b["Text"]
            for b in blocks
            if b["BlockType"] == "LINE" and b.get("Confidence", 0) >= 70.0
        ]
        return "\n".join(lines)

    raise ValueError(f"Unknown provider: {provider}")
