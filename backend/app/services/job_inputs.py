from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Asset, PromptRow, PromptTemplate
from app.services.ai_config import load_ai_configuration
from app.services.worker import resolve_job_prompts


@dataclass(frozen=True)
class FrozenJobInput:
    fingerprint: str
    snapshot: dict[str, object]


def freeze_job_input(
    session: Session,
    row: PromptRow,
    settings: Settings,
    *,
    force_regenerate: bool = False,
) -> FrozenJobInput:
    if not row.scene_asset_id or not row.sofa_asset_id:
        raise ValueError("ROW_NOT_READY")
    scene = session.get(Asset, row.scene_asset_id)
    sofa = session.get(Asset, row.sofa_asset_id)
    if scene is None or sofa is None or scene.status != "READY" or sofa.status != "READY":
        raise ValueError("ROW_NOT_READY")
    configuration = load_ai_configuration(session, settings)
    active_template = session.scalar(
        select(PromptTemplate).where(PromptTemplate.is_active.is_(True))
    )
    system_prompt, user_prompt = resolve_job_prompts(session)
    template_snapshot: dict[str, object] = {
        "id": active_template.id if active_template else None,
        "version": active_template.version if active_template else None,
        "content_hash": active_template.content_hash if active_template else None,
        "system_prompt": system_prompt,
        "user_prompt_template": user_prompt,
        "output_schema_json": active_template.output_schema_json if active_template else None,
    }
    ai_snapshot: dict[str, object] = {
        "provider": configuration.provider,
        "base_url": configuration.base_url,
        "model": configuration.model,
        "chat_path": configuration.chat_path,
        "timeout_seconds": configuration.timeout_seconds,
    }
    payload = {
        "row_revision": row.row_revision,
        "scene": scene.sha256 or scene.id,
        "sofa": sofa.sha256 or sofa.id,
        "requirements": row.custom_requirements,
        "view_override": row.view_override_json,
        "include_person": row.include_person,
        "person_action": row.person_action,
        "output_platform": row.output_platform,
        "prompt_length": row.prompt_length,
        "camera_preference": row.camera_preference,
        "template": template_snapshot,
        "ai": ai_snapshot,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    snapshot: dict[str, object] = {
        "row_id": row.id,
        "row_revision": row.row_revision,
        "scene_asset": {"id": scene.id, "url": scene.public_url, "sha256": scene.sha256},
        "sofa_asset": {"id": sofa.id, "url": sofa.public_url, "sha256": sofa.sha256},
        "row_options": {
            "custom_requirements": row.custom_requirements,
            "include_person": row.include_person,
            "view_override": _snapshot_view_override(row),
        },
        "template": template_snapshot,
        "ai": ai_snapshot,
        "force_regenerate": force_regenerate,
    }
    return FrozenJobInput(fingerprint=fingerprint, snapshot=snapshot)


def _snapshot_view_override(row: PromptRow) -> dict[str, object] | None:
    if not row.view_override_enabled or not row.view_override_json:
        return None
    try:
        value = json.loads(row.view_override_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None
