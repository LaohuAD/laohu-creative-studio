"""公众号文章项目的安全正文、主题目录与修订写入。"""

from __future__ import annotations

import base64
import copy
import hashlib
import inspect
import json
import os
import re
import tempfile
import time
from functools import lru_cache
from urllib.parse import quote
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from canvas_core.json_store import DataFileError, read_json
from studio_projects import StudioProjectNotFound, StudioProjectStore, _clean_project_id, _guard_local_write


MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_HTML_BYTES = 24 * 1024 * 1024
MAX_DATA_IMAGE_BYTES = 12 * 1024 * 1024
ARTICLE_VARIANT_DIR = Path("assets") / "output" / "text" / "articles"
TEMPLATE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,80}$")
ARTICLE_VERSION_KINDS = ("title", "cover", "body")
DATA_IMAGE_PATTERN = re.compile(r"^data:image/(png|jpeg|webp|gif|avif);base64,([A-Za-z0-9+/]+={0,2})$", re.I)
FORBIDDEN_TAGS = {
    "html", "head", "body", "title", "meta", "base", "style", "script", "link",
    "div", "button", "form", "input", "select", "option", "textarea", "video",
    "audio", "canvas", "svg", "iframe", "object", "embed", "source",
}
ALLOWED_TAGS = {
    "section", "p", "span", "strong", "b", "em", "i", "u", "s", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "a", "img", "br", "hr", "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "ul", "ol", "li", "pre", "code", "sup", "sub",
}
VOID_TAGS = {"img", "br", "hr"}
ALLOWED_ATTRIBUTES = {
    "style", "leaf", "src", "alt", "href", "width", "height", "colspan", "rowspan", "scope", "title",
}
ALLOWED_STYLE_PROPERTIES = {
    "align-items", "align-self", "background", "border", "border-bottom", "border-collapse", "border-left",
    "background-color", "border-radius", "border-right", "border-top", "box-shadow", "box-sizing", "color", "display", "flex",
    "flex-direction", "flex-shrink", "flex-wrap", "font-family", "font-size", "font-style", "font-variant-numeric",
    "font-weight", "gap", "height", "justify-content", "letter-spacing", "line-height", "list-style-position",
    "list-style-type", "margin", "margin-bottom", "margin-left", "margin-right", "margin-top", "max-width",
    "min-height", "min-width", "overflow", "overflow-x", "padding", "padding-bottom", "padding-left",
    "padding-right", "padding-top", "text-align", "text-decoration", "text-shadow", "text-transform", "vertical-align", "white-space",
    "width", "writing-mode", "-webkit-overflow-scrolling",
}
CSS_FORBIDDEN = re.compile(r"url\s*\(|expression\s*\(|@import|@media|@keyframes|var\s*\(|(?:^|[;\s])(?:position|float)\s*:|display\s*:\s*grid|--[a-z0-9_-]+", re.I)


class ArticleValidationError(ValueError):
    pass


class ArticleHtmlGuard(HTMLParser):
    """只验证并拒绝不安全片段，不改写或静默删减用户正文。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.root_tags: list[str] = []
        self.errors: list[str] = []

    @staticmethod
    def _safe_http_url(value: str) -> bool:
        parsed = urlsplit(value.strip())
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _safe_image_url(value: str) -> bool:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
            return True
        match = DATA_IMAGE_PATTERN.fullmatch(value.strip())
        if not match:
            return False
        try:
            raw = base64.b64decode(match.group(2), validate=True)
        except (ValueError, base64.binascii.Error):
            return False
        if not 0 < len(raw) <= MAX_DATA_IMAGE_BYTES:
            return False
        mime = match.group(1).lower()
        signatures = {
            "png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
            "jpeg": raw.startswith(b"\xff\xd8\xff"),
            "gif": raw.startswith((b"GIF87a", b"GIF89a")),
            "webp": len(raw) >= 12 and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP",
            "avif": len(raw) >= 12 and raw[4:8] == b"ftyp" and raw[8:12] in {b"avif", b"avis"},
        }
        return bool(signatures.get(mime))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if not self.stack:
            self.root_tags.append(tag)
        if tag in FORBIDDEN_TAGS or tag not in ALLOWED_TAGS:
            self.errors.append(f"不允许的标签 <{tag}>")
        attr_map: dict[str, Optional[str]] = {}
        for name, value in attrs:
            normalized = name.lower()
            if normalized in attr_map:
                self.errors.append(f"重复属性 {normalized}")
            attr_map[normalized] = value
            if normalized.startswith("on") or normalized in {"class", "id"}:
                self.errors.append(f"不允许的属性 {normalized}")
            elif normalized not in ALLOWED_ATTRIBUTES:
                self.errors.append(f"不支持的属性 {normalized}")
        if "leaf" in attr_map and tag != "span":
            self.errors.append("leaf 只能用于 span")
        if "style" in attr_map:
            style = str(attr_map.get("style") or "")
            if CSS_FORBIDDEN.search(style):
                self.errors.append("样式包含不允许的主动内容或布局规则")
            for declaration in style.split(";"):
                if not declaration.strip():
                    continue
                if ":" not in declaration:
                    self.errors.append("样式声明格式不正确")
                    continue
                name, value = declaration.split(":", 1)
                if name.strip().lower() not in ALLOWED_STYLE_PROPERTIES or not value.strip():
                    self.errors.append(f"不支持的样式属性 {name.strip()}")
        if tag == "img":
            source = str(attr_map.get("src") or "")
            if not self._safe_image_url(source):
                self.errors.append("图片只允许安全的 HTTP(S) 地址或受限的内嵌栅格图片")
        elif "src" in attr_map:
            self.errors.append("src 只允许用于图片")
        if tag == "a" and not self._safe_http_url(str(attr_map.get("href") or "")):
            self.errors.append("链接只允许完整的 HTTP(S) 地址")
        if tag != "a" and "href" in attr_map:
            self.errors.append("href 只允许用于链接")
        is_leaf = tag == "span" and "leaf" in attr_map
        if tag not in VOID_TAGS:
            self.stack.append((tag, is_leaf))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
            return
        self.errors.append(f"标签闭合顺序错误：</{tag}>")

    def handle_data(self, data: str) -> None:
        if data.strip() and (not self.stack or not any(is_leaf for _, is_leaf in self.stack)):
            self.errors.append("所有可见文字必须保留在 span leaf 中")

    def handle_decl(self, decl: str) -> None:
        self.errors.append("公众号正文片段不能包含文档声明")

    def finish(self) -> list[str]:
        if self.stack:
            self.errors.append("存在未闭合标签")
        if self.root_tags != ["section"]:
            self.errors.append("公众号正文必须是单一顶层 section 片段")
        return self.errors


class _ArticleImageSourceCollector(HTMLParser):
    """从已验证的文章片段中提取图片地址，不执行或改写 HTML。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "img":
            source = next((value for name, value in attrs if name.lower() == "src"), None)
            if source:
                self.sources.append(source)


