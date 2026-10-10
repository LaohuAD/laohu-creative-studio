"""Stable Studio module identities and module-settings canvas metadata.

Business storage, slot capabilities, and generation behavior remain in their
own modules. This catalog only keeps cross-module identity labels and the
reserved settings-canvas identities used by project and connection routing.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


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

    @property
    def label(self) -> dict[str, str]:
        return {"zh": self.label_zh, "en": self.label_en}


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
        label_zh="Hypit克隆",
        label_en="Hypit Clone",
        project_module=True,
        connection_document=True,
        preparation_document=True,
        settings_canvas_id="hypit-settings",
        settings_project_id="__hypit_settings__",
        settings_canvas_url="/static/smart-canvas.html?id=hypit-settings&mode=hypit-settings",
        settings_canvas_title_zh="Hypit 生成配置",
        settings_canvas_title_en="Hypit generation settings",
        settings_canvas_kind="module-generation",
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
RESERVED_SETTINGS_CANVAS_IDS = frozenset(item.settings_canvas_id for item in _MODULES.values())
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
    "StudioModuleIdentity",
    "settings_canvas_identity",
    "studio_module_identity",
    "studio_module_label",
]
