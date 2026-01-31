"""ReceiptGate MCP client for MetaGate startup receipts."""

from __future__ import annotations

from typing import Any

import httpx

from .config import get_settings
from .logging import get_logger


logger = get_logger(__name__)


def _normalize_endpoint(endpoint: str) -> str:
    endpoint = (endpoint or "").rstrip("/")
    if endpoint and not endpoint.endswith("/mcp"):
        endpoint = f"{endpoint}/mcp"
    return endpoint


async def emit_receipt(payload: dict[str, Any]) -> bool:
    """Emit a receipt to ReceiptGate via MCP."""
    settings = get_settings()
    if not settings.receiptgate_emit_receipts:
        return False
    if not settings.receiptgate_endpoint:
        return False

    endpoint = _normalize_endpoint(settings.receiptgate_endpoint)
    headers = {"Content-Type": "application/json"}
    if settings.receiptgate_auth_token:
        headers["Authorization"] = f"Bearer {settings.receiptgate_auth_token}"

    request_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "receiptgate.submit_receipt",
            "arguments": {"receipt": payload},
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(endpoint, json=request_payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                logger.warning("receiptgate_emit_failed", error=str(data["error"]))
                return False
            return True
    except Exception as exc:
        logger.warning("receiptgate_emit_failed", error=str(exc))
        return False