class _ArticlePlainTextCollector(HTMLParser):
    """从已通过 HTML guard 的排版正文提取短预览文本。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)


@lru_cache(maxsize=128)
def _cached_article_layout_excerpt(
    root_value: str,
    stored_path: str,
    digest: str,
    mtime_ns: int,
    size: int,
    inode: int,
) -> tuple[bool, str]:
    """Cache only guard status and a short excerpt, never the HTML body."""
    try:
        relative = Path(stored_path)
        if relative.is_absolute() or ".." in relative.parts:
            return False, ""
        root = Path(root_value).resolve()
        path = (root / relative).resolve()
        text_root = (root / "assets" / "output" / "text").resolve()
        try:
            path.relative_to(text_root)
        except ValueError:
            return False, ""
        stat = path.stat()
        if (not path.is_file() or stat.st_size > MAX_HTML_BYTES
                or (stat.st_mtime_ns, stat.st_size, stat.st_ino) != (mtime_ns, size, inode)):
            return False, ""
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            return False, ""
        body_html = body.decode("utf-8")
        validate_article_html(body_html)
        parser = _ArticlePlainTextCollector()
        parser.feed(body_html)
        parser.close()
        excerpt = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()[:180]
        return True, excerpt
    except (OSError, RuntimeError, UnicodeError, ArticleValidationError, ValueError):
        return False, ""


def validate_article_html(body_html: str) -> None:
    if not isinstance(body_html, str) or not body_html.strip():
        raise ArticleValidationError("排版正文不能为空")
    if len(body_html.encode("utf-8")) > MAX_HTML_BYTES:
        raise ArticleValidationError("排版正文超过大小限制")
    parser = ArticleHtmlGuard()
    try:
        parser.feed(body_html)
        parser.close()
    except Exception as exc:
        raise ArticleValidationError("排版正文无法解析") from exc
    errors = parser.finish()
    if errors:
        raise ArticleValidationError("；".join(dict.fromkeys(errors)))


def article_source_sha256(title: str, source_markdown: str) -> str:
    content = json.dumps(
        {"title": title, "source_markdown": source_markdown},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


class VariantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body_html: str = Field(
        min_length=1,
        description="完整且正式保存的 HTML 正文；中间排版草稿不得提交。相同 HTML 内容复用同一正文历史版本。",
    )
    source_sha256: Optional[str] = Field(default=None, min_length=64, max_length=64)


class TitleVariantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=240)
    source_sha256: Optional[str] = Field(default=None, min_length=64, max_length=64)


class CoverVariantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    asset_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    result_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    source_sha256: Optional[str] = Field(default=None, min_length=64, max_length=64)


class MediaReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    asset_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    result_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    source_sha256: Optional[str] = Field(default=None, min_length=64, max_length=64)


class ArticlePutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    source_markdown: Optional[str] = Field(
        default=None,
        description="内部创作源稿。它会保留在文章数据中，但不单独形成用户可见的 HTML 正文历史版本。",
    )
    title: Optional[str] = Field(default=None, max_length=240)
    selected_theme_id: Optional[str] = Field(default=None, max_length=81)
    title_variants: Optional[dict[str, TitleVariantInput]] = None
    selected_title_variant_id: Optional[str] = Field(default=None, max_length=128)
    cover_variants: Optional[list[CoverVariantInput]] = None
    selected_cover_variant_id: Optional[str] = Field(default=None, max_length=128)
    media_refs: Optional[list[MediaReferenceInput]] = None
    expected_catalog_fingerprint: Optional[str] = Field(default=None, max_length=128)
    variants: Optional[dict[str, VariantInput]] = Field(
        default=None,
        description="按主题提交已完成的 HTML 正文。仅新的 HTML 内容创建可见正文版本；仅更改源稿不会创建正文版本。",
    )


class ArticleVersionRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    body_view: Optional[Literal["source", "preview"]] = Field(
        default=None,
        description="正文历史恢复目标：preview 选择并恢复 HTML 排版；source 仅为既有 Agent/API 的 Markdown 源稿兼容能力，新界面不提供源稿历史版本选择。",
    )


class ArticleGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot: Literal["text", "image", "video", "audio", "music", "voice"] = "image"
    purpose: Literal["cover", "illustration", "knowledge"]
    output_node_id: str = Field(min_length=1, max_length=160)
    client_operation_id: str = Field(min_length=1, max_length=160)
    base_revision: Optional[int] = Field(default=None, ge=1)
    request: dict[str, Any] = Field(default_factory=dict)


class StudioArticleStore:
    """把文章来源与版本元数据存进项目主记录，排版 HTML 按内容哈希独立保存。"""

    def __init__(
        self,
        root: str | os.PathLike[str],
        project_store: StudioProjectStore,
        catalog_path: str | os.PathLike[str],
        *,
        resolve_media_reference: Callable[[str, str], Mapping[str, Any] | None] | None = None,
        register_managed_result: Callable[..., Mapping[str, Any]] | None = None,
        find_shared_media_by_hash: Callable[[str, str], Mapping[str, Any] | None] | None = None,
    ):
        self.root = Path(root).expanduser().absolute()
        self.project_store = project_store
        self.catalog_path = Path(catalog_path).expanduser().absolute()
        self.resolve_media_reference = resolve_media_reference
        self.register_managed_result = register_managed_result
        self.find_shared_media_by_hash = find_shared_media_by_hash

    def _load_catalog(self) -> dict[str, Any]:
        try:
            catalog_bytes = self.catalog_path.read_bytes()
            if len(catalog_bytes) > 4 * 1024 * 1024:
                raise DataFileError("公众号主题目录超过大小限制，原目录已保留。")
            value = read_json(self.catalog_path)
        except DataFileError:
            raise
        except OSError as exc:
            raise DataFileError("公众号主题目录不可读取，原目录已保留。") from exc
        if not isinstance(value, dict) or not isinstance(value.get("templates"), list) or not value["templates"]:
            raise DataFileError("公众号主题目录格式不正确，原目录已保留。")
        sources = value.get("source_fingerprints")
        theme_sources = sources.get("themes") if isinstance(sources, dict) else None
        if not isinstance(sources, dict) or not isinstance(theme_sources, dict):
            raise DataFileError("公众号主题目录缺少来源指纹，原目录已保留。")
        fingerprint = hashlib.sha256(catalog_bytes).hexdigest()
        seen: set[str] = set()
        templates: list[dict[str, str]] = []
        for raw in value["templates"]:
            if not isinstance(raw, dict):
                raise DataFileError("公众号主题目录条目格式不正确，原目录已保留。")
            theme_id = str(raw.get("id") or "")
            if not TEMPLATE_ID_PATTERN.fullmatch(theme_id) or theme_id in seen:
                raise DataFileError("公众号主题目录包含重复或不合法的 ID，原目录已保留。")
            seen.add(theme_id)
            if not isinstance(theme_sources.get(theme_id), str) or not theme_sources[theme_id]:
                raise DataFileError(f"主题 {theme_id} 缺少组件库来源指纹，原目录已保留。")
            preview = str(raw.get("preview_url") or "")
            if not preview.startswith("/static/article-templates/") or ".." in Path(preview).parts:
                raise DataFileError(f"主题 {theme_id} 的预览地址不合法，原目录已保留。")
            templates.append({key: str(raw.get(key) or "") for key in (
                "id", "name", "name_en", "color", "description", "description_en", "preview_url",
            )})
        return {"templates": templates, "catalog_fingerprint": fingerprint, "source_fingerprints": sources}

    @staticmethod
    def _article_payload(record: Mapping[str, Any]) -> dict[str, Any]:
        article = record.get("article")
        if not isinstance(article, dict):
            raise DataFileError("文章主记录损坏，原文件已保留。")
        title = article.get("title", "")
        source = article.get("source_markdown", "")
        if not isinstance(title, str) or not isinstance(source, str):
            raise DataFileError("文章标题或来源正文格式损坏，原文件已保留。")
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise DataFileError("文章来源正文超过读取限制，原文件已保留。")
        return article

    @staticmethod
    def _sha256_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _version_created_at(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            timestamp = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return timestamp if timestamp > 0 else None

    @staticmethod
    def _version_source_revision(item: Mapping[str, Any]) -> int | None:
        value = item.get("source_revision")
        if isinstance(value, bool):
            return None
        try:
            revision = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return revision if revision > 0 else None

    @staticmethod
    def _new_version_history() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "streams": {kind: [] for kind in ARTICLE_VERSION_KINDS},
            "active_body": {"source": None, "layout": None},
        }

    @staticmethod
    def _version_layout_snapshot(variants: Mapping[str, Any]) -> list[dict[str, Any]]:
        layouts: list[dict[str, Any]] = []
        for theme_id, raw in variants.items():
            if not isinstance(raw, Mapping):
                continue
            digest = str(raw.get("html_sha256") or "")
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                continue
            layouts.append({
                "theme_id": str(theme_id),
                "html_sha256": digest,
                "path": str(raw.get("path") or ""),
                "source_sha256": str(raw.get("source_sha256") or ""),
                "catalog_fingerprint": str(raw.get("catalog_fingerprint") or ""),
                "result_id": str(raw.get("result_id") or "") or None,
                "result_url": str(raw.get("result_url") or "") or None,
                "result_kind": str(raw.get("result_kind") or "") or None,
                "result_mime": str(raw.get("result_mime") or "") or None,
                "embedded_media_ids": [str(item) for item in raw.get("embedded_media_ids", [])
                                       if isinstance(item, str)]
                    if isinstance(raw.get("embedded_media_ids"), list) else [],
                "generated_at": StudioArticleStore._version_created_at(raw.get("generated_at")),
            })
        return layouts

    def _legacy_version_history(self, article: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
        """Project provable legacy article state into stable, read-only history metadata."""
        history = self._new_version_history()
        streams = history["streams"]

        raw_titles = article.get("title_variants", {})
        if not isinstance(raw_titles, Mapping):
            raise DataFileError("文章标题历史记录损坏，原文件已保留。")
        title_items = [(str(key), value, index) for index, (key, value) in enumerate(raw_titles.items())]
        title_items.sort(key=lambda pair: (
            self._version_created_at(pair[1].get("created_at")) is None if isinstance(pair[1], Mapping) else True,
            self._version_created_at(pair[1].get("created_at")) or 0 if isinstance(pair[1], Mapping) else 0,
            pair[2],
        ))
        current_title = str(article.get("title") or "")
        current_source = str(article.get("source_markdown") or "")
        current_source_hash = article_source_sha256(current_title, current_source)
        represented_current_title = False
        for variant_id, raw, _index in title_items:
            if not TEMPLATE_ID_PATTERN.fullmatch(variant_id) or not isinstance(raw, Mapping):
                raise DataFileError("文章标题版本 ID 或内容损坏，原文件已保留。")
            title = raw.get("title")
            digest = raw.get("source_sha256")
            if not isinstance(title, str) or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise DataFileError("文章标题版本指纹损坏，原文件已保留。")
            if title == current_title and digest == current_source_hash:
                represented_current_title = True
            streams["title"].append({
                "id": "",
                "number": 0,
                "created_at": self._version_created_at(raw.get("created_at")),
                "source_revision": self._version_source_revision(raw),
                "origin": "legacy",
                "snapshot": {
                    "title": title,
                    "title_variant_id": variant_id,
                    "source_sha256": digest,
                },
            })
        if current_title and not represented_current_title:
            selected_id = article.get("selected_title_variant_id")
            streams["title"].append({
                "id": "",
                "number": 0,
                "created_at": None,
                "source_revision": None,
                "origin": "legacy",
                "snapshot": {
                    "title": current_title,
                    "title_variant_id": str(selected_id) if selected_id else None,
                    "source_sha256": current_source_hash,
                },
            })

        raw_covers = article.get("cover_variants", [])
        if not isinstance(raw_covers, list):
            raise DataFileError("封面历史记录损坏，原文件已保留。")
        cover_items = list(enumerate(raw_covers))
        cover_items.sort(key=lambda pair: (
            self._version_created_at(pair[1].get("created_at")) is None if isinstance(pair[1], Mapping) else True,
            self._version_created_at(pair[1].get("created_at")) or 0 if isinstance(pair[1], Mapping) else 0,
            pair[0],
        ))
        for _index, raw in cover_items:
            if not isinstance(raw, Mapping):
                raise DataFileError("封面版本内容损坏，原文件已保留。")
            variant_id = str(raw.get("id") or "")
            asset_id = str(raw.get("asset_id") or "")
            result_id = str(raw.get("result_id") or "")
            source_hash = str(raw.get("source_sha256") or "")
            if (not TEMPLATE_ID_PATTERN.fullmatch(variant_id)
                    or bool(asset_id) == bool(result_id)
                    or not re.fullmatch(r"[a-f0-9]{64}", source_hash)):
                raise DataFileError("封面版本 ID、共享引用或来源指纹损坏，原文件已保留。")
            streams["cover"].append({
                "id": "",
                "number": 0,
                "created_at": self._version_created_at(raw.get("created_at")),
                "source_revision": self._version_source_revision(raw),
                "origin": "legacy",
                "snapshot": {
                    "cover_variant_id": variant_id,
                    "asset_id": asset_id or None,
                    "result_id": result_id or None,
                    "source_sha256": source_hash,
                },
            })

        raw_variants = article.get("variants", {})
        if not isinstance(raw_variants, Mapping):
            raise DataFileError("文章主题版本索引损坏，原文件已保留。")
        has_source = "source_markdown" in article and isinstance(article.get("source_markdown"), str)
        source = current_source if has_source else ""
        layouts = self._version_layout_snapshot(raw_variants)
        if has_source and source or layouts:
            streams["body"].append({
                "id": "",
                "number": 0,
                "created_at": None,
                "source_revision": None,
                "origin": "legacy",
                "snapshot": {
                    "title_at_save": current_title,
                    "source_markdown": source if has_source else None,
                    "source_markdown_available": has_source,
                    "source_markdown_sha256": self._sha256_text(source) if has_source else None,
                    "source_sha256_at_save": str(article.get("source_sha256") or current_source_hash)
                        if has_source else None,
                    "layouts": layouts,
                },
            })

        for kind in ARTICLE_VERSION_KINDS:
            for index, entry in enumerate(streams[kind], start=1):
                entry["id"] = f"{kind}_v{index}"
                entry["number"] = index
        return history

    def _version_history(self, article: dict[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
        history = article.get("version_history")
        if history is None:
            history = self._legacy_version_history(article, record)
        if (not isinstance(history, dict) or history.get("schema_version") != 1
                or not isinstance(history.get("streams"), dict)):
            raise DataFileError("文章版本历史结构损坏，原文件已保留。")
        streams = history["streams"]
        if set(streams) != set(ARTICLE_VERSION_KINDS):
            raise DataFileError("文章版本历史分类损坏，原文件已保留。")
        for kind in ARTICLE_VERSION_KINDS:
            entries = streams.get(kind)
            if not isinstance(entries, list):
                raise DataFileError("文章版本历史条目损坏，原文件已保留。")
            for index, entry in enumerate(entries, start=1):
                if (not isinstance(entry, dict) or entry.get("id") != f"{kind}_v{index}"
                        or entry.get("number") != index or not isinstance(entry.get("snapshot"), dict)):
                    raise DataFileError("文章版本历史条目身份损坏，原文件已保留。")
        active = history.get("active_body")
        if not isinstance(active, dict):
            active = {}
        source_id, layout_id = self._derive_active_body_channel_ids(history, article)
        body_entries = {str(entry["id"]): entry["snapshot"] for entry in streams["body"]}
        requested_source = active.get("source")
        requested_layout = active.get("layout")
        if (not isinstance(requested_source, str)
                or requested_source not in body_entries
                or not self._body_source_available(body_entries[requested_source])
                or body_entries[requested_source].get("source_markdown") != article.get("source_markdown")):
            requested_source = source_id
        if (not isinstance(requested_layout, str)
                or requested_layout not in body_entries
                or not self._body_layouts_match_current(body_entries[requested_layout], article)):
            requested_layout = layout_id
        history["active_body"] = {"source": requested_source, "layout": requested_layout}
        return history

    @staticmethod
    def _append_version(
        history: dict[str, Any], kind: str, snapshot: Mapping[str, Any], *,
        source_revision: int, origin: str, created_at: int, reuse_matching: bool = False,
    ) -> dict[str, Any]:
        streams = history["streams"]
        entries = streams[kind]
        frozen = copy.deepcopy(dict(snapshot))
        if kind == "title":
            normalized_title = str(frozen.get("title") or "").strip()
            if normalized_title:
                for entry in entries:
                    prior = entry.get("snapshot")
                    if (isinstance(prior, Mapping)
                            and str(prior.get("title") or "").strip() == normalized_title):
                        # A title is its own version identity. Keep the first
                        # immutable source fingerprint and stable version ID.
                        return entry
        if reuse_matching:
            for entry in entries:
                prior = entry.get("snapshot")
                if (prior == frozen
                        or (kind == "body" and isinstance(prior, Mapping)
                            and StudioArticleStore._body_snapshot_identity(prior)
                            == StudioArticleStore._body_snapshot_identity(frozen))):
                    return entry
        number = len(entries) + 1
        entry = {
            "id": f"{kind}_v{number}",
            "number": number,
            "created_at": created_at,
            "source_revision": source_revision,
            "origin": origin,
            "snapshot": frozen,
        }
        entries.append(entry)
        return entry

    @staticmethod
    def _body_snapshot_identity(snapshot: Mapping[str, Any]) -> tuple[Any, ...]:
        layouts = snapshot.get("layouts")
        # A visible body version represents HTML bytes only. Source text,
        # title, catalog, theme and managed-result provenance stay in the
        # immutable snapshot but do not create another version of the same HTML.
        layout_identity = tuple(sorted({
            str(item.get("html_sha256") or "")
            for item in layouts if isinstance(item, Mapping)
            and re.fullmatch(r"[a-f0-9]{64}", str(item.get("html_sha256") or ""))
        })) if isinstance(layouts, list) else ()
        return (layout_identity,)

    @classmethod
    def _visible_body_entries(cls, history: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Project immutable event snapshots into one visible entry per HTML hash."""
        visible: list[dict[str, Any]] = []
        seen_html: set[str] = set()
        for raw_entry in history["streams"]["body"]:
            snapshot = raw_entry.get("snapshot")
            layouts = snapshot.get("layouts") if isinstance(snapshot, Mapping) else None
            if not isinstance(layouts, list):
                continue
            novel_layouts: list[dict[str, Any]] = []
            event_html: set[str] = set()
            for raw_layout in layouts:
                if not isinstance(raw_layout, Mapping):
                    continue
                theme_id = str(raw_layout.get("theme_id") or "")
                digest = str(raw_layout.get("html_sha256") or "")
                if (not TEMPLATE_ID_PATTERN.fullmatch(theme_id)
                        or not re.fullmatch(r"[a-f0-9]{64}", digest)
                        or digest in seen_html or digest in event_html):
                    continue
                event_html.add(digest)
                novel_layouts.append(copy.deepcopy(dict(raw_layout)))
            if not novel_layouts:
                continue

            raw_id = str(raw_entry["id"])
            for raw_layout in novel_layouts:
                display_id = (raw_id if len(novel_layouts) == 1 else
                              f"{raw_id}__{raw_layout['theme_id']}")
                entry = copy.deepcopy(raw_entry)
                entry["id"] = display_id
                entry["number"] = len(visible) + 1
                entry["_raw_id"] = raw_id
                entry["_layout_digest"] = str(raw_layout["html_sha256"])
                entry["_html_only"] = True
                entry["snapshot"]["layouts"] = [raw_layout]
                visible.append(entry)
            seen_html.update(event_html)
        return visible

    @classmethod
    def _visible_body_entry(cls, history: Mapping[str, Any], version_id: str) -> dict[str, Any] | None:
        return next((entry for entry in cls._visible_body_entries(history)
                     if entry["id"] == version_id), None)

    @classmethod
    def _visible_body_active_id(cls, history: Mapping[str, Any], article: Mapping[str, Any]) -> str | None:
        selected_theme = str(article.get("selected_theme_id") or "")
        variants = article.get("variants", {})
        current = variants.get(selected_theme) if selected_theme and isinstance(variants, Mapping) else None
        digest = str(current.get("html_sha256") or "") if isinstance(current, Mapping) else ""
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            return None
        return next((entry["id"] for entry in cls._visible_body_entries(history)
                     if entry.get("_layout_digest") == digest), None)

    def _body_raw_entry(self, history: Mapping[str, Any], version_id: str) -> dict[str, Any]:
        # Derived IDs are valid only when they exactly match a visible
        # projection. The raw compatibility API accepts only its canonical ID,
        # otherwise an unknown suffix could silently resolve to a different
        # layout snapshot.
        match = re.fullmatch(r"body_v[1-9][0-9]*", version_id)
        if not match:
            raise HTTPException(status_code=404, detail="文章历史版本不存在")
        return self._version_entry(history, "body", version_id)

    @staticmethod
    def _title_snapshot(title: str, source: str, variant_id: str | None) -> dict[str, Any]:
        return {
            "title": title,
            "title_variant_id": variant_id,
            "source_sha256": article_source_sha256(title, source),
        }

    @staticmethod
    def _cover_snapshot(item: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "cover_variant_id": str(item.get("id") or ""),
            "asset_id": str(item.get("asset_id") or "") or None,
            "result_id": str(item.get("result_id") or "") or None,
            "source_sha256": str(item.get("source_sha256") or ""),
        }

    def _body_snapshot(self, article: Mapping[str, Any]) -> dict[str, Any]:
        title = str(article.get("title") or "")
        has_source = "source_markdown" in article and isinstance(article.get("source_markdown"), str)
        source = str(article.get("source_markdown") or "") if has_source else ""
        variants = article.get("variants", {})
        if not isinstance(variants, Mapping):
            raise DataFileError("文章主题版本索引损坏，原文件已保留。")
        return {
            "title_at_save": title,
            "source_markdown": source if has_source else None,
            "source_markdown_available": has_source,
            "source_markdown_sha256": self._sha256_text(source) if has_source else None,
            "source_sha256_at_save": str(article.get("source_sha256") or article_source_sha256(title, source))
                if has_source else None,
            "layouts": self._version_layout_snapshot(variants),
        }

    @staticmethod
    def _version_snapshot_matches_current(kind: str, snapshot: Mapping[str, Any], article: Mapping[str, Any]) -> bool:
        if kind == "title":
            title = str(article.get("title") or "").strip()
            return str(snapshot.get("title") or "").strip() == title
        if kind == "cover":
            return bool(snapshot.get("cover_variant_id")) and snapshot.get("cover_variant_id") == article.get("selected_cover_variant_id")
        if kind == "body":
            if (not snapshot.get("source_markdown_available")
                    or not isinstance(snapshot.get("source_markdown"), str)
                    or snapshot.get("source_markdown") != article.get("source_markdown")):
                return False
            variants = article.get("variants", {})
            if not isinstance(variants, Mapping):
                return False
            current_layouts = StudioArticleStore._version_layout_snapshot(variants)
            historical_layouts = snapshot.get("layouts", [])
            if not isinstance(historical_layouts, list):
                return False
            def layout_signature(items: list[Mapping[str, Any]]) -> list[tuple[str, str, str, str]]:
                return sorted((
                    str(item.get("theme_id") or ""), str(item.get("html_sha256") or ""),
                    str(item.get("source_sha256") or ""), str(item.get("catalog_fingerprint") or ""),
                ) for item in items if isinstance(item, Mapping))
            return layout_signature(current_layouts) == layout_signature(historical_layouts)
        return False

    @classmethod
    def _body_source_available(cls, snapshot: Mapping[str, Any]) -> bool:
        source = snapshot.get("source_markdown")
        return (
            bool(snapshot.get("source_markdown_available"))
            and isinstance(source, str)
            and cls._sha256_text(source) == snapshot.get("source_markdown_sha256")
        )

    @staticmethod
    def _body_layouts_available(snapshot: Mapping[str, Any]) -> bool:
        layouts = snapshot.get("layouts")
        return bool(
            isinstance(layouts, list) and layouts
            and all(
                isinstance(item, Mapping)
                and TEMPLATE_ID_PATTERN.fullmatch(str(item.get("theme_id") or ""))
                and re.fullmatch(r"[a-f0-9]{64}", str(item.get("html_sha256") or ""))
                for item in layouts
            )
        )

    @staticmethod
    def _body_layouts_match_current(snapshot: Mapping[str, Any], article: Mapping[str, Any]) -> bool:
        historical = snapshot.get("layouts")
        current = article.get("variants", {})
        if not isinstance(historical, list) or not historical or not isinstance(current, Mapping):
            return False
        current_by_theme = {
            str(item.get("theme_id") or ""): str(item.get("html_sha256") or "")
            for item in StudioArticleStore._version_layout_snapshot(current)
        }
        seen: set[str] = set()
        for item in historical:
            if not isinstance(item, Mapping):
                return False
            theme_id = str(item.get("theme_id") or "")
            digest = str(item.get("html_sha256") or "")
            if (not TEMPLATE_ID_PATTERN.fullmatch(theme_id) or theme_id in seen
                    or not re.fullmatch(r"[a-f0-9]{64}", digest)):
                return False
            seen.add(theme_id)
            if current_by_theme.get(theme_id) != digest:
                return False
        return True

    @classmethod
    def _derive_active_body_channel_ids(cls, history: Mapping[str, Any], article: Mapping[str, Any]) -> tuple[str | None, str | None]:
        source_id: str | None = None
        layout_id: str | None = None
        for entry in reversed(history["streams"]["body"]):
            snapshot = entry["snapshot"]
            if source_id is None and cls._body_source_available(snapshot):
                if snapshot.get("source_markdown") == article.get("source_markdown"):
                    source_id = str(entry["id"])
            if layout_id is None and cls._body_layouts_match_current(snapshot, article):
                layout_id = str(entry["id"])
            if source_id is not None and layout_id is not None:
                break
        return source_id, layout_id

    @classmethod
    def _active_body_channel_ids(cls, history: Mapping[str, Any], article: Mapping[str, Any]) -> tuple[str | None, str | None]:
        active = history.get("active_body")
        if isinstance(active, Mapping):
            entries = {str(entry["id"]): entry["snapshot"] for entry in history["streams"]["body"]}
            source_id = active.get("source")
            layout_id = active.get("layout")
            if (isinstance(source_id, str) and source_id in entries
                    and cls._body_source_available(entries[source_id])
                    and entries[source_id].get("source_markdown") == article.get("source_markdown")):
                valid_source_id = source_id
            else:
                valid_source_id = None
            if (isinstance(layout_id, str) and layout_id in entries
                    and cls._body_layouts_match_current(entries[layout_id], article)):
                valid_layout_id = layout_id
            else:
                valid_layout_id = None
            derived_source_id, derived_layout_id = cls._derive_active_body_channel_ids(history, article)
            return valid_source_id or derived_source_id, valid_layout_id or derived_layout_id
        return cls._derive_active_body_channel_ids(history, article)

    @classmethod
    def _active_version_id(cls, history: Mapping[str, Any], kind: str, article: Mapping[str, Any]) -> str | None:
        entries = history["streams"][kind]
        if kind == "title":
            selected_id = str(article.get("selected_title_variant_id") or "")
            if selected_id:
                for entry in reversed(entries):
                    snapshot = entry.get("snapshot")
                    if (isinstance(snapshot, Mapping)
                            and str(snapshot.get("title_variant_id") or "") == selected_id
                            and cls._version_snapshot_matches_current(kind, snapshot, article)):
                        return str(entry["id"])
        for entry in reversed(entries):
            if cls._version_snapshot_matches_current(kind, entry["snapshot"], article):
                return str(entry["id"])
        return None

    @staticmethod
    def _title_manifest_entries(entries: list[dict[str, Any]], active_id: str | None) -> list[dict[str, Any]]:
        """Deduplicate legacy title snapshots for reads without changing storage."""
        winners: dict[tuple[str, str], dict[str, Any]] = {}
        entry_keys: dict[int, tuple[str, str]] = {}
        for entry in entries:
            snapshot = entry.get("snapshot")
            raw_title = snapshot.get("title") if isinstance(snapshot, Mapping) else None
            normalized = str(raw_title or "").strip()
            key = ("title", normalized) if normalized else ("id", str(entry.get("id") or ""))
            entry_keys[id(entry)] = key
            previous = winners.get(key)
            if previous is None or (entry.get("id") == active_id and previous.get("id") != active_id):
                winners[key] = entry
        return [entry for entry in entries if winners.get(entry_keys[id(entry)]) is entry]

    def _layout_manifest_excerpt(self, raw: Mapping[str, Any]) -> tuple[bool, str]:
        theme_id = str(raw.get("theme_id") or "")
        digest = str(raw.get("html_sha256") or "")
        if (not TEMPLATE_ID_PATTERN.fullmatch(theme_id)
                or not re.fullmatch(r"[a-f0-9]{64}", digest)):
            return False, ""
        stored_path = str(raw.get("path") or (ARTICLE_VARIANT_DIR / f"{digest}.html"))
        relative = Path(stored_path)
        if relative.is_absolute() or ".." in relative.parts:
            return False, ""
        try:
            path = (self.root / relative).resolve()
            text_root = (self.root / "assets" / "output" / "text").resolve()
            path.relative_to(text_root)
            stat = path.stat()
        except (OSError, RuntimeError, ValueError):
            return False, ""
        if not path.is_file() or stat.st_size > MAX_HTML_BYTES:
            return False, ""
        return _cached_article_layout_excerpt(
            str(self.root.resolve()), stored_path, digest, stat.st_mtime_ns, stat.st_size, stat.st_ino,
        )

    def _body_manifest_preview(
        self, snapshot: Mapping[str, Any], preferred_theme_id: str | None,
    ) -> dict[str, Any]:
        layouts = snapshot.get("layouts")
        readable: list[tuple[str, str]] = []
        if isinstance(layouts, list):
            ordered = [item for item in layouts if isinstance(item, Mapping)]
            if preferred_theme_id:
                ordered.sort(key=lambda item: str(item.get("theme_id") or "") != preferred_theme_id)
            for item in ordered:
                available, excerpt = self._layout_manifest_excerpt(item)
                if available:
                    readable.append((str(item.get("theme_id") or ""), excerpt))
                    if str(item.get("theme_id") or "") == preferred_theme_id:
                        break
        if readable:
            preview_theme_id, layout_excerpt = readable[0]
        else:
            preview_theme_id, layout_excerpt = None, ""
        return {
            "layout_excerpt": layout_excerpt,
            "preview_theme_id": preview_theme_id,
        }

    def _version_list(self, project_id: str, record: Mapping[str, Any], article: dict[str, Any]) -> dict[str, Any]:
        history = self._version_history(article, record)
        revision = max(1, int(record.get("revision") or 1))
        streams = []
        for kind in ARTICLE_VERSION_KINDS:
            if kind == "body":
                entries = self._visible_body_entries(history)
                active_id = self._visible_body_active_id(history, article)
            else:
                entries = history["streams"][kind]
                active_id = self._active_version_id(history, kind, article)
            if kind == "title":
                entries = self._title_manifest_entries(entries, active_id)
            versions = []
            for entry in entries:
                snapshot = entry["snapshot"]
                label = str(snapshot.get("title") or "") if kind == "title" else f"{kind.capitalize()} v{entry['number']}"
                source_sha = (snapshot.get("source_sha256") if kind in {"title", "cover"}
                              else None)
                version = {
                    "id": entry["id"],
                    "number": entry["number"],
                    "created_at": entry.get("created_at"),
                    "source_revision": entry.get("source_revision"),
                    "origin": str(entry.get("origin") or "legacy"),
                    "label": label,
                    "source_sha256": source_sha if isinstance(source_sha, str) else None,
                    "active": entry["id"] == active_id,
                    "availability": None,
                }
                if kind == "body":
                    version.update({
                        "layout_active": entry["id"] == active_id,
                        "layout_available": self._body_layouts_available(snapshot),
                    })
                    version.update(self._body_manifest_preview(snapshot, article.get("selected_theme_id")))
                elif kind == "cover":
                    try:
                        resolved = self._resolve_cover(
                            str(snapshot.get("asset_id") or ""), str(snapshot.get("result_id") or ""),
                        )
                        public_media = {
                            "url": resolved["url"], "name": resolved["name"],
                            "mime": resolved["mime"], "available": True,
                        }
                    except HTTPException:
                        public_media = {"url": "", "name": "", "mime": "", "available": False}
                    version["public_media"] = public_media
                versions.append(version)
            streams.append({
                "kind": kind,
                "title": {"title": "标题", "cover": "封面", "body": "正文"}[kind],
                "versions": versions,
            })
        return {"project_id": project_id, "revision": revision, "streams": streams}

    def _version_entry(self, history: Mapping[str, Any], kind: str, version_id: str) -> dict[str, Any]:
        if kind not in ARTICLE_VERSION_KINDS:
            raise HTTPException(status_code=404, detail="文章历史分类不存在")
        if not re.fullmatch(rf"{kind}_v[1-9][0-9]*", version_id):
            raise HTTPException(status_code=404, detail="文章历史版本不存在")
        number = int(version_id.rsplit("_v", 1)[1])
        entries = history["streams"][kind]
        if number > len(entries) or entries[number - 1].get("id") != version_id:
            raise HTTPException(status_code=404, detail="文章历史版本不存在")
        return entries[number - 1]

    def _version_detail(
        self, project_id: str, record: Mapping[str, Any], article: dict[str, Any], kind: str,
        entry: Mapping[str, Any], catalog: Mapping[str, Any],
    ) -> dict[str, Any]:
        snapshot = entry["snapshot"]
        html_only = kind == "body" and bool(entry.get("_html_only"))
        current_hash = article_source_sha256(str(article.get("title") or ""), str(article.get("source_markdown") or ""))
        public_snapshot: dict[str, Any]
        source_available_for_response: bool | None = None
        layout_available_for_response: bool | None = None
        if kind == "title":
            public_snapshot = {
                "title": str(snapshot.get("title") or ""),
                "title_variant_id": snapshot.get("title_variant_id"),
                "source_sha256": snapshot.get("source_sha256"),
            }
        elif kind == "cover":
            asset_id = str(snapshot.get("asset_id") or "")
            result_id = str(snapshot.get("result_id") or "")
            try:
                resolved = self._resolve_cover(asset_id, result_id)
                public_media = {"url": resolved["url"], "name": resolved["name"], "mime": resolved["mime"], "available": True}
            except HTTPException:
                public_media = {"url": "", "name": "", "mime": "", "available": False}
            public_snapshot = {
                "cover_variant_id": snapshot.get("cover_variant_id"),
                "asset_id": asset_id or None,
                "result_id": result_id or None,
                "source_sha256": snapshot.get("source_sha256"),
                "public_media": public_media,
            }
        else:
            # Public HTML versions are projections of immutable snapshots. Their
            # visibility and readability depend on the guarded HTML object, not
            # on the integrity of the private Markdown snapshot that happened to
            # be recorded in the same historical event. Raw compatibility reads
            # still validate and expose their Markdown source as before.
            source_available = False
            source_markdown = None
            if not html_only:
                source_available = bool(snapshot.get("source_markdown_available"))
                source_markdown = snapshot.get("source_markdown")
                if source_available and not isinstance(source_markdown, str):
                    raise DataFileError("文章历史正文快照损坏，原文件已保留。")
                if source_available and self._sha256_text(source_markdown) != snapshot.get("source_markdown_sha256"):
                    raise DataFileError("文章历史正文快照指纹损坏，原文件已保留。")
            layouts = snapshot.get("layouts", [])
            if not isinstance(layouts, list):
                raise DataFileError("文章历史排版索引损坏，原文件已保留。")
            public_layouts = []
            for raw in layouts:
                if not isinstance(raw, Mapping):
                    continue
                theme_id = str(raw.get("theme_id") or "")
                digest = str(raw.get("html_sha256") or "")
                source_sha = str(raw.get("source_sha256") or "")
                catalog_fingerprint = str(raw.get("catalog_fingerprint") or "")
                item: dict[str, Any] = {
                    "theme_id": theme_id,
                    "html_sha256": digest,
                    "source_sha256": source_sha,
                    "catalog_fingerprint": catalog_fingerprint,
                    "result_id": str(raw.get("result_id") or "") or None,
                    "available": False,
                    "valid_for_current": False,
                    "source_matches": source_sha == current_hash,
                    "catalog_matches": catalog_fingerprint == str(catalog["catalog_fingerprint"]),
                }
                try:
                    if not TEMPLATE_ID_PATTERN.fullmatch(theme_id) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                        raise DataFileError("主题排版身份或哈希无效")
                    stored_path = str(raw.get("path") or (ARTICLE_VARIANT_DIR / f"{digest}.html"))
                    html_path = self._article_html_path(stored_path, digest)
                    body_html = html_path.read_text(encoding="utf-8")
                    validate_article_html(body_html)
                    item.update({
                        "available": True,
                        # This remains a provenance-match indicator for legacy
                        # clients. Availability is the HTML read/preview gate;
                        # source/catalog mismatch must not suppress saved HTML.
                        "valid_for_current": item["source_matches"] and item["catalog_matches"],
                        "body_html": body_html,
                    })
                except (OSError, UnicodeError, ArticleValidationError, DataFileError) as exc:
                    item["error"] = f"历史排版不可用：{exc}"
                public_layouts.append(item)
            source_available_for_response = source_available
            layout_available_for_response = bool(public_layouts) and all(item["available"] for item in public_layouts)
            public_snapshot = {
                "layout_available": layout_available_for_response,
                "layouts": public_layouts,
            }
            if not html_only:
                public_snapshot.update({
                    "source_markdown_sha256": snapshot.get("source_markdown_sha256"),
                    "source_sha256_at_save": snapshot.get("source_sha256_at_save"),
                    "source_markdown_available": source_available,
                })
                if source_available:
                    public_snapshot["source_markdown"] = source_markdown
        history = self._version_history(article, record) if kind == "body" else None
        source_active_id = None
        visible_active_id = None
        if history is not None:
            visible_active_id = self._visible_body_active_id(history, article)
            if not html_only:
                source_active_id, _layout_active_id = self._active_body_channel_ids(history, article)
        entry_id = str(entry["id"])
        raw_entry_id = str(entry.get("_raw_id") or entry_id)
        is_body_active = entry_id == visible_active_id
        response = {
            "project_id": project_id,
            "current_revision": max(1, int(record.get("revision") or 1)),
            "kind": kind,
            "id": entry["id"],
            "number": entry["number"],
            "created_at": entry.get("created_at"),
            "source_revision": entry.get("source_revision"),
            "origin": str(entry.get("origin") or "legacy"),
            "active": is_body_active if kind == "body" else
                entry["id"] == self._active_version_id(self._version_history(article, record), kind, article),
            "snapshot": public_snapshot,
        }
        if kind == "body":
            response.update({
                "layout_active": is_body_active,
                "layout_available": bool(layout_available_for_response),
            })
            if not html_only:
                response.update({
                    "source_active": raw_entry_id == source_active_id,
                    "source_available": self._body_source_available(snapshot),
                })
        return response

    @staticmethod
    def _layouts_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
        return StudioArticleStore._version_layout_snapshot(left) == StudioArticleStore._version_layout_snapshot(right)

    @staticmethod
    def _restore_layout_index(snapshot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        layouts = snapshot.get("layouts", [])
        if not isinstance(layouts, list):
            raise DataFileError("文章历史排版索引损坏，原文件已保留。")
        restored: dict[str, dict[str, Any]] = {}
        for raw in layouts:
            if not isinstance(raw, Mapping):
                raise DataFileError("文章历史排版条目损坏，原文件已保留。")
            theme_id = str(raw.get("theme_id") or "")
            digest = str(raw.get("html_sha256") or "")
            if not TEMPLATE_ID_PATTERN.fullmatch(theme_id) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise DataFileError("文章历史排版身份或哈希损坏，原文件已保留。")
            path = str(raw.get("path") or (ARTICLE_VARIANT_DIR / f"{digest}.html"))
            restored[theme_id] = {
                "path": path,
                "html_sha256": digest,
                "source_sha256": str(raw.get("source_sha256") or ""),
                "catalog_fingerprint": str(raw.get("catalog_fingerprint") or ""),
                "result_id": str(raw.get("result_id") or "") or None,
                "result_url": str(raw.get("result_url") or "") or None,
                "result_kind": str(raw.get("result_kind") or "") or None,
                "result_mime": str(raw.get("result_mime") or "") or None,
                "embedded_media_ids": [str(item) for item in raw.get("embedded_media_ids", [])
                                       if isinstance(item, str)]
                    if isinstance(raw.get("embedded_media_ids"), list) else [],
                "generated_at": raw.get("generated_at") or 0,
            }
        return restored

    def _html_path(self, digest: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", str(digest or "")):
            raise DataFileError("排版版本哈希格式损坏，原文件已保留。")
        return self.root / ARTICLE_VARIANT_DIR / f"{digest}.html"

    @staticmethod
    def _title_variant_id(title: str, source_hash: str) -> str:
        digest = hashlib.sha256(f"{source_hash}\0{title}".encode("utf-8")).hexdigest()
        return f"title_{digest[:24]}"

    @staticmethod
    def _cover_variant_id(source_hash: str, reference_kind: str, reference_id: str) -> str:
        digest = hashlib.sha256(f"{source_hash}\0{reference_kind}\0{reference_id}".encode("utf-8")).hexdigest()
        return f"cover_{digest[:24]}"

    @staticmethod
    def _media_variant_id(source_hash: str, reference_kind: str, reference_id: str) -> str:
        digest = hashlib.sha256(f"{source_hash}\0{reference_kind}\0{reference_id}".encode("utf-8")).hexdigest()
        return f"media_{digest[:24]}"

    def _resolve_shared_media(self, asset_id: str, result_id: str) -> dict[str, Any]:
        if bool(asset_id) == bool(result_id):
            raise HTTPException(status_code=400, detail="文章媒体版本必须且只能引用一个共享素材或生成结果 ID")
        if self.resolve_media_reference is None:
            raise HTTPException(status_code=503, detail="共享素材读取服务尚未接入，不能保存媒体引用")
        try:
            resolved = self.resolve_media_reference(asset_id, result_id)
        except (OSError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail="文章媒体引用无法验证") from exc
        if not isinstance(resolved, Mapping):
            raise HTTPException(status_code=400, detail="文章媒体不存在或文件已缺失")
        url = str(resolved.get("url") or "")
        name = str(resolved.get("name") or "")
        mime = str(resolved.get("mime") or "")
        kind = str(resolved.get("kind") or "").strip().lower()
        if (not url.startswith(("/api/materials/", "/api/results/")) or not name
                or kind not in {"image", "video", "audio", "text"} or not mime):
            raise HTTPException(status_code=400, detail="文章媒体引用缺少稳定地址、名称或已知媒体类型")
        return {"url": url, "name": name, "mime": mime, "kind": kind}

    def _resolve_cover(self, asset_id: str, result_id: str) -> dict[str, Any]:
        resolved = self._resolve_shared_media(asset_id, result_id)
        if resolved["kind"] != "image" or not resolved["mime"].startswith("image/"):
            raise HTTPException(status_code=400, detail="封面只能引用图片素材或图片生成结果")
        return resolved

    def _project_title_variants(self, raw: Any, source: str) -> dict[str, dict[str, Any]]:
        if not isinstance(raw, dict):
            raise DataFileError("文章标题历史记录损坏，原文件已保留。")
        projected = {}
        for variant_id, item in raw.items():
            if not TEMPLATE_ID_PATTERN.fullmatch(str(variant_id)) or not isinstance(item, dict):
                raise DataFileError("文章标题版本 ID 或内容损坏，原文件已保留。")
            title = item.get("title")
            source_hash = item.get("source_sha256")
            if not isinstance(title, str) or not isinstance(source_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", source_hash):
                raise DataFileError("文章标题版本指纹损坏，原文件已保留。")
            projected[str(variant_id)] = {
                "title": title,
                "source_sha256": source_hash,
                "created_at": int(item.get("created_at") or 0),
                "valid": True,
                "source_matches": source_hash == article_source_sha256(title, source),
            }
        return projected

    def _project_cover_variants(self, raw: Any, source_hash: str) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            raise DataFileError("封面历史记录损坏，原文件已保留。")
        projected = []
        for item in raw:
            if not isinstance(item, dict):
                raise DataFileError("封面版本内容损坏，原文件已保留。")
            variant_id = str(item.get("id") or "")
            asset_id = str(item.get("asset_id") or "")
            result_id = str(item.get("result_id") or "")
            stored_hash = str(item.get("source_sha256") or "")
            if not TEMPLATE_ID_PATTERN.fullmatch(variant_id) or not re.fullmatch(r"[a-f0-9]{64}", stored_hash):
                raise DataFileError("封面版本 ID 或指纹损坏，原文件已保留。")
            try:
                resolved = self._resolve_cover(asset_id, result_id)
                available = True
                error = ""
            except HTTPException as exc:
                resolved = {"url": "", "name": "", "mime": ""}
                available = False
                error = str(exc.detail)
            projected.append({
                "id": variant_id,
                "asset_id": asset_id or None,
                "result_id": result_id or None,
                "source_sha256": stored_hash,
                "created_at": int(item.get("created_at") or 0),
                "valid": available,
                "source_matches": stored_hash == source_hash,
                "error": error,
                **{key: resolved[key] for key in ("url", "name", "mime")},
            })
        return projected

    def _project_media_refs(self, raw: Any, source_hash: str) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            raise DataFileError("文章媒体记录损坏，原文件已保留。")
        projected = []
        for item in raw:
            if not isinstance(item, dict):
                raise DataFileError("文章媒体条目损坏，原文件已保留。")
            variant_id = str(item.get("id") or "")
            asset_id = str(item.get("asset_id") or "")
            result_id = str(item.get("result_id") or "")
            stored_hash = str(item.get("source_sha256") or "")
            if not TEMPLATE_ID_PATTERN.fullmatch(variant_id) or not re.fullmatch(r"[a-f0-9]{64}", stored_hash):
                raise DataFileError("文章媒体 ID 或来源指纹损坏，原文件已保留。")
            try:
                resolved = self._resolve_shared_media(asset_id, result_id)
                available = True
                error = ""
            except HTTPException as exc:
                resolved = {"url": "", "name": "", "mime": "", "kind": ""}
                available = False
                error = str(exc.detail)
            projected.append({
                "id": variant_id,
                "asset_id": asset_id or None,
                "result_id": result_id or None,
                "source_sha256": stored_hash,
                "created_at": int(item.get("created_at") or 0),
                "valid": available,
                "source_matches": stored_hash == source_hash,
                "error": error,
                **{key: resolved[key] for key in ("kind", "url", "name", "mime")},
            })
        return projected

    def _write_html(self, body_html: str, digest: str) -> str:
        target = self._html_path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise DataFileError("同哈希排版文件内容不匹配，已拒绝覆盖。")
        else:
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, prefix=f".{digest}.", suffix=".tmp", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(body_html.encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            except OSError as exc:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
                raise DataFileError("无法保存排版版本；文章记录未更新。") from exc
        return target.relative_to(self.root).as_posix()

    def _write_embedded_image(self, content: bytes, digest: str, extension: str) -> Path:
        target = self.root / "assets" / "output" / "image" / "articles" / f"{digest}{extension}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise DataFileError("同哈希公众号图片文件内容不匹配，已拒绝覆盖。")
            return target
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, prefix=f".{digest}.", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except OSError as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise DataFileError("无法保存公众号内嵌图片的共享副本。") from exc
        return target

    def _register_embedded_images(self, body_html: str, source_hash: str) -> tuple[list[str], list[dict[str, Any]]]:
        collector = _ArticleImageSourceCollector()
        collector.feed(body_html)
        collector.close()
        extension_for = {"png": ".png", "jpeg": ".jpg", "webp": ".webp", "gif": ".gif", "avif": ".avif"}
        registered_ids: list[str] = []
        media_refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source in collector.sources:
            match = DATA_IMAGE_PATTERN.fullmatch(source.strip())
            if not match:
                # 外链由 Agent 先通过共享上传/导入流程登记；服务端不抓取远端内容。
                continue
            content = base64.b64decode(match.group(2), validate=True)
            digest = hashlib.sha256(content).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            extension = extension_for[match.group(1).lower()]
            item = self._find_shared_media(digest, "image")
            if item is None:
                path = self._write_embedded_image(content, digest, extension)
                if self.register_managed_result is None:
                    raise HTTPException(status_code=503, detail="共享结果登记服务尚未接入，不能保存内嵌图片")
                try:
                    stored = self.register_managed_result(
                        path,
                        f"公众号内嵌图片-{digest[:12]}{extension}",
                        source_module="article",
                    )
                except Exception as exc:
                    raise DataFileError("公众号内嵌图片已写入，但共享素材库登记失败；文章记录未更新。") from exc
                if (not isinstance(stored, Mapping)
                        or not re.fullmatch(r"res_[a-f0-9]{24}", str(stored.get("id") or ""))
                        or str(stored.get("sha256") or "") != digest
                        or str(stored.get("kind") or "") != "image"
                        or not str(stored.get("mime") or "").startswith("image/")):
                    raise DataFileError("共享素材库返回的公众号图片身份、哈希或类型不匹配。")
                result_id = str(stored["id"])
                asset_id = ""
                registered_ids.append(result_id)
            else:
                result_id = str(item.get("result_id") or "")
                asset_id = str(item.get("asset_id") or "")
                registered_ids.append(asset_id or result_id)
            media_refs.append({
                "id": self._media_variant_id(source_hash, "asset" if asset_id else "result", asset_id or result_id),
                "asset_id": asset_id or None,
                "result_id": result_id or None,
                "source_sha256": source_hash,
                "created_at": int(time.time() * 1000),
            })
        return registered_ids, media_refs

    @staticmethod
    def _merge_internal_media_refs(existing: list[Any], additions: list[dict[str, Any]]) -> bool:
        known = {str(item.get("id") or "") for item in existing if isinstance(item, dict)}
        changed = False
        for item in additions:
            if item["id"] not in known:
                existing.append(item)
                known.add(item["id"])
                changed = True
        return changed

    def _register_html_result(self, digest: str, path: Path | None = None) -> dict[str, str]:
        """把已验证的 HTML 原文件登记到共享结果索引，不复制正文。"""
        path = path or self._html_path(digest)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise DataFileError("公众号排版文件缺失或哈希不匹配，不能登记到共享素材库。")
        if self.register_managed_result is None:
            raise HTTPException(status_code=503, detail="共享结果登记服务尚未接入，不能保存排版版本")
        try:
            item = self.register_managed_result(
                path,
                f"公众号排版-{digest[:12]}.html",
                source_module="article",
            )
        except Exception as exc:
            raise DataFileError("公众号排版已写入内容文件，但共享素材库登记失败；文章记录未更新。") from exc
        if not isinstance(item, Mapping):
            raise DataFileError("共享素材库未返回公众号排版结果记录。")
        result_id = str(item.get("id") or "")
        result_url = str(item.get("url") or "")
        if (not re.fullmatch(r"res_[a-f0-9]{24}", result_id)
                or result_url != f"/api/results/{quote(result_id, safe='')}"
                or str(item.get("sha256") or "") != digest
                or str(item.get("kind") or "") != "text"
                or not str(item.get("mime") or "").startswith("text/")):
            raise DataFileError("共享素材库返回的排版结果身份、哈希或文本类型不匹配。")
        return {"result_id": result_id, "result_url": result_url, "result_kind": "text",
                "result_mime": str(item.get("mime") or "text/html")}

    def _find_shared_media(self, digest: str, kind: str) -> dict[str, Any] | None:
        if self.find_shared_media_by_hash is None:
            return None
        try:
            item = self.find_shared_media_by_hash(digest, kind)
        except Exception as exc:
            raise DataFileError("共享素材索引不可读取，已阻止文章保存。") from exc
        if item is None:
            return None
        if not isinstance(item, Mapping) or str(item.get("sha256") or "") != digest or str(item.get("kind") or "") != kind:
            raise DataFileError("共享素材哈希查询返回了不匹配的记录。")
        asset_id = str(item.get("asset_id") or "")
        result_id = str(item.get("result_id") or "")
        if bool(asset_id) == bool(result_id):
            raise DataFileError("共享素材哈希查询没有返回唯一稳定 ID。")
        expected_prefix = "/api/materials/" if asset_id else "/api/results/"
        expected_id = asset_id or result_id
        if str(item.get("url") or "") != f"{expected_prefix}{quote(expected_id, safe='')}":
            raise DataFileError("共享素材哈希查询返回了不稳定地址。")
        if not str(item.get("name") or "") or not str(item.get("mime") or "").startswith(f"{kind}/"):
            raise DataFileError("共享素材哈希查询缺少名称或类型信息。")
        return dict(item)

    def _shared_html_variant(self, digest: str) -> tuple[str, dict[str, str]] | None:
        item = self._find_shared_media(digest, "text")
        if item is None:
            return None
        result_id = str(item.get("result_id") or "")
        result_path = Path(str(item.get("path") or "")).resolve()
        text_root = (self.root / "assets" / "output" / "text").resolve()
        try:
            result_path.relative_to(text_root)
        except ValueError as exc:
            raise DataFileError("已有公众号排版结果不在共享文本结果目录，已拒绝复用。") from exc
        if (not result_id or not result_path.is_file()
                or hashlib.sha256(result_path.read_bytes()).hexdigest() != digest):
            raise DataFileError("已有公众号排版结果缺失或哈希不匹配，已拒绝复用。")
        return result_path.relative_to(self.root).as_posix(), {
            "result_id": result_id,
            "result_url": str(item["url"]),
            "result_kind": "text",
            "result_mime": str(item["mime"]),
        }

    def _article_html_path(self, stored_path: str, digest: str) -> Path:
        relative = Path(stored_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise DataFileError("排版文件路径记录不合法")
        path = (self.root / relative).resolve()
        text_root = (self.root / "assets" / "output" / "text").resolve()
        try:
            path.relative_to(text_root)
        except ValueError as exc:
            raise DataFileError("排版文件不在共享文本结果目录，已拒绝读取。") from exc
        if (not path.is_file() or path.stat().st_size > MAX_HTML_BYTES
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise DataFileError("排版文件缺失、超过读取限制或哈希不匹配")
        return path

    def _backfill_html_result_refs(self, record: dict[str, Any]) -> bool:
        """为旧版已存在且完整的排版文件幂等补登记，不改变文章修订号。"""
        article = self._article_payload(record)
        variants = article.get("variants")
        if not isinstance(variants, dict):
            return False
        changed = False
        for raw in variants.values():
            if not isinstance(raw, dict):
                continue
            digest = str(raw.get("html_sha256") or "")
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                continue
            try:
                path = self._article_html_path(str(raw.get("path") or ""), digest)
                body_html = path.read_text(encoding="utf-8")
                validate_article_html(body_html)
                existing_shared = self._shared_html_variant(digest)
                if existing_shared:
                    shared_path, registered = existing_shared
                    if raw.get("path") != shared_path:
                        raw["path"] = shared_path
                        changed = True
                else:
                    registered = self._register_html_result(digest, path)
                embedded_ids, embedded_refs = self._register_embedded_images(
                    body_html, str(raw.get("source_sha256") or article.get("source_sha256") or "")
                )
                if embedded_ids and raw.get("embedded_media_ids") != embedded_ids:
                    raw["embedded_media_ids"] = embedded_ids
                    changed = True
                if any(raw.get(key) != value for key, value in registered.items()):
                    raw.update(registered)
                    changed = True
                media_refs = article.get("media_refs") if isinstance(article.get("media_refs"), list) else []
                if self._merge_internal_media_refs(media_refs, embedded_refs):
                    changed = True
                article["media_refs"] = media_refs
                raw.pop("_result_registration_error", None)
            except (OSError, UnicodeError, ArticleValidationError, DataFileError, HTTPException):
                # 旧正文仍可读取；索引不可写时不覆盖原文章记录，后续 GET 可重试。
                raw["_result_registration_error"] = True
                continue
        if changed:
            record["article"] = article
            self.project_store.write_article_record(record)
        return changed

    def _project_variant(
        self, theme_id: str, raw: Any, source_hash: str, theme_fingerprint: str,
        known_theme_ids: set[str],
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {
                "body_html": "", "source_sha256": "", "valid": False, "available": False,
                "source_matches": False, "catalog_matches": False, "error": "版本记录损坏",
            }
        body_html = ""
        valid = False
        error = "排版文件不可用"
        result_id = ""
        result_url = ""
        result_kind = ""
        result_mime = ""
        digest = str(raw.get("html_sha256") or "")
        stored_path = str(raw.get("path") or "")
        source_matches = raw.get("source_sha256") == source_hash
        catalog_matches = raw.get("catalog_fingerprint") == theme_fingerprint
        try:
            if theme_id not in known_theme_ids:
                raise DataFileError("排版主题不属于当前文章主题目录")
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise DataFileError("排版文件路径记录不合法")
            path = self._article_html_path(stored_path, digest)
            encoded = path.read_bytes()
            candidate_html = encoded.decode("utf-8")
            validate_article_html(candidate_html)
            # Do not expose a stored file until its hash and HTML guard pass.
            body_html = candidate_html
            result_id = str(raw.get("result_id") or "") if not raw.get("_result_registration_error") else ""
            if result_id and re.fullmatch(r"res_[a-f0-9]{24}", result_id):
                result_url = f"/api/results/{quote(result_id, safe='')}"
                result_kind = str(raw.get("result_kind") or "text")
                result_mime = str(raw.get("result_mime") or "text/html")
            else:
                result_id = ""
            # A saved layout is independently selectable content. Keep its
            # source/catalog provenance visible, but do not make those older
            # fingerprints a read/copy gate after title or source edits.
            valid = True
            error = ""
        except (OSError, UnicodeError, ArticleValidationError, DataFileError) as exc:
            error = str(exc)
        return {
            "body_html": body_html,
            "source_sha256": str(raw.get("source_sha256") or ""),
            "catalog_fingerprint": str(raw.get("catalog_fingerprint") or ""),
            "html_sha256": digest,
            "result_id": result_id or None,
            "result_url": result_url or None,
            "result_kind": result_kind or None,
            "result_mime": result_mime or None,
            "result_available": bool(result_id),
            "result_registration_error": "共享素材库登记暂不可用" if body_html and not result_id else "",
            "embedded_media_ids": list(raw.get("embedded_media_ids") or []),
            "valid": valid,
            "available": valid,
            "source_matches": source_matches,
            "catalog_matches": catalog_matches,
            "generated_at": int(raw.get("generated_at") or 0),
            "error": error,
        }

    def _public_article(self, record: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
        article = self._article_payload(record)
        current_hash = article_source_sha256(article["title"], article["source_markdown"])
        saved_hash = article.get("source_sha256")
        if saved_hash not in (None, "", current_hash):
            raise DataFileError("文章来源指纹与正文不匹配，原文件已保留。")
        raw_variants = article.get("variants", {})
        if not isinstance(raw_variants, dict):
            raise DataFileError("文章主题版本索引损坏，原文件已保留。")
        known_theme_ids = {str(item["id"]) for item in catalog["templates"]}
        variants = {
            str(theme_id): self._project_variant(
                str(theme_id), item, current_hash, str(catalog["catalog_fingerprint"]), known_theme_ids,
            )
            for theme_id, item in raw_variants.items()
        }
        title_variants = self._project_title_variants(article.get("title_variants", {}), article["source_markdown"])
        selected_title_variant_id = article.get("selected_title_variant_id")
        if selected_title_variant_id is not None and selected_title_variant_id not in title_variants:
            raise DataFileError("当前标题选择引用了不存在的历史版本，原文件已保留。")
        cover_variants = self._project_cover_variants(article.get("cover_variants", []), current_hash)
        selected_cover_variant_id = article.get("selected_cover_variant_id")
        if selected_cover_variant_id is not None and selected_cover_variant_id not in {
            item["id"] for item in cover_variants
        }:
            raise DataFileError("当前封面选择引用了不存在的历史版本，原文件已保留。")
        media_refs = self._project_media_refs(article.get("media_refs", []), current_hash)
        return {
            "project_id": str(record.get("id") or ""),
            "title": article["title"],
            "source_markdown": article["source_markdown"],
            "source_sha256": current_hash,
            "revision": max(1, int(record.get("revision") or 1)),
            "selected_theme_id": article.get("selected_theme_id"),
            "variants": variants,
            "title_variants": title_variants,
            "selected_title_variant_id": selected_title_variant_id,
            "cover_variants": cover_variants,
            "selected_cover_variant_id": selected_cover_variant_id,
            "media_refs": media_refs,
            "updated_at": int(record.get("updated_at") or 0),
            "catalog_fingerprint": str(catalog["catalog_fingerprint"]),
        }

    def get(self, project_id: str) -> dict[str, Any]:
        project_id = _clean_project_id(project_id)
        with self.project_store.lock:
            record = self.project_store.read_article_record(project_id)
            self._backfill_html_result_refs(record)
            catalog = self._load_catalog()
            return self._public_article(record, catalog)

    def get_versions(self, project_id: str) -> dict[str, Any]:
        project_id = _clean_project_id(project_id)
        with self.project_store.lock:
            record = self.project_store.read_article_record(project_id)
            article = self._article_payload(record)
            return self._version_list(project_id, record, article)

    def get_version(self, project_id: str, kind: str, version_id: str) -> dict[str, Any]:
        project_id = _clean_project_id(project_id)
        with self.project_store.lock:
            record = self.project_store.read_article_record(project_id)
            article = self._article_payload(record)
            history = self._version_history(article, record)
            if kind == "body":
                entry = self._visible_body_entry(history, version_id) or self._body_raw_entry(history, version_id)
            else:
                entry = self._version_entry(history, kind, version_id)
            return self._version_detail(project_id, record, article, kind, entry, self._load_catalog())

    def restore_version(
        self, project_id: str, kind: str, version_id: str, *, expected_revision: int,
        body_view: str | None = None,
    ) -> dict[str, Any]:
        project_id = _clean_project_id(project_id)
        with self.project_store.lock:
            record = self.project_store.read_article_record(project_id)
            current_revision = max(1, int(record.get("revision") or 1))
            catalog = self._load_catalog()
            if current_revision != expected_revision:
                raise HTTPException(status_code=409, detail={
                    "message": "文章已在其他页面更新，请重新读取后再采用历史版本。",
                    "article": self._public_article(record, catalog),
                    "revision": current_revision,
                })
            self._backfill_html_result_refs(record)
            article = copy.deepcopy(self._article_payload(record))
            history = self._version_history(article, record)
            article["version_history"] = history
            if kind == "body" and body_view == "preview":
                entry = self._visible_body_entry(history, version_id)
                if entry is None:
                    raise HTTPException(status_code=404, detail="HTML 正文版本不存在")
            elif kind == "body":
                entry = self._body_raw_entry(history, version_id)
            else:
                entry = self._version_entry(history, kind, version_id)
            snapshot = copy.deepcopy(entry["snapshot"])
            if kind != "body" and body_view is not None:
                raise HTTPException(status_code=400, detail="body_view 只适用于正文历史")
            if kind == "body" and body_view == "source":
                active_source_id, _active_layout_id = self._active_body_channel_ids(history, article)
                already_current = (
                    active_source_id == str(entry.get("_raw_id") or entry["id"])
                    and self._body_source_available(snapshot)
                    and snapshot.get("source_markdown") == article.get("source_markdown")
                )
            elif kind == "body" and body_view == "preview":
                target_layout = snapshot.get("layouts", [{}])[0]
                target_theme_id = str(target_layout.get("theme_id") or "") if isinstance(target_layout, Mapping) else ""
                current_variants = article.get("variants", {})
                current_layout = current_variants.get(target_theme_id) if isinstance(current_variants, Mapping) else None
                already_current = (
                    self._visible_body_active_id(history, article) == version_id
                    and str(article.get("selected_theme_id") or "") == target_theme_id
                    and isinstance(current_layout, Mapping)
                    and str(current_layout.get("html_sha256") or "") == str(target_layout.get("html_sha256") or "")
                )
            else:
                already_current = (
                    kind == "title" and snapshot.get("title") == str(article.get("title") or "")
                ) or self._version_snapshot_matches_current(kind, snapshot, article)
            if already_current:
                restored = {"kind": kind, "id": version_id}
                if kind == "body":
                    restored["body_view"] = body_view or "whole"
                return {
                    "article": self._public_article(record, catalog),
                    "restored": restored,
                    "revision": current_revision,
                }

            now = int(time.time() * 1000)
            next_revision = current_revision + 1
            old_source = str(article.get("source_markdown") or "")
            variants = article.get("variants") if isinstance(article.get("variants"), dict) else {}
            title_variants = article.get("title_variants") if isinstance(article.get("title_variants"), dict) else {}
            cover_variants = article.get("cover_variants") if isinstance(article.get("cover_variants"), list) else []

            # The pre-restore state must remain addressable even when this project
            # predates history metadata or received a legacy write.
            if kind == "title":
                current_title = str(article.get("title") or "")
                current_hash = article_source_sha256(current_title, old_source)
                current_id = article.get("selected_title_variant_id")
                self._append_version(
                    history, "title", self._title_snapshot(current_title, old_source, str(current_id) if current_id else None),
                    source_revision=current_revision, origin="restore", created_at=now, reuse_matching=True,
                )
                restored_title = snapshot.get("title")
                if not isinstance(restored_title, str) or "\x00" in restored_title or len(restored_title) > 240:
                    raise HTTPException(status_code=409, detail="历史标题内容无法安全恢复")
                new_source_hash = article_source_sha256(restored_title, old_source)
                selected_id = self._title_variant_id(restored_title, new_source_hash) if restored_title else None
                if selected_id:
                    existing = title_variants.get(selected_id)
                    candidate = {
                        "title": restored_title,
                        "source_sha256": new_source_hash,
                        "created_at": now,
                        "source_revision": next_revision,
                    }
                    if existing and (existing.get("title") != restored_title or existing.get("source_sha256") != new_source_hash):
                        raise HTTPException(status_code=409, detail="当前标题候选身份与历史版本冲突")
                    title_variants.setdefault(selected_id, candidate)
                article["title"] = restored_title
                article["title_variants"] = title_variants
                article["selected_title_variant_id"] = selected_id
                article["source_sha256"] = new_source_hash
                resulting_snapshot = self._title_snapshot(restored_title, old_source, selected_id)
                restored_entry = self._append_version(
                    history, "title", resulting_snapshot, source_revision=next_revision,
                    origin="restore", created_at=now, reuse_matching=True,
                )
            elif kind == "cover":
                variant_id = str(snapshot.get("cover_variant_id") or "")
                asset_id = str(snapshot.get("asset_id") or "")
                result_id = str(snapshot.get("result_id") or "")
                source_hash = str(snapshot.get("source_sha256") or "")
                if (not TEMPLATE_ID_PATTERN.fullmatch(variant_id)
                        or bool(asset_id) == bool(result_id)
                        or not re.fullmatch(r"[a-f0-9]{64}", source_hash)):
                    raise HTTPException(status_code=409, detail="历史封面版本记录不完整，无法恢复")
                try:
                    self._resolve_cover(asset_id, result_id)
                except HTTPException as exc:
                    raise HTTPException(status_code=409, detail="历史封面素材当前不可用，无法采用") from exc
                current_cover_id = article.get("selected_cover_variant_id")
                current_cover = next((item for item in cover_variants
                                      if isinstance(item, dict) and item.get("id") == current_cover_id), None)
                if isinstance(current_cover, Mapping):
                    self._append_version(
                        history, "cover", self._cover_snapshot(current_cover),
                        source_revision=current_revision, origin="restore", created_at=now, reuse_matching=True,
                    )
                candidate = {
                    "id": variant_id,
                    "asset_id": asset_id or None,
                    "result_id": result_id or None,
                    "source_sha256": source_hash,
                    "created_at": entry.get("created_at") or now,
                }
                existing = next((item for item in cover_variants
                                 if isinstance(item, dict) and item.get("id") == variant_id), None)
                if existing and any(existing.get(key) != candidate.get(key) for key in (
                    "asset_id", "result_id", "source_sha256",
                )):
                    raise HTTPException(status_code=409, detail="当前封面版本身份与历史记录冲突")
                if not existing:
                    cover_variants.append(candidate)
                article["cover_variants"] = cover_variants
                article["selected_cover_variant_id"] = variant_id
                restored_entry = self._append_version(
                    history, "cover", self._cover_snapshot(candidate), source_revision=next_revision,
                    origin="restore", created_at=now, reuse_matching=True,
                )
            elif kind == "body":
                source_available = bool(snapshot.get("source_markdown_available"))
                restored_source = snapshot.get("source_markdown")
                restore_source = body_view in {None, "source"}
                restore_preview = body_view in {None, "preview"}
                if restore_source and (not source_available or not isinstance(restored_source, str)):
                    raise HTTPException(status_code=409, detail="该历史版本没有可恢复的 Markdown 正文")
                if restore_source and (
                    self._sha256_text(restored_source) != snapshot.get("source_markdown_sha256")
                    or len(restored_source.encode("utf-8")) > MAX_SOURCE_BYTES or "\x00" in restored_source
                ):
                    raise HTTPException(status_code=409, detail="历史正文指纹或内容无效，无法恢复")
                historical_layouts = snapshot.get("layouts", [])
                if restore_preview and not self._body_layouts_available(snapshot):
                    raise HTTPException(status_code=409, detail="该历史版本没有可恢复的主题排版")
                if restore_preview:
                    for raw in historical_layouts:
                        try:
                            stored_path = str(raw.get("path") or (ARTICLE_VARIANT_DIR / f"{raw['html_sha256']}.html"))
                            html_path = self._article_html_path(stored_path, str(raw["html_sha256"]))
                            body_html = html_path.read_text(encoding="utf-8")
                            validate_article_html(body_html)
                        except (OSError, UnicodeError, ArticleValidationError, DataFileError, KeyError, TypeError) as exc:
                            raise HTTPException(status_code=409, detail="历史主题排版缺失或损坏，无法恢复") from exc
                self._append_version(
                    history, "body", self._body_snapshot(article),
                    source_revision=current_revision, origin="restore", created_at=now, reuse_matching=True,
                )
                if restore_source:
                    article["source_markdown"] = restored_source
                    source_hash = article_source_sha256(str(article.get("title") or ""), restored_source)
                    article["source_sha256"] = source_hash
                    current_title = str(article.get("title") or "")
                    current_title_id = self._title_variant_id(current_title, source_hash) if current_title else None
                    if current_title_id:
                        title_variants = article.get("title_variants") if isinstance(article.get("title_variants"), dict) else {}
                        title_variants.setdefault(current_title_id, {
                            "title": current_title,
                            "source_sha256": source_hash,
                            "created_at": now,
                            "source_revision": next_revision,
                        })
                        article["title_variants"] = title_variants
                        article["selected_title_variant_id"] = current_title_id
                if restore_preview:
                    # A historical preview changes only the themes it contains.
                    # Other currently saved themes remain available side by side.
                    merged_layouts = copy.deepcopy(variants)
                    merged_layouts.update(self._restore_layout_index(snapshot))
                    article["variants"] = merged_layouts
                    if body_view == "preview" and historical_layouts:
                        article["selected_theme_id"] = str(historical_layouts[0].get("theme_id") or "")
                resulting_snapshot = self._body_snapshot(article)
                restored_entry = self._append_version(
                    history, "body", resulting_snapshot, source_revision=next_revision,
                    origin="restore", created_at=now, reuse_matching=True,
                )
                active_body = history.setdefault("active_body", {"source": None, "layout": None})
                if body_view == "source":
                    active_body["source"] = str(entry.get("_raw_id") or entry["id"])
                elif body_view == "preview":
                    active_body["layout"] = str(entry.get("_raw_id") or entry["id"])
                else:
                    active_body["source"] = str(entry.get("_raw_id") or entry["id"])
                    active_body["layout"] = str(entry.get("_raw_id") or entry["id"])

            article["version_history"] = history
            record["article"] = article
            record["updated_at"] = now
            record["revision"] = next_revision
            self.project_store.write_article_record(record)
            return {
                "article": self._public_article(record, catalog),
                "restored": {
                    "kind": kind, "id": version_id,
                    "active_version_id": self._visible_body_active_id(history, article)
                        if kind == "body" else restored_entry["id"],
                    **({"body_view": body_view or "whole"} if kind == "body" else {}),
                },
                "revision": next_revision,
            }

    def templates(self) -> dict[str, Any]:
        catalog = self._load_catalog()
        return {"templates": catalog["templates"], "catalog_fingerprint": catalog["catalog_fingerprint"]}

    def put(self, project_id: str, payload: ArticlePutRequest) -> dict[str, Any]:
        project_id = _clean_project_id(project_id)
        with self.project_store.lock:
            record = self.project_store.read_article_record(project_id)
            current_revision = max(1, int(record.get("revision") or 1))
            catalog = self._load_catalog()
            if current_revision != payload.expected_revision:
                raise HTTPException(status_code=409, detail={
                    "message": "文章已在其他页面更新，请重新读取并合并。",
                    "article": self._public_article(record, catalog),
                    "revision": current_revision,
                })
            if payload.expected_catalog_fingerprint and payload.expected_catalog_fingerprint != catalog["catalog_fingerprint"]:
                raise HTTPException(status_code=409, detail={
                    "message": "公众号主题目录已更新，请重新读取模板后再保存。",
                    "catalog_fingerprint": catalog["catalog_fingerprint"],
                })
            self._backfill_html_result_refs(record)
            article = copy.deepcopy(self._article_payload(record))
            history = self._version_history(article, record)
            article["version_history"] = history
            before = copy.deepcopy(article)
            fields_set = payload.model_fields_set
            title = payload.title if "title" in fields_set else article.get("title", "")
            source = payload.source_markdown if "source_markdown" in fields_set else article.get("source_markdown", "")
            previous_title = str(article.get("title") or "")
            previous_source = str(article.get("source_markdown") or "")
            title = str(title or "")
            source = str(source or "")
            if "\x00" in title or "\x00" in source:
                raise HTTPException(status_code=400, detail="标题或来源正文包含无效字符")
            if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
                raise HTTPException(status_code=413, detail="文章来源正文超过大小限制")
            source_hash = article_source_sha256(title, source)
            title_variants = article.get("title_variants") if isinstance(article.get("title_variants"), dict) else {}
            title_variants = copy.deepcopy(title_variants)
            if "title_variants" in fields_set and payload.title_variants is not None:
                for variant_id, variant in payload.title_variants.items():
                    if not TEMPLATE_ID_PATTERN.fullmatch(variant_id):
                        raise HTTPException(status_code=400, detail=f"标题版本 ID 不合法：{variant_id}")
                    variant_hash = article_source_sha256(variant.title, source)
                    if variant.source_sha256 and variant.source_sha256 != variant_hash:
                        raise HTTPException(status_code=409, detail=f"标题版本 {variant_id} 基于不同正文，不能写入当前文章。")
                    candidate = {
                        "title": variant.title,
                        "source_sha256": variant_hash,
                        "created_at": int(time.time() * 1000),
                    }
                    previous = title_variants.get(variant_id)
                    if previous and (previous.get("title") != candidate["title"]
                                     or previous.get("source_sha256") != candidate["source_sha256"]):
                        raise HTTPException(status_code=409, detail=f"标题版本 {variant_id} 已存在且不可覆盖。")
                    title_variants.setdefault(variant_id, candidate)

            selected_title_variant_id = article.get("selected_title_variant_id")
            if "selected_title_variant_id" in fields_set:
                selected_title_variant_id = payload.selected_title_variant_id
                if selected_title_variant_id is not None:
                    selected_variant = title_variants.get(selected_title_variant_id)
                    if not isinstance(selected_variant, dict):
                        raise HTTPException(status_code=400, detail="所选标题版本不存在")
                    if "title" in fields_set and title != selected_variant.get("title"):
                        raise HTTPException(status_code=400, detail="title 与 selected_title_variant_id 指向不同标题")
                    title = str(selected_variant.get("title") or "")
                    source_hash = article_source_sha256(title, source)

            # 每次当前标题或正文进入新配方时都保留一个可追溯标题版本；不覆盖已有版本。
            current_title_id = self._title_variant_id(title, source_hash) if title else None
            if current_title_id:
                title_variants.setdefault(current_title_id, {
                    "title": title,
                    "source_sha256": source_hash,
                    "created_at": int(time.time() * 1000),
                })
                if "selected_title_variant_id" not in fields_set or selected_title_variant_id is not None:
                    selected_title_variant_id = current_title_id

            if "selected_theme_id" in fields_set:
                selected_theme_id = payload.selected_theme_id
                known_ids = {item["id"] for item in catalog["templates"]}
                if selected_theme_id is not None and selected_theme_id not in known_ids:
                    raise HTTPException(status_code=400, detail="所选排版主题不存在")
                article["selected_theme_id"] = selected_theme_id

            cover_variants = article.get("cover_variants") if isinstance(article.get("cover_variants"), list) else []
            cover_variants = copy.deepcopy(cover_variants)
            if "cover_variants" in fields_set and payload.cover_variants is not None:
                known_cover_ids = {str(item.get("id") or ""): item for item in cover_variants if isinstance(item, dict)}
                for variant in payload.cover_variants:
                    asset_id = str(variant.asset_id or "")
                    result_id = str(variant.result_id or "")
                    resolved = self._resolve_cover(asset_id, result_id)
                    variant_hash = variant.source_sha256 or source_hash
                    if not re.fullmatch(r"[a-f0-9]{64}", variant_hash):
                        raise HTTPException(status_code=400, detail="封面版本 source_sha256 不合法")
                    variant_id = variant.id or self._cover_variant_id(
                        variant_hash, "asset" if asset_id else "result", asset_id or result_id
                    )
                    if not TEMPLATE_ID_PATTERN.fullmatch(variant_id):
                        raise HTTPException(status_code=400, detail="封面版本 ID 不合法")
                    candidate = {
                        "id": variant_id,
                        "asset_id": asset_id or None,
                        "result_id": result_id or None,
                        "source_sha256": variant_hash,
                        "created_at": int(time.time() * 1000),
                    }
                    previous = known_cover_ids.get(variant_id)
                    if previous and any(previous.get(key) != candidate.get(key) for key in (
                        "asset_id", "result_id", "source_sha256",
                    )):
                        raise HTTPException(status_code=409, detail=f"封面版本 {variant_id} 已存在且不可覆盖。")
                    if not previous:
                        cover_variants.append(candidate)
                        known_cover_ids[variant_id] = candidate
            selected_cover_variant_id = article.get("selected_cover_variant_id")
            if "selected_cover_variant_id" in fields_set:
                selected_cover_variant_id = payload.selected_cover_variant_id
                if selected_cover_variant_id is not None and selected_cover_variant_id not in {
                    str(item.get("id") or "") for item in cover_variants if isinstance(item, dict)
                }:
                    raise HTTPException(status_code=400, detail="所选封面版本不存在")

            media_refs = article.get("media_refs") if isinstance(article.get("media_refs"), list) else []
            media_refs = copy.deepcopy(media_refs)
            if "media_refs" in fields_set and payload.media_refs is not None:
                known_media_ids = {str(item.get("id") or ""): item for item in media_refs if isinstance(item, dict)}
                for reference in payload.media_refs:
                    asset_id = str(reference.asset_id or "")
                    result_id = str(reference.result_id or "")
                    self._resolve_shared_media(asset_id, result_id)
                    reference_hash = reference.source_sha256 or source_hash
                    if not re.fullmatch(r"[a-f0-9]{64}", reference_hash):
                        raise HTTPException(status_code=400, detail="文章媒体 source_sha256 不合法")
                    reference_id = asset_id or result_id
                    reference_kind = "asset" if asset_id else "result"
                    variant_id = reference.id or self._media_variant_id(reference_hash, reference_kind, reference_id)
                    if not TEMPLATE_ID_PATTERN.fullmatch(variant_id):
                        raise HTTPException(status_code=400, detail="文章媒体版本 ID 不合法")
                    candidate = {
                        "id": variant_id,
                        "asset_id": asset_id or None,
                        "result_id": result_id or None,
                        "source_sha256": reference_hash,
                        "created_at": int(time.time() * 1000),
                    }
                    previous = known_media_ids.get(variant_id)
                    if previous and any(previous.get(key) != candidate.get(key) for key in (
                        "asset_id", "result_id", "source_sha256",
                    )):
                        raise HTTPException(status_code=409, detail=f"文章媒体版本 {variant_id} 已存在且不可覆盖。")
                    if not previous:
                        media_refs.append(candidate)
                        known_media_ids[variant_id] = candidate

            variants = article.get("variants") if isinstance(article.get("variants"), dict) else {}
            staged: dict[str, dict[str, Any]] = {}
            if "variants" in fields_set and payload.variants is not None:
                known_ids = {item["id"] for item in catalog["templates"]}
                for theme_id, variant in payload.variants.items():
                    if theme_id not in known_ids:
                        raise HTTPException(status_code=400, detail=f"排版主题不存在：{theme_id}")
                    if variant.source_sha256 and variant.source_sha256 != source_hash:
                        raise HTTPException(status_code=409, detail=f"主题 {theme_id} 的排版基于旧文章内容，请重新排版。")
                    try:
                        validate_article_html(variant.body_html)
                    except ArticleValidationError as exc:
                        raise HTTPException(status_code=400, detail=str(exc)) from exc
                    body_bytes = variant.body_html.encode("utf-8")
                    html_hash = hashlib.sha256(body_bytes).hexdigest()
                    staged[theme_id] = {
                        "body_html": variant.body_html,
                        "source_sha256": source_hash,
                        "catalog_fingerprint": str(catalog["catalog_fingerprint"]),
                        "html_sha256": html_hash,
                        "generated_at": int(time.time() * 1000),
                    }

            # 先校验全部变体，再写不可变 HTML；最后原子替换同一项目 JSON。
            for theme_id, item in staged.items():
                body_html = item.pop("body_html")
                existing_shared = self._shared_html_variant(item["html_sha256"])
                if existing_shared:
                    item["path"], result_reference = existing_shared
                else:
                    item["path"] = self._write_html(body_html, item["html_sha256"])
                    result_reference = self._register_html_result(item["html_sha256"])
                item.update(result_reference)
                embedded_ids, embedded_refs = self._register_embedded_images(body_html, source_hash)
                item["embedded_media_ids"] = embedded_ids
                self._merge_internal_media_refs(media_refs, embedded_refs)
                variants[theme_id] = item
            article["title"] = title
            article["source_markdown"] = source
            article["source_sha256"] = source_hash
            article["variants"] = variants
            article["title_variants"] = title_variants
            article["selected_title_variant_id"] = selected_title_variant_id
            article["cover_variants"] = cover_variants
            article["selected_cover_variant_id"] = selected_cover_variant_id
            article["media_refs"] = media_refs
            next_revision = current_revision + 1
            now = int(time.time() * 1000)

            old_title_ids = set(before.get("title_variants", {})) if isinstance(before.get("title_variants"), dict) else set()
            added_title_ids = [variant_id for variant_id in title_variants if variant_id not in old_title_ids]
            auto_current_id = self._title_variant_id(title, source_hash) if title else None
            for variant_id in added_title_ids:
                item = title_variants.get(variant_id)
                if not isinstance(item, Mapping):
                    continue
                # Keep the compatibility candidate tied to an edited body, but
                # do not report an unchanged title as a new title-history event.
                if variant_id == auto_current_id and title == previous_title and source != previous_source:
                    continue
                variant_title = str(item.get("title") or "")
                variant_source_hash = str(item.get("source_sha256") or "")
                self._append_version(
                    history,
                    "title",
                    {
                        "title": variant_title,
                        "title_variant_id": variant_id,
                        "source_sha256": variant_source_hash,
                    },
                    source_revision=next_revision,
                    origin="put",
                    created_at=now,
                )

            old_cover_ids = {
                str(item.get("id") or "") for item in before.get("cover_variants", [])
                if isinstance(item, Mapping)
            } if isinstance(before.get("cover_variants"), list) else set()
            for item in cover_variants:
                if not isinstance(item, Mapping) or str(item.get("id") or "") in old_cover_ids:
                    continue
                self._append_version(
                    history,
                    "cover",
                    self._cover_snapshot(item),
                    source_revision=next_revision,
                    origin="put",
                    created_at=now,
                )

            old_variants = before.get("variants", {}) if isinstance(before.get("variants"), dict) else {}
            new_variants = variants if isinstance(variants, dict) else {}
            old_layouts = self._version_layout_snapshot(old_variants)
            new_layouts = self._version_layout_snapshot(new_variants)
            old_layout_identity = self._body_snapshot_identity({"layouts": old_layouts})
            new_layout_identity = self._body_snapshot_identity({"layouts": new_layouts})
            if old_layout_identity != new_layout_identity:
                body_entry = self._append_version(
                    history,
                    "body",
                    self._body_snapshot(article),
                    source_revision=next_revision,
                    origin="put",
                    created_at=now,
                    reuse_matching=True,
                )
                active_body = history.setdefault("active_body", {"source": None, "layout": None})
                active_body["layout"] = body_entry["id"]
            article["version_history"] = history
            record["article"] = article
            record["updated_at"] = now
            record["revision"] = next_revision
            self.project_store.write_article_record(record)
            return self._public_article(record, catalog)

    def associate_generation_media(
        self,
        project_id: str,
        *,
        generation: Mapping[str, Any],
        purpose: str,
        slot: str,
        accepted_revision: int,
        source_hash: str,
    ) -> dict[str, Any]:
        """把已完成任务引用追加到文章历史，不复制媒体也不覆盖较新的正文或选择。"""
        project_id = _clean_project_id(project_id)
        if str(generation.get("status") or "").lower() != "succeeded":
            return self.get(project_id)
        if not re.fullmatch(r"[a-f0-9]{64}", source_hash):
            raise HTTPException(status_code=400, detail="生成任务缺少有效的文章来源指纹")
        target_kind = {"text": "text", "image": "image", "video": "video", "audio": "audio",
                       "music": "audio", "voice": "audio"}.get(slot)
        if target_kind is None or str(generation.get("output_kind") or "").lower() != target_kind:
            raise HTTPException(status_code=409, detail="生成结果类型与文章请求用途不匹配")
        run_id = str(generation.get("run_id") or "").strip()
        if not run_id:
            raise HTTPException(status_code=502, detail="生成任务缺少持久 run_id")
        media = generation.get("media") if isinstance(generation.get("media"), list) else []
        candidates: list[dict[str, Any]] = []
        for item in media:
            if not isinstance(item, Mapping):
                continue
            result_id = str(item.get("resultId") or item.get("result_id") or "")
            asset_id = str(item.get("assetId") or item.get("asset_id") or "")
            if not asset_id and not result_id:
                url = str(item.get("url") or "")
                marker = "/api/results/"
                if marker in url:
                    result_id = url.split(marker, 1)[1].split("?", 1)[0].strip("/")
            if not asset_id and not result_id:
                continue
            try:
                resolved = self._resolve_shared_media(asset_id, result_id)
            except HTTPException:
                continue
            if resolved["kind"] != target_kind:
                continue
            candidates.append({"asset_id": asset_id, "result_id": result_id, "resolved": resolved})
        if not candidates:
            raise HTTPException(status_code=409, detail="已完成的生成任务没有可关联的匹配类型托管素材")

        with self.project_store.lock:
            record = self.project_store.read_article_record(project_id)
            self._backfill_html_result_refs(record)
            article = copy.deepcopy(self._article_payload(record))
            history = self._version_history(article, record)
            article["version_history"] = history
            current_hash = article_source_sha256(article["title"], article["source_markdown"])
            refs = article.get("media_refs") if isinstance(article.get("media_refs"), list) else []
            covers = article.get("cover_variants") if isinstance(article.get("cover_variants"), list) else []
            known_refs = {str(item.get("id") or ""): item for item in refs if isinstance(item, dict)}
            known_covers = {str(item.get("id") or ""): item for item in covers if isinstance(item, dict)}
            changed = False
            accepted_current = (
                max(1, int(record.get("revision") or 1)) == accepted_revision
                and current_hash == source_hash
            )
            selected_cover = article.get("selected_cover_variant_id")
            now = int(time.time() * 1000)
            for candidate in candidates:
                asset_id = candidate["asset_id"]
                result_id = candidate["result_id"]
                ref_kind = "asset" if asset_id else "result"
                ref_id = asset_id or result_id
                media_id = self._media_variant_id(source_hash, ref_kind, ref_id)
                entry = {
                    "id": media_id, "asset_id": asset_id or None, "result_id": result_id or None,
                    "source_sha256": source_hash, "created_at": now, "run_id": run_id,
                }
                if media_id not in known_refs:
                    refs.append(entry)
                    known_refs[media_id] = entry
                    changed = True
                if purpose == "cover":
                    if slot != "image" or candidate["resolved"]["kind"] != "image":
                        raise HTTPException(status_code=409, detail="封面生成只能关联图片结果")
                    cover_id = self._cover_variant_id(source_hash, ref_kind, ref_id)
                    cover = {
                        "id": cover_id, "asset_id": asset_id or None, "result_id": result_id or None,
                        "source_sha256": source_hash, "created_at": now, "run_id": run_id,
                    }
                    if cover_id not in known_covers:
                        covers.append(cover)
                        known_covers[cover_id] = cover
                        changed = True
                        self._append_version(
                            history,
                            "cover",
                            self._cover_snapshot(cover),
                            source_revision=max(1, int(record.get("revision") or 1)) + 1,
                            origin="generation",
                            created_at=now,
                        )
                    if accepted_current:
                        changed = changed or selected_cover != cover_id
                        selected_cover = cover_id
            if not changed:
                return self._public_article(record, self._load_catalog())
            article["media_refs"] = refs
            article["cover_variants"] = covers
            article["version_history"] = history
            if accepted_current and purpose == "cover":
                article["selected_cover_variant_id"] = selected_cover
            record["article"] = article
            record["updated_at"] = now
            record["revision"] = max(1, int(record.get("revision") or 1)) + 1
            self.project_store.write_article_record(record)
            return self._public_article(record, self._load_catalog())


def create_studio_articles_router(
    root: str | os.PathLike[str],
    project_store: StudioProjectStore,
    *,
    catalog_path: str | os.PathLike[str],
    resolve_media_reference: Callable[[str, str], Mapping[str, Any] | None] | None = None,
    register_managed_result: Callable[..., Mapping[str, Any]] | None = None,
    find_shared_media_by_hash: Callable[[str, str], Mapping[str, Any] | None] | None = None,
    store: StudioArticleStore | None = None,
    submit_generation: Callable[[str, Mapping[str, Any], Mapping[str, Any]], Any] | None = None,
    get_generation: Callable[[str, str], Any] | None = None,
) -> APIRouter:
    store = store or StudioArticleStore(
        root, project_store, catalog_path,
        resolve_media_reference=resolve_media_reference,
        register_managed_result=register_managed_result,
        find_shared_media_by_hash=find_shared_media_by_hash,
    )
    router = APIRouter(prefix="/api/studio/articles", tags=["Studio Articles"])

    @router.get("/templates")
    async def get_templates():
        try:
            return store.templates()
        except (DataFileError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/settings-canvas")
    async def article_settings_canvas_not_configured():
        # 此路由实际由 article settings router 在此应用之前注册；若独立装配
        # Article router，则明确提示宿主缺少专用配置图，而不把路径当文章 ID。
        raise HTTPException(status_code=503, detail="文章模块配置图路由尚未接入")

    @router.post("/{project_id}/generations", dependencies=[Depends(_guard_local_write)])
    async def submit_article_generation(project_id: str, payload: ArticleGenerationRequest):
        if submit_generation is None:
            raise HTTPException(status_code=503, detail="文章生成执行入口尚未接入")
        try:
            article = store.get(project_id)
            accepted_revision = int(article.get("revision") or 1)
            if payload.purpose == "cover" and payload.slot != "image":
                raise HTTPException(status_code=400, detail="封面用途只能选择图片输出槽")
            accepted_context = {
                "accepted_revision": accepted_revision,
                "source_hash": str(article.get("source_sha256") or ""),
                "requested_revision": payload.base_revision,
            }
            callback_value = submit_generation(project_id, payload.model_dump(), accepted_context)
            generation = await callback_value if inspect.isawaitable(callback_value) else callback_value
            if not isinstance(generation, Mapping) or not generation.get("run_id"):
                raise HTTPException(status_code=502, detail="文章生成入口未返回持久任务 ID")
            return {"generation": dict(generation)}
        except StudioProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=exc.detail) from exc
        except HTTPException:
            raise
        except (DataFileError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/{project_id}/generations/{run_id}")
    async def get_article_generation(project_id: str, run_id: str):
        if get_generation is None:
            raise HTTPException(status_code=503, detail="文章生成任务读取入口尚未接入")
        try:
            # 确认文章当前仍存在；任务查询不得把已删除文章重建回来。
            article = store.get(project_id)
            callback_value = get_generation(project_id, run_id)
            generation = await callback_value if inspect.isawaitable(callback_value) else callback_value
            if not isinstance(generation, Mapping):
                raise HTTPException(status_code=404, detail="文章生成任务不存在")
            # 成功查询可能刚完成延迟素材关联；返回关联后的最新文章修订。
            article = store.get(project_id)
            return {"generation": dict(generation), "article": article}
        except StudioProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=exc.detail) from exc
        except HTTPException:
            raise
        except (DataFileError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/{project_id}/versions")
    async def get_article_versions(project_id: str):
        try:
            return store.get_versions(project_id)
        except StudioProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=exc.detail) from exc
        except HTTPException:
            raise
        except (DataFileError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/{project_id}/versions/{kind}/{version_id}")
    async def get_article_version(project_id: str, kind: str, version_id: str):
        try:
            return store.get_version(project_id, kind, version_id)
        except StudioProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=exc.detail) from exc
        except HTTPException:
            raise
        except (DataFileError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post(
        "/{project_id}/versions/{kind}/{version_id}/restore",
        dependencies=[Depends(_guard_local_write)],
    )
    async def restore_article_version(project_id: str, kind: str, version_id: str,
                                      payload: ArticleVersionRestoreRequest):
        try:
            return store.restore_version(
                project_id, kind, version_id, expected_revision=payload.expected_revision,
                body_view=payload.body_view,
            )
        except StudioProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=exc.detail) from exc
        except HTTPException:
            raise
        except (DataFileError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/{project_id}")
    async def get_article(project_id: str):
        try:
            return {"article": store.get(project_id)}
        except StudioProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=exc.detail) from exc
        except HTTPException:
            raise
        except (DataFileError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.put("/{project_id}", dependencies=[Depends(_guard_local_write)])
    async def put_article(project_id: str, payload: ArticlePutRequest):
        try:
            return {"article": store.put(project_id, payload)}
        except StudioProjectNotFound as exc:
            raise HTTPException(status_code=404, detail=exc.detail) from exc
        except HTTPException:
            raise
        except (DataFileError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router


__all__ = [
    "ArticlePutRequest",
    "StudioArticleStore",
    "article_source_sha256",
    "create_studio_articles_router",
    "validate_article_html",
]
