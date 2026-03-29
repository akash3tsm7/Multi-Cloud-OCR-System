"""
ocr_router.py
Smart OCR routing and failover control plane.
Decides which cloud OCR service to use based on:
  - Image size (< 1MB → prefer Azure Vision, >= 1MB → prefer AWS)
  - Filename hint (_doc_ prefix → AWS Textract for documents)
  - Provider availability (failover if primary is down)
"""

import time
import logging

logger = logging.getLogger(__name__)

# Size threshold in bytes (1 MB)
SIZE_THRESHOLD_BYTES = 1_000_000


def route_and_extract(image_bytes: bytes, filename: str) -> dict:
    """
    Main entry point. Routes to the appropriate OCR provider and returns result.

    Returns:
        {
            "provider": "azure" | "aws_rekognition" | "aws_textract",
            "text": "<extracted text>",
            "latency_ms": <float>,
            "error": None | "<error message>"
        }
    """
    image_size = len(image_bytes)
    is_document = _is_document(filename)
    primary = _choose_primary(image_size, is_document)

    logger.info(
        f"[Router] file={filename} size={image_size}B is_document={is_document} → primary={primary}"
    )

    # Try primary
    result = _call_provider(primary, image_bytes, filename)
    if result["error"] is None:
        return result

    # Failover to secondary
    secondary = _choose_secondary(primary)
    logger.warning(
        f"[Router] Primary '{primary}' failed: {result['error']}. Failing over to '{secondary}'."
    )
    result = _call_provider(secondary, image_bytes, filename)
    if result["error"] is None:
        return result

    # Both failed
    logger.error("[Router] All OCR providers failed.")
    return {
        "provider": "none",
        "text": "",
        "latency_ms": 0,
        "error": "All OCR providers unavailable.",
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_document(filename: str) -> bool:
    """Returns True if filename hints at a document (use Textract)."""
    name = filename.lower()
    return "_doc_" in name or name.endswith(".pdf")


def _choose_primary(image_size: int, is_document: bool) -> str:
    """Choose primary provider based on size and type."""
    if is_document:
        return "aws_textract"
    if image_size < SIZE_THRESHOLD_BYTES:
        return "azure"
    return "aws_rekognition"


def _choose_secondary(primary: str) -> str:
    """Choose fallback provider."""
    fallback_map = {
        "azure": "aws_rekognition",
        "aws_rekognition": "azure",
        "aws_textract": "azure",
    }
    return fallback_map.get(primary, "aws_rekognition")


def _call_provider(provider: str, image_bytes: bytes, filename: str) -> dict:
    """Call the specified provider and return a standardised result dict."""
    start = time.monotonic()
    result = {"provider": provider, "text": "", "latency_ms": 0.0, "error": None}

    try:
        if provider == "azure":
            from shared.azure_vision import extract_text
            result["text"] = extract_text(image_bytes)

        elif provider == "aws_rekognition":
            from shared.aws_rekognition import detect_text
            result["text"] = detect_text(image_bytes)

        elif provider == "aws_textract":
            from shared.aws_textract import analyze_document
            result["text"] = analyze_document(image_bytes)

        else:
            raise ValueError(f"Unknown provider: {provider}")

    except Exception as exc:
        result["error"] = str(exc)
        logger.error(f"[Router] Provider '{provider}' error: {exc}")

    result["latency_ms"] = round((time.monotonic() - start) * 1000, 2)
    logger.info(
        f"[Router] provider={provider} latency={result['latency_ms']}ms error={result['error']}"
    )
    return result
