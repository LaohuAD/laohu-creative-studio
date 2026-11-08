"""阅读主题目录与静态示例回归；不读取或改写用户文章。"""
import json
import unittest
from pathlib import Path

from studio_articles import validate_article_html

ROOT = Path(__file__).resolve().parents[1]
GALLERY = ROOT / 'static/article-templates'
READING = {'wedraft-plain-paper', 'wedraft-ink-journal', 'wedraft-jade-notes',
           'wedraft-blueprint', 'wedraft-cinnabar'}


class ArticleReadingTemplatesTest(unittest.TestCase):
    def test_catalog_has_reading_templates_and_keeps_default(self):
        data = json.loads((GALLERY / 'catalog.json').read_text(encoding='utf-8'))
        self.assertTrue(READING <= {t['id'] for t in data['templates']})
        self.assertEqual(data['templates'][0]['id'], 'moyu-green')
        for entry in data['templates']:
            if entry['id'] in READING:
                self.assertTrue(entry['name_en'])
                self.assertTrue(entry['description_en'])
                self.assertTrue(data['source_fingerprints']['themes'][entry['id']])

    def test_previews_are_safe_and_do_not_include_upstream_brand_copy(self):
        for theme in READING:
            with self.subTest(theme=theme):
                path = GALLERY / (theme + '.html')
                self.assertTrue(path.is_file(), '模板目录必须对应真实示例')
                body = path.read_text(encoding='utf-8')
                validate_article_html(body)
                self.assertIn('老胡画梦枋与老胡造梦技能', body)
                self.assertNotIn('小哈公社', body)
                self.assertNotIn('{{', body)

    def test_reading_license_and_directory_count_are_not_mislabelled(self):
        notice = (GALLERY / 'NOTICE.md').read_text(encoding='utf-8')
        self.assertIn('pafa/WeDraft', notice)
        self.assertIn('WEDRAFT-LICENSE', notice)
        license_text = (GALLERY / 'WEDRAFT-LICENSE').read_text(encoding='utf-8')
        self.assertIn('Copyright (c) 2026 pafa and WeDraft contributors', license_text)
        script = (ROOT / 'static/js/studio-projects.js').read_text(encoding='utf-8')
        self.assertNotIn('六种正文版式', script)
        self.assertNotIn('Six body layouts', script)


if __name__ == '__main__':
    unittest.main()
