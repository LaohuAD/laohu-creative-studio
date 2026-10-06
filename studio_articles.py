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
    body_html: str = Field(min_length=1)
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
    source_markdown: Optional[str] = None
    title: Optional[str] = Field(default=None, max_length=240)
    selected_theme_id: Optional[str] = Field(default=None, max_length=81)
    title_variants: Optional[dict[str, TitleVariantInput]] = None
    selected_title_variant_id: Optional[str] = Field(default=None, max_length=128)
    cover_variants: Optional[list[CoverVariantInput]] = None
    selected_cover_variant_id: Optional[str] = Field(default=None, max_length=128)
    media_refs: Optional[list[MediaReferenceInput]] = None
    expected_catalog_fingerprint: Optional[str] = Field(default=None, max_length=128)
    variants: Optional[dict[str, VariantInput]] = None


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

    def _project_variant(self, theme_id: str, raw: Any, source_hash: str, theme_fingerprint: str) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {"body_html": "", "source_sha256": "", "valid": False, "error": "版本记录损坏"}
        body_html = ""
        valid = False
        error = "排版文件不可用"
        result_id = ""
        result_url = ""
        result_kind = ""
        result_mime = ""
        digest = str(raw.get("html_sha256") or "")
        stored_path = str(raw.get("path") or "")
        try:
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise DataFileError("排版文件路径记录不合法")
            path = self._article_html_path(stored_path, digest)
            encoded = path.read_bytes()
            body_html = encoded.decode("utf-8")
            validate_article_html(body_html)
            result_id = str(raw.get("result_id") or "") if not raw.get("_result_registration_error") else ""
            if result_id and re.fullmatch(r"res_[a-f0-9]{24}", result_id):
                result_url = f"/api/results/{quote(result_id, safe='')}"
                result_kind = str(raw.get("result_kind") or "text")
                result_mime = str(raw.get("result_mime") or "text/html")
            else:
                result_id = ""
            valid = raw.get("source_sha256") == source_hash and raw.get("catalog_fingerprint") == theme_fingerprint
            error = "" if valid else "原文或主题组件已变化，请重新排版"
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
        variants = {
            str(theme_id): self._project_variant(
                str(theme_id), item, current_hash, str(catalog["catalog_fingerprint"])
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
            article = copy.deepcopy(self._article_payload(record))
            fields_set = payload.model_fields_set
            title = payload.title if "title" in fields_set else article.get("title", "")
            source = payload.source_markdown if "source_markdown" in fields_set else article.get("source_markdown", "")
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
            record["article"] = article
            record["updated_at"] = int(time.time() * 1000)
            record["revision"] = current_revision + 1
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
            article = copy.deepcopy(self._article_payload(record))
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
                    if accepted_current:
                        changed = changed or selected_cover != cover_id
                        selected_cover = cover_id
            if not changed:
                return self._public_article(record, self._load_catalog())
            article["media_refs"] = refs
            article["cover_variants"] = covers
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
