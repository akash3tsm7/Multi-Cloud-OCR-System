"""
tests/integration_test.py
End-to-end integration test — Azure + AWS side-by-side OCR comparison.

Usage:
    python tests/integration_test.py --image tests/sample.jpg

Requires live credentials in environment (copy from .env.example).
"""

import os
import sys
import time
import json
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Add azure-functions/shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "azure-functions"))


def run_azure_ocr(image_path: str) -> dict:
    """Upload image to Azure Blob, trigger OCR, read result."""
    from shared.storage_helper import azure_upload, azure_download
    from shared.ocr_router import route_and_extract

    filename = os.path.basename(image_path)
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    logger.info(f"[Azure] Running OCR on {filename} ({len(image_bytes)} bytes)")
    start = time.monotonic()

    # Upload to Azure input-images
    azure_upload("input-images", filename, image_bytes, content_type="image/jpeg")

    # Run OCR directly (simulates what BlobImageTrigger would do)
    result = route_and_extract(image_bytes, filename)

    if result["error"]:
        return {"cloud": "azure", "error": result["error"], "text": ""}

    # Save result to output-results
    azure_upload(
        "output-results", f"{filename}.txt",
        result["text"].encode("utf-8"), content_type="text/plain"
    )

    elapsed = round((time.monotonic() - start) * 1000, 2)
    logger.info(f"[Azure] Done in {elapsed}ms via {result['provider']}")
    return {
        "cloud": "azure",
        "provider": result["provider"],
        "latency_ms": elapsed,
        "char_count": len(result["text"]),
        "text": result["text"],
    }


def run_aws_ocr(image_path: str) -> dict:
    """Upload image to AWS S3, run Rekognition/Textract, read result."""
    import boto3

    filename = os.path.basename(image_path)
    input_bucket = os.environ.get("AWS_S3_INPUT_BUCKET", "ocr-input-bucket")
    output_bucket = os.environ.get("AWS_S3_OUTPUT_BUCKET", "ocr-output-bucket")
    region = os.environ.get("AWS_REGION", "us-east-1")

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    logger.info(f"[AWS] Running OCR on {filename} ({len(image_bytes)} bytes)")
    start = time.monotonic()

    s3 = boto3.client("s3", region_name=region)

    # Upload to S3
    s3.put_object(Bucket=input_bucket, Key=filename, Body=image_bytes, ContentType="image/jpeg")

    # Choose provider
    is_document = "_doc_" in filename.lower()
    provider = "textract" if is_document else "rekognition"

    try:
        if provider == "rekognition":
            reko = boto3.client("rekognition", region_name=region)
            response = reko.detect_text(
                Image={"S3Object": {"Bucket": input_bucket, "Name": filename}}
            )
            lines = [
                d["DetectedText"]
                for d in response.get("TextDetections", [])
                if d["Type"] == "LINE" and d["Confidence"] >= 70.0
            ]
        else:
            textract = boto3.client("textract", region_name=region)
            response = textract.detect_document_text(
                Document={"S3Object": {"Bucket": input_bucket, "Name": filename}}
            )
            lines = [
                b["Text"]
                for b in response.get("Blocks", [])
                if b["BlockType"] == "LINE" and b.get("Confidence", 0) >= 70.0
            ]

        text = "\n".join(lines)

        # Save to output bucket
        s3.put_object(
            Bucket=output_bucket, Key=f"{filename}.txt",
            Body=text.encode("utf-8"), ContentType="text/plain"
        )

        elapsed = round((time.monotonic() - start) * 1000, 2)
        logger.info(f"[AWS] Done in {elapsed}ms via {provider}")
        return {
            "cloud": "aws",
            "provider": provider,
            "latency_ms": elapsed,
            "char_count": len(text),
            "text": text,
        }

    except Exception as exc:
        logger.error(f"[AWS] Error: {exc}")
        return {"cloud": "aws", "error": str(exc), "text": ""}


def print_comparison(azure_result: dict, aws_result: dict):
    print("\n" + "=" * 70)
    print(" MULTI-CLOUD OCR COMPARISON RESULTS")
    print("=" * 70)
    for r in [azure_result, aws_result]:
        cloud = r["cloud"].upper()
        if r.get("error"):
            print(f"\n❌ [{cloud}] ERROR: {r['error']}")
        else:
            print(f"\n✅ [{cloud}] Provider: {r.get('provider')} | "
                  f"Latency: {r.get('latency_ms')}ms | "
                  f"Chars: {r.get('char_count')}")
            print(f"   Text preview: {r['text'][:200]!r}{'...' if len(r['text']) > 200 else ''}")

    # Similarity check
    if azure_result.get("text") and aws_result.get("text"):
        azure_words = set(azure_result["text"].lower().split())
        aws_words = set(aws_result["text"].lower().split())
        if azure_words or aws_words:
            overlap = len(azure_words & aws_words) / len(azure_words | aws_words) * 100
            print(f"\n📊 Word overlap between Azure and AWS: {overlap:.1f}%")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Multi-cloud OCR integration test")
    parser.add_argument("--image", required=True, help="Path to image file to test")
    parser.add_argument("--cloud", choices=["azure", "aws", "both"], default="both")
    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(f"ERROR: Image not found: {args.image}")
        sys.exit(1)

    azure_result = {"cloud": "azure", "text": "", "skipped": True}
    aws_result = {"cloud": "aws", "text": "", "skipped": True}

    if args.cloud in ("azure", "both"):
        azure_result = run_azure_ocr(args.image)

    if args.cloud in ("aws", "both"):
        aws_result = run_aws_ocr(args.image)

    print_comparison(azure_result, aws_result)


if __name__ == "__main__":
    main()
