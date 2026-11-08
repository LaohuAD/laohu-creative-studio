"""Stable Studio module identities and module-settings canvas metadata.

Business storage, slot capabilities, and generation behavior remain in their
own modules. This catalog only keeps cross-module identity labels and the
reserved settings-canvas identities used by project and connection routing.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


STUDIO_CAPABILITY_LABELS = MappingProxyType({
    "text": {"zh": "文本处理", "en": "Text Processing"},
    "image": {"zh": "图片创作", "en": "Image Creation"},
    "video": {"zh": "视频创作", "en": "Video Creation"},
    "voice": {"zh": "配音", "en": "Voice-over"},
    "audio": {"zh": "音效", "en": "Sound Effects"},
    "music": {"zh": "音乐", "en": "Music"},
})


def studio_capability_label(slot: str) -> dict[str, str]:
    """展示名称与稳定槽位键分开；返回副本供各模块安全使用。"""
    return dict(STUDIO_CAPABILITY_LABELS[slot])


@dataclass(frozen=True)
class StudioModuleIdentity:
    module_id: str
    label_zh: str
    label_en: str
    project_module: bool
    connection_document: bool
    preparation_document: bool
    settings_canvas_id: str
    settings_project_id: str
    settings_canvas_url: str
    settings_canvas_title_zh: str
    settings_canvas_title_en: str
    settings_canvas_kind: str
    settings_canvas_slots: tuple[str, ...] = ()

    @property
    def label(self) -> dict[str, str]:
        return {"zh": self.label_zh, "en": self.label_en}

    @property
    def settings_canvas_mode(self) -> str:
        return self.settings_canvas_id


_MODULES = {
    "canvas": StudioModuleIdentity(
        module_id="canvas",
        label_zh="画布",
        label_en="Canvas",
        project_module=True,
        connection_document=True,
        preparation_document=True,
        settings_canvas_id="canvas-settings",
        settings_project_id="__canvas_settings__",
        settings_canvas_url="/static/smart-canvas.html?id=canvas-settings&mode=canvas-settings",
        settings_canvas_title_zh="画布模型设置",
        settings_canvas_title_en="Canvas model settings",
        settings_canvas_kind="model-management",
    ),
    "hypit": StudioModuleIdentity(
        module_id="hypit",
        label_zh="视频克隆",
        label_en="Video Cloning",
        project_module=True,
        connection_document=True,
        preparation_document=True,
        settings_canvas_id="hypit-settings",
        settings_project_id="__hypit_settings__",
        settings_canvas_url="/static/smart-canvas.html?id=hypit-settings&mode=hypit-settings",
        settings_canvas_title_zh="视频克隆生成配置",
        settings_canvas_title_en="Video Cloning generation settings",
        settings_canvas_kind="module-generation",
        settings_canvas_slots=("text", "image", "video", "audio", "music", "voice"),
    ),
    "article": StudioModuleIdentity(
        module_id="article",
        label_zh="公众号文章",
        label_en="Article",
        project_module=True,
        connection_document=True,
        preparation_document=True,
        settings_canvas_id="article-settings",
        settings_project_id="__article_settings__",
        settings_canvas_url="/static/smart-canvas.html?id=article-settings&mode=article-settings",
        settings_canvas_title_zh="文章生成配置",
        settings_canvas_title_en="Article generation settings",
        settings_canvas_kind="module-generation",
        settings_canvas_slots=("text", "image", "video", "audio", "music", "voice"),
    ),
    "music": StudioModuleIdentity(
        module_id="music",
        label_zh="音乐创作",
        label_en="Music Creation",
        project_module=True,
        connection_document=True,
        preparation_document=True,
        settings_canvas_id="music-settings",
        settings_project_id="__music_settings__",
        settings_canvas_url="/static/smart-canvas.html?id=music-settings&mode=music-settings",
        settings_canvas_title_zh="音乐生成配置",
        settings_canvas_title_en="Music generation settings",
        settings_canvas_kind="module-generation",
        settings_canvas_slots=("music", "image"),
    ),
    "script": StudioModuleIdentity(
        module_id="script",
        label_zh="剧本创作",
        label_en="Script Writing",
        project_module=True,
        connection_document=True,
        preparation_document=True,
        settings_canvas_id="script-settings",
        settings_project_id="__script_settings__",
        settings_canvas_url="/static/smart-canvas.html?id=script-settings&mode=script-settings",
        settings_canvas_title_zh="剧本文本设置",
        settings_canvas_title_en="Script text settings",
        settings_canvas_kind="module-generation",
        settings_canvas_slots=("text",),
    ),
    "novel": StudioModuleIdentity(
        module_id="novel",
        label_zh="小说创作",
        label_en="Novel Writing",
        project_module=True,
        connection_document=True,
        preparation_document=True,
        settings_canvas_id="novel-settings",
        settings_project_id="__novel_settings__",
        settings_canvas_url="/static/smart-canvas.html?id=novel-settings&mode=novel-settings",
        settings_canvas_title_zh="小说文本设置",
        settings_canvas_title_en="Novel text settings",
        settings_canvas_kind="module-generation",
        settings_canvas_slots=("text",),
    ),
}

STUDIO_MODULES: Mapping[str, StudioModuleIdentity] = MappingProxyType(_MODULES)
PROJECT_MODULE_IDS = frozenset(module_id for module_id, item in _MODULES.items() if item.project_module)
CONNECTION_MODULE_IDS = frozenset(
    module_id for module_id, item in _MODULES.items() if item.connection_document
)
PREPARATION_MODULE_IDS = frozenset(
    module_id for module_id, item in _MODULES.items() if item.preparation_document
)
RESERVED_SETTINGS_CANVAS_IDS = frozenset(item.settings_canvas_id for item in _MODULES.values() if item.settings_canvas_id)
MODULE_SETTINGS_CANVAS_MODULES = MappingProxyType({
    item.settings_canvas_id: module_id
    for module_id, item in _MODULES.items()
    if item.settings_canvas_kind == "module-generation"
})


def studio_module_identity(module_id: str) -> StudioModuleIdentity | None:
    return STUDIO_MODULES.get(str(module_id or "").strip().lower())


def studio_module_label(module_id: str) -> dict[str, str] | None:
    identity = studio_module_identity(module_id)
    return identity.label if identity else None


def settings_canvas_identity(module_id: str) -> StudioModuleIdentity | None:
    identity = studio_module_identity(module_id)
    return identity if identity and identity.settings_canvas_id else None


__all__ = [
    "CONNECTION_MODULE_IDS",
    "MODULE_SETTINGS_CANVAS_MODULES",
    "PREPARATION_MODULE_IDS",
    "PROJECT_MODULE_IDS",
    "RESERVED_SETTINGS_CANVAS_IDS",
    "STUDIO_MODULES",
    "STUDIO_CAPABILITY_LABELS",
    "studio_capability_label",
    "StudioModuleIdentity",
    "settings_canvas_identity",
    "studio_module_identity",
    "studio_module_label",
]
