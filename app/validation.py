"""导入数据校验。时间一律为整数毫秒；区间为左闭右开。"""
from __future__ import annotations

from typing import Any

SLOT_FIELDS = {
    "id": ("slot_id", str),
    "material_id": ("material_id", str),
    "planned_start": ("planned_start", int),
    "duration": ("duration", int),
    "tolerance": ("tolerance", int),
    "max_pause": ("max_pause", int),
}
SEG_FIELDS = {
    "id": ("seg_id", str),
    "material_id": ("material_id", str),
    "air_start": ("air_start", int),
    "air_end": ("air_end", int),
    "src_start": ("src_start", int),
    "src_end": ("src_end", int),
}


def _is_strict_int(v: Any) -> bool:
    # bool 是 int 的子类，显式排除
    return isinstance(v, int) and not isinstance(v, bool)


def _validate_items(raw: Any, kind: str, fields: dict[str, tuple[str, type]], errors: list[str]):
    if not isinstance(raw, list):
        errors.append(f"{kind} 必须是数组")
        return []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, obj in enumerate(raw):
        prefix = f"{kind}[{i}]"
        if not isinstance(obj, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        item: dict[str, Any] = {}
        for src, (dst, typ) in fields.items():
            if src not in obj:
                errors.append(f"{prefix} 缺少字段 {src}")
                continue
            v = obj[src]
            if typ is int:
                if not _is_strict_int(v):
                    errors.append(f"{prefix}.{src} 必须是整数毫秒值")
                    continue
            else:
                if not isinstance(v, str) or not v.strip():
                    errors.append(f"{prefix}.{src} 必须是非空字符串")
                    continue
                v = v.strip()
            item[dst] = v
        if len(item) != len(fields):
            continue
        if kind == "计划广告位":
            if item["duration"] <= 0:
                errors.append(f"{prefix}.duration 必须为正整数（时长 > 0）")
                continue
            if item["tolerance"] < 0:
                errors.append(f"{prefix}.tolerance 必须为非负整数")
                continue
            if item["max_pause"] < 0:
                errors.append(f"{prefix}.max_pause 必须为非负整数")
                continue
        else:
            air_len = item["air_end"] - item["air_start"]
            src_len = item["src_end"] - item["src_start"]
            if air_len <= 0:
                errors.append(f"{prefix} 播出区间 [{air_len}] 长度必须大于 0（左闭右开）")
                continue
            if src_len <= 0:
                errors.append(f"{prefix} 素材源区间长度必须大于 0（左闭右开）")
                continue
            if air_len != src_len:
                errors.append(
                    f"{prefix} 播出区间长度 {air_len} 与素材源区间长度 {src_len} 必须相等"
                )
                continue
        if item["slot_id" if kind == "计划广告位" else "seg_id"] in seen:
            errors.append(f"{prefix} ID 重复：{item['slot_id' if kind == '计划广告位' else 'seg_id']}")
            continue
        seen.add(item["slot_id" if kind == "计划广告位" else "seg_id"])
        items.append(item)
    return items


def validate_payload(payload: Any) -> tuple[list[dict], list[dict], list[str]]:
    """返回 (slots, segments, errors)。errors 非空时前两个结果无效。"""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [], [], ["导入体必须是 JSON 对象，形如 {\"slots\": [...], \"segments\": [...]}"]
    slots = _validate_items(payload.get("slots"), "计划广告位", SLOT_FIELDS, errors)
    segments = _validate_items(payload.get("segments"), "实播片段", SEG_FIELDS, errors)
    return slots, segments, errors
