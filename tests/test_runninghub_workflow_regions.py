import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main


class RunningHubWorkflowRegionTests(unittest.TestCase):
    def setUp(self):
        cache = ROOT / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=cache)
        self.root = Path(self.temporary.name)
        self.store_file = self.root / "runninghub_workflows.json"
        self.providers_file = self.root / "api_providers.json"
        self.patches = ExitStack()
        self.patches.enter_context(patch.object(main, "RUNNINGHUB_WORKFLOW_STORE_FILE", str(self.store_file)))
        self.patches.enter_context(patch.object(main, "API_PROVIDERS_FILE", str(self.providers_file)))
        self.patches.enter_context(patch.object(main, "DATA_DIR", str(self.root / "data")))
        self.patches.enter_context(patch.object(main, "STATIC_RUNNINGHUB_DIR", str(self.root / "static")))
        self.patches.enter_context(patch.object(main, "STATIC_RUNNINGHUB_API_PROVIDERS_FILE", str(self.root / "static" / "api_providers.json")))
        self.addCleanup(self.patches.close)
        self.addCleanup(self.temporary.cleanup)

    @staticmethod
    def workflow_payload(region, value):
        return main.RunningHubWorkflowConfig(
            workflowId="shared-workflow",
            title=f"{region} workflow",
            region=region,
            fields=[{
                "id": "prompt",
                "nodeId": "node-1",
                "fieldName": "prompt",
                "fieldValue": value,
            }],
            workflowJson={"region": region},
        )

    @staticmethod
    def provider(selected_region="cn"):
        return main.normalize_provider({
            "id": "runninghub",
            "rh_region": selected_region,
            "rh_regions": {
                "cn": {"enabled": True, "rh_workflows": []},
                "global": {"enabled": True, "rh_workflows": []},
            },
        })

    def save_both_regions(self):
        with patch.object(main, "sync_runninghub_workflow_to_provider"):
            main.save_runninghub_workflow(
                "shared-workflow",
                self.workflow_payload("cn", "cn-value"),
            )
            main.save_runninghub_workflow(
                "shared-workflow",
                self.workflow_payload("global", "global-value"),
            )

    def test_same_workflow_id_reads_the_selected_region_config(self):
        self.save_both_regions()

        with patch.object(main, "runninghub_provider_workflow_config", return_value=None):
            cn = main.get_runninghub_workflow("shared-workflow", region="cn")["workflow"]
            global_cfg = main.get_runninghub_workflow("shared-workflow", region="global")["workflow"]

        self.assertEqual(cn["fields"][0]["fieldValue"], "cn-value")
        self.assertEqual(global_cfg["fields"][0]["fieldValue"], "global-value")

    def test_deleting_one_region_keeps_the_other_region_store_entry(self):
        self.save_both_regions()

        with patch.object(main, "runninghub_provider_workflow_config", return_value=None), \
             patch.object(main, "remove_runninghub_workflow_from_provider"):
            main.delete_runninghub_workflow("shared-workflow", region="cn")
            with self.assertRaises(main.HTTPException) as raised:
                main.get_runninghub_workflow("shared-workflow", region="cn")
            global_cfg = main.get_runninghub_workflow("shared-workflow", region="global")["workflow"]

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(global_cfg["fields"][0]["fieldValue"], "global-value")

    def test_legacy_flat_store_is_owned_by_the_original_selected_region(self):
        self.store_file.write_text(json.dumps({
            "shared-workflow": {
                "workflowId": "shared-workflow",
                "title": "legacy",
                "fields": [{"id": "prompt", "fieldValue": "legacy-cn-value"}],
                "workflowJson": {"legacy": True},
                "updatedAt": 1,
            }
        }), encoding="utf-8")
        provider = self.provider("cn")

        with patch.object(main, "load_api_providers", return_value=[provider]):
            cn = main.get_runninghub_workflow("shared-workflow", region="cn")["workflow"]
            with self.assertRaises(main.HTTPException) as raised:
                main.get_runninghub_workflow("shared-workflow", region="global")

        self.assertEqual(cn["fields"][0]["fieldValue"], "legacy-cn-value")
        self.assertEqual(raised.exception.status_code, 404)

    def test_hidden_workflow_ids_are_scoped_to_the_selected_region(self):
        self.providers_file.write_text(json.dumps([{
            "id": "runninghub",
            "rh_region": "cn",
            "rh_regions": {
                "cn": {"rh_workflows": [{"id": "shared-workflow", "hidden": True}]},
                "global": {"rh_workflows": [{"id": "shared-workflow", "hidden": False}]},
            },
        }]), encoding="utf-8")

        self.assertEqual(main.runninghub_saved_hidden_workflow_ids("cn"), {"shared-workflow"})
        self.assertEqual(main.runninghub_saved_hidden_workflow_ids("global"), set())

    def test_provider_store_merge_only_exposes_the_selected_region(self):
        self.save_both_regions()

        with patch.object(main, "runninghub_saved_hidden_workflow_ids", return_value=set()):
            cn = main.runninghub_provider_with_workflow_store(self.provider("cn"))
            global_provider = main.runninghub_provider_with_workflow_store(self.provider("global"))

        self.assertEqual(cn["rh_workflows"][0]["fields"][0]["fieldValue"], "cn-value")
        self.assertEqual(global_provider["rh_workflows"][0]["fields"][0]["fieldValue"], "global-value")

    def test_execution_config_lookup_consumes_the_selected_region(self):
        self.save_both_regions()
        provider = self.provider("global")

        with patch.object(main, "runninghub_provider_workflow_config", return_value=None):
            cn = main.runninghub_entry_config_from_model(
                main.runninghub_provider_for_region(provider, "cn"),
                "workflow:shared-workflow",
                region="cn",
            )
            global_cfg = main.runninghub_entry_config_from_model(
                provider,
                "workflow:shared-workflow",
                region="global",
            )

        self.assertEqual(cn["fields"][0]["fieldValue"], "cn-value")
        self.assertEqual(global_cfg["fields"][0]["fieldValue"], "global-value")

    def test_list_route_is_region_scoped(self):
        self.save_both_regions()
        self.providers_file.write_text(json.dumps([self.provider("global")]), encoding="utf-8")

        cn = main.list_runninghub_workflows(region="cn")
        global_items = main.list_runninghub_workflows(region="global")["workflows"]
        cn_item = next(item for item in cn["workflows"] if item["workflowId"] == "shared-workflow")
        global_item = next(item for item in global_items if item["workflowId"] == "shared-workflow")

        self.assertEqual(cn_item["title"], "cn workflow")
        self.assertEqual(global_item["title"], "global workflow")

    def test_pruning_one_region_does_not_remove_the_other_region_store_entry(self):
        self.store_file.write_text(json.dumps({
            "cn::shared-workflow": {
                "workflowId": "shared-workflow",
                "region": "cn",
                "fields": [{"id": "prompt", "fieldValue": "cn-value"}],
            },
            "global::shared-workflow": {
                "workflowId": "shared-workflow",
                "region": "global",
                "fields": [{"id": "prompt", "fieldValue": "global-value"}],
            },
        }), encoding="utf-8")

        main.prune_runninghub_workflow_store_for_provider(self.provider("cn"), region="cn")
        stored = main.load_runninghub_workflow_store()

        self.assertNotIn("cn::shared-workflow", stored)
        self.assertIn("global::shared-workflow", stored)

    def test_provider_sync_and_remove_are_region_scoped(self):
        provider = main.normalize_provider({
            "id": "runninghub",
            "rh_region": "cn",
            "rh_regions": {
                "cn": {"enabled": True, "rh_workflows": [{"id": "shared-workflow", "fields": [{"id": "prompt", "fieldValue": "old-cn"}]}]},
                "global": {"enabled": True, "rh_workflows": [{"id": "shared-workflow", "fields": [{"id": "global-value", "fieldValue": "global-value"}]}]},
            },
        })
        saved = []
        with patch.object(main, "load_api_providers", return_value=[provider]), \
             patch.object(main, "save_api_providers", side_effect=lambda value: saved.append(value)), \
             patch.object(main, "sync_runninghub_provider_workflows_to_static_template", return_value=False):
            main.sync_runninghub_workflow_to_provider({
                "workflowId": "shared-workflow",
                "region": "cn",
                "fields": [{"id": "prompt", "fieldValue": "new-cn"}],
                "workflowJson": {"region": "cn"},
            }, region="cn")

        synced = saved[-1][0]
        self.assertEqual(synced["rh_regions"]["cn"]["rh_workflows"][0]["fields"][0]["fieldValue"], "new-cn")
        self.assertEqual(synced["rh_regions"]["global"]["rh_workflows"][0]["fields"][0]["fieldValue"], "global-value")

        saved.clear()
        with patch.object(main, "load_api_providers", return_value=[synced]), \
             patch.object(main, "save_api_providers", side_effect=lambda value: saved.append(value)), \
             patch.object(main, "load_static_runninghub_provider", return_value=None):
            main.remove_runninghub_workflow_from_provider("shared-workflow", region="cn")

        removed = saved[-1][0]
        self.assertEqual(removed["rh_regions"]["cn"]["rh_workflows"], [])
        self.assertEqual(removed["rh_regions"]["global"]["rh_workflows"][0]["id"], "shared-workflow")


if __name__ == "__main__":
    unittest.main()
