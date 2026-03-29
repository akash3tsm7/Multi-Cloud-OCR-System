"""
azure_vision.py
Azure Computer Vision Read API wrapper.
Sends image bytes to Azure OCR and returns extracted text.
"""

import os
import time
import logging
from io import BytesIO

from azure.cognitiveservices.vision.computervision import ComputerVisionClient
from azure.cognitiveservices.vision.computervision.models import OperationStatusCodes
from msrest.authentication import CognitiveServicesCredentials

logger = logging.getLogger(__name__)

def _get_client() -> ComputerVisionClient:
    key = os.environ.get("AZURE_VISION_KEY", "")
    endpoint = os.environ.get("AZURE_VISION_ENDPOINT", "")
    if not key or not endpoint:
        raise RuntimeError("Missing Azure Vision configurations in environment variables.")
        
    return ComputerVisionClient(
        endpoint,
        CognitiveServicesCredentials(key),
    )


def extract_text(image_bytes: bytes, timeout_sec: int = 30) -> str:
    """
    Send image bytes to Azure Computer Vision Read API.

    Args:
        image_bytes: Raw image data.
        timeout_sec: Max seconds to wait for async read operation.

    Returns:
        Extracted text as a single newline-joined string.

    Raises:
        RuntimeError: If OCR operation fails or times out.
    """
    client = _get_client()
    stream = BytesIO(image_bytes)

    # Submit async Read operation
    response = client.read_in_stream(stream, raw=True)
    operation_id = response.headers["Operation-Location"].split("/")[-1]
    logger.info(f"[AzureVision] Submitted read operation: {operation_id}")

    # Poll for result
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        result = client.get_read_result(operation_id)
        status = result.status

        if status == OperationStatusCodes.succeeded:
            lines = []
            for page in result.analyze_result.read_results:
                for line in page.lines:
                    lines.append(line.text)
            text = "\n".join(lines)
            logger.info(f"[AzureVision] Extracted {len(lines)} lines.")
            return text

        elif status == OperationStatusCodes.failed:
            raise RuntimeError(f"Azure Vision Read operation failed: {result}")

        # Still running — wait and retry
        time.sleep(1)

    raise RuntimeError(
        f"Azure Vision Read operation timed out after {timeout_sec}s (id={operation_id})"
    )
