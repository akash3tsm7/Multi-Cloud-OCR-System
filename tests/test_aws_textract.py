"""
tests/test_aws_textract.py
Unit tests for aws_textract.analyze_document().
Uses mocked boto3 — no AWS credentials needed.
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "azure-functions"))
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")


class TestTextractAnalyzeDocument(unittest.TestCase):
    @patch("shared.aws_textract.boto3")
    def test_extracts_line_blocks(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.detect_document_text.return_value = {
            "Blocks": [
                {"BlockType": "PAGE"},
                {"BlockType": "LINE", "Text": "Invoice No: 123", "Confidence": 99.5},
                {"BlockType": "LINE", "Text": "Total: $42.00", "Confidence": 87.0},
                {"BlockType": "WORD", "Text": "Invoice", "Confidence": 99.0},
                {"BlockType": "LINE", "Text": "Faint text", "Confidence": 40.0},  # excluded
            ]
        }
        from shared.aws_textract import analyze_document
        result = analyze_document(b"fake doc")
        self.assertEqual(result, "Invoice No: 123\nTotal: $42.00")

    @patch("shared.aws_textract.boto3")
    def test_empty_document(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.detect_document_text.return_value = {"Blocks": []}
        from shared.aws_textract import analyze_document
        result = analyze_document(b"blank")
        self.assertEqual(result, "")

    @patch("shared.aws_textract.boto3")
    def test_textract_error_raises_runtime_error(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.detect_document_text.side_effect = Exception("Textract error")
        from shared.aws_textract import analyze_document
        with self.assertRaises(RuntimeError) as ctx:
            analyze_document(b"bad")
        self.assertIn("Textract", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
