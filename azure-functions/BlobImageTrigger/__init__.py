"""
BlobImageTrigger/__init__.py
Azure Function — Blob Storage Trigger

Triggered automatically when an image is uploaded to the 'input-images' container.
Extracts text via the smart OCR router (Azure Vision or AWS fallback),
then stores the result in the 'output-results' container.
"""

import os
import json
import logging

import azure.functions as func
from shared.ocr_router import route_and_extract
from shared.storage_helper import azure_upload, s3_upload

logger = logging.getLogger(__name__)

OUTPUT_CONTAINER = "output-results"
AWS_OUTPUT_BUCKET = os.environ.get("AWS_S3_OUTPUT_BUCKET", "ocr-output-bucket")


def main(myblob: func.InputStream):
    blob_name = myblob.name.split("/")[-1]  # e.g. "book_page.jpg"
    image_bytes = myblob.read()

    logger.info(f"[BlobImageTrigger] Processing: {blob_name} ({len(image_bytes)} bytes)")

    # ── Route to OCR provider ─────────────────────────────────────────────────
    result = route_and_extract(image_bytes, blob_name)

    if result["error"]:
        logger.error(f"[BlobImageTrigger] OCR failed for {blob_name}: {result['error']}")
        _save_error(blob_name, result)
        return

    extracted_text = result["text"]
    logger.info(
        f"[BlobImageTrigger] OCR success via '{result['provider']}' "
        f"in {result['latency_ms']}ms. {len(extracted_text)} chars extracted."
    )

    # ── Save result to Azure Blob (output-results) ────────────────────────────
    output_blob_name = f"{blob_name}.txt"
    azure_upload(
        container=OUTPUT_CONTAINER,
        blob_name=output_blob_name,
        data=extracted_text.encode("utf-8"),
        content_type="text/plain",
    )
    logger.info(f"[BlobImageTrigger] Saved to Azure Blob: {OUTPUT_CONTAINER}/{output_blob_name}")

    # ── Mirror result to AWS S3 (cross-cloud redundancy) ─────────────────────
    try:
        s3_upload(
            bucket=AWS_OUTPUT_BUCKET,
            key=output_blob_name,
            data=extracted_text.encode("utf-8"),
            content_type="text/plain",
        )
        logger.info(f"[BlobImageTrigger] Mirrored result to S3: {AWS_OUTPUT_BUCKET}/{output_blob_name}")
    except Exception as exc:
        logger.warning(f"[BlobImageTrigger] S3 mirror failed (non-critical): {exc}")

    # ── Save metadata alongside result ────────────────────────────────────────
    metadata = {
        "filename": blob_name,
        "provider": result["provider"],
        "latency_ms": result["latency_ms"],
        "char_count": len(extracted_text),
        "line_count": extracted_text.count("\n") + 1,
    }
    azure_upload(
        container=OUTPUT_CONTAINER,
        blob_name=f"{blob_name}.meta.json",
        data=json.dumps(metadata, indent=2).encode("utf-8"),
        content_type="application/json",
    )


def _save_error(blob_name: str, result: dict):
    """Save error info to output container for debugging."""
    error_data = json.dumps({"filename": blob_name, "error": result["error"]}, indent=2)
    azure_upload(
        container=OUTPUT_CONTAINER,
        blob_name=f"{blob_name}.error.json",
        data=error_data.encode("utf-8"),
        content_type="application/json",
    )
