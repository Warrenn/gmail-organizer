"""Shared helpers for the feedback-loop Lambda handlers.

Each Lambda is a thin wrapper around an existing ``gmail_cleanup`` CLI command:
it loads the credential it needs from SSM into an environment variable (never a
file — same fileless contract as scripts/feedback-loop.sh), reads/writes the
S3 artifact bucket, and shells into the existing command logic.

Boto3 clients are created lazily and cached so the tests' moto mocks (which set
fake AWS creds + region via env) are picked up, and so a warm Lambda reuses the
client across invocations.
"""

from __future__ import annotations

import os
from pathlib import Path

import boto3

SSM_PREFIX = os.environ.get("SSM_PREFIX", "/cleanup-gmail")

_ssm_client = None
_s3_client = None


def ssm_client():
    global _ssm_client
    if _ssm_client is None:
        _ssm_client = boto3.client("ssm")
    return _ssm_client


def s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def get_secret(name: str) -> str:
    """Fetch a decrypted SSM SecureString. ``name`` is the bare param name
    (e.g. ``gmail-token-json``); it is resolved under ``SSM_PREFIX``."""
    full = name if name.startswith("/") else f"{SSM_PREFIX}/{name}"
    resp = ssm_client().get_parameter(Name=full, WithDecryption=True)
    value = resp["Parameter"]["Value"]
    if not value:
        raise RuntimeError(f"empty SSM parameter: {full}")
    return value


def load_secret_into_env(env_var: str, ssm_name: str) -> None:
    """Load an SSM SecureString into ``os.environ[env_var]`` — never to disk.
    The value dies with the (warm-reused) process; nothing is persisted."""
    os.environ[env_var] = get_secret(ssm_name)


def _key(prefix: str, name: str) -> str:
    prefix = (prefix or "").strip("/")
    return f"{prefix}/{name}" if prefix else name


def upload(bucket: str, name: str, local_path: str | os.PathLike, prefix: str = "") -> str:
    """Upload a local file to ``s3://bucket/<prefix>/name``. Returns the key."""
    key = _key(prefix, name)
    s3_client().upload_file(str(local_path), bucket, key)
    return key


def download(bucket: str, name: str, local_path: str | os.PathLike, prefix: str = "") -> bool:
    """Download ``s3://bucket/<prefix>/name`` to ``local_path``. Returns True on
    success, False if the object does not exist (caller decides if that's fatal)."""
    key = _key(prefix, name)
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        s3_client().download_file(bucket, key, str(local_path))
        return True
    except s3_client().exceptions.ClientError as e:  # type: ignore[attr-defined]
        code = e.response.get("Error", {}).get("Code")
        if code in ("404", "NoSuchKey"):
            return False
        raise


def env(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"required environment variable not set: {name}")
    return val  # type: ignore[return-value]
