"""Receipt construction helpers for MetaGate startup lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..models.db_models import StartupSession
from ..receiptgate_client import emit_receipt
from ..logging import get_logger

try:
    from legivellum.models import Receipt as CanonicalReceipt
except ImportError:
    CanonicalReceipt = None
    for parent in Path(__file__).resolve().parents:
        shared_root = parent / "LegiVellum" / "shared"
        if shared_root.exists():
            sys.path.append(str(shared_root))
            try:
                from legivellum.models import Receipt as CanonicalReceipt
            except ImportError:
                CanonicalReceipt = None
            break


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
    is_accepted = phase == "accepted"
    is_complete = phase == "complete"
    recipient_ai = session.component_key if is_accepted else session.subject_principal_key
    outcome_kind = "NA" if is_accepted else "response_text"
    outcome_text_value = "NA" if is_accepted else outcome_text
    completed_at_value = None if is_accepted else completed_at

    inputs = {
        "startup_id": str(session.id),
        "component_key": session.component_key,
        "profile_key": session.profile_key,
        "manifest_key": session.manifest_key,
        "deployment_key": session.deployment_key,
        "packet_etag": session.packet_etag,
    }
    task_body = json.dumps(inputs, sort_keys=True)

    body_payload: dict[str, Any] = {
        "startup_id": str(session.id),
        "phase": phase,
        "status": status,
        "component_key": session.component_key,
        "profile_key": session.profile_key,
        "manifest_key": session.manifest_key,
        "deployment_key": session.deployment_key,
        "packet_etag": session.packet_etag,
        "mirror_status": session.mirror_status,
        "outcome_text": outcome_text_value,
    }
    if is_complete and status == "success":
        body_payload["ready_payload"] = session.ready_payload
    if is_complete and status == "failure":
        body_payload["failure_payload"] = session.failure_payload

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
        "recipient_ai": recipient_ai,
        "trust_domain": "default",
        "phase": phase,
        "status": status,
        "realtime": False,
        "task_type": "startup",
        "task_summary": f"Startup {phase} for {session.component_key}",
        "task_body": task_body,
        "inputs": inputs,
        "expected_outcome_kind": "response_text",
        "expected_artifact_mime": "NA",
        "outcome_kind": outcome_kind,
        "outcome_text": outcome_text_value,
        "artifact_location": "NA",
        "artifact_pointer": "NA",
        "artifact_checksum": "NA",
        "artifact_size_bytes": 0,
        "artifact_mime": "NA",
        "escalation_class": "NA",
        "escalation_reason": "NA",
        "escalation_to": "NA",
        "retry_requested": False,
        "body": body_payload,
        "artifact_refs": [],
        "created_at": _iso(now),
        "stored_at": None,
        "started_at": _iso(started_at),
        "completed_at": _iso(completed_at_value),
        "read_at": None,
        "archived_at": None,
        "metadata": {
            "startup_id": str(session.id),
            "component_key": session.component_key,
            "mirror_status": session.mirror_status,
        },
    }

    if CanonicalReceipt is None:
        return base

    try:
        return CanonicalReceipt.model_validate(base).model_dump(mode="json")
    except Exception as exc:
        logger.warning("startup_receipt_validation_failed", error=str(exc))
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
