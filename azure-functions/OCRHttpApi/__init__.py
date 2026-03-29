"""
OCRHttpApi/__init__.py
Azure HTTP-triggered Function — REST API for OCR results.

Routes:
  POST /api/ocr
    Body (direct upload): { "image_base64": "<b64>", "filename": "img.jpg" }
    Body (existing blob):  { "blob_name": "img.jpg" }
    → Runs OCR and returns extracted text.

  GET /api/result/{name}
    → Fetches stored OCR result from output-results/{name}.txt
"""

import os
import json
import logging
import base64

import azure.functions as func
from shared.ocr_router import route_and_extract
from shared.storage_helper import azure_download, azure_upload, azure_blob_exists

logger = logging.getLogger(__name__)

INPUT_CONTAINER = "input-images"
OUTPUT_CONTAINER = "output-results"


def main(req: func.HttpRequest) -> func.HttpResponse:
    method = req.method.upper()

    # ── CORS preflight ────────────────────────────────────────────────────────
    if method == "OPTIONS":
        return func.HttpResponse(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, x-functions-key",
            },
        )

    # ── GET /api/result/{name} ────────────────────────────────────────────────
    if method == "GET":
        blob_name = req.route_params.get("name")
        if not blob_name:
            return _error(400, "Missing 'name' route parameter.")

        result_blob = f"{blob_name}.txt"
        if not azure_blob_exists(OUTPUT_CONTAINER, result_blob):
            return _error(404, f"Result not found for '{blob_name}'. Try POSTing first.")

        text = azure_download(OUTPUT_CONTAINER, result_blob).decode("utf-8")
        return _json_response(200, {"filename": blob_name, "text": text})

    # ── POST /api/ocr ─────────────────────────────────────────────────────────
    elif method == "POST":
        try:
            body = req.get_json()
        except ValueError:
            return _error(400, "Request body must be valid JSON.")

        # ── Path A: direct base64 upload (from browser UI) ────────────────────
        image_b64 = body.get("image_base64")
        filename  = body.get("filename", "upload.jpg")

        if image_b64:
            try:
                image_bytes = base64.b64decode(image_b64)
            except Exception as exc:
                return _error(400, f"Invalid base64 image data: {exc}")

            # Archive to input container (best-effort)
            try:
                azure_upload(
                    container=INPUT_CONTAINER,
                    blob_name=filename,
                    data=image_bytes,
                    content_type="application/octet-stream",
                )
            except Exception as e:
                logger.warning(f"Could not archive to blob (non-fatal): {e}")

            result = route_and_extract(image_bytes, filename)

            if result["error"]:
                return _error(502, f"OCR failed: {result['error']}")

            # Save result
            try:
                azure_upload(
                    container=OUTPUT_CONTAINER,
                    blob_name=f"{filename}.txt",
                    data=result["text"].encode("utf-8"),
                    content_type="text/plain",
                )
            except Exception as e:
                logger.warning(f"Could not save result to blob (non-fatal): {e}")

            return _json_response(200, {
                "filename": filename,
                "provider": result["provider"],
                "latency_ms": result["latency_ms"],
                "text": result["text"],
            })

        # ── Path B: existing blob_name flow ───────────────────────────────────
        blob_name = body.get("blob_name")
        if not blob_name:
            return _error(400, "Missing 'blob_name' or 'image_base64' in request body.")

        try:
            image_bytes = azure_download(INPUT_CONTAINER, blob_name)
        except Exception as exc:
            return _error(404, f"Image '{blob_name}' not found in '{INPUT_CONTAINER}': {exc}")

        result = route_and_extract(image_bytes, blob_name)

        if result["error"]:
            return _error(502, f"OCR failed: {result['error']}")

        azure_upload(
            container=OUTPUT_CONTAINER,
            blob_name=f"{blob_name}.txt",
            data=result["text"].encode("utf-8"),
            content_type="text/plain",
        )

        return _json_response(200, {
            "filename": blob_name,
            "provider": result["provider"],
            "latency_ms": result["latency_ms"],
            "text": result["text"],
        })

    return _error(405, f"Method '{method}' not allowed.")


def _json_response(status: int, body: dict) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(body),
        status_code=status,
        mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )


def _error(status: int, message: str) -> func.HttpResponse:
    logger.error(f"[OCRHttpApi] {status}: {message}")
    return func.HttpResponse(
        body=json.dumps({"error": message}),
        status_code=status,
        mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )
