"""Receipt construction helpers for MetaGate startup lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..models.db_models import StartupSession
from ..receiptgate_client import emit_receipt
from ..logging import get_logger


logger = get_logger(__name__)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.isoformat()


def build_startup_receipt(
    *,
    session: StartupSession,
    phase: str,
    status: str,
    outcome_text: str,
    completed_at: datetime | None,
) -> dict[str, Any]:
    """Build a startup lifecycle receipt payload."""
    now = datetime.now(timezone.utc)
    task_id = f"startup-{session.id}"
    started_at = session.opened_at or now

    base: dict[str, Any] = {
        "schema_version": "1.0",
        "tenant_id": session.tenant_key or "default",
        "receipt_id": str(uuid4()),
        "task_id": task_id,
        "parent_task_id": "NA",
        "caused_by_receipt_id": "NA",
        "dedupe_key": f"startup:{session.id}:{phase}",
        "attempt": 0,
        "from_principal": session.subject_principal_key,
        "for_principal": session.subject_principal_key,
        "source_system": "metagate",
        "recipient_ai": session.component_key,
        "trust_domain": "default",
        "phase": phase,
        "status": status,
        "realtime": False,
        "task_type": "startup",
        "task_summary": f"Startup {phase} for {session.component_key}",
        "task_body": f"Startup session {session.id} for {session.component_key}",
        "inputs": {
            "startup_id": str(session.id),
            "component_key": session.component_key,
            "profile_key": session.profile_key,
            "manifest_key": session.manifest_key,
            "deployment_key": session.deployment_key,
            "packet_etag": session.packet_etag,
        },
        "expected_outcome_kind": "response_text",
        "expected_artifact_mime": "NA",
        "outcome_text": outcome_text,
        "artifact_location": "NA",
        "artifact_pointer": "NA",
        "artifact_checksum": "NA",
        "artifact_size_bytes": 0,
        "artifact_mime": "NA",
        "escalation_class": "NA",
        "escalation_reason": "NA",
        "escalation_to": "NA",
        "retry_requested": False,
        "created_at": _iso(session.opened_at or now),
        "stored_at": None,
        "started_at": _iso(started_at),
        "completed_at": _iso(completed_at),
        "read_at": None,
        "archived_at": None,
        "metadata": {
            "startup_id": str(session.id),
            "component_key": session.component_key,
            "mirror_status": session.mirror_status,
        },
    }

    if phase == "accepted":
        base.update(
            {
                "status": "NA",
                "outcome_kind": "NA",
                "outcome_text": "NA",
                "completed_at": None,
            }
        )
    else:
        base.update(
            {
                "outcome_kind": "response_text",
            }
        )

    return base


async def emit_startup_receipt(
    *,
    session: StartupSession,
    phase: str,
    status: str,
    outcome_text: str,
    completed_at: datetime | None,
) -> None:
    """Emit a startup lifecycle receipt to ReceiptGate."""
    payload = build_startup_receipt(
        session=session,
        phase=phase,
        status=status,
        outcome_text=outcome_text,
        completed_at=completed_at,
    )

    success = await emit_receipt(payload)
    if success:
        logger.info(
            "startup_receipt_emitted",
            receipt_id=payload.get("receipt_id"),
            startup_id=str(session.id),
            phase=phase,
            status=status,
        )
    else:
        logger.warning(
            "startup_receipt_emit_skipped",
            startup_id=str(session.id),
            phase=phase,
            status=status,
        )
