from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_NEGATIVE_PROMPT = "镜像，强行转正，增减模块，改变产品颜色和材质，产品变形，文字，水印"
WRAPPER_KEYS = ("data", "result", "output", "response", "config")


class NeutralModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SofaView(NeutralModel):
    view_type: str = "uncertain"
    view_label_zh: str = "无法判断"
    near_end: str = ""
    far_end: str = ""
    camera_position: str = ""
    space_extension: str = ""
    angle_bucket: str = "unknown"
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class SofaProduct(NeutralModel):
    category: str = ""
    color: str = ""
    material: str = ""
    module_description: str = ""
    immutable_features: list[str] = Field(default_factory=list)


class SceneObservations(NeutralModel):
    space_type: str = ""
    style: str = ""
    layout: str = ""
    architecture: list[str] = Field(default_factory=list)
    floor: str = ""
    window: str = ""
    coffee_table: str = ""
    rug: str = ""
    dining_kitchen: str = ""
    lighting: str = ""
    camera_language: str = ""
    visible_evidence: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)


class CompositionPlan(NeutralModel):
    camera_adjustment: str = ""
    sofa_placement: str = ""
    coffee_table_adjustment: str = ""
    rug_adjustment: str = ""
    window_adjustment: str = ""
    dining_kitchen_adjustment: str = ""
    person_placement: str = ""


class Review(NeutralModel):
    required: bool = False
    reasons: list[str] = Field(default_factory=list)


class PromptResultPayload(NeutralModel):
    schema_version: Literal[1] = 1
    sofa_view: SofaView = Field(default_factory=SofaView)
    sofa_product: SofaProduct = Field(default_factory=SofaProduct)
    scene_observations: SceneObservations = Field(default_factory=SceneObservations)
    composition_plan: CompositionPlan = Field(default_factory=CompositionPlan)
    positive_prompt: str = ""
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT
    review: Review = Field(default_factory=Review)
    warnings: list[str] = Field(default_factory=list)


MODEL_FIELDS: dict[str, dict[str, type[Any] | tuple[type[Any], ...]]] = {
    "sofa_view": {
        "view_type": str,
        "view_label_zh": str,
        "near_end": str,
        "far_end": str,
        "camera_position": str,
        "space_extension": str,
        "angle_bucket": str,
        "confidence": (int, float),
        "evidence": list,
    },
    "sofa_product": {
        "category": str,
        "color": str,
        "material": str,
        "module_description": str,
        "immutable_features": list,
    },
    "scene_observations": {
        "space_type": str,
        "style": str,
        "layout": str,
        "architecture": list,
        "floor": str,
        "window": str,
        "coffee_table": str,
        "rug": str,
        "dining_kitchen": str,
        "lighting": str,
        "camera_language": str,
        "visible_evidence": list,
        "unknown_fields": list,
    },
    "composition_plan": {
        "camera_adjustment": str,
        "sofa_placement": str,
        "coffee_table_adjustment": str,
        "rug_adjustment": str,
        "window_adjustment": str,
        "dining_kitchen_adjustment": str,
        "person_placement": str,
    },
    "review": {"required": bool, "reasons": list},
}


def _extract_text(payload: Any) -> Any:
    if isinstance(payload, list):
        return "".join(
            part.get("text", "")
            for part in payload
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return payload


def _parse_json_text(text: str) -> dict[str, Any]:
    unfenced = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).replace("```", "")
    start = unfenced.find("{")
    end = unfenced.rfind("}")
    if start < 0 or end <= start:
        return {}
    parsed = json.loads(unfenced[start : end + 1])
    return parsed if isinstance(parsed, dict) else {}


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    current = payload
    for _ in range(len(WRAPPER_KEYS)):
        wrapped = next(
            (current[key] for key in WRAPPER_KEYS if isinstance(current.get(key), dict)),
            None,
        )
        if wrapped is None:
            break
        current = wrapped
    return current


def _sanitize_module(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    expected = MODEL_FIELDS[name]
    return {
        key: field_value
        for key, field_value in value.items()
        if key in expected and isinstance(field_value, expected[key])
    }


def normalize_provider_payload(payload: Any) -> PromptResultPayload:
    extracted = _extract_text(payload)
    if isinstance(extracted, str):
        try:
            extracted = _parse_json_text(extracted)
        except (json.JSONDecodeError, TypeError, ValueError):
            extracted = {}
    if not isinstance(extracted, dict):
        extracted = {}
    data = _unwrap(extracted)
    data = _normalize_provider_aliases(data)
    sanitized: dict[str, Any] = {}
    for module_name in MODEL_FIELDS:
        sanitized[module_name] = _sanitize_module(module_name, data.get(module_name))
    for key in ("positive_prompt", "negative_prompt"):
        if isinstance(data.get(key), str):
            sanitized[key] = data[key]
    if isinstance(data.get("warnings"), list):
        sanitized["warnings"] = [item for item in data["warnings"] if isinstance(item, str)]
    return PromptResultPayload.model_validate(sanitized)


def _normalize_provider_aliases(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    raw_view = data.get("sofa_view")
    if isinstance(raw_view, dict):
        view = dict(raw_view)
        orientation = view.get("orientation")
        view_name = view.get("view_angle") or view.get("viewpoint")
        if isinstance(view_name, str):
            view.setdefault("view_type", view_name)
            view.setdefault("view_label_zh", view_name)
        if isinstance(view.get("visible_sides"), list):
            view.setdefault("evidence", view["visible_sides"])
        if isinstance(orientation, dict):
            if isinstance(orientation.get("near_end"), str):
                view.setdefault("near_end", orientation["near_end"])
            if isinstance(orientation.get("far_end"), str):
                view.setdefault("far_end", orientation["far_end"])
            if isinstance(orientation.get("proximal_end"), str):
                view.setdefault("near_end", orientation["proximal_end"])
            if isinstance(orientation.get("distal_end"), str):
                view.setdefault("far_end", orientation["distal_end"])
        normalized["sofa_view"] = view

    review = data.get("review")
    if isinstance(review, dict) and not isinstance(review.get("required"), bool):
        review = dict(review)
        review["required"] = False
        review["reasons"] = []
        normalized["review"] = review
    return normalized
