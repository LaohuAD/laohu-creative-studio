"""音乐创作项目的版本化内容与共享素材引用。"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Callable, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from canvas_core.json_store import DataFileError
from studio_projects import StudioProjectConflict, StudioProjectNotFound, StudioProjectStore, _clean_project_id, _guard_local_write


MAX_TEXT_BYTES = 2 * 1024 * 1024
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SCORE_FORMATS = {"abc", "musicxml", "midi"}
TIMED_LYRIC_MAX_ROWS = 5000


def music_source_sha256(music: Mapping[str, Any]) -> str:
    source = {key: str(music.get(key) or "") for key in ("title", "lyrics", "style_prompt", "notes", "cover_prompt")}
    source["score_refs"] = copy.deepcopy(music.get("score_refs") or [])
    source["reference_audio_refs"] = copy.deepcopy(music.get("reference_audio_refs") or [])
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class TitleCandidateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=240)


class MusicReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    asset_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    result_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    format: Optional[str] = None


class TimedLyricInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: float = Field(ge=0, le=86400)
    end: Optional[float] = Field(default=None, ge=0, le=86400)
    text: str = Field(min_length=1, max_length=2000)


class MusicPutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    title: Optional[str] = None
    lyrics: Optional[str] = None
    style_prompt: Optional[str] = None
    notes: Optional[str] = None
    cover_prompt: Optional[str] = None
    title_candidates: Optional[dict[str, TitleCandidateInput]] = None
    selected_title_candidate_id: Optional[str] = None
    score_refs: Optional[list[MusicReferenceInput]] = None
    reference_audio_refs: Optional[list[MusicReferenceInput]] = None
    audio_refs: Optional[list[MusicReferenceInput]] = None
    cover_refs: Optional[list[MusicReferenceInput]] = None
    selected_audio_variant_id: Optional[str] = None
    selected_cover_variant_id: Optional[str] = None
    timed_lyrics: Optional[dict[str, list[TimedLyricInput]]] = None


class MusicGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: str = Field(min_length=1, max_length=16)
    slot: str = Field(min_length=1, max_length=16)
    output_node_id: str = Field(min_length=1, max_length=160)
    client_operation_id: str = Field(min_length=1, max_length=160)
    base_revision: Optional[int] = Field(default=None, ge=1)
    request: dict[str, Any] = Field(default_factory=dict)


class StudioMusicStore:
    """音乐源文和历史引用复用 StudioProjectStore，不复制媒体文件。"""

    def __init__(self, project_store: StudioProjectStore,
                 resolve_media_reference: Callable[[str, str], Mapping[str, Any] | None] | None = None,
                 read_media_reference: Callable[[str, str], bytes | None] | None = None):
        self.project_store = project_store
        self.resolve_media_reference = resolve_media_reference
        self.read_media_reference = read_media_reference

    @staticmethod
    def _music(record: Mapping[str, Any]) -> dict[str, Any]:
        raw = record.get("music")
        if not isinstance(raw, dict):
            raise DataFileError("音乐项目记录损坏，原文件已保留。")
        return raw

    def _resolve_ref(self, raw: Mapping[str, Any], *, expected_kind: str = "") -> dict[str, Any]:
        asset_id = str(raw.get("asset_id") or "").strip()
        result_id = str(raw.get("result_id") or "").strip()
        if bool(asset_id) == bool(result_id):
            raise HTTPException(400, "音乐素材引用必须且只能包含一个 asset_id 或 result_id")
        if self.resolve_media_reference is None:
            raise HTTPException(503, "共享素材读取服务尚未接入，不能保存素材引用")
        resolved = self.resolve_media_reference(asset_id, result_id)
        if not isinstance(resolved, Mapping):
            raise HTTPException(400, "音乐素材不存在或文件已缺失")
        kind = str(resolved.get("kind") or "").strip().lower()
        mime = str(resolved.get("mime") or "").strip().lower()
        url = str(resolved.get("url") or "")
        name = str(resolved.get("name") or "")
        if kind not in {"audio", "image", "text", "file"} or not mime or not name or not url.startswith(("/api/materials/", "/api/results/")):
            raise HTTPException(400, "音乐素材引用缺少稳定地址、名称或可识别类型")
        if expected_kind and kind != expected_kind:
            raise HTTPException(400, f"该位置只接受 {expected_kind} 类型素材")
        value = {
            # Stable IDs are derived by the server; clients cannot forge variants or references.
            "id": self._reference_id(asset_id, result_id),
            "asset_id": asset_id or None,
            "result_id": result_id or None,
            "url": url,
            "name": name,
            "mime": mime,
            "kind": kind,
        }
        if raw.get("format") is not None:
            format_name = str(raw.get("format") or "").strip().lower()
            if format_name not in SCORE_FORMATS:
                raise HTTPException(400, "乐谱格式只允许 abc、musicxml 或 midi")
            if kind not in {"text", "file"}:
                raise HTTPException(400, "乐谱引用必须是共享文本或文件结果")
            value["format"] = format_name
        return value

    @staticmethod
    def _reference_id(asset_id: str, result_id: str) -> str:
        key = f"asset\0{asset_id}" if asset_id else f"result\0{result_id}"
        return "ref_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _merge_refs(existing: list[Any], additions: list[dict[str, Any]], *, field: str) -> list[dict[str, Any]]:
        merged = [copy.deepcopy(item) for item in existing if isinstance(item, dict)]
        by_identity = {(str(item.get("asset_id") or ""), str(item.get("result_id") or "")): item for item in merged}
        for item in additions:
            identity = (str(item.get("asset_id") or ""), str(item.get("result_id") or ""))
            previous = by_identity.get(identity)
            if previous is not None:
                if field == "score_refs" and previous.get("format") != item.get("format"):
                    raise HTTPException(409, "同一乐谱素材已经以其他格式登记")
                continue
            merged.append(copy.deepcopy(item))
            by_identity[identity] = item
        return merged

    def get(self, project_id: str) -> dict[str, Any]:
        project_id = _clean_project_id(project_id)
        with self.project_store.lock:
            record = self.project_store.read_music_record(project_id)
            music = copy.deepcopy(self._music(record))
            music["revision"] = max(1, int(record.get("revision") or 1))
            music["updated_at"] = int(record.get("updated_at") or 0)
            music["project_id"] = project_id
            music["source_sha256"] = music_source_sha256(music)
            music["source_versions"] = self._project_source_versions(music.get("source_versions") or [])
            music["title_candidates"] = self._project_candidates(music.get("title_candidates"))
            music["score_refs"] = self._project_refs(music.get("score_refs"), score=True)
            music["reference_audio_refs"] = self._project_refs(music.get("reference_audio_refs"), expected_kind="audio")
            music["cover_variants"] = self._project_history(music.get("cover_variants"), "image")
            music["audio_variants"] = self._project_history(music.get("audio_variants"), "audio")
            return music

    def _project_candidates(self, raw: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(raw, dict):
            raise DataFileError("歌曲标题候选记录损坏，原文件已保留。")
        result = {}
        for candidate_id, item in raw.items():
            if not ID_PATTERN.fullmatch(str(candidate_id)) or not isinstance(item, dict) or not isinstance(item.get("title"), str):
                raise DataFileError("歌曲标题候选内容损坏，原文件已保留。")
            result[str(candidate_id)] = {"title": item["title"], "created_at": int(item.get("created_at") or 0)}
        return result

    @staticmethod
    def _snapshot(music: Mapping[str, Any], *, source_hash: str = "", accepted_revision: int = 0) -> dict[str, Any]:
        value = {key: str(music.get(key) or "") for key in ("title", "lyrics", "style_prompt", "notes", "cover_prompt")}
        value["reference_audio_refs"] = copy.deepcopy(music.get("reference_audio_refs") or [])
        # Score attachments contribute to source_sha256, so every immutable source
        # version must retain the shared identities that produced that fingerprint.
        value["score_refs"] = copy.deepcopy(music.get("score_refs") or [])
        value["source_sha256"] = source_hash or music_source_sha256(music)
        if accepted_revision:
            value["accepted_revision"] = int(accepted_revision)
        return value

    def _project_source_versions(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            raise DataFileError("歌曲来源历史记录损坏，原文件已保留。")
        result = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise DataFileError("歌曲来源历史内容损坏，原文件已保留。")
            source_hash = str(item.get("source_sha256") or "")
            if not re.fullmatch(r"[a-f0-9]{64}", source_hash):
                raise DataFileError("歌曲来源历史指纹损坏，原文件已保留。")
            snapshot = self._snapshot(item, source_hash=source_hash, accepted_revision=int(item.get("revision") or 1))
            snapshot["score_refs"] = self._project_refs(snapshot.get("score_refs"), score=True)
            result.append({"id": str(item.get("id") or source_hash[:24]), "revision": int(item.get("revision") or 1),
                           "created_at": int(item.get("created_at") or 0), **snapshot})
        return result

    @staticmethod
    def _validate_score_format(reference: Mapping[str, Any], content: bytes) -> None:
        format_name = str(reference.get("format") or "").lower()
        mime = str(reference.get("mime") or "").lower().split(";", 1)[0].strip()
        name = str(reference.get("name") or "").lower()
        suffix = name.rsplit(".", 1)[-1] if "." in name else ""
        expected = {
            "abc": ({"abc", "txt"}, {"text/plain", "text/x-abc", "application/x-abc"}),
            "musicxml": ({"musicxml", "xml"}, {"application/vnd.recordare.musicxml", "application/vnd.recordare.musicxml+xml",
                                                   "application/xml", "text/xml", "text/plain"}),
            "midi": ({"mid", "midi"}, {"audio/midi", "audio/x-midi", "application/x-midi", "application/octet-stream"}),
        }
        allowed_suffixes, allowed_mimes = expected.get(format_name, (set(), set()))
        if suffix not in allowed_suffixes or mime not in allowed_mimes:
            raise HTTPException(400, f"乐谱格式 {format_name or '(空)'} 与素材 MIME/文件名不匹配")
        if not content or len(content) > 5 * 1024 * 1024:
            raise HTTPException(400, "乐谱文件为空或超过 5 MiB 校验上限")
        if format_name == "midi":
            if len(content) < 22 or content[:4] != b"MThd":
                raise HTTPException(400, "乐谱内容没有有效的 MIDI 文件头")
            header_length = int.from_bytes(content[4:8], "big")
            tracks = int.from_bytes(content[10:12], "big")
            if header_length < 6 or 8 + header_length + 8 > len(content) or tracks < 1:
                raise HTTPException(400, "MIDI 文件头或轨道信息无效")
            if content[8 + header_length:12 + header_length] != b"MTrk":
                raise HTTPException(400, "MIDI 文件缺少轨道数据")
        else:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise HTTPException(400, "乐谱文本不是有效 UTF-8 内容") from exc
            if format_name == "abc":
                directives = list(re.finditer(r"(?m)^\s*(?:X|T|M|L|Q|K):", text))
                body = "\n".join(line for line in text.splitlines()
                                   if not re.match(r"^\s*(?:[A-Za-z]|%)\s*:", line))
                if not directives or not re.search(r"(?<![A-Za-z])[A-Ga-g](?:[,']*)", body):
                    raise HTTPException(400, "文件内容不像有效的 ABC 乐谱")
            else:
                if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
                    raise HTTPException(400, "MusicXML 不接受 DTD 或外部实体")
                try:
                    root = ET.fromstring(text)
                except ET.ParseError as exc:
                    raise HTTPException(400, "MusicXML 文档格式无效") from exc
                root_name = str(root.tag).rsplit("}", 1)[-1]
                if root_name not in {"score-partwise", "score-timewise"}:
                    raise HTTPException(400, "XML 根节点不是 MusicXML 乐谱")

    def _validate_score_reference(self, reference: Mapping[str, Any]) -> None:
        if self.read_media_reference is None:
            raise HTTPException(503, "共享素材读取服务尚未接入，不能验证乐谱文件内容")
        content = self.read_media_reference(str(reference.get("asset_id") or ""),
                                            str(reference.get("result_id") or ""))
        if not isinstance(content, bytes):
            raise HTTPException(400, "乐谱素材不可读取或已缺失")
        self._validate_score_format(reference, content)

    def _project_refs(self, raw: Any, *, score: bool = False, expected_kind: str = "") -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            raise DataFileError("音乐素材引用记录损坏，原文件已保留。")
        output = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise DataFileError("音乐素材引用内容损坏，原文件已保留。")
            try:
                value = self._resolve_ref(item, expected_kind=expected_kind)
                if score and value.get("format") not in SCORE_FORMATS:
                    raise HTTPException(400, "乐谱引用缺少有效格式")
                if score:
                    self._validate_score_reference(value)
                output.append({**value, "available": True})
            except HTTPException as exc:
                output.append({"id": str(item.get("id") or ""), "asset_id": item.get("asset_id"),
                               "result_id": item.get("result_id"), "format": item.get("format"),
                               "url": "", "name": str(item.get("name") or ""), "mime": "",
                               "kind": str(item.get("kind") or ""), "available": False,
                               "error": str(exc.detail)})
        return output

    def _project_history(self, raw: Any, expected_kind: str) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            raise DataFileError("音乐生成历史记录损坏，原文件已保留。")
        output = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise DataFileError("音乐生成历史内容损坏，原文件已保留。")
            try:
                reference = self._resolve_ref(item, expected_kind=expected_kind)
                output.append({**reference, "id": str(item.get("id") or reference.get("id") or ""), "available": True,
                               "created_at": int(item.get("created_at") or 0),
                               "run_id": str(item.get("run_id") or ""),
                               "origin": str(item.get("origin") or ("generation" if item.get("run_id") else "agent")),
                               "snapshot": copy.deepcopy(item.get("snapshot") if isinstance(item.get("snapshot"), Mapping) else {}),
                               "timed_lyrics": copy.deepcopy(item.get("timed_lyrics") or []),
                               **self._safe_history_metadata(item)})
            except HTTPException as exc:
                output.append({"id": str(item.get("id") or ""), "asset_id": item.get("asset_id"),
                               "result_id": item.get("result_id"), "url": "", "name": str(item.get("name") or ""),
                               "mime": "", "kind": expected_kind, "created_at": int(item.get("created_at") or 0),
                               "run_id": str(item.get("run_id") or ""), "snapshot": copy.deepcopy(item.get("snapshot") or {}),
                               "origin": str(item.get("origin") or ("generation" if item.get("run_id") else "agent")),
                               "timed_lyrics": copy.deepcopy(item.get("timed_lyrics") or []),
                               **self._safe_history_metadata(item),
                               "available": False, "error": str(exc.detail)})
        return output

    @staticmethod
    def _safe_history_metadata(item: Mapping[str, Any]) -> dict[str, Any]:
        metadata = {}
        for key in ("model", "source"):
            value = item.get(key)
            if isinstance(value, str) and len(value) <= 240:
                metadata[key] = value
        duration = item.get("duration")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and 0 <= duration <= 86400:
            metadata["duration"] = float(duration)
        return metadata

    def put(self, project_id: str, payload: MusicPutRequest) -> dict[str, Any]:
        project_id = _clean_project_id(project_id)
        with self.project_store.lock:
            record = self.project_store.read_music_record(project_id)
            actual_revision = max(1, int(record.get("revision") or 1))
            if payload.expected_revision != actual_revision:
                raise HTTPException(409, detail={"message": "音乐项目已在其他页面更新，请重新读取并合并。",
                                                  "music": self.get(project_id), "revision": actual_revision})
            music = copy.deepcopy(self._music(record))
            fields = payload.model_fields_set
            for key in ("title", "lyrics", "style_prompt", "notes", "cover_prompt"):
                if key in fields:
                    value = getattr(payload, key)
                    value = str(value or "")
                    if "\x00" in value or len(value.encode("utf-8")) > MAX_TEXT_BYTES:
                        raise HTTPException(413, f"{key} 内容超过大小限制或包含无效字符")
                    music[key] = value

            candidates = music.get("title_candidates") if isinstance(music.get("title_candidates"), dict) else {}
            candidates = copy.deepcopy(candidates)
            if payload.title_candidates is not None:
                for candidate_id, candidate in payload.title_candidates.items():
                    if not ID_PATTERN.fullmatch(candidate_id):
                        raise HTTPException(400, f"标题候选 ID 不合法：{candidate_id}")
                    value = {"title": candidate.title, "created_at": int(time.time() * 1000)}
                    prior = candidates.get(candidate_id)
                    if prior and prior.get("title") != candidate.title:
                        raise HTTPException(409, f"标题候选 {candidate_id} 已存在且不可覆盖")
                    candidates.setdefault(candidate_id, value)
            music["title_candidates"] = candidates
            if "selected_title_candidate_id" in fields:
                selected = payload.selected_title_candidate_id
                if selected is not None and selected not in candidates:
                    raise HTTPException(400, "所选标题候选不存在")
                music["selected_title_candidate_id"] = selected
                if selected is not None:
                    music["title"] = str(candidates[selected]["title"])

            for field, expected_kind in (("score_refs", ""), ("reference_audio_refs", "audio")):
                if field in fields and getattr(payload, field) is not None:
                    additions = []
                    for raw in getattr(payload, field) or []:
                        entry = raw.model_dump(exclude_none=True)
                        value = self._resolve_ref(entry, expected_kind=expected_kind)
                        if field == "score_refs" and value.get("format") not in SCORE_FORMATS:
                            raise HTTPException(400, "每项乐谱引用都必须提供 abc、musicxml 或 midi 格式")
                        if field == "score_refs":
                            self._validate_score_reference(value)
                        additions.append(value)
                    music[field] = self._merge_refs(music.get(field, []), additions, field=field)

            if payload.audio_refs is not None:
                self._attach_references(music, payload.audio_refs, "audio", record, project_id, actual_revision + 1)
            if payload.cover_refs is not None:
                self._attach_references(music, payload.cover_refs, "image", record, project_id, actual_revision + 1)
            if "selected_audio_variant_id" in fields:
                selected = payload.selected_audio_variant_id
                selected_item = next((item for item in music.get("audio_variants", [])
                                      if isinstance(item, Mapping) and str(item.get("id") or "") == str(selected or "")), None)
                if selected is not None:
                    if selected_item is None:
                        raise HTTPException(400, "所选歌曲版本不存在")
                    self._resolve_ref(selected_item, expected_kind="audio")
                music["selected_audio_variant_id"] = selected
            if "selected_cover_variant_id" in fields:
                selected = payload.selected_cover_variant_id
                selected_item = next((item for item in music.get("cover_variants", [])
                                      if isinstance(item, Mapping) and str(item.get("id") or "") == str(selected or "")), None)
                if selected is not None:
                    if selected_item is None:
                        raise HTTPException(400, "所选封面版本不存在")
                    self._resolve_ref(selected_item, expected_kind="image")
                music["selected_cover_variant_id"] = selected
            if "timed_lyrics" in fields and payload.timed_lyrics is not None:
                by_id = {str(item.get("id") or ""): item for item in music.get("audio_variants", []) if isinstance(item, dict)}
                for variant_id, rows in payload.timed_lyrics.items():
                    variant = by_id.get(variant_id)
                    if variant is None:
                        raise HTTPException(400, f"歌曲版本不存在：{variant_id}")
                    serialized = [row.model_dump() for row in rows]
                    if len(serialized) > TIMED_LYRIC_MAX_ROWS:
                        raise HTTPException(413, "歌词时间轴项目过多")
                    prior_start = -1.0
                    for row in serialized:
                        if row["start"] < prior_start or (row["end"] is not None and row["end"] < row["start"]):
                            raise HTTPException(400, "歌词时间轴必须按开始时间递增，结束时间不能早于开始时间")
                        prior_start = row["start"]
                    variant["timed_lyrics"] = serialized

            new_source_hash = music_source_sha256(music)
            old_source_hash = music_source_sha256(record["music"])
            next_revision = actual_revision + 1
            source_versions = music.get("source_versions") if isinstance(music.get("source_versions"), list) else []
            source_versions = copy.deepcopy(source_versions)
            if new_source_hash != old_source_hash:
                source_versions.append({
                    "id": f"source_{next_revision}_{new_source_hash[:16]}", "source_sha256": new_source_hash, "revision": next_revision,
                    "created_at": int(time.time() * 1000), **self._snapshot(music, source_hash=new_source_hash),
                })
            music["source_versions"] = source_versions
            record["music"] = music
            record["updated_at"] = int(time.time() * 1000)
            record["revision"] = next_revision
            self.project_store.write_music_record(record)
            return self.get(project_id)

    def _attach_references(self, music: dict[str, Any], references: list[MusicReferenceInput], kind: str,
                           record: Mapping[str, Any], project_id: str, accepted_revision: int) -> None:
        field = "audio_variants" if kind == "audio" else "cover_variants"
        existing = music.get(field) if isinstance(music.get(field), list) else []
        by_identity = {(str(item.get("asset_id") or ""), str(item.get("result_id") or "")): item
                       for item in existing if isinstance(item, Mapping)}
        snapshot = self._snapshot(music, accepted_revision=max(1, int(accepted_revision)))
        for reference in references:
            resolved = self._resolve_ref(reference.model_dump(exclude_none=True), expected_kind=kind)
            identity = (str(resolved.get("asset_id") or ""), str(resolved.get("result_id") or ""))
            if identity in by_identity:
                continue
            variant_id = ("agent_" + hashlib.sha256(f"{project_id}\0{kind}\0{identity[0]}\0{identity[1]}".encode()).hexdigest()[:24])
            item = {**resolved, "id": variant_id, "origin": "agent", "run_id": "",
                    "created_at": int(time.time() * 1000), "snapshot": snapshot, "timed_lyrics": []}
            existing.append(item)
            by_identity[identity] = item
        music[field] = existing

    def associate_generation(self, project_id: str, *, run_id: str, purpose: str, media: list[Mapping[str, Any]],
                             snapshot: Mapping[str, Any], accepted_revision: int) -> None:
        project_id = _clean_project_id(project_id)
        expected_kind = "audio" if purpose == "song" else "image"
        if purpose not in {"song", "cover"}:
            raise HTTPException(400, "音乐生成用途无效")
        additions = []
        for item in media:
            if not isinstance(item, Mapping):
                continue
            kind = str(item.get("kind") or item.get("media_type") or "").strip().lower()
            if kind != expected_kind:
                raise HTTPException(422, f"该{('歌曲' if purpose == 'song' else '封面')}任务返回了错误的素材类型")
            asset_id = str(item.get("assetId") or item.get("asset_id") or "").strip()
            result_id = str(item.get("resultId") or item.get("result_id") or "").strip()
            resolved = self._resolve_ref({"asset_id": asset_id or None, "result_id": result_id or None}, expected_kind=expected_kind)
            variant_id = "music_" + hashlib.sha256(f"{run_id}\0{asset_id}\0{result_id}".encode()).hexdigest()[:24]
            additions.append({
                **resolved,
                "id": variant_id,
                "run_id": run_id,
                "origin": "generation",
                "created_at": int(time.time() * 1000),
                "snapshot": {**copy.deepcopy(dict(snapshot)), "accepted_revision": int(accepted_revision)},
                "timed_lyrics": [],
                **self._safe_history_metadata(item),
            })
        with self.project_store.lock:
            record = self.project_store.read_music_record(project_id)
            music = copy.deepcopy(self._music(record))
            field = "audio_variants" if purpose == "song" else "cover_variants"
            existing = music.get(field) if isinstance(music.get(field), list) else []
            by_run = {str(item.get("id") or "") for item in existing if isinstance(item, Mapping)}
            if not additions:
                if any(isinstance(item, Mapping) and str(item.get("run_id") or "") == run_id for item in existing):
                    return
                raise HTTPException(422, f"音乐任务没有返回可访问的受管{('音频' if purpose == 'song' else '图片')}结果")
            merged = list(existing)
            for item in additions:
                if item["id"] not in by_run:
                    merged.append(item)
                    by_run.add(item["id"])
            music[field] = merged
            if len(merged) == len(existing):
                return
            # 结果入历史不选中版本：内容可能已经在生成期间改动，采用必须由用户明确操作。
            record["music"] = music
            record["revision"] = max(1, int(record.get("revision") or 1)) + 1
            record["updated_at"] = int(time.time() * 1000)
            self.project_store.write_music_record(record)

    def router(self, *, submit_generation: Callable[..., Any] | None = None,
               get_generation: Callable[..., Any] | None = None,
               list_generations: Callable[..., Any] | None = None) -> APIRouter:
        router = APIRouter(prefix="/api/studio/music", tags=["Studio Music"])

        @router.get("/{project_id}")
        async def get_music(project_id: str):
            try:
                return self.get(project_id)
            except StudioProjectNotFound as exc:
                raise HTTPException(404, exc.detail) from exc

        @router.put("/{project_id}", dependencies=[Depends(_guard_local_write)])
        async def put_music(project_id: str, payload: MusicPutRequest):
            try:
                return self.put(project_id, payload)
            except StudioProjectNotFound as exc:
                raise HTTPException(404, exc.detail) from exc

        @router.post("/{project_id}/generations", dependencies=[Depends(_guard_local_write)])
        async def submit_music_generation(project_id: str, payload: MusicGenerationRequest):
            if submit_generation is None:
                raise HTTPException(503, "音乐生成执行入口尚未接入")
            if (payload.purpose, payload.slot) not in {("song", "music"), ("cover", "image")}:
                raise HTTPException(400, "歌曲使用 music 输出，封面使用 image 输出")
            music = self.get(project_id)
            value = submit_generation(project_id, payload.model_dump(), {
                "accepted_revision": int(music.get("revision") or 1),
                "source_hash": str(music.get("source_sha256") or ""),
                "requested_revision": payload.base_revision,
            })
            if hasattr(value, "__await__"):
                value = await value
            if not isinstance(value, Mapping) or not value.get("run_id"):
                raise HTTPException(502, "音乐生成入口未返回持久任务 ID")
            return {"generation": dict(value)}

        @router.get("/{project_id}/generations")
        async def get_music_generations(project_id: str):
            self.get(project_id)
            if list_generations is None:
                return {"generations": []}
            value = list_generations(project_id)
            if hasattr(value, "__await__"):
                value = await value
            return {"generations": list(value or [])}

        @router.get("/{project_id}/generations/{run_id}")
        async def get_music_generation(project_id: str, run_id: str):
            if get_generation is None:
                raise HTTPException(503, "音乐生成任务读取入口尚未接入")
            self.get(project_id)
            value = get_generation(project_id, run_id)
            if hasattr(value, "__await__"):
                value = await value
            if not isinstance(value, Mapping):
                raise HTTPException(404, "音乐生成任务不存在")
            return {"generation": dict(value), "music": self.get(project_id)}

        return router


__all__ = ["MusicGenerationRequest", "MusicPutRequest", "StudioMusicStore", "music_source_sha256"]
