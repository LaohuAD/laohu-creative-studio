"""Shared, revisioned storage and Agent APIs for script and novel projects.

The project JSON remains the metadata and concurrency root. Markdown is stored
as immutable, content-addressed UTF-8 blobs; no database, model executor, or
media result store is introduced here.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, create_model
from starlette.concurrency import run_in_threadpool

from canvas_core.json_store import DataFileError, write_json
from studio_projects import (
    StudioProjectConflict,
    StudioProjectError,
    StudioProjectNotFound,
    StudioProjectStore,
    _guard_local_write,
)

MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 10000
MAX_BATCH_OPERATIONS = 100
DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 100
MANUSCRIPT_MARKDOWN_FORMAT_VERSION = "laohu-manuscript-v1"
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")
DEFAULT_SETTING_CATEGORIES = (
    {"id": "characters", "title": {"zh": "人物", "en": "Characters"}},
    {"id": "relationships", "title": {"zh": "关系与势力", "en": "Relationships & Factions"}},
    {"id": "locations", "title": {"zh": "场景与地点", "en": "Locations"}},
    {"id": "props", "title": {"zh": "道具与资源", "en": "Props & Resources"}},
    {"id": "abilities", "title": {"zh": "能力与规则", "en": "Abilities & Rules"}},
    {"id": "world", "title": {"zh": "世界设定", "en": "Worldbuilding"}},
    {"id": "timeline", "title": {"zh": "事件与时间线", "en": "Events & Timeline"}},
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ChapterBasisRef(_StrictModel):
    kind: Literal["chapter"]
    chapter_id: str
    content_sha256: str = Field(pattern=HASH_PATTERN.pattern)


class _SettingBasisRef(_StrictModel):
    kind: Literal["setting"]
    entry_id: str
    version_id: str
    content_sha256: str = Field(pattern=HASH_PATTERN.pattern)


class _ExpectedSettingSource(_StrictModel):
    entry_id: str
    version_id: str
    content_sha256: str = Field(pattern=HASH_PATTERN.pattern)


class _AnchorBaseline(_StrictModel):
    kind: Literal["baseline"]


class _AnchorUnspecified(_StrictModel):
    kind: Literal["unspecified"]


class _AnchorChapter(_StrictModel):
    kind: Literal["chapter_boundary"]
    chapter_id: str
    side: Literal["before", "after"]


class _AnchorEvent(_StrictModel):
    kind: Literal["event"]
    event_entry_id: str
    event_version_id: str
    side: Literal["before", "after"]
    chapter_id: Optional[str] = None


StoryAnchor = Annotated[Union[_AnchorBaseline, _AnchorUnspecified, _AnchorChapter, _AnchorEvent], Field(discriminator="kind")]
BasisRef = Annotated[Union[_ChapterBasisRef, _SettingBasisRef], Field(discriminator="kind")]


class _SegmentSpec(_StrictModel):
    id: Optional[str] = None
    client_ref: Optional[str] = None
    title: str
    start: Optional[int] = None
    end: Optional[int] = None
    exact_text: Optional[str] = None


class _RangedSceneSpec(_StrictModel):
    client_ref: Optional[str] = None
    title: str
    body_markdown: str
    start: Optional[int] = None
    end: Optional[int] = None
    segments: list[_SegmentSpec] = Field(default_factory=list)


class _RangedEpisodeSpec(_StrictModel):
    client_ref: Optional[str] = None
    title: str
    scenes: list[_RangedSceneSpec]


class _EpisodeSpec(_StrictModel):
    client_ref: Optional[str] = None
    title: str
    scenes: list[_RangedSceneSpec]


class _ContextPin(_StrictModel):
    entry_id: str
    version_id: Optional[str] = None


class ManuscriptMarkdownExport(_StrictModel):
    project_id: str
    revision: int
    format_version: Literal["laohu-manuscript-v1"]
    source_sha256: str = Field(pattern=HASH_PATTERN.pattern)
    body_markdown: str


class ManuscriptMarkdownHistory(_StrictModel):
    project_id: str
    revision: int
    content_sha256: str = Field(pattern=HASH_PATTERN.pattern)
    char_count: int
    created_at: Optional[int] = None
    label: Optional[str] = None
    body_markdown: str


class ManuscriptOutlineDocument(_StrictModel):
    project_id: str
    revision: int
    parent_id: str
    outline_revision: int
    current_outline_revision: int
    outline_sha256: str
    outline_markdown: str
    selected_revision: Literal["current", "history"]


class ManuscriptCommandReceipt(_StrictModel):
    request_id: str
    status: Literal["succeeded"]
    project_id: str
    revision: int
    changed_ids: list[str]
    created_ids: dict[str, str]
    warnings: list[str]
    source_sha256: Optional[str] = Field(None, pattern=HASH_PATTERN.pattern)
    markdown_source_sha256s: Optional[list[str]] = None


def _arg_model(action: str, fields: Mapping[str, tuple[Any, Any]]) -> type[BaseModel]:
    return create_model(f"{action.title().replace('_', '')}Args", __config__=ConfigDict(extra="forbid"), **dict(fields))


_REQ = ...
_OPT = None
_SCRIPT_ARG_FIELDS: dict[str, dict[str, tuple[Any, Any]]] = {
    "import_markdown": {"body_markdown": (str, _REQ), "replace": (StrictBool, _REQ)},
    "set_draft": {"body_markdown": (str, _REQ)},
    "structure_draft": {"episodes": (list[_EpisodeSpec], _REQ)},
    "restore_draft": {"source_sha256": (str, Field(..., pattern=HASH_PATTERN.pattern)),
                       "replace_structured": (Literal[True], _REQ)},
    "set_episode_outline": {"episode_id": (str, _REQ), "body_markdown": (str, _REQ)},
    "create_episode": {"title": (str, _REQ), "after_episode_id": (Optional[str], _OPT), "client_ref": (Optional[str], _OPT)},
    "create_scene": {"episode_id": (str, _REQ), "title": (str, _REQ), "body_markdown": (str, _REQ), "after_scene_id": (Optional[str], _OPT), "client_ref": (Optional[str], _OPT)},
    "create_segment": {"scene_id": (str, _REQ), "body_markdown": (str, _REQ), "after_segment_id": (Optional[str], _OPT), "title": (Optional[str], _OPT), "client_ref": (Optional[str], _OPT)},
    "update_scene": {"scene_id": (str, _REQ), "body_markdown": (str, _REQ)},
    "set_scene_segments": {"scene_id": (str, _REQ), "source_sha256": (str, _REQ), "segments": (list[_SegmentSpec], _REQ)},
    "replace_segment_text": {"segment_id": (str, _REQ), "body_markdown": (str, _REQ)},
    "rename_item": {"item_type": (Literal["episode", "scene", "segment"], _REQ), "item_id": (str, _REQ), "title": (str, _REQ)},
    "reorder_items": {"parent_type": (Literal["root", "episode"], _REQ), "parent_id": (Optional[str], _OPT), "ordered_ids": (list[str], _REQ)},
    "delete_item": {"item_type": (Literal["episode", "scene", "segment"], _REQ), "item_id": (str, _REQ), "include_descendants": (bool, False)},
    "restore_item": {"item_id": (str, _REQ)},
}
_NOVEL_ARG_FIELDS: dict[str, dict[str, tuple[Any, Any]]] = {
    "import_markdown": {"body_markdown": (str, _REQ), "replace": (StrictBool, _REQ)},
    "create_volume": {"title": (str, _REQ), "after_volume_id": (Optional[str], _OPT), "client_ref": (Optional[str], _OPT)},
    "create_chapter": {"volume_id": (str, _REQ), "title": (str, _REQ), "body_markdown": (str, _REQ), "after_chapter_id": (Optional[str], _OPT), "basis_refs": (Optional[list[BasisRef]], _OPT), "client_ref": (Optional[str], _OPT)},
    "update_chapter": {"chapter_id": (str, _REQ), "body_markdown": (str, _REQ), "basis_refs": (Optional[list[BasisRef]], _OPT)},
    "set_chapter_outline": {"chapter_id": (str, _REQ), "body_markdown": (str, _REQ)},
    "rename_item": {"item_type": (Literal["volume", "chapter"], _REQ), "item_id": (str, _REQ), "title": (str, _REQ)},
    "reorder_items": {"parent_type": (Literal["root", "volume"], _REQ), "parent_id": (Optional[str], _OPT), "ordered_ids": (list[str], _REQ)},
    "delete_item": {"item_type": (Literal["volume", "chapter"], _REQ), "item_id": (str, _REQ), "include_descendants": (bool, False)},
    "restore_item": {"item_id": (str, _REQ)},
    "create_setting_entry": {"category_id": (Optional[str], _OPT), "body_markdown": (str, _REQ), "use_state": (Literal["draft", "confirmed"], _REQ), "story_anchor": (Optional[StoryAnchor], _OPT), "client_ref": (Optional[str], _OPT)},
    "revise_setting_version": {"entry_id": (str, _REQ), "version_id": (str, _REQ), "body_markdown": (str, _REQ)},
    "add_setting_version": {"entry_id": (str, _REQ), "based_on_version_id": (str, _REQ), "body_markdown": (str, _REQ), "use_state": (Literal["draft", "confirmed"], _REQ), "story_anchor": (Optional[StoryAnchor], _OPT), "client_ref": (Optional[str], _OPT)},
    "set_setting_version_state": {"entry_id": (str, _REQ), "version_id": (str, _REQ), "use_state": (Literal["draft", "confirmed"], _REQ)},
    "set_setting_version_anchor": {"entry_id": (str, _REQ), "version_id": (str, _REQ), "story_anchor": (StoryAnchor, _REQ)},
    "move_setting_entry": {"entry_id": (str, _REQ), "category_id": (Optional[str], _REQ)},
    "archive_setting_entry": {"entry_id": (str, _REQ)},
    "restore_setting_entry": {"entry_id": (str, _REQ)},
    "restore_setting_revision": {"entry_id": (str, _REQ), "version_id": (str, _REQ), "revision": (int, _REQ)},
    "create_setting_category": {"name": (str, _REQ), "after_category_id": (Optional[str], _OPT), "client_ref": (Optional[str], _OPT)},
    "rename_setting_category": {"category_id": (str, _REQ), "name": (str, _REQ)},
    "archive_setting_category": {"category_id": (str, _REQ), "move_entries_to": (Optional[str], _REQ)},
    "update_handoff_record": {"body_markdown": (str, _REQ), "source_refs": (Optional[list[BasisRef]], _OPT)},
    "set_context_pins": {"refs": (list[_ContextPin], _REQ)},
}


def _command_schema(action_fields: Mapping[str, Mapping[str, tuple[Any, Any]]], include_expected_sources: bool,
                    *, batch_name: str) -> Any:
    args_by_action = {action: _arg_model(action, fields) for action, fields in action_fields.items() if action != "batch"}
    operation_variants: list[type[BaseModel]] = []
    for action, args_model in args_by_action.items():
        operation_variants.append(create_model(f"{action.title().replace('_', '')}BatchOperation",
            __config__=ConfigDict(extra="forbid"), action=(Literal[action], ...), args=(args_model, ...)))
    operation_type = Annotated[Union[tuple(operation_variants)], Field(discriminator="action")]
    args_by_action["batch"] = create_model(f"{batch_name}BatchArgs", __config__=ConfigDict(extra="forbid"),
        operations=(list[operation_type], Field(..., min_length=1, max_length=MAX_BATCH_OPERATIONS)))
    command_variants: list[type[BaseModel]] = []
    for action, args_model in args_by_action.items():
        fields: dict[str, tuple[Any, Any]] = {
            "request_id": (str, Field(..., min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")),
            "expected_revision": (int, Field(..., ge=1)),
            "action": (Literal[action], ...),
            "args": (args_model, ...),
        }
        if include_expected_sources:
            fields["expected_sources"] = (Optional[list[_ExpectedSettingSource]], None)
        command_variants.append(create_model(f"{action.title().replace('_', '')}Command", __config__=ConfigDict(extra="forbid"), **fields))
    command_type = Annotated[Union[tuple(command_variants)], Field(discriminator="action")]
    return command_type, args_by_action, operation_type


_SCRIPT_ARG_FIELDS["batch"] = {"operations": (list[Any], Field(..., min_length=1, max_length=MAX_BATCH_OPERATIONS))}
_NOVEL_ARG_FIELDS["batch"] = {"operations": (list[Any], Field(..., min_length=1, max_length=MAX_BATCH_OPERATIONS))}
ScriptCommand, SCRIPT_ARGS, ScriptOperation = _command_schema(_SCRIPT_ARG_FIELDS, False, batch_name="Script")
NovelCommand, NOVEL_ARGS, NovelOperation = _command_schema(_NOVEL_ARG_FIELDS, True, batch_name="Novel")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _body(value: Any) -> str:
    if not isinstance(value, str):
        raise StudioProjectError("body_markdown 必须是字符串")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in value:
        raise StudioProjectError("Markdown 正文不能包含 NUL 字符")
    if len(value.encode("utf-8")) > MAX_BODY_BYTES:
        raise StudioProjectError(f"单份 Markdown 正文不能超过 {MAX_BODY_BYTES // 1024 // 1024} MiB")
    return value


def _structure_tokens(body: str, module: str) -> list[dict[str, Any]]:
    """Find reserved level-one/two structure lines outside fenced code blocks."""
    tokens: list[dict[str, Any]] = []
    offset = 0
    fence_char = ""
    fence_size = 0
    for line in body.splitlines(keepends=True):
        content = line[:-1] if line.endswith("\n") else line
        if fence_char:
            closing = re.match(r"^ {0,3}(`+|~+)[ \t]*$", content)
            if closing and closing.group(1)[0] == fence_char and len(closing.group(1)) >= fence_size:
                fence_char = ""
                fence_size = 0
            offset += len(line)
            continue
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", content)
        if opening:
            fence_char = opening.group(1)[0]
            fence_size = len(opening.group(1))
            offset += len(line)
            continue
        match = re.match(r"^(#{1,2})[ \t]+(.+?)[ \t]*$", content)
        token = None
        if match:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2))
            title = _clean_title(title)
            if not title:
                raise StudioProjectError(
                    f"第 {body.count(chr(10), 0, offset) + 1} 行使用了保留的 Markdown 一级/二级标题；"
                    "结构标题必须带名称；作品正文小标题请从 ### 开始。"
                )
            token = {"kind": "parent" if match.group(1) == "#" else "child",
                     "title": title, "start": offset,
                     "body_start": offset + len(line)}
        elif re.match(r"^#{1,2}[ \t]+$", content):
            raise StudioProjectError(
                f"第 {body.count(chr(10), 0, offset) + 1} 行使用了保留的 Markdown 一级/二级标题；"
                "结构标题必须带名称；作品正文小标题请从 ### 开始。"
            )
        if token is not None:
            tokens.append(token)
        offset += len(line)
    return tokens


def _token_bodies(body: str, tokens: list[dict[str, Any]]) -> list[str]:
    bodies: list[str] = []
    for index, token in enumerate(tokens):
        end = tokens[index + 1]["start"] if index + 1 < len(tokens) else len(body)
        value = body[token["body_start"]:end]
        if index + 1 < len(tokens) and value.endswith("\n"):
            # One LF immediately before the next structural heading is syntax.
            # An additional LF remains part of the preceding body.
            value = value[:-1]
        bodies.append(value)
    return bodies


def _split_script_segments(body: str) -> list[str]:
    """Split only on an exact standalone --- line; delimiter bytes are syntax."""
    return [body[start:end] for start, end in _split_script_segments_with_ranges(body)]


def _split_script_segments_with_ranges(body: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for match in re.finditer(r"(?m)^---(?:\n|$)", body):
        # The LF that puts the delimiter on its own line is syntax. Any
        # additional LF immediately before it remains part of the segment.
        separator_start = match.start()
        if separator_start > cursor and body[separator_start - 1] == "\n":
            separator_start -= 1
        ranges.append((cursor, separator_start))
        cursor = match.end()
    ranges.append((cursor, len(body)))
    return ranges


def _parse_script_markdown(body: str) -> Optional[list[dict[str, Any]]]:
    tokens = _structure_tokens(body, "script")
    if not tokens:
        if body == "":
            return []
        return None
    if body[:tokens[0]["start"]] != "":
        raise StudioProjectError("剧本 Markdown 结构标题前不能有未归属正文")
    values = _token_bodies(body, tokens)
    episodes: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    for index, token in enumerate(tokens):
        if token["kind"] == "parent":
            if values[index] != "":
                raise StudioProjectError("集标题后、第一场前不能有未归属正文")
            current = {"title": token["title"], "scenes": []}
            episodes.append(current)
        else:
            if current is None:
                raise StudioProjectError("剧本场次的 ## 标题必须位于一个 # 集标题之后")
            content = values[index]
            if _structure_tokens(content, "script"):
                raise StudioProjectError("场正文中的 Markdown 一级/二级标题会被解析为剧本结构；正文小标题请从 ### 开始")
            current["scenes"].append({"title": token["title"], "body_markdown": content,
                                      "segments": _split_script_segments(content)})
    return episodes


def _parse_novel_markdown(body: str) -> list[dict[str, Any]]:
    tokens = _structure_tokens(body, "novel")
    if not tokens:
        if body == "":
            return []
        raise StudioProjectError("小说 Markdown 必须使用 # 卷标题 与 ## 章标题；不自动创建无卷章节")
    if body[:tokens[0]["start"]] != "":
        raise StudioProjectError("小说 Markdown 结构标题前不能有未归属正文")
    values = _token_bodies(body, tokens)
    volumes: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    for index, token in enumerate(tokens):
        if token["kind"] == "parent":
            if values[index] != "":
                raise StudioProjectError("卷标题后、第一章前不能有未归属正文")
            current = {"title": token["title"], "chapters": []}
            volumes.append(current)
        else:
            if current is None:
                raise StudioProjectError("章标题必须位于一个一级标题卷标题之后")
            content = values[index]
            if _structure_tokens(content, "novel"):
                raise StudioProjectError("章节正文中的 Markdown 一级/二级标题会被解析为小说结构；正文小标题请从 ### 开始")
            current["chapters"].append({"title": token["title"], "body_markdown": content})
    return volumes


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _need_keys(args: Mapping[str, Any], allowed: set[str], required: set[str] = frozenset()) -> None:
    unknown = set(args) - allowed
    missing = required - set(args)
    if unknown:
        raise StudioProjectError(f"未知字段：{', '.join(sorted(unknown))}")
    if missing:
        raise StudioProjectError(f"缺少字段：{', '.join(sorted(missing))}")


def _safe_id(value: Any, label: str = "ID") -> str:
    item = str(value or "").strip()
    if not ID_PATTERN.fullmatch(item):
        raise StudioProjectError(f"{label}不合法")
    return item


def _clean_title(value: Any, fallback: str = "未命名") -> str:
    if value is None:
        return fallback
    if not isinstance(value, str):
        raise StudioProjectError("标题必须是字符串")
    title = " ".join(value.replace("\x00", "").split())[:160]
    return title or fallback


def _markdown_title(body: str, fallback: str = "无标题条目") -> str:
    for line in body.splitlines():
        match = re.match(r"^#\s+(.+?)\s*#*\s*$", line)
        if match:
            return _clean_title(match.group(1), fallback)
    return fallback


def _cursor_encode(revision: int, offset: int) -> str:
    raw = json.dumps({"r": int(revision), "o": int(offset)}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _cursor_decode(cursor: str, revision: int) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict) or int(value["r"]) != revision:
            raise ValueError("revision")
        offset = int(value["o"])
        if offset < 0:
            raise ValueError("offset")
        return offset
    except Exception as exc:
        raise StudioProjectConflict({"message": "读取游标与当前项目修订不匹配，请重新打开目录。", "revision": revision}) from exc


class StudioManuscriptStore:
    """Manuscript domain store coordinated by StudioProjectStore's shared lock."""

    def __init__(self, root: str | os.PathLike[str], projects: StudioProjectStore):
        self.root = Path(root).expanduser().absolute()
        self.projects = projects
        self.blob_root = self.root / "data" / "studio_manuscripts" / "blobs"

    def _default(self, module: str) -> dict[str, Any]:
        if module == "script":
            return {"schema_version": 1, "state": "draft", "draft_sha256": "", "episodes": [],
                    "history": [], "archive": [], "operations": {}}
        return {"schema_version": 2, "volumes": [], "settings": {"schema_version": 1, "categories": [], "entries": []},
                "handoff": {"records": []}, "history": [], "archive": [], "operations": {}}

    def _read_blob(self, digest: str) -> str:
        digest = str(digest or "")
        if not HASH_PATTERN.fullmatch(digest):
            raise DataFileError("项目正文指纹无效；原项目记录已保留。")
        path = self.blob_root / f"{digest}.md"
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise DataFileError(f"正文块 {digest[:12]} 缺失或不可读；原项目记录已保留。") from exc
        if hashlib.sha256(raw).hexdigest() != digest:
            raise DataFileError(f"正文块 {digest[:12]} 校验失败；原项目记录已保留。")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DataFileError(f"正文块 {digest[:12]} 不是有效 UTF-8；原项目记录已保留。") from exc

    @staticmethod
    def _outline_state(item: Mapping[str, Any]) -> tuple[int, str, int, list[dict[str, Any]]]:
        """Validate lightweight outline metadata, tolerating pre-outline records."""
        revision = item.get("outline_revision", 0)
        char_count = item.get("outline_char_count", 0)
        digest = item.get("outline_sha256", "")
        history = item.get("outline_history", [])
        if (isinstance(revision, bool) or not isinstance(revision, int) or revision < 0
                or isinstance(char_count, bool) or not isinstance(char_count, int) or char_count < 0
                or not isinstance(digest, str) or not isinstance(history, list)):
            raise DataFileError("章纲修订元数据损坏；原项目记录已保留。")
        if digest:
            if not HASH_PATTERN.fullmatch(digest) or char_count == 0 or revision == 0:
                raise DataFileError("章纲当前版本指纹或长度无效；原项目记录已保留。")
        elif char_count != 0:
            raise DataFileError("空章纲的长度必须为零；原项目记录已保留。")
        seen: set[int] = set()
        normalized: list[dict[str, Any]] = []
        for entry in history:
            if not isinstance(entry, Mapping):
                raise DataFileError("章纲历史目录损坏；原项目记录已保留。")
            entry_revision = entry.get("revision")
            entry_count = entry.get("char_count")
            entry_digest = entry.get("content_sha256", "")
            if (isinstance(entry_revision, bool) or not isinstance(entry_revision, int) or entry_revision < 0
                    or entry_revision in seen or entry_revision >= revision
                    or isinstance(entry_count, bool) or not isinstance(entry_count, int) or entry_count < 0
                    or not isinstance(entry_digest, str)
                    or (entry_digest and (not HASH_PATTERN.fullmatch(entry_digest) or entry_count == 0))
                    or (not entry_digest and entry_count != 0)):
                raise DataFileError("章纲历史版本元数据无效；原项目记录已保留。")
            seen.add(entry_revision)
            normalized.append(dict(entry))
        if len(seen) != revision or any(value != index for index, value in enumerate(sorted(seen))):
            raise DataFileError("章纲历史版本不连续；原项目记录已保留。")
        return revision, digest, char_count, normalized

    def _outline_body(self, digest: str, char_count: int,
                      staged: Optional[Mapping[str, bytes]] = None) -> str:
        if not digest:
            if char_count != 0:
                raise DataFileError("空章纲的长度与正文不匹配；原项目记录已保留。")
            return ""
        raw = (staged or {}).get(digest)
        if raw is None:
            body = self._read_blob(digest)
        else:
            if hashlib.sha256(raw).hexdigest() != digest:
                raise DataFileError("待提交章纲正文指纹不匹配；原项目记录已保留。")
            try:
                body = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise DataFileError("待提交章纲正文不是有效 UTF-8；原项目记录已保留。") from exc
        if len(body) != char_count:
            raise DataFileError("章纲正文长度与已保存记录不匹配；原项目记录已保留。")
        return body

    def _set_outline(self, item: dict[str, Any], body_markdown: Any,
                     staged: dict[str, bytes]) -> None:
        revision, old_digest, old_count, history = self._outline_state(item)
        # Verify the current immutable blob before adding it to history so a
        # corrupt reference is never made to look like a valid prior version.
        self._outline_body(old_digest, old_count, staged)
        history.append({"revision": revision, "content_sha256": old_digest,
                        "char_count": old_count, "created_at": _now_ms()})
        body = _body(body_markdown)
        digest = self._stage_blob(body, staged) if body else ""
        item.update({"outline_revision": revision + 1, "outline_sha256": digest,
                     "outline_char_count": len(body), "outline_history": history})

    def outline_document(self, module: str, project_id: str, parent_id: str,
                         outline_revision: Optional[int] = None) -> dict[str, Any]:
        if module not in {"script", "novel"}:
            raise StudioProjectError("章纲只支持 script 或 novel")
        parent_id = _safe_id(parent_id, "集/章 ID")
        if outline_revision is not None and (isinstance(outline_revision, bool) or outline_revision < 0):
            raise StudioProjectError("outline_revision 必须是非负整数")
        with self.projects.lock:
            record = self._record(str(project_id), module)
            if module == "script":
                _, item = self._script_episode(record["script"], parent_id)
            else:
                _, item = self._chapter(record["novel"], parent_id)
            current_revision, current_digest, current_count, history = self._outline_state(item)
            if outline_revision is None or outline_revision == current_revision:
                selected_revision = current_revision
                digest, count = current_digest, current_count
                selected = "current"
            else:
                historical = next((value for value in history if value.get("revision") == outline_revision), None)
                if historical is None:
                    raise StudioProjectNotFound("指定的章纲修订不存在")
                selected_revision = int(historical["revision"])
                digest, count = str(historical.get("content_sha256") or ""), int(historical.get("char_count") or 0)
                selected = "history"
            body = self._outline_body(digest, count)
            return {"project_id": record["id"], "revision": self._revision(record),
                    "parent_id": parent_id, "outline_revision": selected_revision,
                    "current_outline_revision": current_revision, "outline_sha256": digest,
                    "outline_markdown": body, "selected_revision": selected}

    def _generation_source_unlocked(self, record: Mapping[str, Any], module: str,
                                    scope: str, source_id: str) -> dict[str, Any]:
        """Resolve the exact editable source and its stable object-version guard."""
        source_id = _safe_id(source_id, "source_id")
        content = record.get(module) if isinstance(record.get(module), Mapping) else {}
        if module == "script" and scope in {"scene", "segment"}:
            episode, scene = self._script_scene(dict(content), source_id) if scope == "scene" else (None, None)
            segment = None
            if scope == "segment":
                episode, scene, segment = self._segment(dict(content), source_id)
            scene_id = str(scene.get("id") or "")
            scene_digest = str(scene.get("content_sha256") or "")
            scene_body = self._read_blob(scene_digest) if scene_digest else ""
            if segment is None:
                body = self._script_editable_text(scene, scene_body)
                object_id = scene_id
                segment_count = len(scene.get("segments") or []) or (1 if scene_body else 0)
            else:
                start, end = int(segment.get("start", -1)), int(segment.get("end", -1))
                if start < 0 or end < start or end > len(scene_body):
                    raise DataFileError("分段范围损坏；原项目记录已保留。")
                body = scene_body[start:end]
                object_id = str(segment.get("id") or "")
                segment_count = None
            return {"module": module, "scope": scope, "source_id": object_id,
                    "parent_id": scene_id, "project_revision": self._revision(record),
                    "source_revision": int(scene.get("revision") or 1),
                    "source_sha256": scene_digest,
                    "source_object_sha256": _digest(body), "body_markdown": body,
                    "title": str((segment or scene).get("title") or ""),
                    "segment_count": segment_count}
        if module == "script" and scope == "episode_outline":
            _, episode = self._script_episode(dict(content), source_id)
            outline_revision, digest, count, _ = self._outline_state(episode)
            body = self._outline_body(digest, count)
            return {"module": module, "scope": scope, "source_id": source_id,
                    "parent_id": source_id, "project_revision": self._revision(record),
                    "source_revision": outline_revision, "source_sha256": digest,
                    "source_object_sha256": _digest(body) if body else "",
                    "body_markdown": body, "title": str(episode.get("title") or "")}
        if module == "novel" and scope == "chapter":
            _, chapter = self._chapter(dict(content), source_id)
            digest = str(chapter.get("content_sha256") or "")
            body = self._read_blob(digest) if digest else ""
            return {"module": module, "scope": scope, "source_id": source_id,
                    "parent_id": source_id, "project_revision": self._revision(record),
                    "source_revision": int(chapter.get("revision") or 1),
                    "source_sha256": digest, "source_object_sha256": _digest(body) if body else "",
                    "body_markdown": body, "title": str(chapter.get("title") or "")}
        if module == "novel" and scope == "chapter_outline":
            _, chapter = self._chapter(dict(content), source_id)
            outline_revision, digest, count, _ = self._outline_state(chapter)
            body = self._outline_body(digest, count)
            return {"module": module, "scope": scope, "source_id": source_id,
                    "parent_id": source_id, "project_revision": self._revision(record),
                    "source_revision": outline_revision, "source_sha256": digest,
                    "source_object_sha256": _digest(body) if body else "",
                    "body_markdown": body, "title": str(chapter.get("title") or "")}
        raise StudioProjectError("该模块不支持此文本优化范围")

    def generation_source(self, project_id: str, module: str, scope: str, source_id: str) -> dict[str, Any]:
        if module not in {"script", "novel"}:
            raise StudioProjectError("文本优化只支持 script 或 novel 项目")
        with self.projects.lock:
            record = self._record(_safe_id(project_id, "项目 ID"), module)
            source = self._generation_source_unlocked(record, module, scope, source_id)
            if not source["body_markdown"].strip():
                raise StudioProjectConflict({"code": "EMPTY_SOURCE", "message": "所选正文或章纲为空，填写内容后再优化。"})
            return source

    def apply_generated_text(self, project_id: str, module: str, *, scope: str, source_id: str,
                             source_revision: int, source_sha256: str, source_object_sha256: str,
                             body_markdown: str, request_id: str, run_id: str, result_id: str,
                             source_segment_count: Optional[int] = None) -> dict[str, Any]:
        """Apply a managed result only if the exact source object version is still current."""
        project_id = _safe_id(project_id, "项目 ID")
        source_id = _safe_id(source_id, "source_id")
        request_id = _safe_id(request_id, "request_id")
        run_id = _safe_id(run_id, "run_id")
        result_id = _safe_id(result_id, "result_id")
        if module not in {"script", "novel"}:
            raise StudioProjectError("文本优化只支持 script 或 novel 项目")
        body = _body(body_markdown)
        if not body.strip():
            raise StudioProjectError("文本优化结果不能为空")
        operation_key = f"optimize-apply-{request_id}"
        fingerprint = _fingerprint({"module": module, "scope": scope, "source_id": source_id,
                                    "source_revision": source_revision, "source_sha256": source_sha256,
                                    "source_object_sha256": source_object_sha256, "body_sha256": _digest(body),
                                    "run_id": run_id, "result_id": result_id})
        with self.projects.lock:
            root_record = self._record(project_id, module)
            content = copy.deepcopy(root_record[module])
            operations = content.setdefault("operations", {})
            prior = operations.get(operation_key)
            if prior is not None:
                if not isinstance(prior, Mapping) or prior.get("fingerprint") != fingerprint:
                    raise StudioProjectConflict({"code": "IDEMPOTENCY_KEY_REUSED", "message": "request_id 已用于其他结果或来源。"})
                return copy.deepcopy(prior.get("receipt") or {})
            current = self._generation_source_unlocked(root_record, module, scope, source_id)
            if (current["source_revision"] != source_revision
                    or current["source_sha256"] != source_sha256
                    or current["source_object_sha256"] != source_object_sha256):
                raise StudioProjectConflict({"code": "SOURCE_CHANGED", "message": "原文或章纲已更新；请重新读取并再次生成。",
                                              "current_revision": self._revision(root_record),
                                              "source_revision": current["source_revision"],
                                              "source_sha256": current["source_sha256"]})
            if module == "script" and scope == "scene":
                if (isinstance(source_segment_count, bool) or not isinstance(source_segment_count, int)
                        or source_segment_count < 1):
                    raise StudioProjectError("场次分段结构快照无效；请重新读取场次后再采用。")
                found_segments = len(_split_script_segments_with_ranges(body))
                if found_segments != source_segment_count:
                    raise StudioProjectConflict({"code": "SCENE_SEGMENT_STRUCTURE_CHANGED",
                        "message": f"优化结果包含 {found_segments} 个分段，原场次有 {source_segment_count} 段。请保留结果并手动调整分段后再采用。",
                        "current_revision": self._revision(root_record)})
            if module == "novel" and scope == "chapter" and _structure_tokens(body, "novel"):
                raise StudioProjectError("章节优化结果包含保留的一级或二级结构标题；正文小标题请从 ### 开始，已保留原正文。")

            staged: dict[str, bytes] = {}
            aliases: dict[str, str] = {}
            if module == "script":
                action, args = {
                    "scene": ("update_scene", {"scene_id": source_id, "body_markdown": body}),
                    "segment": ("replace_segment_text", {"segment_id": source_id, "body_markdown": body}),
                    "episode_outline": ("set_episode_outline", {"episode_id": source_id, "body_markdown": body}),
                }.get(scope, ("", {}))
                changed, _created = self._script_action(content, action, args, aliases, staged)
            else:
                action, args = {
                    "chapter": ("update_chapter", {"chapter_id": source_id, "body_markdown": body}),
                    "chapter_outline": ("set_chapter_outline", {"chapter_id": source_id, "body_markdown": body}),
                }.get(scope, ("", {}))
                changed, _created = self._novel_action(content, action, args, aliases, staged,
                                                       expected_sources=None)
            if not action:
                raise StudioProjectError("该模块不支持此文本优化范围")
            next_revision = self._revision(root_record) + 1
            root_record[module] = content
            root_record["revision"] = next_revision
            root_record["updated_at"] = _now_ms()
            receipt = {"request_id": request_id, "status": "succeeded", "project_id": project_id,
                       "revision": next_revision, "changed_ids": list(dict.fromkeys(changed)),
                       "created_ids": {}, "warnings": [], "generation_run_id": run_id,
                       "result_id": result_id, "source_scope": scope, "source_id": source_id,
                       "source_sha256": source_sha256}
            operations[operation_key] = {"fingerprint": fingerprint, "receipt": copy.deepcopy(receipt),
                                         "created_at": _now_ms()}
            self._commit_blobs(staged)
            self.projects.write_manuscript_record(root_record)
            return receipt

    def generation_apply_receipt(self, project_id: str, module: str, request_id: str,
                                 run_id: str, result_id: str) -> Optional[dict[str, Any]]:
        """Check the durable apply idempotency record before reading a result file."""
        with self.projects.lock:
            record = self._record(_safe_id(project_id, "项目 ID"), module)
            item = (record.get(module) or {}).get("operations", {}).get(f"optimize-apply-{_safe_id(request_id, 'request_id')}")
            if item is None:
                return None
            receipt = item.get("receipt") if isinstance(item, Mapping) else None
            if (not isinstance(receipt, Mapping) or receipt.get("generation_run_id") != run_id
                    or receipt.get("result_id") != result_id):
                raise StudioProjectConflict({"code": "IDEMPOTENCY_KEY_REUSED", "message": "request_id 已用于其他结果或来源。"})
            return copy.deepcopy(dict(receipt))

    def _stage_blob(self, body: str, staged: dict[str, bytes]) -> str:
        value = _body(body)
        raw = value.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        staged[digest] = raw
        return digest

    def _commit_blobs(self, staged: Mapping[str, bytes]) -> None:
        if not staged:
            return
        self.blob_root.mkdir(parents=True, exist_ok=True)
        for digest, raw in staged.items():
            path = self.blob_root / f"{digest}.md"
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise DataFileError(f"正文块 {digest[:12]} 已存在但校验失败；拒绝覆盖。")
                continue
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    temporary.replace(path)
                except FileExistsError:
                    temporary.unlink(missing_ok=True)
            finally:
                temporary.unlink(missing_ok=True)

    def _record(self, project_id: str, module: str) -> dict[str, Any]:
        record = self.projects._read_manuscript_record(project_id, module)
        if record is None:
            raise StudioProjectNotFound("项目不存在")
        if not isinstance(record.get(module), dict):
            record[module] = self._default(module)
        data = record[module]
        if not isinstance(data.get("history", []), list) or not isinstance(data.get("operations", {}), dict):
            raise DataFileError("手稿目录或操作回执损坏；原项目记录已保留。")
        return record

    @staticmethod
    def _revision(record: Mapping[str, Any]) -> int:
        try:
            return max(1, int(record.get("revision") or 1))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _entry(collection: list[dict[str, Any]], item_id: str, label: str) -> dict[str, Any]:
        result = next((item for item in collection if isinstance(item, dict) and item.get("id") == item_id), None)
        if result is None:
            raise StudioProjectNotFound(f"{label}不存在")
        return result

    @staticmethod
    def _resolve(value: Any, aliases: Mapping[str, str], label: str) -> str:
        raw = str(value or "").strip()
        return _safe_id(aliases.get(raw, raw), label)

    def _all_script_scenes(self, script: Mapping[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        return [(episode, scene) for episode in script.get("episodes") or []
                for scene in episode.get("scenes") or []]

    def _script_scene(self, script: dict[str, Any], scene_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        for episode in script.get("episodes") or []:
            for scene in episode.get("scenes") or []:
                if scene.get("id") == scene_id:
                    return episode, scene
        raise StudioProjectNotFound("场次不存在")

    def _segment(self, script: dict[str, Any], segment_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        for episode in script.get("episodes") or []:
            for scene in episode.get("scenes") or []:
                for segment in scene.get("segments") or []:
                    if segment.get("id") == segment_id:
                        return episode, scene, segment
        raise StudioProjectNotFound("分段不存在")

    def _validate_segments(self, body: str, entries: Any, source_sha: str, aliases: dict[str, str], staged: dict[str, bytes]) -> list[dict[str, Any]]:
        if not isinstance(entries, list) or len(entries) > MAX_ITEMS:
            raise StudioProjectError("segments 必须是有限数组")
        result: list[dict[str, Any]] = []
        previous_end = 0
        used_ids: set[str] = set()
        for index, raw in enumerate(entries, 1):
            if not isinstance(raw, Mapping):
                raise StudioProjectError("segment 必须是对象")
            _need_keys(raw, {"id", "client_ref", "title", "start", "end", "exact_text"}, {"title"})
            segment_id = _safe_id(raw.get("id"), "分段 ID") if raw.get("id") else _new_id("segment")
            client_ref = str(raw.get("client_ref") or "").strip()
            if client_ref:
                if not ID_PATTERN.fullmatch(client_ref) or client_ref in aliases:
                    raise StudioProjectError("分段 client_ref 无效或重复")
                aliases[client_ref] = segment_id
            if segment_id in used_ids:
                raise StudioProjectError("分段 ID 重复")
            used_ids.add(segment_id)
            start, end = raw.get("start"), raw.get("end")
            exact_text = raw.get("exact_text")
            if start is None and end is None and isinstance(exact_text, str):
                first = body.find(exact_text, previous_end)
                if not exact_text or first < 0 or body.find(exact_text, first + 1) >= 0:
                    raise StudioProjectError("分段原文不唯一或不存在；重复文本请提供精确码点范围")
                start, end = first, first + len(exact_text)
            if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int)
                    or not isinstance(end, int) or start < previous_end or end < start or end > len(body)):
                raise StudioProjectError("分段范围必须是递增且不重叠的 Unicode 码点范围")
            if exact_text is not None and (not isinstance(exact_text, str) or body[start:end] != exact_text):
                raise StudioProjectConflict("分段正文与提交的精确范围不一致")
            result.append({"id": segment_id, "order": index, "title": _clean_title(raw.get("title"), f"分段 {index}"),
                           "start": start, "end": end, "source_sha256": source_sha})
            previous_end = end
        return result

    def _segments_for_body(self, body: str, digest: str, previous: Optional[list[dict[str, Any]]] = None,
                           old_body: str = "", old_digest: str = "") -> list[dict[str, Any]]:
        ranges = _split_script_segments_with_ranges(body)
        parts = [body[start:end] for start, end in ranges]
        preserved: dict[int, dict[str, Any]] = {}
        previous = previous or []
        if previous:
            old_parts = []
            for item in previous:
                if item.get("source_sha256") != old_digest:
                    raise StudioProjectConflict("原分段来源已变化，请重新读取场次后再编辑")
                start, end = item.get("start"), item.get("end")
                if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int)
                        or not isinstance(end, int) or start < 0 or end < start or end > len(old_body)):
                    raise DataFileError("原分段码点范围无效；原项目记录已保留。")
                old_parts.append((item, old_body[start:end]))
            for index, (old, new_part) in enumerate(zip(old_parts, parts)):
                if old[1] == new_part:
                    preserved[index] = old[0]
        result = []
        for index, ((start, end), text_value) in enumerate(zip(ranges, parts), 1):
            old = preserved.get(index - 1)
            result.append({"id": old.get("id") if old else _new_id("segment"), "order": index,
                           "title": _clean_title(old.get("title"), f"第 {index} 段") if old else f"第 {index} 段",
                           "start": start, "end": end, "source_sha256": digest})
        return result

    @staticmethod
    def _script_editable_text(scene: Mapping[str, Any], body: str) -> str:
        segments = list(scene.get("segments") or [])
        delimiter_ranges = _split_script_segments_with_ranges(body)
        has_delimiter = bool(re.search(r"(?m)^---(?:\n|$)", body))
        if not segments:
            return body
        ranges: list[tuple[int, int]] = []
        digest = str(scene.get("content_sha256") or "")
        cursor = 0
        for item in segments:
            if item.get("source_sha256") != digest:
                raise StudioProjectConflict("场次分段来源已变化，无法生成 Markdown 编辑正文")
            start, end = item.get("start"), item.get("end")
            if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int)
                    or not isinstance(end, int) or start < cursor or end < start or end > len(body)):
                raise DataFileError("场次分段码点范围无效；原项目记录已保留。")
            ranges.append((start, end))
            cursor = end
        if has_delimiter:
            if ranges != delimiter_ranges:
                raise StudioProjectConflict("场次中的 --- 边界与已保存分段不一致；请先重新读取或修复场次正文")
            return body
        parts = []
        cursor = 0
        for start, end in ranges:
            parts.append(body[cursor:end])
            cursor = end
        if cursor < len(body):
            parts[-1] += body[cursor:]
        return "\n---\n".join(parts)

    def _script_segment_parts(self, scene: Mapping[str, Any], body: str) -> list[str]:
        """Return the exact editable text belonging to each saved segment.

        Segment deletion and restoration must not guess how legacy range gaps
        were intended to move. Require each visible part to map to its saved
        Unicode range before changing the scene body.
        """
        segments = list(scene.get("segments") or [])
        if not segments:
            if body:
                raise StudioProjectConflict({"code": "SEGMENT_RANGE_CONFLICT",
                    "message": "场次尚未划分分段；请先整理 Markdown 正文后再执行分段操作。"})
            return []
        editable = self._script_editable_text(scene, body)
        ranges = _split_script_segments_with_ranges(editable)
        if len(ranges) != len(segments):
            raise StudioProjectConflict({"code": "SEGMENT_RANGE_CONFLICT",
                "message": "场次正文与分段目录无法一一对应；请先在 Markdown 编辑器中整理分段边界。"})
        parts = [editable[start:end] for start, end in ranges]
        for segment, part in zip(segments, parts):
            start, end = segment.get("start"), segment.get("end")
            if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int)
                    or not isinstance(end, int) or start < 0 or end < start or end > len(body)):
                raise DataFileError("场次分段码点范围无效；原项目记录已保留。")
            if body[start:end] != part:
                raise StudioProjectConflict({"code": "SEGMENT_RANGE_CONFLICT",
                    "message": "该分段没有对应一段连续、完整的场次正文；请先在 Markdown 编辑器中整理边界。"})
        return parts

    def _delete_script_segment(self, scene: dict[str, Any], index: int,
                               staged: dict[str, bytes]) -> tuple[dict[str, Any], dict[str, Any]]:
        segments = copy.deepcopy(scene.get("segments") or [])
        if not 0 <= index < len(segments):
            raise StudioProjectNotFound("分段不存在")
        old_digest = str(scene.get("content_sha256") or "")
        body = self._read_blob(old_digest) if old_digest else ""
        if len(body) != int(scene.get("char_count") or 0):
            raise DataFileError("场次正文长度与已保存记录不匹配；原项目记录已保留。")
        if any(item.get("source_sha256") != old_digest for item in segments):
            raise StudioProjectConflict({"code": "SEGMENT_RANGE_CONFLICT",
                "message": "场次分段来源已变化，请重新读取场次后再删除。"})
        parts = self._script_segment_parts(scene, body)
        removed = segments.pop(index)
        removed_text = parts.pop(index)
        remaining_ids = [item["id"] for item in segments]
        new_body = "\n---\n".join(parts) if parts else ""

        scene_revision = int(scene.get("revision", 1))
        scene.setdefault("history", []).append({"revision": scene_revision,
            "content_sha256": old_digest, "segments": copy.deepcopy(scene.get("segments") or []),
            "created_at": _now_ms()})
        digest = self._stage_blob(new_body, staged)
        ranges = _split_script_segments_with_ranges(new_body) if segments else []
        if len(ranges) != len(segments):
            raise DataFileError("删除分段后的边界校验失败；原项目记录已保留。")
        next_segments = self._segments_from_ranges(new_body, digest, [
            {"id": item["id"], "title": item.get("title"), "start": start, "end": end}
            for item, (start, end) in zip(segments, ranges)])
        next_scene_revision = scene_revision + 1
        scene.update({"content_sha256": digest, "char_count": len(new_body),
                      "revision": next_scene_revision, "segments": next_segments,
                      "segment_state": "structured" if next_segments else "unsegmented"})
        restore_guard = {"scene_revision": next_scene_revision, "content_sha256": digest,
                         "remaining_segment_ids": remaining_ids,
                         "remaining_segment_text_sha256s": [_digest(part) for part in parts],
                         "deleted_segment_text_sha256": _digest(removed_text)}
        return removed, restore_guard

    def _restore_script_segment(self, scene: dict[str, Any], archived: dict[str, Any],
                                staged: dict[str, bytes]) -> list[str]:
        item = copy.deepcopy(archived.get("item") or {})
        item_id = str(item.get("id") or "")
        segments = copy.deepcopy(scene.get("segments") or [])
        if any(value.get("id") == item_id for value in segments):
            raise StudioProjectConflict("该 ID 已存在，不能覆盖")
        guard = archived.get("restore_guard")
        if not isinstance(guard, Mapping):
            raise StudioProjectConflict({"code": "SEGMENT_RESTORE_CONFLICT",
                "message": "该旧归档没有可验证的删除后快照，不能安全恢复；请从历史正文手动整理。"})

        digest = str(scene.get("content_sha256") or "")
        scene_revision = int(scene.get("revision", 1))
        expected_ids = guard.get("remaining_segment_ids")
        actual_ids = [str(value.get("id") or "") for value in segments]
        if (scene_revision != guard.get("scene_revision") or digest != guard.get("content_sha256")
                or actual_ids != expected_ids):
            raise StudioProjectConflict({"code": "SEGMENT_RESTORE_CONFLICT",
                "message": "删除分段后场次正文或分段结构已变化，未恢复以免覆盖后续编辑。",
                "current_scene_revision": scene_revision})

        body = self._read_blob(digest) if digest else ""
        if len(body) != int(scene.get("char_count") or 0):
            raise DataFileError("场次正文长度与已保存记录不匹配；原项目记录已保留。")
        parts = self._script_segment_parts(scene, body)
        expected_text_hashes = guard.get("remaining_segment_text_sha256s")
        if (not isinstance(expected_text_hashes, list) or len(expected_text_hashes) != len(parts)
                or [_digest(part) for part in parts] != expected_text_hashes):
            raise StudioProjectConflict({"code": "SEGMENT_RESTORE_CONFLICT",
                "message": "删除分段后的正文校验不匹配，未恢复以免覆盖后续编辑。",
                "current_scene_revision": scene_revision})

        source_digest = str(item.get("source_sha256") or "")
        source_body = self._read_blob(source_digest) if source_digest else ""
        start, end = item.get("start"), item.get("end")
        if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int)
                or not isinstance(end, int) or start < 0 or end < start or end > len(source_body)):
            raise DataFileError("归档分段的来源码点范围无效；原项目记录已保留。")
        restored_text = source_body[start:end]
        if _digest(restored_text) != guard.get("deleted_segment_text_sha256"):
            raise DataFileError("归档分段正文与删除时快照不一致；原项目记录已保留。")

        original_order = item.get("order")
        if isinstance(original_order, bool) or not isinstance(original_order, int) or original_order < 1:
            raise DataFileError("归档分段顺序无效；原项目记录已保留。")
        position = min(original_order - 1, len(segments))
        parts.insert(position, restored_text)
        segments.insert(position, item)
        new_body = "\n---\n".join(parts)
        ranges = _split_script_segments_with_ranges(new_body)
        if len(ranges) != len(segments):
            raise DataFileError("恢复分段后的边界校验失败；原项目记录已保留。")

        scene.setdefault("history", []).append({"revision": scene_revision,
            "content_sha256": digest, "segments": copy.deepcopy(scene.get("segments") or []),
            "created_at": _now_ms()})
        new_digest = self._stage_blob(new_body, staged)
        restored_segments = self._segments_from_ranges(new_body, new_digest, [
            {"id": value["id"], "title": value.get("title"), "start": begin, "end": finish}
            for value, (begin, finish) in zip(segments, ranges)])
        scene.update({"content_sha256": new_digest, "char_count": len(new_body),
                      "revision": scene_revision + 1, "segments": restored_segments,
                      "segment_state": "structured"})
        return [scene["id"], *(value["id"] for value in restored_segments)]

    @staticmethod
    def _segments_from_ranges(body: str, digest: str, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for index, item in enumerate(specs, 1):
            result.append({"id": item["id"], "order": index,
                           "title": _clean_title(item.get("title"), f"第 {index} 段"),
                           "start": item["start"], "end": item["end"], "source_sha256": digest})
        return result

    def _import_script_markdown(self, script: dict[str, Any], body: str, replace: bool, staged: dict[str, bytes]) -> list[str]:
        if not isinstance(replace, bool):
            raise StudioProjectError("replace 必须是布尔值")
        has_content = bool(script.get("draft_sha256") or script.get("episodes"))
        if has_content and not replace:
            raise StudioProjectConflict("项目已有剧本内容；显式提交 replace:true 才能归档并替换")
        parsed = _parse_script_markdown(body)
        old_snapshot = {"kind": "markdown_replace", "state": script.get("state"),
                        "draft_sha256": script.get("draft_sha256") or "",
                        "draft_char_count": int(script.get("draft_char_count") or 0),
                        "episodes": copy.deepcopy(script.get("episodes") or []), "created_at": _now_ms()}
        if has_content:
            script.setdefault("archive", []).append(old_snapshot)
        source_sha = self._stage_blob(body, staged)
        script.setdefault("history", []).append({"kind": "markdown_import", "content_sha256": source_sha,
                                                   "created_at": _now_ms(), "label": "导入的剧本 Markdown"})
        if parsed is None:
            script.update({"state": "draft", "draft_sha256": source_sha, "draft_char_count": len(body), "episodes": []})
            return ["script"]
        episodes = []
        changed = []
        for episode_index, parsed_episode in enumerate(parsed, 1):
            episode_id = _new_id("episode")
            scenes = []
            for scene_index, parsed_scene in enumerate(parsed_episode["scenes"], 1):
                scene_body = parsed_scene["body_markdown"]
                digest = self._stage_blob(scene_body, staged)
                ranges = _split_script_segments_with_ranges(scene_body)
                segments = [{"id": _new_id("segment"), "order": index,
                             "title": f"第 {index} 段", "start": start, "end": end,
                             "source_sha256": digest}
                            for index, (start, end) in enumerate(ranges, 1)]
                scene_id = _new_id("scene")
                scenes.append({"id": scene_id, "title": parsed_scene["title"], "order": scene_index,
                               "content_sha256": digest, "char_count": len(scene_body), "revision": 1,
                               "segments": segments, "segment_state": "structured", "history": []})
                changed.extend([scene_id, *(item["id"] for item in segments)])
            episodes.append({"id": episode_id, "title": parsed_episode["title"], "order": episode_index,
                             "scenes": scenes, "outline_revision": 0, "outline_sha256": "",
                             "outline_char_count": 0, "outline_history": []})
            changed.append(episode_id)
        script.update({"state": "structured", "draft_sha256": "", "draft_char_count": 0, "episodes": episodes})
        return changed or ["script"]

    def _import_novel_markdown(self, novel: dict[str, Any], body: str, replace: bool, staged: dict[str, bytes]) -> list[str]:
        if not isinstance(replace, bool):
            raise StudioProjectError("replace 必须是布尔值")
        has_content = bool(novel.get("volumes"))
        if has_content and not replace:
            raise StudioProjectConflict("项目已有卷章正文；显式提交 replace:true 才能归档并替换")
        parsed = _parse_novel_markdown(body)
        if has_content:
            novel.setdefault("archive", []).append({"kind": "markdown_replace",
                "volumes": copy.deepcopy(novel.get("volumes") or []), "created_at": _now_ms()})
        source_sha = self._stage_blob(body, staged)
        novel.setdefault("history", []).append({"kind": "markdown_import", "content_sha256": source_sha,
                                                  "created_at": _now_ms(), "label": "导入的小说 Markdown"})
        volumes = []
        changed = []
        for volume_index, parsed_volume in enumerate(parsed, 1):
            volume_id = _new_id("volume")
            chapters = []
            for chapter_index, parsed_chapter in enumerate(parsed_volume["chapters"], 1):
                chapter_body = parsed_chapter["body_markdown"]
                digest = self._stage_blob(chapter_body, staged)
                chapter_id = _new_id("chapter")
                chapters.append({"id": chapter_id, "title": parsed_chapter["title"], "order": chapter_index,
                                 "content_sha256": digest, "char_count": len(chapter_body), "revision": 1,
                                 "basis_refs": [], "history": [], "created_at": _now_ms(),
                                 "outline_revision": 0, "outline_sha256": "",
                                 "outline_char_count": 0, "outline_history": []})
                changed.append(chapter_id)
            volumes.append({"id": volume_id, "title": parsed_volume["title"], "order": volume_index,
                            "chapters": chapters})
            changed.append(volume_id)
        novel["volumes"] = volumes
        return changed or ["novel"]

    def script_markdown(self, project_id: str) -> dict[str, Any]:
        with self.projects.lock:
            record = self._record(str(project_id), "script")
            script = record["script"]
            if script.get("state") == "draft":
                body = self._read_blob(script["draft_sha256"]) if script.get("draft_sha256") else ""
            else:
                pieces = []
                episodes = script.get("episodes") or []
                for episode_index, episode in enumerate(episodes):
                    if episode_index:
                        previous = episodes[episode_index - 1]
                        if previous.get("scenes"):
                            pieces.append("\n")
                    pieces.append(f"# {_clean_title(episode.get('title'), f'第 {episode_index + 1} 集')}\n")
                    for scene_index, scene in enumerate(episode.get("scenes") or []):
                        if scene_index:
                            pieces.append("\n")
                        title = _clean_title(scene.get("title"), f"第 {scene_index + 1} 场")
                        digest = scene.get("content_sha256") or ""
                        scene_body = self._read_blob(digest) if digest else ""
                        if len(scene_body) != int(scene.get("char_count") or 0):
                            raise DataFileError("场次正文长度与已保存记录不匹配；原项目记录已保留。")
                        pieces.append(f"## {title}\n")
                        pieces.append(self._script_editable_text(scene, scene_body))
                body = "".join(pieces)
                try:
                    parsed = _parse_script_markdown(body)
                except StudioProjectError as exc:
                    raise StudioProjectConflict({"code": "MARKDOWN_FORMAT_CONFLICT",
                        "message": "剧本目录无法无损表示为当前 Markdown 格式，请检查集、场标题及正文中的一级/二级标题。"}) from exc
                expected = [{"title": _clean_title(ep.get("title"), f"第 {ep_index + 1} 集"),
                             "scenes": [{"title": _clean_title(scene.get("title"), f"第 {scene_index + 1} 场"),
                                         "body_markdown": self._script_editable_text(scene,
                                             self._read_blob(scene.get("content_sha256") or "") if scene.get("content_sha256") else "")}
                                         for scene_index, scene in enumerate(ep.get("scenes") or [])]}
                            for ep_index, ep in enumerate(episodes)]
                actual = [] if parsed is None else [{"title": ep["title"], "scenes": [
                    {"title": scene["title"], "body_markdown": scene["body_markdown"]} for scene in ep["scenes"]]}
                    for ep in parsed]
                if parsed is None or actual != expected:
                    raise StudioProjectConflict({"code": "MARKDOWN_FORMAT_CONFLICT",
                        "message": "剧本目录无法无损表示为当前 Markdown 格式，请检查集、场标题及正文中的一级/二级标题。"})
            return {"project_id": record["id"], "revision": self._revision(record),
                    "format_version": MANUSCRIPT_MARKDOWN_FORMAT_VERSION,
                    "source_sha256": _digest(body), "body_markdown": body}

    def novel_markdown(self, project_id: str) -> dict[str, Any]:
        with self.projects.lock:
            record = self._record(str(project_id), "novel")
            novel = record["novel"]
            pieces = []
            volumes = novel.get("volumes") or []
            for volume_index, volume in enumerate(volumes):
                if volume_index:
                    previous = volumes[volume_index - 1]
                    if previous.get("chapters"):
                        pieces.append("\n")
                pieces.append(f"# {_clean_title(volume.get('title'), f'第 {volume_index + 1} 卷')}\n")
                for chapter_index, chapter in enumerate(volume.get("chapters") or []):
                    if chapter_index:
                        pieces.append("\n")
                    title = _clean_title(chapter.get("title"), f"第 {chapter_index + 1} 章")
                    digest = chapter.get("content_sha256") or ""
                    chapter_body = self._read_blob(digest) if digest else ""
                    if len(chapter_body) != int(chapter.get("char_count") or 0):
                        raise DataFileError("章节正文长度与已保存记录不匹配；原项目记录已保留。")
                    pieces.append(f"## {title}\n")
                    pieces.append(chapter_body)
            body = "".join(pieces)
            try:
                parsed = _parse_novel_markdown(body)
            except StudioProjectError as exc:
                raise StudioProjectConflict({"code": "MARKDOWN_FORMAT_CONFLICT",
                    "message": "小说目录无法无损表示为当前 Markdown 格式，请检查卷、章标题及章节中的一级/二级标题。"}) from exc
            expected = [{"title": _clean_title(volume.get("title"), f"第 {index + 1} 卷"),
                         "chapters": [{"title": _clean_title(chapter.get("title"), f"第 {chapter_index + 1} 章"),
                                      "body_markdown": self._read_blob(chapter.get("content_sha256") or "")
                                          if chapter.get("content_sha256") else ""}
                                      for chapter_index, chapter in enumerate(volume.get("chapters") or [])]}
                        for index, volume in enumerate(volumes)]
            if parsed != expected:
                raise StudioProjectConflict({"code": "MARKDOWN_FORMAT_CONFLICT",
                    "message": "小说目录无法无损表示为当前 Markdown 格式，请检查卷、章标题及章节中的一级/二级标题。"})
            return {"project_id": record["id"], "revision": self._revision(record),
                    "format_version": MANUSCRIPT_MARKDOWN_FORMAT_VERSION,
                    "source_sha256": _digest(body), "body_markdown": body}

    def _script_action(self, script: dict[str, Any], action: str, args: Mapping[str, Any],
                       aliases: dict[str, str], staged: dict[str, bytes]) -> tuple[list[str], dict[str, str]]:
        changed: list[str] = []
        created: dict[str, str] = {}
        if action == "set_episode_outline":
            _need_keys(args, {"episode_id", "body_markdown"}, {"episode_id", "body_markdown"})
            episode_id = self._resolve(args["episode_id"], aliases, "集 ID")
            _, episode = self._script_episode(script, episode_id)
            self._set_outline(episode, args["body_markdown"], staged)
            changed.append(episode_id)
        elif action == "import_markdown":
            _need_keys(args, {"body_markdown", "replace"}, {"body_markdown", "replace"})
            changed.extend(self._import_script_markdown(script, _body(args["body_markdown"]), args["replace"], staged))
        elif action == "set_draft":
            _need_keys(args, {"body_markdown"}, {"body_markdown"})
            if script.get("state") == "structured" and script.get("episodes"):
                raise StudioProjectConflict("结构化剧本不能用 set_draft 覆盖；请明确修改场次正文")
            body = _body(args["body_markdown"])
            old = script.get("draft_sha256") or ""
            if old:
                script.setdefault("history", []).append({"kind": "draft", "content_sha256": old,
                                                          "created_at": _now_ms(), "label": "上一版完整剧本"})
            digest = self._stage_blob(body, staged) if body else ""
            script.update({"state": "draft", "draft_sha256": digest, "draft_char_count": len(body), "episodes": []})
            changed.append("script")
        elif action == "restore_draft":
            _need_keys(args, {"source_sha256", "replace_structured"}, {"source_sha256", "replace_structured"})
            if args.get("replace_structured") is not True:
                raise StudioProjectError("恢复旧草稿必须明确 replace_structured:true")
            source_digest = str(args.get("source_sha256") or "")
            if not HASH_PATTERN.fullmatch(source_digest):
                raise StudioProjectError("source_sha256 格式无效")
            history = script.get("history") or []
            if not any(item.get("kind") == "draft" and item.get("content_sha256") == source_digest
                       for item in history if isinstance(item, Mapping)):
                raise StudioProjectNotFound("指定的完整草稿不在本项目历史中")
            body = self._read_blob(source_digest)
            current_digest = str(script.get("draft_sha256") or "")
            current_episodes = copy.deepcopy(script.get("episodes") or [])
            if current_digest and current_digest != source_digest:
                history.append({"kind": "draft", "content_sha256": current_digest,
                                "created_at": _now_ms(), "label": "恢复前完整草稿快照"})
            if current_episodes:
                script.setdefault("archive", []).append({
                    "kind": "structured_script_snapshot", "state": script.get("state"),
                    "draft_sha256": current_digest, "draft_char_count": int(script.get("draft_char_count") or 0),
                    "episodes": current_episodes, "created_at": _now_ms(),
                    "reason": "restore_draft",
                })
            script.update({"state": "draft", "draft_sha256": source_digest,
                           "draft_char_count": len(body), "episodes": []})
            changed.append("script")
        elif action == "structure_draft":
            _need_keys(args, {"episodes"}, {"episodes"})
            if script.get("state") != "draft" or not script.get("draft_sha256"):
                raise StudioProjectConflict("只有已保存的完整草稿可以结构化")
            source = self._read_blob(script["draft_sha256"])
            episodes = args["episodes"]
            if not isinstance(episodes, list) or not episodes or len(episodes) > MAX_ITEMS:
                raise StudioProjectError("episodes 必须是非空数组")
            made: list[dict[str, Any]] = []
            alias_ranges: list[tuple[int, int]] = []
            inferred_parts: list[str] = []
            inferred_scenes = 0
            for e_index, raw_episode in enumerate(episodes, 1):
                if not isinstance(raw_episode, Mapping):
                    raise StudioProjectError("episode 必须是对象")
                _need_keys(raw_episode, {"client_ref", "title", "scenes"}, {"title", "scenes"})
                episode_id = _new_id("episode")
                client_ref = str(raw_episode.get("client_ref") or "").strip()
                if client_ref:
                    if not ID_PATTERN.fullmatch(client_ref) or client_ref in aliases:
                        raise StudioProjectError("episode client_ref 无效或重复")
                    aliases[client_ref] = episode_id
                    created[client_ref] = episode_id
                scenes_raw = raw_episode.get("scenes")
                if not isinstance(scenes_raw, list) or not scenes_raw:
                    raise StudioProjectError("每一集必须至少包含一个场次")
                scenes = []
                for s_index, raw_scene in enumerate(scenes_raw, 1):
                    if not isinstance(raw_scene, Mapping):
                        raise StudioProjectError("scene 必须是对象")
                    _need_keys(raw_scene, {"client_ref", "title", "body_markdown", "start", "end", "segments"},
                               {"title", "body_markdown"})
                    body = _body(raw_scene["body_markdown"])
                    if "start" in raw_scene or "end" in raw_scene:
                        start, end = raw_scene.get("start"), raw_scene.get("end")
                        if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int)
                                or not isinstance(end, int) or start < 0 or end <= start or end > len(source)
                                or source[start:end] != body):
                            raise StudioProjectConflict("场次正文必须与完整草稿的精确码点范围一致")
                        alias_ranges.append((start, end))
                    else:
                        inferred_parts.append(body)
                        inferred_scenes += 1
                    scene_id = _new_id("scene")
                    scene_ref = str(raw_scene.get("client_ref") or "").strip()
                    if scene_ref:
                        if not ID_PATTERN.fullmatch(scene_ref) or scene_ref in aliases:
                            raise StudioProjectError("scene client_ref 无效或重复")
                        aliases[scene_ref] = scene_id
                        created[scene_ref] = scene_id
                    digest = self._stage_blob(body, staged)
                    segments = self._validate_segments(body, raw_scene.get("segments", []), digest, aliases, staged)
                    scenes.append({"id": scene_id, "title": _clean_title(raw_scene.get("title"), f"第 {s_index} 场"),
                                   "order": s_index, "content_sha256": digest, "char_count": len(body),
                                   "revision": 1, "segments": segments, "segment_state": "structured" if segments else "unsegmented",
                                   "history": []})
                    if scene_ref:
                        created[scene_ref] = scene_id
                made.append({"id": episode_id, "title": _clean_title(raw_episode.get("title"), f"第 {e_index} 集"),
                             "order": e_index, "scenes": scenes, "outline_revision": 0,
                             "outline_sha256": "", "outline_char_count": 0, "outline_history": []})
            if alias_ranges and inferred_scenes:
                raise StudioProjectConflict("结构化时必须为全部场次提供来源范围，或全部依赖逐字拼接校验")
            if alias_ranges:
                alias_ranges.sort()
                if alias_ranges[0][0] != 0 or alias_ranges[-1][1] != len(source) or any(
                    left[1] != right[0] for left, right in zip(alias_ranges, alias_ranges[1:])
                ):
                    raise StudioProjectConflict("结构化范围必须无遗漏、无重叠地覆盖完整草稿")
            elif "".join(inferred_parts) != source:
                raise StudioProjectConflict("结构化场次拼接后必须逐字等于完整草稿，不能遗漏、重复或改写")
            script.setdefault("history", []).append({"kind": "draft", "content_sha256": script["draft_sha256"],
                                                      "created_at": _now_ms(), "label": "结构化前草稿快照"})
            script.update({"state": "structured", "draft_sha256": "", "draft_char_count": 0, "episodes": made})
            changed.extend([scene["id"] for episode in made for scene in episode["scenes"]])
            changed.extend(episode["id"] for episode in made)
        elif action == "create_episode":
            _need_keys(args, {"title", "after_episode_id", "client_ref"}, {"title"})
            if script.get("state") == "draft" and script.get("draft_sha256"):
                raise StudioProjectConflict("先用 structure_draft 保留完整草稿，再新增分集")
            episodes = script.setdefault("episodes", [])
            if len(episodes) >= MAX_ITEMS:
                raise StudioProjectError("分集数量已达上限")
            episode_id = _new_id("episode")
            episode = {"id": episode_id, "title": _clean_title(args.get("title"), "未命名剧集"),
                       "order": len(episodes) + 1, "scenes": [], "outline_revision": 0,
                       "outline_sha256": "", "outline_char_count": 0, "outline_history": []}
            if args.get("after_episode_id"):
                after_id = self._resolve(args["after_episode_id"], aliases, "集 ID")
                position = next((i + 1 for i, item in enumerate(episodes) if item.get("id") == after_id), None)
                if position is None:
                    raise StudioProjectNotFound("插入位置对应的剧集不存在")
                episodes.insert(position, episode)
            else:
                episodes.append(episode)
            self._renumber(episodes)
            script["state"] = "structured"
            if args.get("client_ref"):
                ref = str(args["client_ref"])
                if not ID_PATTERN.fullmatch(ref) or ref in aliases:
                    raise StudioProjectError("client_ref 无效或重复")
                aliases[ref] = episode_id
                created[ref] = episode_id
            changed.append(episode_id)
        elif action == "create_scene":
            _need_keys(args, {"episode_id", "episode_ref", "title", "body_markdown", "after_scene_id", "client_ref"},
                       {"title", "body_markdown"})
            if script.get("state") == "draft" and script.get("draft_sha256"):
                raise StudioProjectConflict("先用 structure_draft 保留完整草稿，再新增场次")
            parent_ref = args.get("episode_id") or args.get("episode_ref")
            if not parent_ref:
                raise StudioProjectError("缺少 episode_id")
            episode_id = self._resolve(parent_ref, aliases, "集 ID")
            episode = self._entry(script.setdefault("episodes", []), episode_id, "剧集")
            if len(episode.setdefault("scenes", [])) >= MAX_ITEMS:
                raise StudioProjectError("场次数量已达上限")
            body = _body(args["body_markdown"])
            digest = self._stage_blob(body, staged)
            scene_id = _new_id("scene")
            segments = self._segments_for_body(body, digest)
            scene = {"id": scene_id, "title": _clean_title(args.get("title"), "未命名场次"),
                     "order": len(episode["scenes"]) + 1, "content_sha256": digest, "char_count": len(body),
                     "revision": 1, "segments": segments, "segment_state": "structured", "history": []}
            after_id = args.get("after_scene_id")
            if after_id:
                after_id = self._resolve(after_id, aliases, "场次 ID")
                position = next((i + 1 for i, item in enumerate(episode["scenes"]) if item.get("id") == after_id), None)
                if position is None:
                    raise StudioProjectNotFound("插入位置对应的场次不存在")
                episode["scenes"].insert(position, scene)
            else:
                episode["scenes"].append(scene)
            self._renumber(episode["scenes"])
            script["state"] = "structured"
            if args.get("client_ref"):
                ref = str(args["client_ref"])
                if not ID_PATTERN.fullmatch(ref) or ref in aliases:
                    raise StudioProjectError("client_ref 无效或重复")
                aliases[ref] = scene_id
                created[ref] = scene_id
            changed.extend([episode_id, scene_id, *(item["id"] for item in segments)])
        elif action == "create_segment":
            _need_keys(args, {"scene_id", "body_markdown", "after_segment_id", "title", "client_ref"},
                       {"scene_id", "body_markdown"})
            scene_id = self._resolve(args["scene_id"], aliases, "场次 ID")
            _, scene = self._script_scene(script, scene_id)
            new_part = _body(args["body_markdown"])
            if any(line == "---" for line in new_part.splitlines()):
                raise StudioProjectError("分段正文不能包含独立 ---；请在场次正文编辑器中管理分段边界")
            body = self._read_blob(scene.get("content_sha256") or "") if scene.get("content_sha256") else ""
            old_segments = copy.deepcopy(scene.get("segments") or [])
            if not old_segments:
                if body:
                    ranges = _split_script_segments_with_ranges(body)
                    old_segments = [{"id": _new_id("segment"), "title": f"第 {index} 段", "start": start,
                                     "end": end, "source_sha256": scene.get("content_sha256") or ""}
                                    for index, (start, end) in enumerate(ranges, 1)]
                    parts = [body[start:end] for start, end in ranges]
                else:
                    # Deleting a scene's sole segment intentionally leaves no
                    # placeholder row. A later manual create starts with only
                    # the requested segment.
                    parts = []
            else:
                expected_ranges = _split_script_segments_with_ranges(body)
                actual_ranges = []
                for item in old_segments:
                    if item.get("source_sha256") != (scene.get("content_sha256") or ""):
                        raise StudioProjectConflict("分段来源已变化，请先重新读取场次")
                    start, end = item.get("start"), item.get("end")
                    if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int)
                            or not isinstance(end, int) or start < 0 or end < start or end > len(body)):
                        raise StudioProjectConflict("当前分段码点范围无效；请先重新读取场次")
                    actual_ranges.append((start, end))
                if re.search(r"(?m)^---(?:\n|$)", body):
                    if actual_ranges != expected_ranges:
                        raise StudioProjectConflict("当前分段之间含未归属正文或边界不匹配；请先在场次 Markdown 中整理 --- 边界")
                    parts = [body[start:end] for start, end in expected_ranges]
                else:
                    cursor = 0
                    parts = []
                    for start, end in actual_ranges:
                        if start != cursor:
                            raise StudioProjectConflict("当前分段之间含未归属正文；请先在场次 Markdown 中整理 --- 边界")
                        parts.append(body[start:end])
                        cursor = end
                    if cursor != len(body):
                        raise StudioProjectConflict("当前分段末尾含未归属正文；请先在场次 Markdown 中整理 --- 边界")
            if args.get("after_segment_id"):
                after_id = self._resolve(args["after_segment_id"], aliases, "分段 ID")
                position = next((index + 1 for index, item in enumerate(old_segments) if item.get("id") == after_id), None)
                if position is None:
                    raise StudioProjectNotFound("插入位置对应的分段不属于当前场次")
            else:
                position = len(parts)
            new_segment = {"id": _new_id("segment"),
                           "title": _clean_title(args.get("title"), f"第 {position + 1} 段")}
            client_ref = str(args.get("client_ref") or "").strip()
            if client_ref:
                if not ID_PATTERN.fullmatch(client_ref) or client_ref in aliases:
                    raise StudioProjectError("client_ref 无效或重复")
                aliases[client_ref] = new_segment["id"]
                created[client_ref] = new_segment["id"]
            parts.insert(position, new_part)
            old_segments.insert(position, new_segment)
            new_body = "\n---\n".join(parts)
            old_digest = scene.get("content_sha256") or ""
            scene.setdefault("history", []).append({"revision": scene.get("revision", 1),
                "content_sha256": old_digest, "segments": copy.deepcopy(scene.get("segments") or []),
                "created_at": _now_ms()})
            digest = self._stage_blob(new_body, staged)
            ranges = _split_script_segments_with_ranges(new_body)
            if len(ranges) != len(old_segments):
                raise DataFileError("新建分段后的分段边界校验失败；原项目记录已保留。")
            segments = self._segments_from_ranges(new_body, digest, [
                {"id": value["id"], "title": value.get("title"), "start": start, "end": end}
                for value, (start, end) in zip(old_segments, ranges)])
            scene.update({"content_sha256": digest, "char_count": len(new_body),
                          "revision": int(scene.get("revision", 1)) + 1,
                          "segments": segments, "segment_state": "structured"})
            changed.extend([scene_id, *(item["id"] for item in segments)])
        elif action == "update_scene":
            _need_keys(args, {"scene_id", "body_markdown"}, {"scene_id", "body_markdown"})
            scene_id = self._resolve(args["scene_id"], aliases, "场次 ID")
            _, scene = self._script_scene(script, scene_id)
            body = _body(args["body_markdown"])
            old_sha = scene.get("content_sha256") or ""
            old_body = self._read_blob(old_sha) if old_sha else ""
            scene.setdefault("history", []).append({"revision": scene.get("revision", 1), "content_sha256": old_sha,
                                                     "segments": copy.deepcopy(scene.get("segments") or []), "created_at": _now_ms()})
            digest = self._stage_blob(body, staged)
            segments = self._segments_for_body(body, digest, scene.get("segments") or [], old_body, old_sha)
            scene.update({"content_sha256": digest, "char_count": len(body), "revision": int(scene.get("revision", 1)) + 1,
                          "segments": segments, "segment_state": "structured"})
            changed.extend([scene_id, *(item["id"] for item in segments)])
        elif action == "set_scene_segments":
            _need_keys(args, {"scene_id", "source_sha256", "segments"}, {"scene_id", "source_sha256", "segments"})
            scene_id = self._resolve(args["scene_id"], aliases, "场次 ID")
            _, scene = self._script_scene(script, scene_id)
            if args["source_sha256"] != scene.get("content_sha256"):
                raise StudioProjectConflict("场次正文已变化，请重新读取后再划分分段")
            body = self._read_blob(scene["content_sha256"]) if scene.get("content_sha256") else ""
            existing_ids = {item.get("id") for item in scene.get("segments") or []}
            for item in args["segments"] if isinstance(args["segments"], list) else []:
                if isinstance(item, Mapping) and item.get("id") and item["id"] not in existing_ids:
                    if any(item["id"] == segment.get("id") for _, other in self._all_script_scenes(script)
                           for segment in other.get("segments") or []):
                        raise StudioProjectConflict("分段 ID 已被其他场次使用")
            segments = self._validate_segments(body, args["segments"], scene.get("content_sha256") or "", aliases, staged)
            scene.setdefault("history", []).append({"revision": scene.get("revision", 1), "content_sha256": scene.get("content_sha256"),
                                                     "segments": copy.deepcopy(scene.get("segments") or []), "created_at": _now_ms()})
            scene["segments"] = segments
            scene["segment_state"] = "structured" if segments else "unsegmented"
            scene["revision"] = int(scene.get("revision", 1)) + 1
            changed.append(scene_id)
            changed.extend(item["id"] for item in segments)
        elif action == "replace_segment_text":
            _need_keys(args, {"segment_id", "body_markdown"}, {"segment_id", "body_markdown"})
            segment_id = self._resolve(args["segment_id"], aliases, "分段 ID")
            _, scene, segment = self._segment(script, segment_id)
            body = self._read_blob(scene.get("content_sha256") or "")
            if any(item.get("source_sha256") != scene.get("content_sha256") for item in scene.get("segments") or []):
                raise StudioProjectConflict("分段来源已变化，请先重新划分")
            replacement = _body(args["body_markdown"])
            if any(line == "---" for line in replacement.splitlines()):
                raise StudioProjectError("分段正文不能包含独立 ---；请在场次正文编辑器中管理分段边界")
            start, end = int(segment["start"]), int(segment["end"])
            if body[start:end] == replacement:
                return changed, created
            new_body = body[:start] + replacement + body[end:]
            delta = len(replacement) - (end - start)
            old_sha = scene["content_sha256"]
            scene.setdefault("history", []).append({"revision": scene.get("revision", 1), "content_sha256": old_sha,
                                                     "segments": copy.deepcopy(scene.get("segments") or []), "created_at": _now_ms()})
            new_sha = self._stage_blob(new_body, staged)
            for item in scene.get("segments") or []:
                if item["id"] == segment_id:
                    item["end"] = start + len(replacement)
                elif item["start"] >= end:
                    item["start"] += delta
                    item["end"] += delta
                elif item["start"] < start < item["end"]:
                    raise StudioProjectConflict("分段范围重叠，拒绝更新")
                item["source_sha256"] = new_sha
            scene.update({"content_sha256": new_sha, "char_count": len(new_body), "revision": int(scene.get("revision", 1)) + 1})
            changed.extend([scene["id"], segment_id])
        elif action == "rename_item":
            _need_keys(args, {"item_type", "item_id", "title"}, {"item_type", "item_id", "title"})
            kind = args["item_type"]
            item_id = self._resolve(args["item_id"], aliases, "条目 ID")
            if kind == "episode":
                item = self._entry(script.setdefault("episodes", []), item_id, "剧集")
            elif kind == "scene":
                _, item = self._script_scene(script, item_id)
            elif kind == "segment":
                _, _, item = self._segment(script, item_id)
            else:
                raise StudioProjectError("item_type 必须为 episode、scene 或 segment")
            item["title"] = _clean_title(args["title"])
            changed.append(item_id)
        elif action == "reorder_items":
            _need_keys(args, {"parent_type", "parent_id", "ordered_ids"}, {"parent_type", "ordered_ids"})
            if args["parent_type"] == "root":
                collection = script.setdefault("episodes", [])
                if args.get("parent_id"):
                    raise StudioProjectError("root 重排不能提供 parent_id")
            elif args["parent_type"] == "episode":
                parent_id = self._resolve(args.get("parent_id"), aliases, "集 ID")
                parent = self._entry(script.setdefault("episodes", []), parent_id, "剧集")
                collection = parent.setdefault("scenes", [])
            else:
                raise StudioProjectError("parent_type 必须为 root 或 episode")
            ordered = args["ordered_ids"]
            ids = [self._resolve(item, aliases, "条目 ID") for item in ordered] if isinstance(ordered, list) else []
            existing = [item.get("id") for item in collection]
            if len(ids) != len(existing) or len(set(ids)) != len(ids) or set(ids) != set(existing):
                raise StudioProjectConflict("重排必须恰好包含全部同级条目，不可重复或跨级")
            by_id = {item["id"]: item for item in collection}
            collection[:] = [by_id[item_id] for item_id in ids]
            self._renumber(collection)
            changed.extend(ids)
        elif action in {"delete_item", "restore_item"}:
            if action == "delete_item":
                _need_keys(args, {"item_type", "item_id", "include_descendants"}, {"item_type", "item_id"})
                kind, item_id = args["item_type"], self._resolve(args["item_id"], aliases, "条目 ID")
                include = args.get("include_descendants", False)
                if not isinstance(include, bool):
                    raise StudioProjectError("include_descendants 必须是布尔值")
                archive_parent_id = None
                if kind == "episode":
                    collection = script.setdefault("episodes", [])
                    item = self._entry(collection, item_id, "剧集")
                    if item.get("scenes") and not include:
                        raise StudioProjectConflict("该集包含场次，需明确 include_descendants:true")
                elif kind == "scene":
                    parent, item = self._script_scene(script, item_id)
                    collection = parent["scenes"]
                    if item.get("segments") and not include:
                        raise StudioProjectConflict("该场包含分段，需明确 include_descendants:true")
                elif kind == "segment":
                    _, scene, item = self._segment(script, item_id)
                    collection = scene["segments"]
                    archive_parent_id = scene.get("id")
                else:
                    raise StudioProjectError("item_type 必须为 episode、scene 或 segment")
                if kind == "segment":
                    position = next(i for i, value in enumerate(collection) if value.get("id") == item_id)
                    removed, restore_guard = self._delete_script_segment(scene, position, staged)
                    script.setdefault("archive", []).append({"kind": kind, "item": removed,
                        "parent_id": archive_parent_id, "restore_guard": restore_guard, "created_at": _now_ms()})
                    changed.extend([scene["id"], *(value["id"] for value in scene.get("segments") or []), item_id])
                else:
                    removed = collection.pop(next(i for i, value in enumerate(collection) if value.get("id") == item_id))
                    script.setdefault("archive", []).append({"kind": kind, "item": removed,
                        "parent_id": parent.get("id") if kind == "scene" else archive_parent_id,
                        "created_at": _now_ms()})
                    self._renumber(collection)
                    changed.append(item_id)
            else:
                _need_keys(args, {"item_id"}, {"item_id"})
                item_id = self._resolve(args["item_id"], aliases, "条目 ID")
                archive = next((item for item in reversed(script.get("archive") or [])
                                if isinstance(item, dict) and (item.get("item") or {}).get("id") == item_id
                                and (item.get("kind") != "segment" or not item.get("restored_at"))), None)
                if archive is None:
                    raise StudioProjectNotFound("没有可恢复的剧本条目")
                kind, item = archive["kind"], archive["item"]
                if kind == "episode":
                    collection = script.setdefault("episodes", [])
                elif kind == "scene":
                    _, parent = self._script_episode(script, archive.get("parent_id"))
                    collection = parent.setdefault("scenes", [])
                elif kind == "segment":
                    _, scene = self._script_scene(script, self._find_archived_segment_parent(script, item_id))
                    changed.extend(self._restore_script_segment(scene, archive, staged))
                    archive["restored_at"] = _now_ms()
                    changed.append(item_id)
                    collection = None
                else:
                    raise DataFileError("归档条目类型无效")
                if kind != "segment":
                    if any(value.get("id") == item_id for value in collection):
                        raise StudioProjectConflict("该 ID 已存在，不能覆盖")
                    collection.append(item)
                    archive["restored_at"] = _now_ms()
                    self._renumber(collection)
                    changed.append(item_id)
        else:
            raise StudioProjectError(f"剧本动作不受支持：{action}")
        return changed, created

    @staticmethod
    def _renumber(items: list[dict[str, Any]]) -> None:
        for index, item in enumerate(items, 1):
            item["order"] = index

    def _script_episode(self, script: dict[str, Any], episode_id: str) -> tuple[None, dict[str, Any]]:
        return None, self._entry(script.setdefault("episodes", []), episode_id, "剧集")

    def _find_archived_segment_parent(self, script: dict[str, Any], segment_id: str) -> str:
        for archived in script.get("archive") or []:
            if (archived.get("kind") == "segment" and (archived.get("item") or {}).get("id") == segment_id):
                return str(archived.get("parent_id") or "")
        raise StudioProjectNotFound("分段归档缺少所属场次")

    def script_summary(self, project_id: str) -> dict[str, Any]:
        project_id = str(project_id)
        with self.projects.lock:
            record = self._record(project_id, "script")
            script = record["script"]
            episodes = []
            scene_count = segment_count = char_count = 0
            for episode in script.get("episodes") or []:
                scenes = []
                outline_revision, outline_digest, outline_count, _ = self._outline_state(episode)
                for scene in episode.get("scenes") or []:
                    segments = scene.get("segments") or []
                    scene_count += 1
                    segment_count += len(segments)
                    char_count += int(scene.get("char_count") or 0)
                    scenes.append({"id": scene["id"], "title": scene.get("title") or "未命名场次",
                                   "order": scene.get("order", 0), "revision": scene.get("revision", 1),
                                   "char_count": int(scene.get("char_count") or 0),
                                   "segment_state": scene.get("segment_state") or ("structured" if segments else "unsegmented"),
                                   "segments": [{"id": item["id"], "title": item.get("title") or "未命名分段",
                                                 "order": item.get("order", index), "start": item.get("start"), "end": item.get("end")}
                                                for index, item in enumerate(segments, 1)]})
                episodes.append({"id": episode["id"], "title": episode.get("title") or "未命名剧集",
                                 "order": episode.get("order", 0), "scenes": scenes,
                                 "outline_revision": outline_revision, "outline_sha256": outline_digest,
                                 "outline_char_count": outline_count})
            if script.get("state") == "draft":
                char_count = int(script.get("draft_char_count") or 0)
            return {"project": StudioProjectStore._manuscript_public(record), "revision": self._revision(record),
                    "schema_version": int(script.get("schema_version") or 1), "state": script.get("state", "draft"),
                    "directory": {"episodes": episodes},
                    "statistics": {"episodes": len(episodes), "scenes": scene_count, "segments": segment_count,
                                   "characters": char_count},
                    "capabilities": {"external_agent_writes": True, "generation": True,
                                     "generation_purposes": ["optimize"], "generation_slot": "text",
                                     "generation_scopes": ["scene", "segment", "episode_outline"],
                                     "generation_requires_explicit_request": True,
                                     "generation_apply": "explicit_review"}}

    def script_scene(self, project_id: str, scene_id: str, edit_revision: Optional[int] = None) -> dict[str, Any]:
        scene_id = _safe_id(scene_id, "场次 ID")
        with self.projects.lock:
            record = self._record(str(project_id), "script")
            episode, scene = self._script_scene(record["script"], scene_id)
            digest = scene.get("content_sha256") or ""
            body = self._read_blob(digest) if digest else ""
            selected = "current"
            selected_segments = copy.deepcopy(scene.get("segments") or [])
            if edit_revision is not None and int(scene.get("revision", 1)) != edit_revision:
                historical = next((item for item in scene.get("history") or [] if int(item.get("revision", 0)) == edit_revision), None)
                if historical is None:
                    raise StudioProjectNotFound("场次编辑修订不存在")
                digest = historical.get("content_sha256") or ""
                body = self._read_blob(digest) if digest else ""
                selected_segments = copy.deepcopy(historical.get("segments") or [])
                selected = "history"
            selected_scene = {**scene, "content_sha256": digest, "segments": selected_segments}
            return {"project_id": record["id"], "revision": self._revision(record), "episode": {"id": episode["id"], "title": episode["title"]},
                    "scene": {"id": scene["id"], "title": scene.get("title", ""), "revision": scene.get("revision", 1),
                              "content_sha256": digest, "body_markdown": body,
                              "editable_markdown": self._script_editable_text(selected_scene, body),
                              "selected_revision": selected,
                              "segments": [{**item, "body_markdown": body[item["start"]:item["end"]]}
                                           for item in selected_segments]}}

    def script_import_snapshot(self, project_id: str, source_revision: int, scope: Mapping[str, Any]) -> dict[str, Any]:
        """Return an immutable, hash-checked script selection with codepoint ranges."""
        if not isinstance(scope, Mapping):
            raise StudioProjectError("scope 必须是对象")
        unknown = set(scope) - {"type", "ids"}
        if unknown:
            raise StudioProjectError(f"scope 含未知字段：{', '.join(sorted(unknown))}")
        scope_type = str(scope.get("type") or "")
        if scope_type not in {"project", "episode", "scene", "segments"}:
            raise StudioProjectError("scope.type 必须是 project、episode、scene 或 segments")
        ids = scope.get("ids")
        if scope_type == "project":
            if "ids" in scope:
                raise StudioProjectError("project 范围不能提供 ids")
            requested: set[str] = set()
        else:
            if not isinstance(ids, list) or not ids:
                raise StudioProjectError(f"{scope_type} 范围必须提供非空 ids")
            requested = {_safe_id(value, "scope ID") for value in ids}
            if len(requested) != len(ids):
                raise StudioProjectError("scope.ids 不能重复")

        with self.projects.lock:
            record = self._record(str(project_id), "script")
            revision = self._revision(record)
            if isinstance(source_revision, bool) or not isinstance(source_revision, int) or source_revision != revision:
                raise StudioProjectConflict({"code": "SOURCE_REVISION_CONFLICT", "message": "源剧本已更新，请重新读取所选范围。",
                                              "current_revision": revision})
            script = record["script"]
            if script.get("state") != "structured" or not script.get("episodes"):
                raise StudioProjectConflict({"code": "SCRIPT_NOT_STRUCTURED", "message": "请先保存并划分剧本集、场和分段。"})

            episode_ids = {str(ep.get("id") or "") for ep in script.get("episodes") or []}
            scene_ids = {str(scene.get("id") or "") for ep in script.get("episodes") or [] for scene in ep.get("scenes") or []}
            segment_ids = {str(seg.get("id") or "") for ep in script.get("episodes") or []
                           for scene in ep.get("scenes") or [] for seg in scene.get("segments") or []}
            valid_ids = {"episode": episode_ids, "scene": scene_ids, "segments": segment_ids}
            if scope_type != "project" and not requested.issubset(valid_ids[scope_type]):
                raise StudioProjectNotFound("所选集、场或分段不存在于当前剧本")

            selected_episodes = []
            selected_segment_count = 0
            for episode in script.get("episodes") or []:
                episode_id = str(episode.get("id") or "")
                if scope_type == "episode" and episode_id not in requested:
                    continue
                scene_rows = []
                selected_segments = []
                episode_parts = []
                episode_offset = 0
                for scene in episode.get("scenes") or []:
                    scene_id = str(scene.get("id") or "")
                    digest = str(scene.get("content_sha256") or "")
                    body = self._read_blob(digest) if digest else ""
                    if len(body) != int(scene.get("char_count") or 0):
                        raise DataFileError("场次正文长度与已保存记录不匹配；原项目记录已保留。")
                    scene_offset = episode_offset + (2 if episode_parts else 0)
                    episode_parts.append(body)
                    include_all_scene_segments = scope_type in {"project", "episode"} or (
                        scope_type == "scene" and scene_id in requested)
                    selected_segment_ids = requested if scope_type == "segments" else None
                    scene_segments = []
                    if include_all_scene_segments and not (scene.get("segments") or []):
                        raise StudioProjectConflict({"code": "SCENE_NOT_SEGMENTED", "message": f"{scene.get('title') or '所选场次'}尚未划分分段。"})
                    for segment in scene.get("segments") or []:
                        if segment.get("source_sha256") != digest:
                            raise StudioProjectConflict("所选分段来源已变化，请先重新划分分段。")
                        start, end = segment.get("start"), segment.get("end")
                        if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int)
                            or not isinstance(end, int) or start < 0 or end < start or end > len(body)):
                            raise DataFileError("分段码点范围无效；原项目记录已保留。")
                        exact = body[start:end]
                        is_selected = include_all_scene_segments or (
                            selected_segment_ids is not None and str(segment.get("id") or "") in selected_segment_ids)
                        if start == end and is_selected:
                            raise StudioProjectConflict({"code": "EMPTY_SCRIPT_SEGMENT",
                                "message": "所选剧本分段正文为空；请先补充正文，再导入画布。"})
                        if not exact:
                            if is_selected:
                                raise StudioProjectConflict({"code": "EMPTY_SCRIPT_SEGMENT",
                                    "message": "所选剧本分段正文为空；请先补充正文，再导入画布。"})
                        item = {"id": segment["id"], "title": segment.get("title") or "未命名分段",
                                "order": int(segment.get("order") or 0), "body_markdown": exact,
                                "content_sha256": _digest(exact), "source_start": scene_offset + start,
                                "source_end": scene_offset + end, "scene_id": scene_id,
                                "scene_title": scene.get("title") or "未命名场次",
                                "scene_order": int(scene.get("order") or 0)}
                        if body[start:end] != item["body_markdown"]:
                            raise DataFileError("分段正文与来源范围校验失败；原项目记录已保留。")
                        scene_segments.append(item)
                        if include_all_scene_segments or (selected_segment_ids is not None and item["id"] in selected_segment_ids):
                            selected_segments.append(item)
                    scene_rows.append({"id": scene_id, "title": scene.get("title") or "未命名场次",
                                       "order": int(scene.get("order") or 0), "body_markdown": body,
                                       "content_sha256": digest, "segments": scene_segments})
                    episode_offset = scene_offset + len(body)

                episode_body = "\n\n".join(episode_parts)
                if scope_type == "scene":
                    if not any(row["id"] in requested for row in scene_rows):
                        continue
                    if not selected_segments:
                        raise StudioProjectConflict({"code": "NO_SAVED_SEGMENTS", "message": "所选场次没有已保存分段。"})
                if scope_type == "segments":
                    selected_segments = [item for item in selected_segments if item["id"] in requested]
                if scope_type == "episode" and episode_id in requested and not selected_segments:
                    raise StudioProjectConflict({"code": "NO_SAVED_SEGMENTS", "message": f"{episode.get('title') or '所选剧集'}没有已保存分段。"})
                if selected_segments:
                    for item in selected_segments:
                        if episode_body[item["source_start"]:item["source_end"]] != item["body_markdown"]:
                            raise DataFileError("剧集来源码点范围与分段正文不一致；原项目记录已保留。")
                    selected_segment_count += len(selected_segments)
                    selected_episodes.append({"id": episode_id, "title": episode.get("title") or "未命名剧集",
                        "order": int(episode.get("order") or 0), "body_markdown": episode_body,
                        "content_sha256": _digest(episode_body), "scenes": scene_rows,
                        "segments": selected_segments})
            if scope_type == "segments":
                actual = {item["id"] for episode in selected_episodes for item in episode["segments"]}
                if actual != requested:
                    raise StudioProjectNotFound("所选分段不存在或尚未关联到有效来源场次")
            if not selected_episodes or selected_segment_count == 0:
                raise StudioProjectConflict({"code": "NO_SAVED_SEGMENTS", "message": "当前范围没有可导入的已保存分段。"})
            return {"project_id": record["id"], "project_name": record.get("name") or "未命名剧本",
                    "project_revision": revision, "scope": {"type": scope_type,
                    "ids": sorted(requested) if requested else []}, "episodes": selected_episodes,
                    "segment_count": selected_segment_count}

    def script_view(self, project_id: str, scope: str, node_id: str = "", cursor: str = "", limit: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
        with self.projects.lock:
            record = self._record(str(project_id), "script")
            script = record["script"]
            revision = self._revision(record)
            if scope not in {"root", "episode", "scene", "segment"}:
                raise StudioProjectError("scope 必须为 root、episode、scene 或 segment")
            page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
            offset = _cursor_decode(cursor, revision) if cursor else 0
            if scope == "root" and script.get("state") == "draft":
                digest = script.get("draft_sha256") or ""
                metadata = ([{"scope": "root", "id": "root", "title": record.get("name", "完整剧本"),
                              "content_sha256": digest}])
                page_meta = metadata[offset:offset + page_size]
                blocks = [{**item, "body_markdown": self._read_blob(item["content_sha256"]) if item["content_sha256"] else ""}
                          for item in page_meta]
            else:
                scenes = self._all_script_scenes(script)
                if scope == "root":
                    selected = scenes
                elif scope == "episode":
                    episode = self._entry(script.get("episodes") or [], _safe_id(node_id, "集 ID"), "剧集")
                    selected = [(episode, item) for item in episode.get("scenes") or []]
                elif scope == "scene":
                    episode, scene = self._script_scene(script, _safe_id(node_id, "场次 ID"))
                    selected = [(episode, scene)]
                else:
                    episode, scene, segment = self._segment(script, _safe_id(node_id, "分段 ID"))
                    metadata = [{"scope": "segment", "id": segment["id"], "title": segment.get("title", ""),
                                 "path": [episode.get("title", ""), scene.get("title", ""), segment.get("title", "")],
                                 "source_sha256": scene.get("content_sha256"),
                                 "source_range": {"start": segment["start"], "end": segment["end"]},
                                 "scene_digest": scene.get("content_sha256") or ""}]
                    page_meta = metadata[offset:offset + page_size]
                    blocks = []
                    for item in page_meta:
                        body = self._read_blob(item.pop("scene_digest")) if item.get("scene_digest") else ""
                        start, end = item["source_range"]["start"], item["source_range"]["end"]
                        blocks.append({**item, "body_markdown": body[start:end]})
                    selected = None
                if selected is not None:
                    metadata = []
                    for episode, scene in selected:
                        digest = scene.get("content_sha256") or ""
                        metadata.append({"scope": "scene", "id": scene["id"], "title": scene.get("title", ""),
                            "episode": {"id": episode["id"], "title": episode.get("title", "")},
                            "content_sha256": digest,
                            "segments": [{"id": item["id"], "title": item.get("title", ""),
                                          "start": item["start"], "end": item["end"]}
                                         for item in scene.get("segments") or []]})
                    page_meta = metadata[offset:offset + page_size]
                    blocks = []
                    for item in page_meta:
                        body = self._read_blob(item["content_sha256"]) if item["content_sha256"] else ""
                        blocks.append({**item, "body_markdown": body,
                            "editable_markdown": self._script_editable_text(
                                {**self._script_scene(script, item["id"])[1], "content_sha256": item["content_sha256"]}, body),
                            "segments": [{**segment, "body_markdown": body[segment["start"]:segment["end"]]}
                                         for segment in item["segments"]]})
                total = len(metadata) if scope != "segment" else 1
                page = blocks
            if scope == "root" and script.get("state") == "draft":
                total = 1
                page = blocks
            elif scope == "segment":
                total = 1
                page = blocks
            next_offset = offset + len(page)
            return {"project_id": record["id"], "revision": revision, "scope": scope,
                    "blocks": page, "has_more": next_offset < total,
                    "next_cursor": _cursor_encode(revision, next_offset) if next_offset < total else None}

    @staticmethod
    def _novel_entries(novel: dict[str, Any]) -> list[dict[str, Any]]:
        settings = novel.setdefault("settings", {"schema_version": 1, "categories": [], "entries": []})
        if not isinstance(settings.get("categories", []), list) or not isinstance(settings.get("entries", []), list):
            raise DataFileError("小说设定目录损坏；原项目记录已保留。")
        return settings["entries"]

    def _chapter(self, novel: dict[str, Any], chapter_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        for volume in novel.get("volumes") or []:
            for chapter in volume.get("chapters") or []:
                if chapter.get("id") == chapter_id:
                    return volume, chapter
        raise StudioProjectNotFound("章节不存在")

    def _entry_version(self, entry: dict[str, Any], version_id: str) -> dict[str, Any]:
        return self._entry(entry.get("versions") or [], version_id, "设定故事版本")

    def _validate_story_anchor(self, novel: dict[str, Any], value: Any, use_state: str) -> dict[str, Any]:
        if use_state not in {"draft", "confirmed"}:
            raise StudioProjectError("use_state 必须为 draft 或 confirmed")
        if value is None:
            return {"kind": "unspecified"}
        if not isinstance(value, Mapping):
            raise StudioProjectError("story_anchor 必须是对象")
        kind = str(value.get("kind") or "")
        if kind in {"baseline", "unspecified"}:
            _need_keys(value, {"kind"})
            return {"kind": kind}
        if kind == "chapter_boundary":
            _need_keys(value, {"kind", "chapter_id", "side"}, {"chapter_id", "side"})
            chapter_id = _safe_id(value["chapter_id"], "锚点章节 ID")
            self._chapter(novel, chapter_id)
            if value["side"] not in {"before", "after"}:
                raise StudioProjectError("chapter_boundary.side 必须为 before 或 after")
            return {"kind": kind, "chapter_id": chapter_id, "side": value["side"]}
        if kind == "event":
            _need_keys(value, {"kind", "event_entry_id", "event_version_id", "side", "chapter_id"},
                       {"event_entry_id", "event_version_id", "side"})
            event_id = _safe_id(value["event_entry_id"], "事件条目 ID")
            version_id = _safe_id(value["event_version_id"], "事件版本 ID")
            event = self._entry(self._novel_entries(novel), event_id, "事件条目")
            if event.get("category_id") != "timeline":
                raise StudioProjectConflict("事件锚点必须引用本项目时间线分类的条目")
            event_version = self._entry_version(event, version_id)
            if value["side"] not in {"before", "after"}:
                raise StudioProjectError("event.side 必须为 before 或 after")
            result = {"kind": kind, "event_entry_id": event_id, "event_version_id": version_id,
                      "event_content_sha256": event_version.get("content_sha256"), "side": value["side"]}
            if value.get("chapter_id"):
                chapter_id = _safe_id(value["chapter_id"], "锚点章节 ID")
                self._chapter(novel, chapter_id)
                result["chapter_id"] = chapter_id
            return result
        raise StudioProjectError("story_anchor.kind 必须为 baseline、chapter_boundary、event 或 unspecified")

    def _story_anchor_context(self, novel: dict[str, Any], anchor: Mapping[str, Any]) -> Optional[dict[str, Any]]:
        """Capture outline identity around an anchor only to flag stale references."""
        chapter_id = str(anchor.get("chapter_id") or "") if anchor.get("kind") in {"chapter_boundary", "event"} else ""
        if not chapter_id:
            return None
        volume, chapter = self._chapter(novel, chapter_id)
        chapters = volume.get("chapters") or []
        index = next(i for i, item in enumerate(chapters) if item.get("id") == chapter_id)
        return {"kind": "chapter_location", "chapter_id": chapter_id,
                "volume_id": volume.get("id"), "volume_order": int(volume.get("order") or 0),
                "chapter_order": int(chapter.get("order") or 0),
                "previous_chapter_id": chapters[index - 1].get("id") if index else None,
                "next_chapter_id": chapters[index + 1].get("id") if index + 1 < len(chapters) else None}

    def _validate_basis_refs(self, novel: dict[str, Any], values: Any) -> list[dict[str, str]]:
        if values is None:
            return []
        if not isinstance(values, list) or len(values) > 100:
            raise StudioProjectError("basis_refs 必须是有限数组")
        result = []
        seen = set()
        for item in values:
            if not isinstance(item, Mapping):
                raise StudioProjectError("basis_refs 项必须是对象")
            kind = item.get("kind")
            if kind == "chapter":
                _need_keys(item, {"kind", "chapter_id", "content_sha256"}, {"kind", "chapter_id", "content_sha256"})
                chapter_id = _safe_id(item["chapter_id"], "依赖章节 ID")
                _, chapter = self._chapter(novel, chapter_id)
                key = (kind, chapter_id, "")
                digest = chapter.get("content_sha256") or ""
                normalized = {"kind": "chapter", "chapter_id": chapter_id, "content_sha256": str(item["content_sha256"])}
            elif kind == "setting":
                _need_keys(item, {"kind", "entry_id", "version_id", "content_sha256"},
                           {"kind", "entry_id", "version_id", "content_sha256"})
                entry_id = _safe_id(item["entry_id"], "依赖设定 ID")
                version_id = _safe_id(item["version_id"], "依赖版本 ID")
                entry = self._entry(self._novel_entries(novel), entry_id, "依赖设定")
                version = self._entry_version(entry, version_id)
                key = (kind, entry_id, version_id)
                digest = version.get("content_sha256") or ""
                normalized = {"kind": "setting", "entry_id": entry_id, "version_id": version_id,
                              "content_sha256": str(item["content_sha256"])}
            else:
                raise StudioProjectError("basis_refs.kind 必须为 chapter 或 setting")
            if key in seen:
                raise StudioProjectError("basis_refs 不能重复引用同一来源")
            seen.add(key)
            if item["content_sha256"] != digest:
                raise StudioProjectConflict("依赖版本指纹已变化，请重新读取后确认")
            result.append(normalized)
        return result

    def _expected_has(self, values: Any, wanted: Mapping[str, Any]) -> bool:
        if not isinstance(values, list):
            return False
        for item in values:
            if isinstance(item, Mapping) and all(item.get(key) == value for key, value in wanted.items()):
                return True
        return False

    def _validate_expected_sources(self, novel: dict[str, Any], values: Any) -> list[dict[str, str]]:
        if values is None:
            return []
        if not isinstance(values, list) or len(values) > 100:
            raise StudioProjectError("expected_sources 必须是有限数组")
        result: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for raw in values:
            if not isinstance(raw, Mapping):
                raise StudioProjectError("expected_sources 项必须是对象")
            _need_keys(raw, {"entry_id", "version_id", "content_sha256"},
                       {"entry_id", "version_id", "content_sha256"})
            entry_id = _safe_id(raw["entry_id"], "expected_sources 设定 ID")
            version_id = _safe_id(raw["version_id"], "expected_sources 版本 ID")
            entry = self._entry(self._novel_entries(novel), entry_id, "expected_sources 设定")
            version = self._entry_version(entry, version_id)
            key = (entry_id, version_id)
            if key in seen:
                raise StudioProjectError("expected_sources 不能重复")
            seen.add(key)
            digest = str(version.get("content_sha256") or "")
            if raw["content_sha256"] != digest:
                raise StudioProjectConflict("expected_sources 基线指纹已变化，请重新读取后确认")
            result.append({"entry_id": entry_id, "version_id": version_id, "content_sha256": digest})
        return result

    def _novel_action(self, novel: dict[str, Any], action: str, args: Mapping[str, Any],
                      aliases: dict[str, str], staged: dict[str, bytes],
                      expected_sources: Any = None) -> tuple[list[str], dict[str, str]]:
        changed: list[str] = []
        created: dict[str, str] = {}
        if action == "set_chapter_outline":
            _need_keys(args, {"chapter_id", "body_markdown"}, {"chapter_id", "body_markdown"})
            chapter_id = self._resolve(args["chapter_id"], aliases, "章节 ID")
            _, chapter = self._chapter(novel, chapter_id)
            self._set_outline(chapter, args["body_markdown"], staged)
            changed.append(chapter_id)
        elif action == "import_markdown":
            _need_keys(args, {"body_markdown", "replace"}, {"body_markdown", "replace"})
            changed.extend(self._import_novel_markdown(novel, _body(args["body_markdown"]), args["replace"], staged))
        elif action == "create_volume":
            _need_keys(args, {"title", "after_volume_id", "client_ref"}, {"title"})
            volumes = novel.setdefault("volumes", [])
            if len(volumes) >= MAX_ITEMS:
                raise StudioProjectError("卷数已达上限")
            volume_id = _new_id("volume")
            volume = {"id": volume_id, "title": _clean_title(args["title"], "未命名卷"), "order": len(volumes) + 1, "chapters": []}
            if args.get("after_volume_id"):
                after = self._resolve(args["after_volume_id"], aliases, "卷 ID")
                pos = next((i + 1 for i, item in enumerate(volumes) if item.get("id") == after), None)
                if pos is None:
                    raise StudioProjectNotFound("插入位置对应的卷不存在")
                volumes.insert(pos, volume)
            else:
                volumes.append(volume)
            self._renumber(volumes)
            if args.get("client_ref"):
                ref = str(args["client_ref"])
                if not ID_PATTERN.fullmatch(ref) or ref in aliases:
                    raise StudioProjectError("client_ref 无效或重复")
                aliases[ref] = volume_id
                created[ref] = volume_id
            changed.append(volume_id)
        elif action == "create_chapter":
            _need_keys(args, {"volume_id", "title", "body_markdown", "after_chapter_id", "client_ref", "basis_refs"},
                       {"volume_id", "title", "body_markdown"})
            volume_id = self._resolve(args["volume_id"], aliases, "卷 ID")
            volume = self._entry(novel.setdefault("volumes", []), volume_id, "卷")
            chapters = volume.setdefault("chapters", [])
            if len(chapters) >= MAX_ITEMS:
                raise StudioProjectError("章节数量已达上限")
            body = _body(args["body_markdown"])
            digest = self._stage_blob(body, staged) if body else ""
            chapter_id = _new_id("chapter")
            chapter = {"id": chapter_id, "title": _clean_title(args["title"], "未命名章节"), "order": len(chapters) + 1,
                       "content_sha256": digest, "char_count": len(body), "revision": 1, "history": [],
                       "outline_revision": 0, "outline_sha256": "", "outline_char_count": 0, "outline_history": [],
                       "basis_refs": self._validate_basis_refs(novel, args.get("basis_refs", []))}
            if args.get("after_chapter_id"):
                after = self._resolve(args["after_chapter_id"], aliases, "章节 ID")
                pos = next((i + 1 for i, item in enumerate(chapters) if item.get("id") == after), None)
                if pos is None:
                    raise StudioProjectNotFound("插入位置对应的章节不存在")
                chapters.insert(pos, chapter)
            else:
                chapters.append(chapter)
            self._renumber(chapters)
            if args.get("client_ref"):
                ref = str(args["client_ref"])
                if not ID_PATTERN.fullmatch(ref) or ref in aliases:
                    raise StudioProjectError("client_ref 无效或重复")
                aliases[ref] = chapter_id
                created[ref] = chapter_id
            changed.extend([volume_id, chapter_id])
        elif action == "update_chapter":
            _need_keys(args, {"chapter_id", "body_markdown", "basis_refs"}, {"chapter_id", "body_markdown"})
            chapter_id = self._resolve(args["chapter_id"], aliases, "章节 ID")
            _, chapter = self._chapter(novel, chapter_id)
            body = _body(args["body_markdown"])
            old = chapter.get("content_sha256") or ""
            chapter.setdefault("history", []).append({"revision": chapter.get("revision", 1), "content_sha256": old,
                                                       "char_count": chapter.get("char_count", 0), "created_at": _now_ms()})
            digest = self._stage_blob(body, staged) if body else ""
            chapter.update({"content_sha256": digest, "char_count": len(body), "revision": int(chapter.get("revision", 1)) + 1})
            if "basis_refs" in args:
                chapter["basis_refs"] = self._validate_basis_refs(novel, args["basis_refs"])
            changed.append(chapter_id)
        elif action in {"rename_item", "reorder_items", "delete_item", "restore_item"}:
            changed, created = self._novel_outline_action(novel, action, args, aliases)
        elif action == "create_setting_entry":
            _need_keys(args, {"client_ref", "category_id", "body_markdown", "story_anchor", "use_state"},
                       {"body_markdown", "use_state"})
            entries = self._novel_entries(novel)
            if len(entries) >= MAX_ITEMS:
                raise StudioProjectError("设定条目数量已达上限")
            body = _body(args["body_markdown"])
            digest = self._stage_blob(body, staged)
            entry_id, version_id = _new_id("setting"), _new_id("settingv")
            category_id = args.get("category_id")
            if category_id is not None:
                category_id = self._resolve(category_id, aliases, "分类 ID")
                self._require_category(novel, category_id)
            use_state = str(args["use_state"])
            anchor = self._validate_story_anchor(novel, args.get("story_anchor"), use_state)
            version = {"id": version_id, "story_version": 1, "use_state": use_state, "story_anchor": anchor,
                       "story_anchor_context": self._story_anchor_context(novel, anchor),
                       "number": 1, "based_on_version_id": None, "based_on_content_sha256": None,
                       "content_sha256": digest, "edit_revision": 1, "edit_history": [], "basis_refs": [],
                       "state_history": [], "anchor_history": [], "created_at": _now_ms()}
            entry = {"id": entry_id, "category_id": category_id, "title": _markdown_title(body),
                     "current_version_id": version_id, "versions": [version], "created_at": _now_ms(), "updated_at": _now_ms()}
            entries.append(entry)
            client_ref = str(args.get("client_ref") or "").strip()
            if client_ref:
                if not ID_PATTERN.fullmatch(client_ref) or client_ref in aliases:
                    raise StudioProjectError("client_ref 无效或重复")
                aliases[client_ref] = entry_id
                created[client_ref] = entry_id
            changed.extend([entry_id, version_id])
        elif action == "add_setting_version":
            _need_keys(args, {"entry_id", "body_markdown", "story_anchor", "use_state", "based_on_version_id", "client_ref"},
                       {"entry_id", "body_markdown", "use_state", "based_on_version_id"})
            entries = self._novel_entries(novel)
            entry_id = self._resolve(args["entry_id"], aliases, "设定条目 ID")
            entry = self._entry(entries, entry_id, "设定条目")
            if len(entry.get("versions") or []) >= MAX_ITEMS:
                raise StudioProjectError("故事版本数量已达上限")
            body = _body(args["body_markdown"])
            digest = self._stage_blob(body, staged)
            next_number = max([int(item.get("story_version", 0)) for item in entry.get("versions") or []] + [0]) + 1
            use_state = str(args["use_state"])
            anchor = self._validate_story_anchor(novel, args.get("story_anchor"), use_state)
            based_on = self._resolve(args["based_on_version_id"], aliases, "基线故事版本 ID")
            base_version = self._entry_version(entry, based_on)
            source = {"entry_id": entry_id, "version_id": based_on,
                      "content_sha256": base_version.get("content_sha256") or ""}
            if not self._expected_has(expected_sources, source):
                raise StudioProjectConflict("新增故事版本必须携带读取基线时的 expected_sources 指纹")
            version_id = _new_id("settingv")
            entry.setdefault("versions", []).append({"id": version_id, "story_version": next_number,
                "number": next_number, "use_state": use_state, "story_anchor": anchor,
                "story_anchor_context": self._story_anchor_context(novel, anchor),
                "content_sha256": digest, "edit_revision": 1,
                "edit_history": [], "basis_refs": [], "state_history": [], "anchor_history": [],
                "based_on_version_id": based_on, "based_on_content_sha256": base_version.get("content_sha256"),
                "created_at": _now_ms()})
            client_ref = str(args.get("client_ref") or "").strip()
            if client_ref:
                if not ID_PATTERN.fullmatch(client_ref) or client_ref in aliases:
                    raise StudioProjectError("client_ref 无效或重复")
                aliases[client_ref] = version_id
                created[client_ref] = version_id
            entry["current_version_id"] = version_id
            entry["updated_at"] = _now_ms()
            changed.extend([entry_id, version_id])
        elif action == "revise_setting_version":
            _need_keys(args, {"entry_id", "version_id", "body_markdown"}, {"entry_id", "version_id", "body_markdown"})
            entry = self._entry(self._novel_entries(novel), self._resolve(args["entry_id"], aliases, "设定条目 ID"), "设定条目")
            version = self._entry_version(entry, self._resolve(args["version_id"], aliases, "故事版本 ID"))
            body = _body(args["body_markdown"])
            old = version.get("content_sha256") or ""
            version.setdefault("edit_history", []).append({"revision": version.get("edit_revision", 1),
                                                            "content_sha256": old, "created_at": _now_ms()})
            digest = self._stage_blob(body, staged)
            version.update({"content_sha256": digest, "edit_revision": int(version.get("edit_revision", 1)) + 1,
                            "updated_at": _now_ms()})
            entry["title"] = _markdown_title(body)
            entry["updated_at"] = _now_ms()
            changed.extend([entry["id"], version["id"]])
        elif action == "set_setting_version_state":
            _need_keys(args, {"entry_id", "version_id", "use_state"}, {"entry_id", "version_id", "use_state"})
            entry = self._entry(self._novel_entries(novel), self._resolve(args["entry_id"], aliases, "设定条目 ID"), "设定条目")
            version = self._entry_version(entry, self._resolve(args["version_id"], aliases, "故事版本 ID"))
            use_state = str(args["use_state"])
            if use_state not in {"draft", "confirmed"}:
                raise StudioProjectError("use_state 必须为 draft 或 confirmed")
            version.setdefault("state_history", []).append({"use_state": version.get("use_state"), "created_at": _now_ms()})
            version["use_state"] = use_state
            entry["updated_at"] = _now_ms()
            changed.extend([entry["id"], version["id"]])
        elif action == "set_setting_version_anchor":
            _need_keys(args, {"entry_id", "version_id", "story_anchor"}, {"entry_id", "version_id", "story_anchor"})
            entry = self._entry(self._novel_entries(novel), self._resolve(args["entry_id"], aliases, "设定条目 ID"), "设定条目")
            version = self._entry_version(entry, self._resolve(args["version_id"], aliases, "故事版本 ID"))
            version.setdefault("anchor_history", []).append({"story_anchor": copy.deepcopy(version.get("story_anchor")), "created_at": _now_ms()})
            version["story_anchor"] = self._validate_story_anchor(novel, args["story_anchor"], version.get("use_state", "draft"))
            version["story_anchor_context"] = self._story_anchor_context(novel, version["story_anchor"])
            version["anchor_revision"] = int(version.get("anchor_revision", 1)) + 1
            entry["updated_at"] = _now_ms()
            changed.extend([entry["id"], version["id"]])
        elif action == "restore_setting_revision":
            _need_keys(args, {"entry_id", "version_id", "revision"}, {"entry_id", "version_id", "revision"})
            entry = self._entry(self._novel_entries(novel), self._resolve(args["entry_id"], aliases, "设定条目 ID"), "设定条目")
            version = self._entry_version(entry, self._resolve(args["version_id"], aliases, "故事版本 ID"))
            revision = args["revision"]
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise StudioProjectError("revision 必须是正整数")
            old = next((item for item in version.get("edit_history") or [] if item.get("revision") == revision), None)
            if old is None:
                raise StudioProjectNotFound("设定修订不存在")
            version.setdefault("edit_history", []).append({"revision": version.get("edit_revision", 1),
                                                            "content_sha256": version.get("content_sha256"), "created_at": _now_ms()})
            version["content_sha256"] = old["content_sha256"]
            version["edit_revision"] = int(version.get("edit_revision", 1)) + 1
            version["restored_from_revision"] = revision
            entry["title"] = _markdown_title(self._read_blob(version["content_sha256"]))
            entry["updated_at"] = _now_ms()
            changed.extend([entry["id"], version["id"]])
        elif action == "set_context_pins":
            _need_keys(args, {"refs"}, {"refs"})
            values = args["refs"]
            if not isinstance(values, list) or len(values) > 1000:
                raise StudioProjectError("refs 必须是有限数组")
            entries = self._novel_entries(novel)
            pins = []
            seen = set()
            for ref in values:
                if not isinstance(ref, Mapping):
                    raise StudioProjectError("context pin 必须是对象")
                _need_keys(ref, {"entry_id", "version_id"}, {"entry_id"})
                entry_id = self._resolve(ref["entry_id"], aliases, "设定条目 ID")
                entry = self._entry(entries, entry_id, "设定条目")
                version_id = self._resolve(ref["version_id"], aliases, "故事版本 ID") if ref.get("version_id") else None
                if version_id:
                    self._entry_version(entry, version_id)
                key = (entry_id, version_id)
                if key in seen:
                    raise StudioProjectError("context pins 不能重复")
                seen.add(key)
                pins.append({"entry_id": entry_id, "version_id": version_id})
            novel["context_pins"] = pins
            changed.extend([pin["entry_id"] for pin in pins])
        elif action in {"create_setting_category", "rename_setting_category", "archive_setting_category",
                        "move_setting_entry", "archive_setting_entry", "restore_setting_entry"}:
            changed, created = self._novel_settings_action(novel, action, args, aliases)
        elif action == "update_handoff_record":
            changed, created = self._novel_handoff_action(novel, action, args, aliases, staged)
        else:
            raise StudioProjectError(f"小说动作不受支持：{action}")
        return changed, created

    @staticmethod
    def _require_category(novel: dict[str, Any], category_id: str) -> dict[str, Any]:
        fixed = {item["id"]: item for item in DEFAULT_SETTING_CATEGORIES}
        custom = {str(item.get("id")): item for item in novel.setdefault("settings", {}).get("categories", []) if isinstance(item, dict)}
        if category_id not in fixed and category_id not in custom:
            raise StudioProjectNotFound("设定分类不存在")
        return fixed.get(category_id) or custom[category_id]

    def _novel_outline_action(self, novel: dict[str, Any], action: str, args: Mapping[str, Any],
                              aliases: dict[str, str]) -> tuple[list[str], dict[str, str]]:
        changed: list[str] = []
        created: dict[str, str] = {}
        volumes = novel.setdefault("volumes", [])
        if action == "rename_item":
            _need_keys(args, {"item_type", "item_id", "title"}, {"item_type", "item_id", "title"})
            kind = str(args["item_type"])
            item_id = self._resolve(args["item_id"], aliases, "条目 ID")
            if kind == "volume":
                item = self._entry(volumes, item_id, "卷")
            elif kind == "chapter":
                _, item = self._chapter(novel, item_id)
            else:
                raise StudioProjectError("item_type 必须为 volume 或 chapter")
            item["title"] = _clean_title(args["title"])
            item["updated_at"] = _now_ms()
            changed.append(item_id)
        elif action == "reorder_items":
            _need_keys(args, {"parent_type", "parent_id", "ordered_ids"}, {"parent_type", "ordered_ids"})
            if args["parent_type"] == "root":
                if args.get("parent_id"):
                    raise StudioProjectError("root 重排不能提供 parent_id")
                collection = volumes
            elif args["parent_type"] == "volume":
                parent_id = self._resolve(args.get("parent_id"), aliases, "卷 ID")
                parent = self._entry(volumes, parent_id, "卷")
                collection = parent.setdefault("chapters", [])
            else:
                raise StudioProjectError("parent_type 必须为 root 或 volume")
            raw_ids = args["ordered_ids"]
            ids = [self._resolve(item, aliases, "条目 ID") for item in raw_ids] if isinstance(raw_ids, list) else []
            existing = [item.get("id") for item in collection]
            if len(ids) != len(existing) or len(set(ids)) != len(ids) or set(ids) != set(existing):
                raise StudioProjectConflict("重排必须恰好包含全部同级条目，不可重复或跨级")
            by_id = {item["id"]: item for item in collection}
            collection[:] = [by_id[item_id] for item_id in ids]
            self._renumber(collection)
            changed.extend(ids)
        elif action == "delete_item":
            _need_keys(args, {"item_type", "item_id", "include_descendants"}, {"item_type", "item_id"})
            kind, item_id = str(args["item_type"]), self._resolve(args["item_id"], aliases, "条目 ID")
            include = args.get("include_descendants", False)
            if not isinstance(include, bool):
                raise StudioProjectError("include_descendants 必须是布尔值")
            if kind == "volume":
                collection = volumes
                item = self._entry(collection, item_id, "卷")
                if item.get("chapters") and not include:
                    raise StudioProjectConflict("该卷包含章节，需明确 include_descendants:true")
                parent_id = None
            elif kind == "chapter":
                parent, item = self._chapter(novel, item_id)
                collection = parent["chapters"]
                parent_id = parent["id"]
            else:
                raise StudioProjectError("item_type 必须为 volume 或 chapter")
            collection.remove(item)
            novel.setdefault("archive", []).append({"kind": kind, "item": item, "parent_id": parent_id,
                                                      "created_at": _now_ms()})
            self._renumber(collection)
            changed.append(item_id)
        elif action == "restore_item":
            _need_keys(args, {"item_id"}, {"item_id"})
            item_id = self._resolve(args["item_id"], aliases, "条目 ID")
            archive = next((item for item in reversed(novel.get("archive") or [])
                            if isinstance(item, dict) and (item.get("item") or {}).get("id") == item_id
                            and not item.get("restored_at")), None)
            if archive is None:
                raise StudioProjectNotFound("没有可恢复的小说目录条目")
            if archive["kind"] == "volume":
                collection = volumes
            elif archive["kind"] == "chapter":
                parent = self._entry(volumes, archive.get("parent_id"), "原所属卷")
                collection = parent.setdefault("chapters", [])
            else:
                raise DataFileError("归档目录类型无效")
            if any(item.get("id") == item_id for item in collection):
                raise StudioProjectConflict("该 ID 已存在，不能覆盖")
            collection.append(archive["item"])
            archive["restored_at"] = _now_ms()
            self._renumber(collection)
            changed.append(item_id)
        return changed, created

    def _novel_settings_action(self, novel: dict[str, Any], action: str, args: Mapping[str, Any],
                               aliases: dict[str, str]) -> tuple[list[str], dict[str, str]]:
        changed: list[str] = []
        created: dict[str, str] = {}
        settings = novel.setdefault("settings", {"schema_version": 1, "categories": [], "entries": []})
        categories = settings.setdefault("categories", [])
        entries = self._novel_entries(novel)
        fixed_ids = {item["id"] for item in DEFAULT_SETTING_CATEGORIES}
        if action == "create_setting_category":
            _need_keys(args, {"client_ref", "name", "after_category_id"}, {"name"})
            if len(categories) >= 100:
                raise StudioProjectError("自定义分类数量已达上限")
            category_id = _new_id("category")
            item = {"id": category_id, "name": _clean_title(args["name"], "未命名分类"), "created_at": _now_ms()}
            if args.get("after_category_id"):
                after = self._resolve(args["after_category_id"], aliases, "分类 ID")
                pos = next((i + 1 for i, entry in enumerate(categories) if entry.get("id") == after), None)
                if pos is None:
                    raise StudioProjectNotFound("插入位置对应的分类不存在")
                categories.insert(pos, item)
            else:
                categories.append(item)
            if args.get("client_ref"):
                ref = str(args["client_ref"])
                if not ID_PATTERN.fullmatch(ref) or ref in aliases:
                    raise StudioProjectError("client_ref 无效或重复")
                aliases[ref] = category_id
                created[ref] = category_id
            changed.append(category_id)
        elif action == "rename_setting_category":
            _need_keys(args, {"category_id", "name"}, {"category_id", "name"})
            category_id = self._resolve(args["category_id"], aliases, "分类 ID")
            if category_id in fixed_ids:
                raise StudioProjectConflict("七个默认分类的名称由工作台本地化目录提供")
            item = self._entry(categories, category_id, "分类")
            item["name"] = _clean_title(args["name"])
            changed.append(category_id)
        elif action == "archive_setting_category":
            _need_keys(args, {"category_id", "move_entries_to"}, {"category_id"})
            category_id = self._resolve(args["category_id"], aliases, "分类 ID")
            if category_id in fixed_ids:
                raise StudioProjectConflict("默认分类不能删除")
            category = self._entry(categories, category_id, "分类")
            affected = [entry for entry in entries if entry.get("category_id") == category_id]
            target = args.get("move_entries_to")
            if affected and "move_entries_to" not in args:
                raise StudioProjectConflict("分类仍有条目；请明确移入其他分类或归入未分类")
            if target is not None:
                target_id = self._resolve(target, aliases, "目标分类 ID")
                self._require_category(novel, target_id)
                if target_id == category_id:
                    raise StudioProjectError("目标分类必须不同于待删除分类")
                for entry in affected:
                    entry["category_id"] = target_id
            else:
                for entry in affected:
                    entry["category_id"] = None
            categories.remove(category)
            novel.setdefault("archive", []).append({"kind": "setting_category", "item": category,
                                                      "moved_entry_ids": [entry["id"] for entry in affected],
                                                      "created_at": _now_ms()})
            changed.append(category_id)
            changed.extend(entry["id"] for entry in affected)
        elif action == "move_setting_entry":
            _need_keys(args, {"entry_id", "category_id"}, {"entry_id", "category_id"})
            entry_id = self._resolve(args["entry_id"], aliases, "设定條目 ID")
            category_id = self._resolve(args["category_id"], aliases, "分类 ID") if args.get("category_id") else None
            if category_id is not None:
                self._require_category(novel, category_id)
            entry = self._entry(entries, entry_id, "设定条目")
            entry["category_id"] = category_id
            entry["updated_at"] = _now_ms()
            changed.extend([entry_id, category_id])
        elif action == "archive_setting_entry":
            _need_keys(args, {"entry_id"}, {"entry_id"})
            entry_id = self._resolve(args["entry_id"], aliases, "设定条目 ID")
            entry = self._entry(entries, entry_id, "设定条目")
            entries.remove(entry)
            novel.setdefault("archive", []).append({"kind": "setting", "item": entry, "created_at": _now_ms()})
            changed.append(entry_id)
        else:  # restore_setting_entry
            _need_keys(args, {"entry_id"}, {"entry_id"})
            entry_id = self._resolve(args["entry_id"], aliases, "设定条目 ID")
            archive = next((item for item in reversed(novel.get("archive") or [])
                            if isinstance(item, dict) and item.get("kind") == "setting"
                            and (item.get("item") or {}).get("id") == entry_id and not item.get("restored_at")), None)
            if archive is None:
                raise StudioProjectNotFound("没有可恢复的设定条目")
            if any(item.get("id") == entry_id for item in entries):
                raise StudioProjectConflict("该设定 ID 已存在，不能覆盖")
            category_id = archive["item"].get("category_id")
            if category_id is not None:
                self._require_category(novel, category_id)
            entries.append(archive["item"])
            archive["restored_at"] = _now_ms()
            changed.append(entry_id)
        return changed, created

    def _novel_handoff_action(self, novel: dict[str, Any], action: str, args: Mapping[str, Any],
                              aliases: dict[str, str], staged: dict[str, bytes]) -> tuple[list[str], dict[str, str]]:
        handoff = novel.get("handoff")
        if not isinstance(handoff, dict):
            handoff = {"records": []}
            novel["handoff"] = handoff
        records = handoff.setdefault("records", [])
        changed: list[str] = []
        created: dict[str, str] = {}
        if action != "update_handoff_record":
            raise StudioProjectError("小说动作不受支持：" + action)
        _need_keys(args, {"body_markdown", "source_refs"}, {"body_markdown"})
        refs = self._validate_basis_refs(novel, args.get("source_refs", []))
        body = _body(args["body_markdown"])
        digest = self._stage_blob(body, staged)
        if records:
            item = records[-1]
            item.setdefault("history", []).append({"revision": item.get("revision", 1),
                                                    "body_sha256": item.get("body_sha256"),
                                                    "source_refs": copy.deepcopy(item.get("source_refs") or []),
                                                    "created_at": _now_ms()})
            item.update({"body_sha256": digest, "char_count": len(body), "source_refs": refs,
                         "revision": int(item.get("revision", 1)) + 1, "updated_at": _now_ms()})
        else:
            item = {"id": _new_id("handoff"), "title": _markdown_title(body, "创作接续记录"),
                    "body_sha256": digest, "char_count": len(body), "source_refs": refs,
                    "created_at": _now_ms(), "revision": 1, "history": []}
            records.append(item)
        item["title"] = _markdown_title(body, item.get("title") or "创作接续记录")
        handoff["current_id"] = item["id"]
        changed.append(item["id"])
        return changed, created

    def _source_needs_review(self, novel: dict[str, Any], refs: Any) -> bool:
        try:
            self._validate_basis_refs(novel, refs or [])
            return False
        except (StudioProjectError, DataFileError):
            return True

    def _version_needs_review(self, novel: dict[str, Any], entry: Mapping[str, Any], version: Mapping[str, Any]) -> bool:
        if self._source_needs_review(novel, version.get("basis_refs")):
            return True
        based_on_id = version.get("based_on_version_id")
        if based_on_id:
            try:
                base = self._entry_version(dict(entry), str(based_on_id))
                if base.get("content_sha256") != version.get("based_on_content_sha256"):
                    return True
            except StudioProjectError:
                return True
        anchor = version.get("story_anchor") or {}
        try:
            if anchor.get("kind") == "chapter_boundary":
                self._chapter(novel, str(anchor.get("chapter_id") or ""))
            elif anchor.get("kind") == "event":
                event = self._entry(self._novel_entries(novel), str(anchor.get("event_entry_id") or ""), "事件条目")
                event_version = self._entry_version(event, str(anchor.get("event_version_id") or ""))
                if (event.get("category_id") != "timeline"
                        or event_version.get("id") != anchor.get("event_version_id")
                        or event_version.get("content_sha256") != anchor.get("event_content_sha256")):
                    return True
            saved_context = version.get("story_anchor_context")
            if isinstance(saved_context, Mapping):
                if self._story_anchor_context(novel, anchor) != dict(saved_context):
                    return True
            return False
        except StudioProjectError:
            return True

    def novel_summary(self, project_id: str) -> dict[str, Any]:
        with self.projects.lock:
            record = self._record(str(project_id), "novel")
            novel = record["novel"]
            volumes = []
            chapter_count = char_count = 0
            for volume in novel.get("volumes") or []:
                chapters = []
                for chapter in volume.get("chapters") or []:
                    chapter_count += 1
                    char_count += int(chapter.get("char_count") or 0)
                    outline_revision, outline_digest, outline_count, _ = self._outline_state(chapter)
                    chapters.append({"id": chapter["id"], "title": chapter.get("title", "未命名章节"),
                                     "order": chapter.get("order", 0), "revision": chapter.get("revision", 1),
                                     "char_count": int(chapter.get("char_count") or 0),
                                     "outline_revision": outline_revision, "outline_sha256": outline_digest,
                                     "outline_char_count": outline_count,
                                     "needs_review": self._source_needs_review(novel, chapter.get("basis_refs"))})
                volumes.append({"id": volume["id"], "title": volume.get("title", "未命名卷"),
                                "order": volume.get("order", 0), "chapters": chapters})
            categories = [copy.deepcopy(item) for item in DEFAULT_SETTING_CATEGORIES]
            categories.extend({"id": item["id"], "title": item.get("name", "未命名分类"), "custom": True}
                              for item in novel.get("settings", {}).get("categories", []) if isinstance(item, dict))
            entries = self._novel_entries(novel)
            if any(item.get("category_id") is None for item in entries):
                categories.append({"id": None, "title": {"zh": "未分类", "en": "Uncategorized"}})
            setting_summaries = [self._setting_summary(novel, item) for item in entries]
            handoff = novel.get("handoff") or {}
            handoff_records = handoff.get("records") or []
            return {"project": StudioProjectStore._manuscript_public(record), "revision": self._revision(record),
                    "schema_version": int(novel.get("schema_version") or 1), "directory": {"volumes": volumes},
                    "settings": {"categories": categories, "entries": setting_summaries,
                                 "context_pins": copy.deepcopy(novel.get("context_pins") or [])},
                    "handoff": {"current_id": handoff.get("current_id"),
                                "records": [{key: item.get(key) for key in ("id", "title", "revision", "created_at", "char_count")}
                                            for item in handoff_records]},
                    "statistics": {"volumes": len(volumes), "chapters": chapter_count, "characters": char_count,
                                   "settings": len(entries)},
                    "capabilities": {"external_agent_writes": True, "generation": True,
                                     "generation_purposes": ["optimize"], "generation_slot": "text",
                                     "generation_scopes": ["chapter", "chapter_outline"],
                                     "generation_requires_explicit_request": True,
                                     "generation_apply": "explicit_review"}}

    def _setting_summary(self, novel: dict[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
        versions = list(entry.get("versions") or [])
        latest = max(versions, key=lambda item: int(item.get("story_version", item.get("number", 0))), default=None)
        return {"id": entry.get("id"), "category_id": entry.get("category_id"),
                "title": entry.get("title") or "无标题条目", "archived": False,
                "current_version_id": entry.get("current_version_id"),
                "latest_version_id": latest.get("id") if latest else None,
                "version_order_notice": "latest 表示记录顺序，不表示故事适用性。",
                "versions": [{"id": item.get("id"), "number": item.get("story_version", item.get("number")),
                              "use_state": item.get("use_state", "draft"), "story_anchor": copy.deepcopy(item.get("story_anchor") or {"kind": "unspecified"}),
                              "content_sha256": item.get("content_sha256"), "edit_revision": item.get("edit_revision", 1),
                              "created_at": item.get("created_at"), "needs_review": self._version_needs_review(novel, entry, item)}
                             for item in versions]}

    def novel_view(self, project_id: str, scope: str, node_id: str = "", cursor: str = "", limit: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
        with self.projects.lock:
            record = self._record(str(project_id), "novel")
            novel = record["novel"]
            revision = self._revision(record)
            if scope not in {"root", "volume", "chapter"}:
                raise StudioProjectError("scope 必须为 root、volume 或 chapter")
            if scope == "root":
                selected = [(volume, chapter) for volume in novel.get("volumes") or [] for chapter in volume.get("chapters") or []]
            elif scope == "volume":
                volume = self._entry(novel.get("volumes") or [], _safe_id(node_id, "卷 ID"), "卷")
                selected = [(volume, chapter) for chapter in volume.get("chapters") or []]
            else:
                volume, chapter = self._chapter(novel, _safe_id(node_id, "章节 ID"))
                selected = [(volume, chapter)]
            page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
            offset = _cursor_decode(cursor, revision) if cursor else 0
            metadata = [{"scope": "chapter", "id": chapter["id"], "title": chapter.get("title", ""),
                         "volume": {"id": volume["id"], "title": volume.get("title", "")},
                         "content_sha256": chapter.get("content_sha256") or "",
                         "basis_refs": copy.deepcopy(chapter.get("basis_refs") or []),
                         "needs_review": self._source_needs_review(novel, chapter.get("basis_refs"))}
                        for volume, chapter in selected]
            page_meta = metadata[offset:offset + page_size]
            page = [{**item, "body_markdown": self._read_blob(item["content_sha256"]) if item["content_sha256"] else ""}
                    for item in page_meta]
            next_offset = offset + len(page)
            return {"project_id": record["id"], "revision": revision, "scope": scope, "blocks": page,
                    "has_more": next_offset < len(metadata),
                    "next_cursor": _cursor_encode(revision, next_offset) if next_offset < len(metadata) else None}

    def novel_chapter(self, project_id: str, chapter_id: str, edit_revision: Optional[int] = None) -> dict[str, Any]:
        with self.projects.lock:
            record = self._record(str(project_id), "novel")
            novel = record["novel"]
            volume, chapter = self._chapter(novel, _safe_id(chapter_id, "章节 ID"))
            digest = chapter.get("content_sha256") or ""
            if edit_revision is not None and edit_revision != int(chapter.get("revision", 1)):
                historical = next((item for item in chapter.get("history") or [] if int(item.get("revision", 0)) == edit_revision), None)
                if historical is None:
                    raise StudioProjectNotFound("章节编辑修订不存在")
                digest = historical.get("content_sha256") or ""
            return {"project_id": record["id"], "revision": self._revision(record),
                    "volume": {"id": volume["id"], "title": volume.get("title", "")},
                    "chapter": {"id": chapter["id"], "title": chapter.get("title", ""),
                                "revision": chapter.get("revision", 1), "content_sha256": digest,
                                "body_markdown": self._read_blob(digest) if digest else "",
                                "basis_refs": copy.deepcopy(chapter.get("basis_refs") or []),
                                "needs_review": self._source_needs_review(novel, chapter.get("basis_refs"))}}

    def settings_index(self, project_id: str, category_id: Optional[str] = None, cursor: str = "",
                       limit: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
        with self.projects.lock:
            record = self._record(str(project_id), "novel")
            novel, revision = record["novel"], self._revision(record)
            categories = [copy.deepcopy(item) for item in DEFAULT_SETTING_CATEGORIES]
            categories.extend({"id": item["id"], "title": item.get("name", "未命名分类"), "custom": True}
                              for item in novel.get("settings", {}).get("categories", []) if isinstance(item, dict))
            entries = self._novel_entries(novel)
            if any(item.get("category_id") is None for item in entries):
                categories.append({"id": None, "title": {"zh": "未分类", "en": "Uncategorized"}})
            if category_id is not None:
                if category_id != "uncategorized":
                    self._require_category(novel, category_id)
                entries = [entry for entry in entries if (entry.get("category_id") is None if category_id == "uncategorized" else entry.get("category_id") == category_id)]
            entries = sorted(entries, key=lambda item: (str(item.get("title") or "").casefold(), str(item.get("id") or "")))
            page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
            offset = _cursor_decode(cursor, revision) if cursor else 0
            page = [self._setting_summary(novel, item) for item in entries[offset:offset + page_size]]
            next_offset = offset + len(page)
            return {"project_id": record["id"], "revision": revision, "categories": categories,
                    "entries": page, "has_more": next_offset < len(entries),
                    "next_cursor": _cursor_encode(revision, next_offset) if next_offset < len(entries) else None,
                    "latest_version_notice": "版本编号和 latest 只表示记录顺序，不表示故事适用性。"}

    def setting_entry(self, project_id: str, entry_id: str, version_id: str = "",
                      edit_revision: Optional[int] = None) -> dict[str, Any]:
        with self.projects.lock:
            record = self._record(str(project_id), "novel")
            novel = record["novel"]
            entry = self._entry(self._novel_entries(novel), _safe_id(entry_id, "设定条目 ID"), "设定条目")
            wanted_id = version_id or entry.get("current_version_id") or ""
            version = self._entry_version(entry, _safe_id(wanted_id, "故事版本 ID"))
            digest = version.get("content_sha256") or ""
            if edit_revision is not None and edit_revision != int(version.get("edit_revision", 1)):
                historical = next((item for item in version.get("edit_history") or []
                                   if int(item.get("revision", 0)) == edit_revision), None)
                if historical is None:
                    raise StudioProjectNotFound("设定编辑修订不存在")
                digest = historical.get("content_sha256") or ""
            content = self._read_blob(digest) if digest else ""
            summary = self._setting_summary(novel, entry)
            selected = next(item for item in summary["versions"] if item["id"] == version["id"])
            return {"project_id": record["id"], "revision": self._revision(record), "entry": summary,
                    "selected_version": {**selected, "content_sha256": digest, "body_markdown": content,
                                          "selected_edit_revision": edit_revision or version.get("edit_revision", 1)}}

    def setting_revisions(self, project_id: str, entry_id: str, version_id: str, cursor: str = "",
                          limit: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
        with self.projects.lock:
            record = self._record(str(project_id), "novel")
            entry = self._entry(self._novel_entries(record["novel"]), _safe_id(entry_id, "设定条目 ID"), "设定条目")
            version = self._entry_version(entry, _safe_id(version_id, "故事版本 ID"))
            revision = self._revision(record)
            history = list(version.get("edit_history") or [])
            page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
            offset = _cursor_decode(cursor, revision) if cursor else 0
            page = [{"revision": item.get("revision"), "content_sha256": item.get("content_sha256"),
                     "created_at": item.get("created_at")} for item in history[offset:offset + page_size]]
            next_offset = offset + len(page)
            return {"project_id": record["id"], "revision": revision, "entry_id": entry["id"],
                    "version_id": version["id"], "current_edit_revision": version.get("edit_revision", 1),
                    "revisions": page, "has_more": next_offset < len(history),
                    "next_cursor": _cursor_encode(revision, next_offset) if next_offset < len(history) else None}

    def execute(self, project_id: str, module: str, payload: BaseModel) -> dict[str, Any]:
        """Apply one revisioned, durable, idempotent command atomically."""
        project_id = _safe_id(project_id, "项目 ID")
        if module not in {"script", "novel"}:
            raise StudioProjectError("手稿命令只支持 script 或 novel")
        command = payload.model_dump(exclude_unset=True)
        request_id = str(command.get("request_id") or "")
        if not ID_PATTERN.fullmatch(request_id):
            raise StudioProjectError("request_id 只能包含英文字母、数字、下划线和连字符")
        expected_revision = command.get("expected_revision")
        action = str(command.get("action") or "")
        args = command.get("args") or {}
        expected_sources = command.get("expected_sources")
        request_fingerprint = _fingerprint({key: value for key, value in command.items() if key != "request_id"})
        with self.projects.lock:
            root_record = self._record(project_id, module)
            content = copy.deepcopy(root_record[module])
            operations = content.setdefault("operations", {})
            prior = operations.get(request_id)
            if prior is not None:
                if not isinstance(prior, Mapping) or prior.get("fingerprint") != request_fingerprint:
                    raise StudioProjectConflict({"code": "IDEMPOTENCY_KEY_REUSED", "message": "request_id 已用于不同载荷。"})
                return copy.deepcopy(prior.get("receipt") or {})
            actual_revision = self._revision(root_record)
            if expected_revision != actual_revision:
                raise StudioProjectConflict({"code": "REVISION_CONFLICT", "message": "当前作品已更新，请重读后合并。",
                                              "current_revision": actual_revision})

            staged: dict[str, bytes] = {}
            aliases: dict[str, str] = {}
            created_ids: dict[str, str] = {}
            changed_ids: list[str] = []
            markdown_source_sha256s: list[str] = []
            if module == "novel":
                expected_sources = self._validate_expected_sources(content, expected_sources)

            def apply_one(operation_action: str, operation_args: Mapping[str, Any]) -> None:
                before_refs = set(aliases)
                if operation_action == "import_markdown":
                    markdown_source_sha256s.append(_digest(_body(operation_args.get("body_markdown"))))
                if module == "script":
                    changed, created = self._script_action(content, operation_action, operation_args, aliases, staged)
                else:
                    changed, created = self._novel_action(content, operation_action, operation_args, aliases, staged,
                                                          expected_sources=expected_sources)
                for client_ref in set(aliases) - before_refs:
                    created_ids[client_ref] = aliases[client_ref]
                created_ids.update(created)
                changed_ids.extend(str(item) for item in changed if item)

            if action == "batch":
                if not isinstance(args, Mapping) or not isinstance(args.get("operations"), list):
                    raise StudioProjectError("batch.args.operations 必须是数组")
                if not 1 <= len(args["operations"]) <= MAX_BATCH_OPERATIONS:
                    raise StudioProjectError(f"batch 操作数须为 1 到 {MAX_BATCH_OPERATIONS}")
                for operation in args["operations"]:
                    if not isinstance(operation, Mapping) or set(operation) != {"action", "args"}:
                        raise StudioProjectError("batch operation 只接受 action 和 args")
                    op_action = str(operation["action"])
                    op_args = operation["args"]
                    if op_action == "batch" or not isinstance(op_args, Mapping):
                        raise StudioProjectError("batch 不能嵌套且 args 必须是对象")
                    # The action-specific Pydantic schema also applies to nested operations.
                    schema = (SCRIPT_ARGS if module == "script" else NOVEL_ARGS).get(op_action)
                    if schema is None:
                        raise StudioProjectError("batch 包含不支持的动作")
                    validated = schema.model_validate(op_args)
                    apply_one(op_action, validated.model_dump(exclude_unset=True))
            else:
                schema = (SCRIPT_ARGS if module == "script" else NOVEL_ARGS).get(action)
                if schema is None:
                    raise StudioProjectError(f"{module} 动作不受支持：{action}")
                validated = schema.model_validate(args)
                apply_one(action, validated.model_dump(exclude_unset=True))

            next_revision = actual_revision + 1
            root_record[module] = content
            root_record["revision"] = next_revision
            root_record["updated_at"] = _now_ms()
            receipt = {"request_id": request_id, "status": "succeeded", "project_id": project_id,
                       "revision": next_revision, "changed_ids": list(dict.fromkeys(changed_ids)),
                       "created_ids": created_ids, "warnings": []}
            if len(markdown_source_sha256s) == 1:
                receipt["source_sha256"] = markdown_source_sha256s[0]
            elif markdown_source_sha256s:
                receipt["markdown_source_sha256s"] = list(markdown_source_sha256s)
            operations[request_id] = {"fingerprint": request_fingerprint, "receipt": copy.deepcopy(receipt),
                                      "created_at": _now_ms()}
            self._commit_blobs(staged)
            self.projects.write_manuscript_record(root_record)
            return receipt

    def command_receipt(self, project_id: str, module: str, request_id: str) -> dict[str, Any]:
        with self.projects.lock:
            record = self._record(_safe_id(project_id, "项目 ID"), module)
            item = (record.get(module) or {}).get("operations", {}).get(_safe_id(request_id, "request_id"))
            if not isinstance(item, Mapping):
                raise StudioProjectNotFound("项目命令不存在")
            return copy.deepcopy(item.get("receipt") or {})

    def script_history(self, project_id: str, cursor: str = "", limit: int = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
        with self.projects.lock:
            record = self._record(str(project_id), "script")
            script, revision = record["script"], self._revision(record)
            history = list(script.get("history") or [])
            page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
            offset = _cursor_decode(cursor, revision) if cursor else 0
            page = []
            for item in history[offset:offset + page_size]:
                digest = str(item.get("content_sha256") or "")
                page.append({**{key: item.get(key) for key in ("kind", "label", "created_at")},
                             "content_sha256": digest, "char_count": len(self._read_blob(digest)) if digest else 0})
            next_offset = offset + len(page)
            return {"project_id": record["id"], "revision": revision, "history": page,
                    "has_more": next_offset < len(history),
                    "next_cursor": _cursor_encode(revision, next_offset) if next_offset < len(history) else None}

    def script_history_document(self, project_id: str, content_sha256: str) -> dict[str, Any]:
        digest = str(content_sha256 or "")
        if not HASH_PATTERN.fullmatch(digest):
            raise StudioProjectError("content_sha256 格式无效")
        with self.projects.lock:
            record = self._record(str(project_id), "script")
            script = record["script"]
            item = next((value for value in script.get("history") or []
                         if value.get("kind") in {"draft", "markdown_import"}
                         and value.get("content_sha256") == digest), None)
            if item is None:
                raise StudioProjectNotFound("该完整草稿或 Markdown 导入不在本项目历史中")
            body = self._read_blob(digest)
            return {"project_id": record["id"], "revision": self._revision(record),
                    "content_sha256": digest, "char_count": len(body),
                    "created_at": item.get("created_at"), "label": item.get("label"),
                    "body_markdown": body}

    def novel_markdown_history_document(self, project_id: str, content_sha256: str) -> dict[str, Any]:
        digest = str(content_sha256 or "")
        if not HASH_PATTERN.fullmatch(digest):
            raise StudioProjectError("content_sha256 格式无效")
        with self.projects.lock:
            record = self._record(str(project_id), "novel")
            novel = record["novel"]
            item = next((value for value in novel.get("history") or []
                         if value.get("kind") == "markdown_import" and value.get("content_sha256") == digest), None)
            if item is None:
                raise StudioProjectNotFound("该 Markdown 导入不在本项目历史中")
            body = self._read_blob(digest)
            return {"project_id": record["id"], "revision": self._revision(record),
                    "content_sha256": digest, "char_count": len(body),
                    "created_at": item.get("created_at"), "label": item.get("label"),
                    "body_markdown": body}

    def novel_handoff(self, project_id: str, record_id: str = "", edit_revision: Optional[int] = None) -> dict[str, Any]:
        with self.projects.lock:
            record = self._record(str(project_id), "novel")
            novel = record["novel"]
            handoff = novel.get("handoff") or {}
            records = handoff.get("records") or []
            selected_id = record_id or str(handoff.get("current_id") or (records[-1].get("id") if records else ""))
            item = next((value for value in records if value.get("id") == selected_id), None)
            if item is None:
                if not records and not record_id:
                    return {"project_id": record["id"], "revision": self._revision(record),
                            "exists": False, "record": None}
                raise StudioProjectNotFound("创作接续记录不存在")
            digest = str(item.get("body_sha256") or "")
            selected_refs = copy.deepcopy(item.get("source_refs") or [])
            selected_revision = int(item.get("revision", 1))
            if edit_revision is not None and int(item.get("revision", 1)) != edit_revision:
                historical = next((value for value in item.get("history") or [] if int(value.get("revision", 0)) == edit_revision), None)
                if historical is None:
                    raise StudioProjectNotFound("创作接续修订不存在")
                digest = str(historical.get("body_sha256") or "")
                selected_refs = copy.deepcopy(historical.get("source_refs") or [])
                selected_revision = int(historical.get("revision", edit_revision))
            body = self._read_blob(digest)
            return {"project_id": record["id"], "revision": self._revision(record), "exists": True,
                    "record": {"id": item["id"], "title": _markdown_title(body, item.get("title") or "创作接续记录"),
                               "revision": selected_revision, "body_sha256": digest, "body_markdown": body,
                               "source_refs": selected_refs,
                               "needs_review": self._source_needs_review(novel, selected_refs)}}

    def novel_manifest(self, project_id: str) -> dict[str, Any]:
        """Compact inventory for a new Agent session; it never selects a latest story version."""
        with self.projects.lock:
            record = self._record(str(project_id), "novel")
            novel = record["novel"]
            summary = self.novel_summary(project_id)
            chapters = []
            for volume in novel.get("volumes") or []:
                for chapter in volume.get("chapters") or []:
                    outline_revision, outline_digest, outline_count, _ = self._outline_state(chapter)
                    chapters.append({"id": chapter["id"], "volume_id": volume["id"],
                                     "volume_title": volume.get("title", ""), "title": chapter.get("title", ""),
                                     "order": chapter.get("order", 0), "revision": chapter.get("revision", 1),
                                     "content_sha256": chapter.get("content_sha256", ""),
                                     "outline_revision": outline_revision, "outline_sha256": outline_digest,
                                     "outline_char_count": outline_count,
                                     "basis_refs": copy.deepcopy(chapter.get("basis_refs") or []),
                                     "needs_review": self._source_needs_review(novel, chapter.get("basis_refs"))})
            handoff = novel.get("handoff") or {}
            current_id = handoff.get("current_id")
            current = next((item for item in handoff.get("records") or [] if item.get("id") == current_id), None)
            compact_volumes = []
            for volume in novel.get("volumes") or []:
                compact_volumes.append({"id": volume["id"], "title": volume.get("title", ""),
                    "order": volume.get("order", 0), "chapters": [
                        {"id": chapter["id"], "title": chapter.get("title", ""), "order": chapter.get("order", 0),
                         "revision": chapter.get("revision", 1), "char_count": int(chapter.get("char_count") or 0),
                         "content_sha256": chapter.get("content_sha256", ""),
                         "outline_revision": self._outline_state(chapter)[0],
                         "outline_sha256": self._outline_state(chapter)[1],
                         "outline_char_count": self._outline_state(chapter)[2],
                         "basis_refs": copy.deepcopy(chapter.get("basis_refs") or []),
                         "needs_review": self._source_needs_review(novel, chapter.get("basis_refs"))}
                        for chapter in volume.get("chapters") or []]})
            return {"project": summary["project"], "revision": summary["revision"],
                    "inventory": {"volumes": compact_volumes,
                                  "chapters": chapters, "settings": summary["settings"],
                                  "context_pins": copy.deepcopy(novel.get("context_pins") or [])},
                    "handoff": ({"id": current["id"], "title": current.get("title"),
                                 "revision": current.get("revision", 1),
                                 "body_sha256": current.get("body_sha256"),
                                 "source_refs": copy.deepcopy(current.get("source_refs") or []),
                                 "needs_review": self._source_needs_review(novel, current.get("source_refs"))}
                                if current else None),
                    "version_guidance": "story_version/latest_version_id 表示记录顺序，不表示故事适用性；按 story_anchor 与当前章节明确判断，不得默认选最新。",
                    "capabilities": {"generation": True, "generation_purposes": ["optimize"],
                                     "generation_slot": "text",
                                     "generation_scopes": ["chapter", "chapter_outline"],
                                     "generation_requires_explicit_request": True,
                                     "generation_apply": "explicit_review",
                                     "external_agent_writes": True}}

    def novel_search(self, project_id: str, query: str, scope: str = "all", cursor: str = "",
                     limit: int = DEFAULT_PAGE_SIZE, include_drafts: bool = False) -> dict[str, Any]:
        needle = str(query or "").strip()
        if not needle or len(needle) > 200:
            raise StudioProjectError("搜索词须为 1 到 200 个字符")
        if scope not in {"all", "chapters", "settings", "handoff"}:
            raise StudioProjectError("scope 必须为 all、chapters、settings 或 handoff")
        with self.projects.lock:
            record = self._record(str(project_id), "novel")
            novel, revision = record["novel"], self._revision(record)
            folded = needle.casefold()
            matches: list[dict[str, Any]] = []
            if scope in {"all", "chapters"}:
                for volume in novel.get("volumes") or []:
                    for chapter in volume.get("chapters") or []:
                        digest = chapter.get("content_sha256") or ""
                        body = self._read_blob(digest) if digest else ""
                        position = body.casefold().find(folded)
                        if position >= 0:
                            matches.append(self._search_hit("chapter", chapter, body, position,
                                volume={"id": volume["id"], "title": volume.get("title", "")}))
            if scope in {"all", "settings"}:
                for entry in self._novel_entries(novel):
                    for version in entry.get("versions") or []:
                        if version.get("use_state", "draft") != "confirmed" and not include_drafts:
                            continue
                        digest = version.get("content_sha256") or ""
                        body = self._read_blob(digest) if digest else ""
                        position = body.casefold().find(folded)
                        if position >= 0:
                            hit = self._search_hit("setting", entry, body, position)
                            hit.update({"version_id": version["id"], "story_version": version.get("story_version"),
                                        "use_state": version.get("use_state", "draft"),
                                        "story_anchor": copy.deepcopy(version.get("story_anchor") or {"kind": "unspecified"}),
                                        "needs_review": self._version_needs_review(novel, entry, version)})
                            matches.append(hit)
            if scope in {"all", "handoff"}:
                for item in (novel.get("handoff") or {}).get("records") or []:
                    digest = item.get("body_sha256") or ""
                    body = self._read_blob(digest) if digest else ""
                    position = body.casefold().find(folded)
                    if position >= 0:
                        matches.append(self._search_hit("handoff", item, body, position))
            page_size = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
            offset = _cursor_decode(cursor, revision) if cursor else 0
            page = matches[offset:offset + page_size]
            next_offset = offset + len(page)
            return {"project_id": record["id"], "revision": revision, "query": needle, "scope": scope,
                    "results": page, "has_more": next_offset < len(matches),
                    "next_cursor": _cursor_encode(revision, next_offset) if next_offset < len(matches) else None}

    @staticmethod
    def _search_hit(kind: str, item: Mapping[str, Any], body: str, position: int, **extra: Any) -> dict[str, Any]:
        start = max(0, position - 180)
        end = min(len(body), position + 320)
        excerpt = body[start:end]
        if start:
            excerpt = "…" + excerpt
        if end < len(body):
            excerpt += "…"
        return {"kind": kind, "id": item.get("id"), "title": item.get("title") or "无标题",
                "content_sha256": item.get("content_sha256") or item.get("body_sha256") or "",
                "match_offset": position, "excerpt_markdown": excerpt, **extra}

    def novel_context(self, project_id: str, chapter_id: str = "") -> dict[str, Any]:
        """Read explicit handoff/pins and an unranked index of setting candidates."""
        with self.projects.lock:
            record = self._record(str(project_id), "novel")
            novel = record["novel"]
            target = None
            if chapter_id:
                _, target = self._chapter(novel, _safe_id(chapter_id, "章节 ID"))
            omissions: list[dict[str, str]] = []
            documents: list[dict[str, Any]] = []
            used_bytes = 0
            max_documents, max_context_bytes = 30, 5 * 1024 * 1024

            def include(kind: str, item: Mapping[str, Any], version: Optional[Mapping[str, Any]], *, pinned: bool = False) -> None:
                nonlocal used_bytes
                digest = str((version or item).get("content_sha256") or (version or item).get("body_sha256") or "")
                doc_id = str((version or item).get("id") or item.get("id") or "")
                if any(value.get("version_id") == doc_id and value.get("kind") == kind for value in documents):
                    return
                if len(documents) >= max_documents:
                    omissions.append({"kind": kind, "id": str(item.get("id") or ""), "reason": "document_limit"})
                    return
                body = self._read_blob(digest) if digest else ""
                size = len(body.encode("utf-8"))
                if used_bytes + size > max_context_bytes:
                    omissions.append({"kind": kind, "id": str(item.get("id") or ""), "reason": "context_byte_limit"})
                    return
                used_bytes += size
                document = {"kind": kind, "id": item.get("id"), "title": item.get("title") or "无标题",
                            "content_sha256": digest, "body_markdown": body, "pinned": pinned}
                if version:
                    document.update({"version_id": version.get("id"), "story_version": version.get("story_version"),
                                     "use_state": version.get("use_state"), "story_anchor": copy.deepcopy(version.get("story_anchor") or {"kind": "unspecified"}),
                                     "needs_review": self._version_needs_review(novel, item, version)})
                documents.append(document)

            handoff = self.novel_handoff(project_id) if (novel.get("handoff") or {}).get("records") else None
            if handoff:
                document = handoff["record"]
                include("handoff", document, None, pinned=True)
            entries = {entry["id"]: entry for entry in self._novel_entries(novel)}
            for pin in novel.get("context_pins") or []:
                entry = entries.get(str(pin.get("entry_id") or ""))
                if entry is None:
                    omissions.append({"kind": "setting", "id": str(pin.get("entry_id") or ""), "reason": "missing_pin"})
                    continue
                if pin.get("version_id"):
                    version = next((value for value in entry.get("versions") or [] if value.get("id") == pin["version_id"]), None)
                    if version:
                        include("setting", entry, version, pinned=True)
                else:
                    omissions.append({"kind": "setting", "id": entry["id"], "reason": "pinned_entry_requires_story_version_choice"})
            candidate_index = []
            for entry in self._novel_entries(novel):
                for version in entry.get("versions") or []:
                    candidate_index.append({"entry_id": entry["id"], "title": entry.get("title") or "无标题条目",
                        "category_id": entry.get("category_id"), "version_id": version["id"],
                        "story_version": version.get("story_version"), "use_state": version.get("use_state", "draft"),
                        "story_anchor": copy.deepcopy(version.get("story_anchor") or {"kind": "unspecified"}),
                        "content_sha256": version.get("content_sha256"),
                        "basis_refs": copy.deepcopy(version.get("basis_refs") or []),
                        "needs_review": self._version_needs_review(novel, entry, version)})
            return {"project_id": record["id"], "revision": self._revision(record),
                    "target_chapter": ({"id": target["id"], "title": target.get("title", ""), "order": target.get("order", 0)} if target else None),
                    "documents": documents, "candidate_index": candidate_index, "omissions": omissions,
                    "guidance": "候选和故事锚点只是可追溯资料，不由目录顺序、版本号或当前章节顺序自动判定适用性。请依据当前场景及故事内容读取相关版本，并保留不确定性。未明确置顶的全文需按 entry_id/version_id 单独读取。"}


def _raise_manuscript_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, StudioProjectError):
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if isinstance(exc, DataFileError):
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    raise exc


def create_studio_manuscripts_router(store: StudioManuscriptStore) -> APIRouter:
    router = APIRouter(tags=["Studio Manuscripts"])

    @router.get("/api/studio/scripts/{project_id}/markdown", response_model=ManuscriptMarkdownExport)
    async def script_markdown(project_id: str):
        try:
            return await run_in_threadpool(store.script_markdown, project_id)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/scripts/{project_id}")
    async def script_summary(project_id: str):
        try:
            return await run_in_threadpool(store.script_summary, project_id)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/scripts/{project_id}/episodes/{episode_id}/outline",
                response_model=ManuscriptOutlineDocument)
    async def script_episode_outline(project_id: str, episode_id: str,
                                    outline_revision: Optional[int] = Query(None, ge=0)):
        try:
            return await run_in_threadpool(store.outline_document, "script", project_id, episode_id,
                                           outline_revision)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/scripts/{project_id}/view")
    async def script_view(project_id: str, scope: str = "root", node_id: str = "",
                          cursor: str = "", limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)):
        try:
            return await run_in_threadpool(store.script_view, project_id, scope, node_id, cursor, limit)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/scripts/{project_id}/scenes/{scene_id}")
    async def script_scene(project_id: str, scene_id: str, edit_revision: Optional[int] = Query(None, ge=1)):
        try:
            return await run_in_threadpool(store.script_scene, project_id, scene_id, edit_revision)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/scripts/{project_id}/history")
    async def script_history(project_id: str, cursor: str = "",
                             limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)):
        try:
            return await run_in_threadpool(store.script_history, project_id, cursor, limit)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/scripts/{project_id}/history/{content_sha256}")
    async def script_history_document(project_id: str, content_sha256: str):
        try:
            return await run_in_threadpool(store.script_history_document, project_id, content_sha256)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/scripts/{project_id}/markdown/history/{content_sha256}", response_model=ManuscriptMarkdownHistory)
    async def script_markdown_history_document(project_id: str, content_sha256: str):
        try:
            return await run_in_threadpool(store.script_history_document, project_id, content_sha256)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.post("/api/studio/scripts/{project_id}/commands", response_model=ManuscriptCommandReceipt,
                 response_model_exclude_none=True, dependencies=[Depends(_guard_local_write)])
    async def script_command(project_id: str, payload: ScriptCommand):
        try:
            return await run_in_threadpool(store.execute, project_id, "script", payload)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/scripts/{project_id}/commands/{request_id}", response_model=ManuscriptCommandReceipt,
                response_model_exclude_none=True)
    async def script_command_receipt(project_id: str, request_id: str):
        try:
            return await run_in_threadpool(store.command_receipt, project_id, "script", request_id)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/novels/{project_id}")
    async def novel_summary(project_id: str):
        try:
            return await run_in_threadpool(store.novel_summary, project_id)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/novels/{project_id}/chapters/{chapter_id}/outline",
                response_model=ManuscriptOutlineDocument)
    async def novel_chapter_outline(project_id: str, chapter_id: str,
                                    outline_revision: Optional[int] = Query(None, ge=0)):
        try:
            return await run_in_threadpool(store.outline_document, "novel", project_id, chapter_id,
                                           outline_revision)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/novels/{project_id}/manifest")
    async def novel_manifest(project_id: str):
        try:
            return await run_in_threadpool(store.novel_manifest, project_id)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/novels/{project_id}/markdown", response_model=ManuscriptMarkdownExport)
    async def novel_markdown(project_id: str):
        try:
            return await run_in_threadpool(store.novel_markdown, project_id)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/novels/{project_id}/markdown/history/{content_sha256}", response_model=ManuscriptMarkdownHistory)
    async def novel_markdown_history_document(project_id: str, content_sha256: str):
        try:
            return await run_in_threadpool(store.novel_markdown_history_document, project_id, content_sha256)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/novels/{project_id}/context")
    async def novel_context(project_id: str, chapter_id: str = ""):
        try:
            return await run_in_threadpool(store.novel_context, project_id, chapter_id)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/novels/{project_id}/search")
    async def novel_search(project_id: str, q: str, scope: str = "all", cursor: str = "",
                           include_drafts: bool = False,
                           limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)):
        try:
            return await run_in_threadpool(store.novel_search, project_id, q, scope, cursor, limit, include_drafts)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/novels/{project_id}/view")
    async def novel_view(project_id: str, scope: str = "root", node_id: str = "",
                         cursor: str = "", limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)):
        try:
            return await run_in_threadpool(store.novel_view, project_id, scope, node_id, cursor, limit)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/novels/{project_id}/chapters/{chapter_id}")
    async def novel_chapter(project_id: str, chapter_id: str, edit_revision: Optional[int] = Query(None, ge=1)):
        try:
            return await run_in_threadpool(store.novel_chapter, project_id, chapter_id, edit_revision)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/novels/{project_id}/settings")
    async def novel_settings(project_id: str, category_id: Optional[str] = None, cursor: str = "",
                             limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)):
        try:
            return await run_in_threadpool(store.settings_index, project_id, category_id, cursor, limit)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/novels/{project_id}/settings/{entry_id}")
    async def novel_setting_entry(project_id: str, entry_id: str, version_id: str = "",
                                  edit_revision: Optional[int] = Query(None, ge=1)):
        try:
            return await run_in_threadpool(store.setting_entry, project_id, entry_id, version_id, edit_revision)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/novels/{project_id}/settings/{entry_id}/revisions")
    async def novel_setting_revisions(project_id: str, entry_id: str, version_id: str, cursor: str = "",
                                      limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)):
        try:
            return await run_in_threadpool(store.setting_revisions, project_id, entry_id, version_id, cursor, limit)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/novels/{project_id}/handoff")
    async def novel_handoff(project_id: str, record_id: str = "", edit_revision: Optional[int] = Query(None, ge=1)):
        try:
            return await run_in_threadpool(store.novel_handoff, project_id, record_id, edit_revision)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.post("/api/studio/novels/{project_id}/commands", response_model=ManuscriptCommandReceipt,
                 response_model_exclude_none=True, dependencies=[Depends(_guard_local_write)])
    async def novel_command(project_id: str, payload: NovelCommand):
        try:
            return await run_in_threadpool(store.execute, project_id, "novel", payload)
        except Exception as exc:
            _raise_manuscript_error(exc)

    @router.get("/api/studio/novels/{project_id}/commands/{request_id}", response_model=ManuscriptCommandReceipt,
                response_model_exclude_none=True)
    async def novel_command_receipt(project_id: str, request_id: str):
        try:
            return await run_in_threadpool(store.command_receipt, project_id, "novel", request_id)
        except Exception as exc:
            _raise_manuscript_error(exc)

    return router
