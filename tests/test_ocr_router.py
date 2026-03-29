"""
tests/test_ocr_router.py
Unit tests for ocr_router.py smart routing and failover logic.
Uses mocked provider calls — no cloud credentials needed.
"""

import sys
import os
import types
import unittest
from unittest.mock import patch, MagicMock

# Add azure-functions/ to path so shared/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "azure-functions"))

# Stub heavy dependencies before importing
for mod in [
    "azure.cognitiveservices.vision.computervision",
    "azure.cognitiveservices.vision.computervision.models",
    "msrest", "msrest.authentication",
    "azure.storage.blob",
    "boto3",
]:
    parts = mod.split(".")
    for i in range(1, len(parts) + 1):
        pkg = ".".join(parts[:i])
        if pkg not in sys.modules:
            sys.modules[pkg] = types.ModuleType(pkg)

from shared.ocr_router import (
    _choose_primary, _choose_secondary, _is_document, route_and_extract
)


class TestChoosePrimary(unittest.TestCase):
    def test_small_general_image_uses_azure(self):
        self.assertEqual(_choose_primary(500_000, False), "azure")

    def test_large_image_uses_rekognition(self):
        self.assertEqual(_choose_primary(2_000_000, False), "aws_rekognition")

    def test_document_always_uses_textract(self):
        self.assertEqual(_choose_primary(100, True), "aws_textract")
        self.assertEqual(_choose_primary(5_000_000, True), "aws_textract")

    def test_boundary_exactly_1mb_uses_rekognition(self):
        # 1_000_000 is NOT < 1MB threshold
        self.assertEqual(_choose_primary(1_000_000, False), "aws_rekognition")


class TestChooseSecondary(unittest.TestCase):
    def test_azure_falls_back_to_rekognition(self):
        self.assertEqual(_choose_secondary("azure"), "aws_rekognition")

    def test_rekognition_falls_back_to_azure(self):
        self.assertEqual(_choose_secondary("aws_rekognition"), "azure")

    def test_textract_falls_back_to_azure(self):
        self.assertEqual(_choose_secondary("aws_textract"), "azure")


class TestIsDocument(unittest.TestCase):
    def test_doc_hint_in_name(self):
        self.assertTrue(_is_document("invoice_doc_001.jpg"))

    def test_pdf_extension(self):
        self.assertTrue(_is_document("report.pdf"))

    def test_regular_image(self):
        self.assertFalse(_is_document("photo.jpg"))

    def test_uppercase_extension(self):
        self.assertFalse(_is_document("PHOTO.JPG"))


class TestRouteAndExtract(unittest.TestCase):
    @patch("shared.ocr_router._call_provider")
    def test_primary_success_returns_result(self, mock_call):
        mock_call.return_value = {
            "provider": "azure", "text": "Hello World",
            "latency_ms": 120.0, "error": None
        }
        result = route_and_extract(b"x" * 500_000, "photo.jpg")
        self.assertIsNone(result["error"])
        self.assertEqual(result["text"], "Hello World")
        self.assertEqual(result["provider"], "azure")

    @patch("shared.ocr_router._call_provider")
    def test_failover_on_primary_failure(self, mock_call):
        # Primary fails, secondary succeeds
        mock_call.side_effect = [
            {"provider": "azure", "text": "", "latency_ms": 50.0, "error": "timeout"},
            {"provider": "aws_rekognition", "text": "Fallback text",
             "latency_ms": 300.0, "error": None},
        ]
        result = route_and_extract(b"x" * 500_000, "photo.jpg")
        self.assertIsNone(result["error"])
        self.assertEqual(result["text"], "Fallback text")

    @patch("shared.ocr_router._call_provider")
    def test_all_providers_fail(self, mock_call):
        mock_call.return_value = {
            "provider": "azure", "text": "", "latency_ms": 10.0, "error": "unavailable"
        }
        result = route_and_extract(b"x" * 500_000, "photo.jpg")
        self.assertEqual(result["provider"], "none")
        self.assertIn("unavailable", result["error"])


if __name__ == "__main__":
    unittest.main()
