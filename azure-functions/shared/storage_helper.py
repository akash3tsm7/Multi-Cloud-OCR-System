"""
storage_helper.py
Unified storage utilities for Azure Blob Storage and AWS S3.
"""

import os
import logging
from io import BytesIO

import boto3
from azure.storage.blob import BlobServiceClient, ContentSettings

logger = logging.getLogger(__name__)

# ── Azure Blob Storage ─────────────────────────────────────────────────────────

def _azure_client() -> BlobServiceClient:
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    if not conn_str:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is not set.")
    return BlobServiceClient.from_connection_string(conn_str)


def azure_upload(container: str, blob_name: str, data: bytes, content_type: str = "text/plain") -> str:
    """Upload bytes to Azure Blob. Returns blob URL."""
    client = _azure_client()
    blob_client = client.get_blob_client(container=container, blob=blob_name)
    blob_client.upload_blob(data, overwrite=True, content_settings=ContentSettings(content_type=content_type))
    logger.info(f"[AzureBlob] Uploaded {blob_name} to container '{container}'.")
    return blob_client.url


def azure_download(container: str, blob_name: str) -> bytes:
    """Download a blob from Azure Blob Storage."""
    client = _azure_client()
    blob_client = client.get_blob_client(container=container, blob=blob_name)
    data = blob_client.download_blob().readall()
    logger.info(f"[AzureBlob] Downloaded {blob_name} from container '{container}'.")
    return data


def azure_blob_exists(container: str, blob_name: str) -> bool:
    """Check if a blob exists."""
    client = _azure_client()
    blob_client = client.get_blob_client(container=container, blob=blob_name)
    return blob_client.exists()


def azure_list_blobs(container: str, prefix: str = "") -> list:
    """List blob names in a container."""
    client = _azure_client()
    container_client = client.get_container_client(container)
    return [b.name for b in container_client.list_blobs(name_starts_with=prefix)]


# ── AWS S3 ─────────────────────────────────────────────────────────────────────

_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _s3_client():
    return boto3.client(
        "s3",
        region_name=_AWS_REGION,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


def s3_upload(bucket: str, key: str, data: bytes, content_type: str = "text/plain") -> str:
    """Upload bytes to S3. Returns s3://bucket/key URI."""
    client = _s3_client()
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    uri = f"s3://{bucket}/{key}"
    logger.info(f"[S3] Uploaded to {uri}.")
    return uri


def s3_download(bucket: str, key: str) -> bytes:
    """Download an object from S3."""
    client = _s3_client()
    response = client.get_object(Bucket=bucket, Key=key)
    data = response["Body"].read()
    logger.info(f"[S3] Downloaded s3://{bucket}/{key}.")
    return data


def s3_object_exists(bucket: str, key: str) -> bool:
    """Check if an S3 object exists."""
    client = _s3_client()
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except client.exceptions.ClientError:
        return False


def s3_list_objects(bucket: str, prefix: str = "") -> list:
    """List object keys in an S3 bucket."""
    client = _s3_client()
    response = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
    return [obj["Key"] for obj in response.get("Contents", [])]
