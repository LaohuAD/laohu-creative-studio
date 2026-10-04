#!/usr/bin/env python3
"""P1 全平台源目录与能力覆盖审计（只读）。

依据：《老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md》第 4 节、第 16 节 P1。

两条互不替代的审计线（§4.5 要求分开报告）：
  1) 全量发现目录审计 discovery —— 直接读取仓库存量静态档案与区域快照，
     不经过用户启用过滤；没有存量全量快照的平台明确标 not_observed。
  2) 用户启用投影 enabled —— 走 ModelCapabilityRegistry.build_catalog，
     与应用运行时完全同一条代码路径（§13.5 前后端同一份约束数据）。

安全约束：
- 默认只读静态档案与快照；只有显式 --include-config 才读 data/api_providers.json，
  且只导出白名单标识字段，不输出任何凭据字段。
- 全程只读 data/，不回写真实用户配置。

用法：
    python tools/audit_model_coverage.py [--include-config] [--out-dir docs/model-selection-v2]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import model_capabilities as mc  # noqa: E402

FIELDS = [
    "audit_line", "source_scope", "source_file", "source_revision",
    "capability_provider_id", "connection_id", "region_id",
    "catalog_model_id", "request_model_id", "endpoint_id",
    "legacy_family_id", "canonical_family_id",
    "model_version", "edition_id", "operation", "node_type", "output_contract",
    "profile_revision", "evidence_level", "readiness", "runnable",
    "identity_mapping_status", "enabled_in_connection", "enabled_in_module",
    "adapter_id", "parameter_keys", "discovery_status", "unresolved_reasons",
]

CONFIG_FIELDS = ("chat_models", "image_models", "video_models", "audio_models", "music_models")

# 哪些平台在本地存在“全量发现目录”的存量来源；其余平台只有静态档案＋用户配置。
DISCOVERY_SOURCES = {
    "ai-money": "stored_snapshot:ai-money-catalog.json",
    "runninghub": "stored_snapshot:runninghub-{region}.json + runninghub-official-public.json",
}


def sha12(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def load_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def csv_safe(value) -> str:
    """防 CSV 公式注入；真实 ID 原文仍保留在 JSON 中（§13.1）。"""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def output_contract(profile: dict) -> str:
    output = profile.get("output") if isinstance(profile, dict) else None
    if not isinstance(output, dict):
        return ""
    parts = [str(output.get("media_type") or "")]
    for key in ("min", "max"):
        if output.get(key) is not None:
            parts.append(f"{key}={output[key]}")
    if output.get("async"):
        parts.append("async")
    return ",".join(p for p in parts if p)


def blank_record(**overrides) -> dict:
    record = {key: "" for key in FIELDS}
    record.update(overrides)
    return record


def record_from_profile(
    profile: dict, *, audit_line: str, provider_id: str, connection_id: str, region_id: str,
    source_scope: str, source_file: str, source_revision: str, adapter_id: str,
    catalog_model_id: str = "", discovery_status: str = "", enabled: object = "",
) -> dict:
    parameters = profile.get("parameters") if isinstance(profile.get("parameters"), dict) else {}
    mapping = profile.get("request_mapping") if isinstance(profile.get("request_mapping"), dict) else {}
    readiness = mc.ModelCapabilityRegistry.readiness(profile)
    reasons = []
    if readiness == "needs_profile":
        reasons.append("PROFILE_UNCONFIRMED")
    elif readiness == "adapter_missing":
        reasons.append("ADAPTER_MISSING")
    elif readiness == "deprecated":
        reasons.append("PROFILE_DEPRECATED")
    if not parameters:
        reasons.append("NO_PARAMETER_FIELDS")
    return blank_record(
        audit_line=audit_line,
        source_scope=source_scope,
        source_file=source_file,
        source_revision=source_revision,
        capability_provider_id=provider_id,
        connection_id=connection_id,
        region_id=region_id or "",
        catalog_model_id=catalog_model_id or str(profile.get("model_id") or ""),
        request_model_id=str(profile.get("request_model_id") or ""),
        endpoint_id=str(profile.get("endpoint_id") or profile.get("endpoint") or ""),
        legacy_family_id=str(profile.get("family_id") or ""),
        canonical_family_id="",
        model_version=str(profile.get("version") or ""),
        edition_id=str(profile.get("variant_id") or ""),
        operation=str(profile.get("operation") or ""),
        node_type=str(profile.get("node_type") or ""),
        output_contract=output_contract(profile),
        profile_revision=str(profile.get("revision") or profile.get("profile_revision") or ""),
        evidence_level=str(profile.get("evidence_level") or ""),
        readiness=readiness,
        runnable=readiness == "ready",
        identity_mapping_status="provider_local",
        enabled_in_connection=enabled,
        enabled_in_module="not_implemented",
        adapter_id=adapter_id,
        parameter_keys="|".join(sorted(parameters.keys())),
        discovery_status=discovery_status,
        unresolved_reasons="|".join(reasons),
    )


def discovery_records(registry: mc.ModelCapabilityRegistry, loaded: dict, provider_id: str) -> list[dict]:
    """全量发现目录：只读存量静态档案与快照，不经用户启用过滤。"""
    records: list[dict] = []
    profile_set = loaded["profiles"].get(provider_id) or {}
    provider_file = ""
    for ref in loaded["registry"].get("providers") or []:
        if str(ref.get("provider_id") or "").strip() == provider_id:
            provider_file = str(ref.get("file") or "")
            break
    revision = sha12(ROOT / provider_file)
    adapter_id = str(profile_set.get("provider_id") or provider_id)
    stored = DISCOVERY_SOURCES.get(provider_id, "not_observed")

    for model in profile_set.get("models") or []:
        if isinstance(model, dict):
            records.append(record_from_profile(
                model, audit_line="discovery", provider_id=provider_id, connection_id="",
                region_id="", source_scope="static_profile", source_file=provider_file,
                source_revision=revision, adapter_id=adapter_id, discovery_status=stored,
            ))

    if provider_id == "runninghub":
        for region in ("global", "cn"):
            snap = ROOT / "data" / "model_capabilities" / "snapshots" / f"runninghub-{region}.json"
            snap_revision = sha12(snap)
            try:
                profiles = registry.runninghub_snapshot_profiles(region)
            except Exception:  # pragma: no cover
                profiles = {}
            for model_id, profile in profiles.items():
                records.append(record_from_profile(
                    profile, audit_line="discovery", provider_id=provider_id, connection_id="",
                    region_id=region, source_scope=f"region_snapshot:{region}",
                    source_file=f"data/model_capabilities/snapshots/runninghub-{region}.json",
                    source_revision=snap_revision, adapter_id=adapter_id,
                    catalog_model_id=model_id, discovery_status=stored,
                ))
        official = ROOT / "data" / "model_capabilities" / "snapshots" / "runninghub-official-public.json"
        try:
            official_profiles = registry.runninghub_official_snapshot_profiles()
        except Exception:  # pragma: no cover
            official_profiles = {}
        for model_id, profile in official_profiles.items():
            records.append(record_from_profile(
                profile, audit_line="discovery", provider_id=provider_id, connection_id="",
                region_id="", source_scope="official_public_registry",
                source_file="data/model_capabilities/snapshots/runninghub-official-public.json",
                source_revision=sha12(official), adapter_id=adapter_id,
                catalog_model_id=model_id, discovery_status=stored,
            ))

    if provider_id == "ai-money":
        catalog_path = ROOT / "data" / "model_capabilities" / "snapshots" / "ai-money-catalog.json"
        catalog = load_json(catalog_path) or {}
        catalog_revision = sha12(catalog_path)
        for field_name in CONFIG_FIELDS:
            node_types = [nt for nt, f in mc.NODE_MODEL_FIELDS.items() if f == field_name]
            for model_id in catalog.get(field_name) or []:
                if not isinstance(model_id, str) or not model_id.strip():
                    continue
                profile = None
                for node_type in node_types:
                    profile = mc.dynamic_profile_for_model(provider_id, model_id, node_type)
                    if profile:
                        break
                if profile is None:
                    records.append(blank_record(
                        audit_line="discovery", source_scope="discovery_catalog",
                        source_file="data/model_capabilities/snapshots/ai-money-catalog.json",
                        source_revision=catalog_revision, capability_provider_id=provider_id,
                        catalog_model_id=model_id, readiness="needs_profile", runnable=False,
                        identity_mapping_status="unresolved", enabled_in_module="not_implemented",
                        adapter_id=adapter_id, discovery_status=stored,
                        unresolved_reasons="PROFILE_UNCONFIRMED",
                    ))
                else:
                    records.append(record_from_profile(
                        profile, audit_line="discovery", provider_id=provider_id, connection_id="",
                        region_id="", source_scope="discovery_catalog",
                        source_file="data/model_capabilities/snapshots/ai-money-catalog.json",
                        source_revision=catalog_revision, adapter_id=adapter_id,
                        catalog_model_id=model_id, discovery_status=stored,
                    ))
    return records


def enabled_records(registry: mc.ModelCapabilityRegistry, connections: list[dict]) -> list[dict]:
    """用户启用投影：与应用运行时同一条 build_catalog 代码路径。"""
    catalog = registry.build_catalog(connections)
    region_by_connection = {str(c.get("id") or ""): str(c.get("rh_region") or "") for c in connections}
    records: list[dict] = []
    for provider in catalog.get("providers") or []:
        provider_id = str(provider.get("id") or "")
        capability_id = str(provider.get("capability_provider_id") or provider_id)
        for model in provider.get("models") or []:
            if not isinstance(model, dict):
                continue
            regions = model.get("regions") or [region_by_connection.get(provider_id, "") or ""]
            for region in regions:
                scoped = model
                region_profiles = model.get("region_profiles")
                if isinstance(region_profiles, dict) and region in region_profiles:
                    scoped = region_profiles[region]
                records.append(record_from_profile(
                    scoped, audit_line="enabled", provider_id=capability_id,
                    connection_id=provider_id, region_id=region or "",
                    source_scope="user_config_projection",
                    source_file="data/api_providers.json", source_revision="",
                    adapter_id=capability_id,
                    catalog_model_id=str(model.get("model_id") or ""),
                    enabled=True,
                ))
    return records


def summarise(discovery: list[dict], enabled: list[dict], registered: list[str], connections: list[dict]) -> dict:
    def tally(records):
        out = {}
        for r in records:
            entry = out.setdefault(r["capability_provider_id"], {
                "source_entries": 0, "ready": 0, "needs_profile": 0,
                "adapter_missing": 0, "deprecated": 0, "unresolved_identity": 0,
            })
            entry["source_entries"] += 1
            key = r["readiness"] if r["readiness"] in entry else "needs_profile"
            entry[key] += 1
            if r["identity_mapping_status"] in {"unresolved", "provider_local"}:
                entry["unresolved_identity"] += 1
        return out

    interfaces = {
        (r["capability_provider_id"], r["region_id"], r["catalog_model_id"], r["node_type"], r["operation"])
        for r in discovery if r["catalog_model_id"]
    }
    return {
        "discovery": {
            "providers": registered,
            "raw_entries": len(discovery),
            "deduped_interfaces": len(interfaces),
            "capability_profiles": sum(1 for r in discovery if r["readiness"] in {"ready", "adapter_missing", "deprecated"}),
            "needs_profile": sum(1 for r in discovery if r["readiness"] == "needs_profile"),
            "adapter_gap": sum(1 for r in discovery if r["readiness"] == "adapter_missing"),
            "deprecated": sum(1 for r in discovery if r["readiness"] == "deprecated"),
            "per_provider": tally(discovery),
            "discovery_status": {
                p: DISCOVERY_SOURCES.get(p, "not_observed") for p in registered
            },
        },
        "enabled": {
            "records": len(enabled),
            "executable_options": sum(1 for r in enabled if r["runnable"] is True),
            "needs_profile": sum(1 for r in enabled if r["readiness"] == "needs_profile"),
            "adapter_gap": sum(1 for r in enabled if r["readiness"] == "adapter_missing"),
            "per_provider": tally(enabled),
        },
        "module_candidates": "not_implemented",
        "user_connections": [
            {
                "connection_id": str(c.get("id") or ""),
                "capability_provider_id": mc.ModelCapabilityRegistry.capability_provider_id(c),
                "enabled": bool(c.get("enabled")),
                "region_id": str(c.get("rh_region") or ""),
                "counts": {f: len(c.get(f) or []) for f in CONFIG_FIELDS},
            }
            for c in connections
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="P1 全平台源目录与能力覆盖审计（只读）")
    parser.add_argument("--include-config", action="store_true")
    parser.add_argument("--out-dir", default="docs/model-selection-v2")
    args = parser.parse_args()

    registry = mc.ModelCapabilityRegistry(ROOT)
    loaded = registry.load()
    registered = [
        str(ref.get("provider_id") or "").strip()
        for ref in loaded["registry"].get("providers") or []
        if str(ref.get("provider_id") or "").strip()
    ]

    discovery: list[dict] = []
    for provider_id in registered:
        discovery.extend(discovery_records(registry, loaded, provider_id))

    enabled: list[dict] = []
    connections: list[dict] = []
    config_status = "skipped"
    if args.include_config:
        raw = load_json(ROOT / "data" / "api_providers.json")
        if isinstance(raw, list):
            connections = [c for c in raw if isinstance(c, dict)]
            config_status = "read"
        elif isinstance(raw, dict) and isinstance(raw.get("providers"), list):
            connections = [c for c in raw["providers"] if isinstance(c, dict)]
            config_status = "read"
        else:
            config_status = "unreadable"
        if connections:
            enabled = enabled_records(registry, connections)

    payload = {
        "generated_by": "tools/audit_model_coverage.py",
        "plan": "老胡创意工作台_统一模型选择与参数配置_V2_执行规划.md §4 / §16 P1",
        "config_included": args.include_config,
        "config_status": config_status,
        "registered_providers": registered,
        "discovery_record_count": len(discovery),
        "enabled_record_count": len(enabled),
        "summary": summarise(discovery, enabled, registered, connections),
        "discovery_records": discovery,
        "enabled_records": enabled,
    }

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "01-provider-coverage.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with open(out_dir / "01-provider-coverage.csv", "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for record in discovery + enabled:
            writer.writerow({key: csv_safe(record.get(key)) for key in FIELDS})

    summary = payload["summary"]
    print(f"注册平台 {len(registered)} 个；发现记录 {len(discovery)} 条；启用投影 {len(enabled)} 条；用户配置 {config_status}")
    print(f"发现目录可执行 {summary['discovery']['capability_profiles']}；待补 {summary['discovery']['needs_profile']}；适配缺口 {summary['discovery']['adapter_gap']}")
    print(f"用户启用可执行选项 {summary['enabled']['executable_options']}；待补 {summary['enabled']['needs_profile']}；适配缺口 {summary['enabled']['adapter_gap']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
