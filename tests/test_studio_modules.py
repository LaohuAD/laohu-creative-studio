from __future__ import annotations

import unittest
from pathlib import Path

from canvas_core.hypit_config import SETTINGS_CANVAS_MODULES
from studio_canvas_settings import CANVAS_SETTINGS_CANVAS_ID, CANVAS_SETTINGS_CANVAS_URL
from studio_module_models import module_descriptors
from studio_modules import (
    CONNECTION_MODULE_IDS,
    MODULE_SETTINGS_CANVAS_MODULES,
    PREPARATION_MODULE_IDS,
    PROJECT_MODULE_IDS,
    RESERVED_SETTINGS_CANVAS_IDS,
    STUDIO_MODULES,
    studio_module_label,
)


class StudioModuleIdentityTests(unittest.TestCase):
    def test_manuscript_catalog_labels_match_navigation_and_module_pages(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(STUDIO_MODULES["script"].label_zh, "剧本创作")
        self.assertEqual(STUDIO_MODULES["script"].label_en, "Script Writing")
        self.assertEqual(STUDIO_MODULES["novel"].label_zh, "小说创作")
        self.assertEqual(STUDIO_MODULES["novel"].label_en, "Novel Writing")

        index = (root / "static/index.html").read_text(encoding="utf-8")
        for module in ("script", "novel"):
            self.assertIn(f'id="nav-{module}"', index)
            self.assertIn(f'id="frame-{module}"', index)
            self.assertIn(f'data-src="/static/{module}-list.html"', index)

        translations = (root / "static/js/i18n/studio.js").read_text(encoding="utf-8")
        projects = (root / "static/js/studio-projects.js").read_text(encoding="utf-8")
        self.assertIn('"nav.script": { zh: "剧本创作", en: "Script Writing" }', translations)
        self.assertIn('"nav.novel": { zh: "小说创作", en: "Novel Writing" }', translations)
        self.assertIn("title:'Script Writing'", projects)
        self.assertIn("title:'Novel Writing'", projects)

    def test_module_labels_are_single_source_for_model_descriptors(self):
        descriptors = module_descriptors()
        self.assertEqual(set(descriptors), {"canvas", "hypit", "article", "music", "script", "novel"})
        self.assertEqual(descriptors["canvas"]["label"], {"zh": "画布", "en": "Canvas"})
        self.assertEqual(descriptors["hypit"]["label"], {"zh": "Hypit克隆", "en": "Hypit Clone"})
        self.assertEqual(descriptors["article"]["label"], {"zh": "公众号文章", "en": "Article"})
        self.assertEqual(descriptors["music"]["label"], {"zh": "音乐创作", "en": "Music Creation"})
        for module_id in ("script", "novel"):
            descriptor = descriptors[module_id]
            self.assertEqual(descriptor["label"], studio_module_label(module_id))
            self.assertEqual(descriptor["selection_policy"], "fixed")
            self.assertEqual([item["id"] for item in descriptor["slots"]], ["text"])
            self.assertEqual(descriptor["slots"][0]["node_type"], "text_generation")
        for module_id, descriptor in descriptors.items():
            self.assertEqual(descriptor["label"], studio_module_label(module_id))

    def test_project_connection_and_settings_ids_are_closed_over_catalog(self):
        expected_modules = {"canvas", "hypit", "article", "music", "script", "novel"}
        self.assertEqual(PROJECT_MODULE_IDS, expected_modules)
        self.assertEqual(CONNECTION_MODULE_IDS, expected_modules)
        self.assertEqual(PREPARATION_MODULE_IDS, expected_modules)
        self.assertEqual(
            dict(MODULE_SETTINGS_CANVAS_MODULES),
            {"hypit-settings": "hypit", "article-settings": "article", "music-settings": "music",
             "script-settings": "script", "novel-settings": "novel"},
        )
        self.assertEqual(SETTINGS_CANVAS_MODULES, dict(MODULE_SETTINGS_CANVAS_MODULES))
        self.assertEqual(
            RESERVED_SETTINGS_CANVAS_IDS,
            {"canvas-settings", "hypit-settings", "article-settings", "music-settings",
             "script-settings", "novel-settings"},
        )
        for module_id in ("script", "novel"):
            identity = STUDIO_MODULES[module_id]
            self.assertEqual(identity.settings_canvas_id, f"{module_id}-settings")
            self.assertEqual(identity.settings_canvas_mode, identity.settings_canvas_id)
            self.assertEqual(identity.settings_canvas_slots, ("text",))
            self.assertIn(f"id={module_id}-settings&mode={module_id}-settings", identity.settings_canvas_url)

    def test_canvas_model_settings_keep_the_existing_public_constant_names(self):
        identity = STUDIO_MODULES["canvas"]
        self.assertEqual(CANVAS_SETTINGS_CANVAS_ID, identity.settings_canvas_id)
        self.assertEqual(CANVAS_SETTINGS_CANVAS_URL, identity.settings_canvas_url)
        self.assertEqual(CANVAS_SETTINGS_CANVAS_ID, "canvas-settings")


if __name__ == "__main__":
    unittest.main()
