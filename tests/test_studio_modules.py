from __future__ import annotations

import unittest

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
    def test_module_labels_are_single_source_for_model_descriptors(self):
        descriptors = module_descriptors()
        self.assertEqual(set(descriptors), set(STUDIO_MODULES))
        self.assertEqual(descriptors["canvas"]["label"], {"zh": "画布", "en": "Canvas"})
        self.assertEqual(descriptors["hypit"]["label"], {"zh": "Hypit克隆", "en": "Hypit Clone"})
        self.assertEqual(descriptors["article"]["label"], {"zh": "公众号文章", "en": "Article"})
        self.assertEqual(descriptors["music"]["label"], {"zh": "音乐创作", "en": "Music Creation"})
        for module_id, descriptor in descriptors.items():
            self.assertEqual(descriptor["label"], studio_module_label(module_id))

    def test_project_connection_and_settings_ids_are_closed_over_catalog(self):
        expected_modules = {"canvas", "hypit", "article", "music"}
        self.assertEqual(PROJECT_MODULE_IDS, expected_modules)
        self.assertEqual(CONNECTION_MODULE_IDS, expected_modules)
        self.assertEqual(PREPARATION_MODULE_IDS, expected_modules)
        self.assertEqual(
            dict(MODULE_SETTINGS_CANVAS_MODULES),
            {"hypit-settings": "hypit", "article-settings": "article", "music-settings": "music"},
        )
        self.assertEqual(SETTINGS_CANVAS_MODULES, dict(MODULE_SETTINGS_CANVAS_MODULES))
        self.assertEqual(
            RESERVED_SETTINGS_CANVAS_IDS,
            {"canvas-settings", "hypit-settings", "article-settings", "music-settings"},
        )

    def test_canvas_model_settings_keep_the_existing_public_constant_names(self):
        identity = STUDIO_MODULES["canvas"]
        self.assertEqual(CANVAS_SETTINGS_CANVAS_ID, identity.settings_canvas_id)
        self.assertEqual(CANVAS_SETTINGS_CANVAS_URL, identity.settings_canvas_url)
        self.assertEqual(CANVAS_SETTINGS_CANVAS_ID, "canvas-settings")


if __name__ == "__main__":
    unittest.main()
