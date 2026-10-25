from __future__ import annotations

import ast
import copy
import tempfile
import threading
import unittest
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from canvas_core.hypit_config import validate_hypit_settings_canvas
from studio_hypit_canvas import (
    HypitSettingsCanvasService,
    NOVEL_SETTINGS_CANVAS_ID,
    SCRIPT_SETTINGS_CANVAS_ID,
    create_hypit_settings_canvas_router,
)
from studio_manuscripts import StudioManuscriptStore, create_studio_manuscripts_router
from studio_projects import StudioProjectStore, create_studio_projects_router


ROOT = Path(__file__).resolve().parents[1]
VALIDATION_ROOT = ROOT / ".cache" / "validation" / "studio-manuscript-settings-routes"


class _CanvasAdapter:
    def list(self):
        return []

    def get(self, _project_id):
        return None

    def create(self, _name):
        raise AssertionError("script/novel projects must not create canvas projects")

    def rename(self, *_args, **_kwargs):
        raise AssertionError("script/novel projects must not rename canvas projects")

    def delete(self, *_args, **_kwargs):
        raise AssertionError("script/novel projects must not delete canvas projects")


def _settings_service(module_id: str, canvas_id: str) -> HypitSettingsCanvasService:
    records: dict[str, dict] = {}
    lock = threading.RLock()

    def load_canvas(requested_id: str):
        current = records.get(requested_id)
        if current is None:
            raise HTTPException(status_code=404, detail="画布不存在")
        return copy.deepcopy(current)

    def save_canvas(candidate, *, increment_revision: bool, touch_updated_at: bool):
        saved = copy.deepcopy(dict(candidate))
        previous = records.get(canvas_id)
        if previous is not None and increment_revision:
            saved["revision"] = int(previous.get("revision") or 1) + 1
        if touch_updated_at:
            saved["updated_at"] = int(saved.get("updated_at") or 1000) + 1
        records[canvas_id] = saved
        return copy.deepcopy(saved)

    return HypitSettingsCanvasService(
        load_canvas=load_canvas,
        save_canvas=save_canvas,
        lock=lock,
        load_legacy_settings=lambda: None,
        backup_legacy_settings=lambda _record: None,
        migrate_legacy_settings=lambda _defaults, _canvas_id: {},
        validate_canvas=validate_hypit_settings_canvas,
        test_statuses=lambda _canvas_id, _canvas: {},
        broadcast_canvas_updated=lambda *_args: None,
        now_ms=lambda: 1000,
        canvas_id=canvas_id,
        module_id=module_id,
    )


class StudioManuscriptSettingsRouteTests(unittest.TestCase):
    def test_main_registers_static_manuscript_settings_before_project_id_routes(self):
        """The production include order must put both fixed paths before dynamic IDs."""
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        calls: list[tuple[int, str, str | None]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "include_router"):
                continue
            router = node.args[0] if node.args else None
            if not isinstance(router, ast.Call) or not isinstance(router.func, ast.Name):
                continue
            if router.func.id == "create_studio_manuscripts_router":
                calls.append((node.lineno, "manuscripts", None))
            elif router.func.id == "create_hypit_settings_canvas_router":
                service = next((kw.value for kw in router.keywords if kw.arg == "service"), None)
                if isinstance(service, ast.Name) and service.id in {
                    "SCRIPT_SETTINGS_CANVAS_SERVICE", "NOVEL_SETTINGS_CANVAS_SERVICE",
                }:
                    calls.append((node.lineno, "settings", service.id))

        calls.sort()
        manuscript_lines = [line for line, kind, _ in calls if kind == "manuscripts"]
        self.assertEqual(len(manuscript_lines), 1)
        manuscript_line = manuscript_lines[0]
        settings_lines = {service: line for line, kind, service in calls if kind == "settings"}
        self.assertEqual(set(settings_lines), {
            "SCRIPT_SETTINGS_CANVAS_SERVICE", "NOVEL_SETTINGS_CANVAS_SERVICE",
        })
        self.assertLess(settings_lines["SCRIPT_SETTINGS_CANVAS_SERVICE"], manuscript_line)
        self.assertLess(settings_lines["NOVEL_SETTINGS_CANVAS_SERVICE"], manuscript_line)

    def test_settings_get_reset_and_normal_project_get_share_production_router_order(self):
        """Run the production router factories in main.py's verified order on isolated storage."""
        VALIDATION_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=VALIDATION_ROOT) as temp_root:
            adapter = _CanvasAdapter()
            projects = StudioProjectStore(temp_root, adapter)
            manuscripts = StudioManuscriptStore(temp_root, projects)
            app = FastAPI()
            app.include_router(create_studio_projects_router(temp_root, adapter, store=projects))

            # This is the same order asserted against main.py above: fixed paths
            # before the manuscript routes containing `{project_id}`.
            app.include_router(create_hypit_settings_canvas_router(
                service=_settings_service("script", SCRIPT_SETTINGS_CANVAS_ID),
                base_path="/api/studio/scripts/settings-canvas",
                include_test_routes=False,
            ))
            app.include_router(create_hypit_settings_canvas_router(
                service=_settings_service("novel", NOVEL_SETTINGS_CANVAS_ID),
                base_path="/api/studio/novels/settings-canvas",
                include_test_routes=False,
            ))
            app.include_router(create_studio_manuscripts_router(manuscripts))

            with TestClient(app, client=("127.0.0.1", 42000)) as client:
                for module, plural, canvas_id in (
                    ("script", "scripts", SCRIPT_SETTINGS_CANVAS_ID),
                    ("novel", "novels", NOVEL_SETTINGS_CANVAS_ID),
                ):
                    opened = client.get(f"/api/studio/{plural}/settings-canvas")
                    self.assertEqual(opened.status_code, 200, opened.text)
                    self.assertEqual(opened.json()["id"], canvas_id)
                    self.assertEqual(opened.json()["canvas"]["id"], canvas_id)
                    revision = opened.json()["canvas"]["revision"]

                    reset = client.post(
                        f"/api/studio/{plural}/settings-canvas/reset",
                        json={"base_revision": revision, "client_id": "route-order-test"},
                    )
                    self.assertEqual(reset.status_code, 200, reset.text)
                    self.assertTrue(reset.json()["reset"])
                    self.assertEqual(reset.json()["canvas"]["id"], canvas_id)
                    self.assertEqual(reset.json()["canvas"]["revision"], revision + 1)

                    created = client.post("/api/studio/projects", json={
                        "module": module, "name": f"isolated {module} project",
                    })
                    self.assertEqual(created.status_code, 200, created.text)
                    project_id = created.json()["project"]["id"]
                    ordinary = client.get(f"/api/studio/{plural}/{project_id}")
                    self.assertEqual(ordinary.status_code, 200, ordinary.text)
                    self.assertEqual(ordinary.json()["project"]["id"], project_id)


if __name__ == "__main__":
    unittest.main()
