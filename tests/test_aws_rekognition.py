"""
tests/test_aws_rekognition.py
Unit tests for aws_rekognition.detect_text().
Uses mocked boto3 — no AWS credentials needed.
"""

import sys
import os
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "azure-functions"))
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")


class TestRekognitionDetectText(unittest.TestCase):
    @patch("shared.aws_rekognition.boto3")
    def test_extracts_line_detections(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.detect_text.return_value = {
            "TextDetections": [
                {"Type": "LINE", "DetectedText": "First Line", "Confidence": 99.0},
                {"Type": "WORD", "DetectedText": "First", "Confidence": 99.0},
                {"Type": "LINE", "DetectedText": "Second Line", "Confidence": 85.0},
                {"Type": "LINE", "DetectedText": "Low conf", "Confidence": 50.0},  # excluded
            ]
        }
        from shared.aws_rekognition import detect_text
        result = detect_text(b"fake")
        self.assertEqual(result, "First Line\nSecond Line")

    @patch("shared.aws_rekognition.boto3")
    def test_empty_response(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.detect_text.return_value = {"TextDetections": []}
        from shared.aws_rekognition import detect_text
        result = detect_text(b"blank")
        self.assertEqual(result, "")

    @patch("shared.aws_rekognition.boto3")
    def test_client_error_raises_runtime_error(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.detect_text.side_effect = Exception("Rekognition down")
        from shared.aws_rekognition import detect_text
        with self.assertRaises(RuntimeError) as ctx:
            detect_text(b"img")
        self.assertIn("Rekognition", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
