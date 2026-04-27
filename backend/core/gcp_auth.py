"""Helpers to configure Google credentials for Vertex AI at runtime."""

import json
import os
import tempfile
from pathlib import Path

from core.logging_config import logger
from core.settings import settings


def configure_google_credentials_from_env() -> None:
    """
    Configure GOOGLE_APPLICATION_CREDENTIALS from inline JSON env var.

    If GOOGLE_APPLICATION_CREDENTIALS is already set, this function is a no-op.
    If GOOGLE_APPLICATION_CREDENTIALS_JSON is provided, it writes a temporary
    file and exports its path in GOOGLE_APPLICATION_CREDENTIALS.
    """
    if not settings.VERTEX_ENABLED:
        return

    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        logger.debug("GOOGLE_APPLICATION_CREDENTIALS already set; skipping inline credential bootstrap")
        return

    raw_json = settings.GOOGLE_APPLICATION_CREDENTIALS_JSON.strip()
    if not raw_json:
        logger.debug("GOOGLE_APPLICATION_CREDENTIALS_JSON is empty; expecting mounted credentials file")
        return

    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError("GOOGLE_APPLICATION_CREDENTIALS_JSON is not valid JSON") from exc

    required_keys = {"type", "client_email", "private_key", "project_id"}
    missing = [key for key in required_keys if key not in payload]
    if missing:
        raise ValueError(f"GOOGLE_APPLICATION_CREDENTIALS_JSON missing keys: {', '.join(missing)}")

    temp_dir = Path(tempfile.gettempdir())
    cred_path = temp_dir / "vertex_service_account.json"

    with open(cred_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)

    try:
        os.chmod(cred_path, 0o600)
    except OSError:
        # Best-effort on platforms that do not support chmod semantics.
        pass

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cred_path)
    logger.debug("Configured GOOGLE_APPLICATION_CREDENTIALS from inline JSON secret")
