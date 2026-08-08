#!/usr/bin/env python3
"""Validate a generated Jimeng sofa-scene prompt.

Read the prompt body from stdin or from an optional UTF-8 text file path.
Exit 0 when hard checks pass; exit 1 otherwise.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MAX_VISIBLE_CHARS = 3000
RECOMMENDED_MAX = 2500
RECOMMENDED_MIN = 1500

FORBIDDEN_PHRASES = (
    "参考图1",
    "图1",
    "图2",
    "示例图",
    "第一张图",
    "第二张图",
    "原场景图",
)

REQUIRED_GROUPS = {
    "产品唯一依据": ("唯一", "白底产品图"),
    "禁止镜像": ("不镜像", "不得镜像", "禁止镜像"),
    "稳定贴地": ("同一水平", "稳定落地", "稳定贴地"),
    "防悬空": ("悬空",),
    "画面比例": ("3:4", "3∶4"),
}


def load_text(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return sys.stdin.read()


def visible_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def cjk_length(text: str) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", help="UTF-8 text file; otherwise read stdin")
    args = parser.parse_args()

    text = load_text(args.path).strip()
    if not text:
        print("FAIL: prompt is empty")
        return 1

    visible = visible_length(text)
    cjk = cjk_length(text)
    errors: list[str] = []
    warnings: list[str] = []

    if visible > MAX_VISIBLE_CHARS:
        errors.append(f"visible characters {visible} exceed {MAX_VISIBLE_CHARS}")
    elif visible > RECOMMENDED_MAX:
        warnings.append(f"visible characters {visible} exceed recommended {RECOMMENDED_MAX}")
    elif visible < RECOMMENDED_MIN:
        warnings.append(f"visible characters {visible} are below recommended {RECOMMENDED_MIN}")

    for phrase in FORBIDDEN_PHRASES:
        if phrase in text:
            errors.append(f"forbidden phrase found: {phrase}")

    for label, alternatives in REQUIRED_GROUPS.items():
        if not any(item in text for item in alternatives):
            warnings.append(f"missing recommended constraint: {label}")

    print(f"visible_chars={visible}")
    print(f"cjk_chars={cjk}")
    for warning in warnings:
        print(f"WARN: {warning}")
    for error in errors:
        print(f"FAIL: {error}")

    if errors:
        return 1
    print("PASS: prompt satisfies hard validation rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
