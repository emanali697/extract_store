"""Cloud Storage helpers for Firebase Functions."""
from __future__ import annotations

import os
import tempfile
import mimetypes
from pathlib import Path

import google.auth
from google.auth.credentials import Signing
from google.auth.transport.requests import Request
from google.cloud import storage

from config import STORAGE_BUCKET

_client = None


def get_client() -> storage.Client:
    global _client
    if _client is None:
        _client = storage.Client()
    return _client


def bucket() -> storage.Bucket:
    return get_client().bucket(STORAGE_BUCKET)


def video_path(job_id: str) -> str:
    """Storage path for a job's uploaded video."""
    return f"jobs/{job_id}/video.mp4"


def job_output_prefix(job_id: str) -> str:
    """Storage prefix for all pipeline outputs for a job."""
    return f"jobs/{job_id}/outputs/"


def upload_bytes(path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """Upload raw bytes to Cloud Storage."""
    blob = bucket().blob(path)
    blob.upload_from_string(data, content_type=content_type)


def upload_file(local_path: str | Path, storage_path: str,
                content_type: str = "application/octet-stream") -> None:
    """Upload a local file to Cloud Storage."""
    blob = bucket().blob(storage_path)
    blob.upload_from_filename(str(local_path), content_type=content_type)


def download_file(storage_path: str, local_path: str | Path) -> None:
    """Download a Cloud Storage object to a local path."""
    blob = bucket().blob(storage_path)
    blob.download_to_filename(str(local_path))


def download_to_temp(storage_path: str, suffix: str = "") -> str:
    """Download a Cloud Storage object to a temporary file and return the path."""
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    download_file(storage_path, tmp_path)
    return tmp_path


def upload_dir(local_dir: str | Path, storage_prefix: str) -> None:
    """Upload all files from a local directory to a Storage prefix."""
    local_dir = Path(local_dir)
    for f in local_dir.rglob("*"):
        if f.is_file():
            rel = f.relative_to(local_dir)
            storage_path = f"{storage_prefix}{rel.as_posix()}"
            content_type = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            upload_file(f, storage_path, content_type=content_type)


def download_dir(storage_prefix: str, local_dir: str | Path) -> None:
    """Download all files under a Storage prefix to a local directory."""
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    b = bucket()
    blobs = b.list_blobs(prefix=storage_prefix)
    for blob in blobs:
        rel = Path(blob.name).relative_to(storage_prefix)
        local_path = local_dir / rel
        local_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(local_path))


def delete(storage_path: str) -> None:
    """Delete a Cloud Storage object."""
    blob = bucket().blob(storage_path)
    if blob.exists():
        blob.delete()


def signed_url(
    storage_path: str,
    expiration: int = 3600,
    response_type: str | None = None,
) -> str:
    """Generate a signed URL for a Storage object."""
    client = get_client()
    blob = client.bucket(STORAGE_BUCKET).blob(storage_path)
    credentials = client._credentials
    common = {
        "expiration": expiration,
        "version": "v4",
    }
    if response_type:
        common["response_type"] = response_type
    if isinstance(credentials, Signing):
        return blob.generate_signed_url(**common, credentials=credentials)

    # Cloud Run uses metadata-server credentials without a local private key.
    # Supplying its access token and service-account email makes the storage
    # library sign through IAM Credentials (signBlob).
    signing_credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    signing_credentials.refresh(Request())
    service_account_email = getattr(
        signing_credentials, "service_account_email", None
    )
    if not service_account_email:
        raise RuntimeError("runtime service account email is unavailable")
    return blob.generate_signed_url(
        **common,
        credentials=signing_credentials,
        service_account_email=service_account_email,
        access_token=signing_credentials.token,
    )


def exists(storage_path: str) -> bool:
    """Check if a Storage object exists."""
    blob = bucket().blob(storage_path)
    return blob.exists()


def read_text(storage_path: str, encoding: str = "utf-8") -> str:
    """Download a Storage object and return its contents as text."""
    blob = bucket().blob(storage_path)
    return blob.download_as_text(encoding=encoding)
