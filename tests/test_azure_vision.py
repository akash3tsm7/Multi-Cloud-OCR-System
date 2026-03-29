"""
tests/test_azure_vision.py
Unit tests for azure_vision.extract_text().
Mocks the ComputerVision client — no Azure credentials needed.
"""

import sys
import os
import types
import unittest
from unittest.mock import patch, MagicMock

# Stub imports
for mod in ["msrest", "msrest.authentication",
            "azure.cognitiveservices.vision.computervision",
            "azure.cognitiveservices.vision.computervision.models"]:
    parts = mod.split(".")
    for i in range(1, len(parts) + 1):
        pkg = ".".join(parts[:i])
        if pkg not in sys.modules:
            sys.modules[pkg] = types.ModuleType(pkg)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "azure-functions"))

os.environ.setdefault("AZURE_VISION_KEY", "test-key")
os.environ.setdefault("AZURE_VISION_ENDPOINT", "https://mock.cognitiveservices.azure.com/")


class TestAzureVisionExtractText(unittest.TestCase):
    @patch("shared.azure_vision.ComputerVisionClient")
    def test_successful_extraction(self, MockClient):
        # Build a mock result with two lines
        mock_line1 = MagicMock()
        mock_line1.text = "Hello World"
        mock_line2 = MagicMock()
        mock_line2.text = "Test Line Two"

        mock_read_result = MagicMock()
        mock_read_result.lines = [mock_line1, mock_line2]

        mock_final = MagicMock()
        mock_final.status = "succeeded"
        mock_final.analyze_result.read_results = [mock_read_result]

        from azure.cognitiveservices.vision.computervision.models import OperationStatusCodes
        OperationStatusCodes.succeeded = "succeeded"
        OperationStatusCodes.failed = "failed"

        client = MockClient.return_value
        client.read_in_stream.return_value.headers = {
            "Operation-Location": "https://mock/operations/abc123"
        }
        client.get_read_result.return_value = mock_final

        from shared.azure_vision import extract_text
        result = extract_text(b"fake image data")
        self.assertEqual(result, "Hello World\nTest Line Two")

    @patch("shared.azure_vision.ComputerVisionClient")
    def test_failed_operation_raises(self, MockClient):
        from azure.cognitiveservices.vision.computervision.models import OperationStatusCodes
        OperationStatusCodes.succeeded = "succeeded"
        OperationStatusCodes.failed = "failed"

        mock_final = MagicMock()
        mock_final.status = "failed"

        client = MockClient.return_value
        client.read_in_stream.return_value.headers = {
            "Operation-Location": "https://mock/operations/fail999"
        }
        client.get_read_result.return_value = mock_final

        from shared.azure_vision import extract_text
        with self.assertRaises(RuntimeError):
            extract_text(b"bad image")


if __name__ == "__main__":
    unittest.main()
