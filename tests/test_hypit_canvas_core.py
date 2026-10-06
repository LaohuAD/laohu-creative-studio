"""Hypit 专用画布约束与普通画布提示词引用语义回归。"""
from __future__ import annotations

import copy
import unittest

import canvas_core.hypit_config as hypit_config
from canvas_core.hypit_config import (
    HYPIT_SETTINGS_CANVAS_ID,
    legacy_hypit_defaults_to_canvas,
    plan_hypit_slot,
    prepare_hypit_task_canvas,
    project_hypit_test_statuses,
    validate_hypit_settings_canvas,
    verify_hypit_slot_results,
)
from studio_execution import prompt_request_for, request_for


def flow_canvas():
    return {
        "id": HYPIT_SETTINGS_CANVAS_ID,
        "kind": "smart",
        "revision": 4,
        "nodes": [
            {"id": "prompt", "type": "smart-prompt", "text": "前置文字", "x": 10, "y": 20},
            {"id": "reference", "type": "smart-material", "sourceKind": "input", "hypitInputLocked": False,
             "images": [{"kind": "image", "url": "/api/materials/reference.png", "name": "参考图"}],
             "x": 100, "y": 200},
            {"id": "generator", "type": "smart-image-generator", "outputKind": "image",
             "runSettings": {"provider_id": "fixture", "model": "image-model", "count": 1},
             "promptDraftText": "需求", "x": 300, "y": 20},
            {"id": "output", "type": "smart-hypit-output", "hypitSlot": "image", "x": 600, "y": 20},
            {"id": "unrelated", "type": "smart-video-generator", "outputKind": "video",
             "runSettings": {"videoProvider": "fixture", "videoModel": "video-model"},
             "promptDraftText": "不相关分支", "x": 800, "y": 300},
        ],
        "connections": [
            {"from": "prompt", "to": "generator", "kind": "input"},
            {"from": "reference", "to": "generator", "kind": "input"},
            {"from": "generator", "to": "output", "kind": "input"},
        ],
    }


class HypitCanvasCoreTests(unittest.TestCase):
    def test_run_evidence_fingerprint_survives_connecting_output_after_success(self):
        before_connect = flow_canvas()
        before_connect["nodes"] = [node for node in before_connect["nodes"] if node["id"] != "output"]
        before_connect["connections"] = [edge for edge in before_connect["connections"] if edge["to"] != "output"]
        fingerprint = hypit_config.hypit_execution_recipe_fingerprint(before_connect, "generator")

        after_connect = copy.deepcopy(before_connect)
        after_connect["nodes"].append({"id": "output", "type": "smart-hypit-output", "hypitSlot": "image"})
        after_connect["connections"].append({"from": "generator", "to": "output", "kind": "input"})
        self.assertEqual(
            hypit_config.hypit_execution_recipe_fingerprint(after_connect, "generator"),
            fingerprint,
        )

        after_layout = copy.deepcopy(after_connect)
        after_layout["nodes"][2].update(x=1800, y=-600, title="换个位置")
        self.assertEqual(
            hypit_config.hypit_execution_recipe_fingerprint(after_layout, "generator"),
            fingerprint,
        )

        changed_upstream = copy.deepcopy(after_connect)
        changed_upstream["nodes"][0]["text"] = "改过的前置内容"
        self.assertNotEqual(
            hypit_config.hypit_execution_recipe_fingerprint(changed_upstream, "generator"),
            fingerprint,
        )

        # Agent 首次运行会补空元数据；补齐前后仍是同一条生成配方。
        normalized = copy.deepcopy(before_connect)
        source = next(node for node in normalized["nodes"] if node["id"] == "generator")
        source.update(creationDetails="", creationInputBinding=[], connections=[])
        self.assertEqual(
            hypit_config.hypit_execution_recipe_fingerprint(normalized, "generator"),
            fingerprint,
        )

    def test_run_evidence_projection_requires_server_task_current_recipe_and_managed_kind(self):
        canvas = flow_canvas()
        fingerprint = hypit_config.hypit_execution_recipe_fingerprint(canvas, "generator")
        canvas["nodes"][2]["creationTasks"] = [{"id": "studio-server-task"}]
        task = {
            "id": "studio-server-task",
            "canvas_id": HYPIT_SETTINGS_CANVAS_ID,
            "node_id": "generator",
            "kind": "image",
            "status": "succeeded",
            "created_at": 10,
            "hypit_source_node_id": "generator",
            "hypit_source_recipe_fingerprint": fingerprint,
            "hypit_supported_output_slots": ["image"],
            "result": {"media": [{"kind": "image", "resultId": "managed-image"}]},
        }
        tasks = {task["id"]: task}
        results = {"managed-image": {"id": "managed-image", "kind": "image", "_managed_verified": True}}

        statuses = hypit_config.project_hypit_execution_statuses(
            canvas, tasks.get, results.get,
        )
        self.assertTrue(statuses["output"]["test_passed"])
        self.assertEqual(statuses["output"]["output_kind"], "image")

        changed_recipe = copy.deepcopy(canvas)
        changed_recipe["nodes"][2]["promptDraftText"] = "更新后提示词"
        stale = hypit_config.project_hypit_execution_statuses(changed_recipe, tasks.get, results.get)["output"]
        self.assertFalse(stale["test_passed"])
        self.assertFalse(stale["current_recipe_matches"])

        wrong_task = copy.deepcopy(task)
        wrong_task["result"]["media"][0]["kind"] = "video"
        wrong_managed_kind = {"managed-image": {"id": "managed-image", "kind": "video", "_managed_verified": True}}
        wrong = hypit_config.project_hypit_execution_statuses(
            canvas, lambda _id: wrong_task, wrong_managed_kind.get,
        )["output"]
        self.assertFalse(wrong["test_passed"])
        self.assertEqual(wrong["output_kind"], "video")

        missing_managed_result = hypit_config.project_hypit_execution_statuses(canvas, tasks.get, lambda _id: None)["output"]
        self.assertFalse(missing_managed_result["test_passed"])

        failed_task = copy.deepcopy(task)
        failed_task["status"] = "failed"
        failed = hypit_config.project_hypit_execution_statuses(
            canvas, lambda _id: failed_task, results.get,
        )["output"]
        self.assertFalse(failed["test_passed"])

        forged_only_on_canvas = hypit_config.project_hypit_execution_statuses(
            canvas, lambda _id: None, results.get,
        )["output"]
        self.assertFalse(forged_only_on_canvas["test_passed"])

    def test_dynamic_app_evidence_uses_real_managed_output_kind(self):
        canvas = flow_canvas()
        generator = canvas["nodes"][2]
        generator.update(type="smart-ai-app", outputKind="image", runSettings={"rhAppId": "dynamic-app"})
        output = next(node for node in canvas["nodes"] if node["id"] == "output")
        output["hypitSlot"] = "video"
        fingerprint = hypit_config.hypit_execution_recipe_fingerprint(canvas, "generator")
        generator["creationTasks"] = [{"id": "studio-app-task"}]
        task = {
            "id": "studio-app-task", "canvas_id": HYPIT_SETTINGS_CANVAS_ID,
            "node_id": "generator", "kind": "ai_application", "status": "succeeded",
            "created_at": 11, "hypit_source_node_id": "generator",
            "hypit_source_recipe_fingerprint": fingerprint,
            "hypit_supported_output_slots": ["text", "image", "video", "audio", "music", "voice"],
            "result": {"media": [{"kind": "video", "resultId": "managed-video"}]},
        }
        managed = {"managed-video": {"id": "managed-video", "kind": "video", "_managed_verified": True}}
        status = hypit_config.project_hypit_execution_statuses(
            canvas, lambda _id: task, managed.get,
        )["output"]
        self.assertTrue(status["test_passed"])
        self.assertEqual(status["output_kind"], "video")

        unknown_task = copy.deepcopy(task)
        unknown_task["result"]["media"][0]["kind"] = "file"
        unknown = {"managed-video": {"id": "managed-video", "kind": "file", "_managed_verified": True}}
        status = hypit_config.project_hypit_execution_statuses(
            canvas, lambda _id: unknown_task, unknown.get,
        )["output"]
        self.assertFalse(status["test_passed"])

    def test_latest_task_wins_when_server_timestamps_share_a_millisecond(self):
        canvas = flow_canvas()
        fingerprint = hypit_config.hypit_execution_recipe_fingerprint(canvas, "generator")
        canvas["nodes"][2]["creationTasks"] = [{"id": "older"}, {"id": "newer"}]
        tasks = {
            "older": {
                "id": "older", "canvas_id": HYPIT_SETTINGS_CANVAS_ID, "node_id": "generator",
                "kind": "image", "status": "succeeded", "created_at": 20,
                "hypit_source_node_id": "generator", "hypit_source_recipe_fingerprint": fingerprint,
                "hypit_supported_output_slots": ["image"],
                "result": {"media": [{"kind": "image", "resultId": "managed-image"}]},
            },
            "newer": {
                "id": "newer", "canvas_id": HYPIT_SETTINGS_CANVAS_ID, "node_id": "generator",
                "kind": "image", "status": "failed", "created_at": 20,
                "hypit_source_node_id": "generator", "hypit_source_recipe_fingerprint": fingerprint,
                "hypit_supported_output_slots": ["image"], "error": "fixture failure",
                "result": {"media": []},
            },
        }
        managed = {"managed-image": {"id": "managed-image", "kind": "image", "_managed_verified": True}}
        status = hypit_config.project_hypit_execution_statuses(
            canvas, tasks.get, managed.get,
        )["output"]
        self.assertEqual(status["run_id"], "newer")
        self.assertEqual(status["status"], "failed")
        self.assertFalse(status["test_passed"])

    def test_reserved_id_and_single_slot_output_are_valid(self):
        canvas = flow_canvas()
        self.assertEqual(HYPIT_SETTINGS_CANVAS_ID, "hypit-settings")
        self.assertTrue(validate_hypit_settings_canvas(canvas))
        plan = plan_hypit_slot(canvas, "image", "output")
        self.assertEqual(plan["node_ids"], ["prompt", "reference", "generator", "output"])
        self.assertEqual(len(plan["connections"]), 3)
        self.assertEqual(len(plan["recipe_fingerprint"]), 64)

    def test_recipe_hash_ignores_layout_and_titles_but_tracks_prompt_and_locked_input(self):
        canvas = flow_canvas()
        baseline = plan_hypit_slot(canvas, "image", "output")["recipe_fingerprint"]
        moved = copy.deepcopy(canvas)
        moved["nodes"][0].update(x=800, y=-200, title="改了标题")
        self.assertEqual(plan_hypit_slot(moved, "image", "output")["recipe_fingerprint"], baseline)

        changed_prompt = copy.deepcopy(canvas)
        changed_prompt["nodes"][2]["promptDraftHtml"] = '<span class="mention-image-token" data-kind="text" data-text="新内容"></span>'
        self.assertNotEqual(plan_hypit_slot(changed_prompt, "image", "output")["recipe_fingerprint"], baseline)

        changed_lock = copy.deepcopy(canvas)
        changed_lock["nodes"][1]["hypitInputLocked"] = True
        self.assertNotEqual(plan_hypit_slot(changed_lock, "image", "output")["recipe_fingerprint"], baseline)

        execution_output = copy.deepcopy(canvas)
        execution_output["nodes"][2].update(sourceKind="result", outputKind="image", creationRevision=9,
                                             creationId="creation_after_run")
        self.assertEqual(plan_hypit_slot(execution_output, "image", "output")["recipe_fingerprint"], baseline)

    def test_output_slot_requires_one_inbound_edge_and_matching_static_kind(self):
        canvas = flow_canvas()
        second = {"id": "other", "type": "smart-image-generator", "outputKind": "image",
                  "runSettings": {"provider_id": "fixture", "model": "image-model"}}
        canvas["nodes"].append(second)
        canvas["connections"].append({"from": "other", "to": "output", "kind": "input"})
        with self.assertRaisesRegex(ValueError, "只能连接一个"):
            validate_hypit_settings_canvas(canvas)

        canvas = flow_canvas()
        canvas["nodes"][2]["outputKind"] = "video"
        with self.assertRaisesRegex(ValueError, "输出类型"):
            validate_hypit_settings_canvas(canvas)

        canvas = flow_canvas()
        canvas["nodes"][2]["type"] = "smart-video-generator"
        with self.assertRaisesRegex(ValueError, "输出类型"):
            validate_hypit_settings_canvas(canvas)

        canvas = flow_canvas()
        canvas["connections"].append({"from": "output", "to": "generator", "kind": "input"})
        with self.assertRaisesRegex(ValueError, "输出节点不能作为连线来源"):
            validate_hypit_settings_canvas(canvas)

        canvas = flow_canvas()
        canvas["connections"][-1] = {"from": "reference", "to": "output", "kind": "input"}
        with self.assertRaisesRegex(ValueError, "必须连接可执行节点"):
            plan_hypit_slot(canvas, "image", "output")

    def test_group_members_expand_the_execution_closure_without_persisting_fake_connections(self):
        canvas = {
            "id": HYPIT_SETTINGS_CANVAS_ID,
            "revision": 1,
            "nodes": [
                {"id": "member-prompt", "type": "smart-prompt", "text": "先生成一张参考图"},
                {"id": "member-image", "type": "smart-image-generator",
                 "runSettings": {"provider_id": "fixture", "model": "image-model"},
                 "promptDraftText": "成员图片"},
                {"id": "image-group", "type": "smart-group", "items": ["member-image"]},
                {"id": "final-image", "type": "smart-image-generator",
                 "runSettings": {"provider_id": "fixture", "model": "image-model"},
                 "promptDraftText": "基于分组图片继续生成"},
                {"id": "image-output", "type": "smart-hypit-output", "hypitSlot": "image"},
            ],
            "connections": [
                {"from": "member-prompt", "to": "member-image", "kind": "input"},
                {"from": "image-group", "to": "final-image", "kind": "input"},
                {"from": "final-image", "to": "image-output", "kind": "input"},
            ],
        }

        plan = plan_hypit_slot(canvas, "image", "image-output")

        self.assertEqual(plan["node_ids"], [
            "member-prompt", "member-image", "image-group", "final-image", "image-output",
        ])
        self.assertEqual(plan["member_dependencies"], [{"from": "member-image", "to": "image-group"}])
        self.assertEqual(plan["connections"], canvas["connections"])

    def test_prompt_draft_uses_inline_text_and_image_mentions_in_their_original_order(self):
        node = {
            "id": "image-node",
            "type": "smart-image-generator",
            "promptDraftText": "开头 @脚本一 中间 @参考图 以及 @脚本二 结尾",
            "promptDraftHtml": (
                '开头 <span class="mention-image-token" contenteditable="false" data-kind="text" data-name="脚本一" '
                'data-text="过期缓存一" data-node-id="script-one"><div class="mention-text-thumb"><i></i></div><span>脚本一</span></span> 中间 '
                '<span class="mention-image-token" contenteditable="false" data-kind="image" data-name="参考图" '
                'data-url="/api/materials/ref-image" data-node-id="ref"><img src="/api/materials/ref-image"><span>参考图</span></span> 以及 '
                '<span class="mention-image-token" contenteditable="false" data-kind="text" data-name="脚本二" '
                'data-text="过期缓存二" data-node-id="script-two"><div class="mention-text-thumb"><i></i></div><span>脚本二</span></span> 结尾'
            ),
            "runPromptRefs": [
                {"kind": "text", "text": "过期缓存一", "nodeId": "script-one", "name": "脚本一"},
                {"kind": "image", "url": "/api/materials/ref-image", "nodeId": "ref", "name": "参考图"},
                {"kind": "text", "text": "过期缓存二", "nodeId": "script-two", "name": "脚本二"},
            ],
            "runSettings": {"provider_id": "fixture", "model": "image-model", "count": 1},
        }
        current_sources = {
            "script-one": {"id": "script-one", "type": "smart-material", "images": [{"kind": "text", "text": "当前脚本一"}]},
            "script-two": {"id": "script-two", "type": "smart-material", "images": [{"kind": "text", "text": "当前脚本二"}]},
        }
        result = prompt_request_for(node, references=node["runPromptRefs"], source_nodes=current_sources, language="zh")
        self.assertEqual(result["prompt"], "参考图编号：\n图1：参考图\n\n用户需求：\n开头\n\n当前脚本一\n\n 中间 图1 以及\n\n当前脚本二\n\n 结尾")
        self.assertEqual([item["url"] for item in result["references"]], ["/api/materials/ref-image"])
        self.assertEqual(result["display_prompt"], "开头 @脚本一 中间 @参考图 以及 @脚本二 结尾")

    def test_normal_canvas_request_uses_same_inline_mentions_and_live_source_text(self):
        canvas = {
            "id": "hypit-settings",
            "nodes": [
                {"id": "one", "type": "smart-material", "images": [{"kind": "text", "text": "当前脚本一"}]},
                {"id": "ref", "type": "smart-material", "images": [{"kind": "image", "url": "/api/materials/ref-image", "name": "参考图"}]},
                {"id": "two", "type": "smart-material", "images": [{"kind": "text", "text": "当前脚本二"}]},
                {
                    "id": "generator", "type": "smart-image-generator", "promptDraftText": "旧纯文本草稿",
                    "promptDraftHtml": (
                        '开头 <span class="mention-image-token" data-kind="text" data-name="脚本一" '
                        'data-text="旧缓存一" data-node-id="one"><div><i></i></div><span>脚本一</span></span> 中间 '
                        '<span class="mention-image-token" data-kind="image" data-name="参考图" '
                        'data-url="/api/materials/stale-image" data-node-id="ref"><img><span>参考图</span></span> 以及 '
                        '<span class="mention-image-token" data-kind="text" data-name="脚本二" '
                        'data-text="旧缓存二" data-node-id="two"><div><i></i></div><span>脚本二</span></span> 结尾'
                    ),
                    "runSettings": {"provider_id": "fixture", "model": "image-model"},
                },
            ],
            "connections": [
                {"from": "one", "to": "generator", "kind": "input"},
                {"from": "ref", "to": "generator", "kind": "input"},
                {"from": "two", "to": "generator", "kind": "input"},
            ],
        }

        request = request_for(canvas, canvas["nodes"][-1])

        self.assertEqual(request["prompt"], "参考图编号：\n图1：参考图\n\n用户需求：\n开头\n\n当前脚本一\n\n 中间 图1 以及\n\n当前脚本二\n\n 结尾")
        self.assertEqual(request["inputs"]["reference"], ["/api/materials/ref-image"])
        self.assertEqual([ref.get("text") for ref in request["references"] if ref.get("kind") == "text"],
                         ["当前脚本一", "当前脚本二"])

    def test_single_text_mention_keeps_other_connected_text_before_inline_body(self):
        canvas = {
            "id": "hypit-settings",
            "nodes": [
                {"id": "director-note", "type": "smart-prompt", "text": "直连提示节点"},
                {"id": "lead", "type": "smart-material", "images": [{"kind": "text", "text": "未@文字前置"}]},
                {"id": "mentioned", "type": "smart-material", "images": [{"kind": "text", "text": "被@正文"}]},
                {"id": "generator", "type": "smart-image-generator", "runSettings": {"provider_id": "fixture", "model": "image-model"},
                 "promptDraftHtml": '正文 <span class="mention-image-token" data-kind="text" data-name="材料" data-text="旧正文缓存" data-node-id="mentioned"><div><i></i></div><span>材料</span></span> 结束'},
            ],
            "connections": [
                {"from": "director-note", "to": "generator", "kind": "input"},
                {"from": "lead", "to": "generator", "kind": "input"},
                {"from": "mentioned", "to": "generator", "kind": "input"},
            ],
        }

        request = request_for(canvas, canvas["nodes"][-1])

        self.assertEqual(request["prompt"], "直连提示节点\n\n未@文字前置\n\n正文\n\n被@正文\n\n 结束")
        self.assertEqual(request["prompt"].count("被@正文"), 1)

    def test_two_text_mentions_are_excluded_from_connected_prefix_and_live_image_wins_over_stale_reference(self):
        canvas = {
            "id": "hypit-settings",
            "nodes": [
                {"id": "lead", "type": "smart-material", "images": [{"kind": "text", "text": "未@文字前置"}]},
                {"id": "one", "type": "smart-material", "images": [{"kind": "text", "text": "实时一"}]},
                {"id": "ref", "type": "smart-material", "images": [{"kind": "image", "url": "/api/materials/runtime-image", "name": "当前参考"}]},
                {"id": "two", "type": "smart-material", "images": [{"kind": "text", "text": "实时二"}]},
                {"id": "generator", "type": "smart-image-generator", "runSettings": {"provider_id": "fixture", "model": "image-model"},
                 "runPromptRefs": [{"kind": "image", "url": "/api/materials/stale-image", "nodeId": "ref", "imageIndex": 0}],
                 "promptDraftHtml": (
                    '开头 <span class="mention-image-token" data-kind="text" data-name="一" data-text="旧一" data-node-id="one"><div><i></i></div><span>一</span></span> '
                    '<span class="mention-image-token" data-kind="image" data-name="参考" data-url="/api/materials/stale-image" data-node-id="ref"><img><span>参考</span></span> '
                    '<span class="mention-image-token" data-kind="text" data-name="二" data-text="旧二" data-node-id="two"><div><i></i></div><span>二</span></span> 结尾'
                 )},
            ],
            "connections": [
                {"from": "lead", "to": "generator", "kind": "input"},
                {"from": "one", "to": "generator", "kind": "input"},
                {"from": "ref", "to": "generator", "kind": "input"},
                {"from": "two", "to": "generator", "kind": "input"},
            ],
        }

        request = request_for(canvas, canvas["nodes"][-1])

        self.assertTrue(request["prompt"].startswith("参考图编号：\n图1：当前参考"))
        self.assertIn("用户需求：\n未@文字前置", request["prompt"])
        self.assertIn("实时一", request["prompt"])
        self.assertIn("实时二", request["prompt"])
        self.assertEqual(request["prompt"].count("实时一"), 1)
        self.assertEqual(request["prompt"].count("实时二"), 1)
        self.assertEqual(request["inputs"]["reference"], ["/api/materials/runtime-image"])

    def test_legacy_defaults_migrate_to_regular_nodes_without_losing_model_selection(self):
        canvas = legacy_hypit_defaults_to_canvas({
            "image": {"selection_kind": "api_model", "provider": "fixture", "model": "image-v1",
                      "region": "", "parameters": {"size": "1024x1024"}},
        })

        self.assertTrue(canvas["hypit_legacy_migration_done"])
        image_node = next(node for node in canvas["nodes"] if node["id"] == "hypit-run-image")
        self.assertEqual(image_node["type"], "smart-image-generator")
        self.assertEqual(image_node["runSettings"]["provider_id"], "fixture")
        self.assertEqual(image_node["runSettings"]["model"], "image-v1")
        self.assertEqual(image_node["hypitLegacySelection"]["parameters"], {"size": "1024x1024"})
        self.assertEqual({node["type"] for node in canvas["nodes"]}, {"smart-image-generator", "smart-hypit-output"})
        self.assertEqual(len(canvas["nodes"]), 2)
        self.assertEqual(next(node for node in canvas["nodes"] if node["id"] == "hypit-output-image")["hypitSlot"], "image")
        self.assertIn({"from": "hypit-run-image", "to": "hypit-output-image", "kind": "input"}, canvas["connections"])
        self.assertEqual(canvas["connections"], [{"from": "hypit-run-image", "to": "hypit-output-image", "kind": "input"}])
        prepared = prepare_hypit_task_canvas(canvas, "image", {"prompt": "迁移后的普通画布提示"}, "hypit-output-image")
        image_node = next(node for node in prepared["canvas"]["nodes"] if node["id"] == "hypit-run-image")
        request = request_for(prepared["canvas"], image_node)
        self.assertEqual(request["provider_id"], "fixture")
        self.assertEqual(request["model"], "image-v1")
        self.assertEqual(request["parameters"], {"size": "1024x1024"})
        self.assertEqual(request["prompt"], "迁移后的普通画布提示")

    def test_legacy_empty_prompt_scaffold_cleanup_requires_exact_proof_and_preserves_edits(self):
        upgrader = getattr(hypit_config, "upgrade_hypit_legacy_prompt_scaffold", None)
        self.assertTrue(callable(upgrader), "应提供只清理可证明旧自动空提示节点的纯投影 helper")
        canvas = legacy_hypit_defaults_to_canvas({
            "image": {"selection_kind": "api_model", "provider": "fixture", "model": "image-v1",
                      "region": "", "parameters": {"size": "1024x1024"}},
        })
        generator = next(node for node in canvas["nodes"] if node["id"] == "hypit-run-image")
        placeholder = {
            "id": "hypit-prompt-image", "type": "smart-material", "title": "本次提示词",
            "sourceKind": "input", "hypitInputLocked": False,
            "images": [], "x": 0, "y": 220,
        }
        canvas["nodes"].insert(canvas["nodes"].index(generator), placeholder)
        canvas["connections"].insert(0, {"from": placeholder["id"], "to": generator["id"], "kind": "input"})

        updated, changed = upgrader(canvas)
        self.assertTrue(changed)
        self.assertEqual(len(canvas["nodes"]), 3, "纯 helper 不得原位修改输入图")
        self.assertNotIn(placeholder["id"], {node["id"] for node in updated["nodes"]})
        self.assertEqual(updated["connections"], [{"from": "hypit-run-image", "to": "hypit-output-image", "kind": "input"}])

        edited = copy.deepcopy(canvas)
        edited_placeholder = next(node for node in edited["nodes"] if node["id"] == placeholder["id"])
        edited_placeholder["text"] = "用户写下的提示词"
        kept, edited_changed = upgrader(edited)
        self.assertFalse(edited_changed)
        self.assertEqual(next(node for node in kept["nodes"] if node["id"] == placeholder["id"])["text"], "用户写下的提示词")

        unmarked = copy.deepcopy(canvas)
        unmarked.pop("hypit_legacy_migration_done")
        kept, marked_changed = upgrader(unmarked)
        self.assertFalse(marked_changed)
        self.assertIn(placeholder["id"], {node["id"] for node in kept["nodes"]})

    def test_request_overrides_are_private_and_locked_material_stays_as_fixed_reference(self):
        canvas = flow_canvas()
        canvas["nodes"][2]["runSettings"]["capabilityParameters"] = {"image-model": {"size": "1024x1024", "quality": "standard"}}
        request = {"prompt": "本次请求", "parameters": {"quality": "high"},
                   "references": [{"kind": "image", "url": "/api/materials/runtime.png", "name": "本次参考"}]}

        prepared = prepare_hypit_task_canvas(canvas, "image", request, "output")
        task_graph = prepared["canvas"]
        generator = next(node for node in task_graph["nodes"] if node["id"] == "generator")
        locked_material = next(node for node in task_graph["nodes"] if node["id"] == "reference")

        self.assertEqual(generator["promptDraftText"], "需求")
        self.assertEqual(task_graph["nodes"][0]["text"], "本次请求")
        self.assertEqual(generator["runSettings"]["capabilityParameters"]["image-model"],
                         {"size": "1024x1024", "quality": "high"})
        self.assertEqual(locked_material["images"][0]["url"], "/api/materials/runtime.png")
        self.assertNotIn("manualInputRefs", generator)
        self.assertNotIn("manualInputRefs", canvas["nodes"][2])
        self.assertEqual(canvas["nodes"][2]["runSettings"]["capabilityParameters"]["image-model"]["quality"], "standard")

        other = prepare_hypit_task_canvas(canvas, "image", {"prompt": "并发任务", "parameters": {"quality": "low"}, "references": []}, "output")
        other_generator = next(node for node in other["canvas"]["nodes"] if node["id"] == "generator")
        self.assertEqual(other_generator["runSettings"]["capabilityParameters"]["image-model"]["quality"], "low")
        self.assertEqual(generator["runSettings"]["capabilityParameters"]["image-model"]["quality"], "high")

    def test_prompt_chooses_unique_unlocked_text_even_when_another_text_node_is_locked(self):
        canvas = {
            "id": "hypit-settings", "nodes": [
                {"id": "locked", "type": "smart-material", "hypitInputLocked": True,
                 "images": [{"kind": "text", "text": "固定脚本"}]},
                {"id": "editable", "type": "smart-material", "hypitInputLocked": False,
                 "images": [{"kind": "text", "text": "旧提示"}]},
                {"id": "generator", "type": "smart-image-generator", "runSettings": {"provider_id": "fixture", "model": "image-v1"}},
                {"id": "output", "type": "smart-hypit-output", "hypitSlot": "image"},
            ],
            "connections": [
                {"from": "locked", "to": "generator", "kind": "input"},
                {"from": "editable", "to": "generator", "kind": "input"},
                {"from": "generator", "to": "output", "kind": "input"},
            ],
        }
        task = prepare_hypit_task_canvas(canvas, "image", {"prompt": "本次提示"}, "output")["canvas"]
        nodes = {node["id"]: node for node in task["nodes"]}
        self.assertEqual(nodes["locked"]["images"][0]["text"], "固定脚本")
        self.assertEqual(nodes["editable"]["images"][0]["text"], "本次提示")

    def test_legacy_prompt_fallback_preserves_html_template_and_custom_graph_is_not_overwritten(self):
        legacy = {
            "id": "hypit-settings", "nodes": [
                {"id": "legacy-generator", "type": "smart-image-generator",
                 "hypitLegacySelection": {"model": "image-v1"}, "promptDraftText": "旧需求"},
                {"id": "output", "type": "smart-hypit-output", "hypitSlot": "image"},
            ],
            "connections": [{"from": "legacy-generator", "to": "output", "kind": "input"}],
        }
        prepared = prepare_hypit_task_canvas(legacy, "image", {"prompt": "新需求"}, "output")["canvas"]
        self.assertEqual(prepared["nodes"][0]["promptDraftText"], "新需求")

        custom = copy.deepcopy(legacy)
        custom["nodes"][0].pop("hypitLegacySelection")
        custom["nodes"][0]["promptDraftHtml"] = '<span class="mention-image-token" data-kind="text"></span>'
        with self.assertRaisesRegex(ValueError, "没有可接收提示词"):
            prepare_hypit_task_canvas(custom, "image", {"prompt": "不得覆盖"}, "output")
        self.assertIn("mention-image-token", custom["nodes"][0]["promptDraftHtml"])

    def test_request_prompt_updates_unlocked_text_material_and_preserves_mentions_and_locked_audio(self):
        canvas = {
            "id": "hypit-settings", "kind": "smart", "revision": 3,
            "nodes": [
                {"id": "script", "type": "smart-material", "sourceKind": "input", "hypitInputLocked": False,
                 "images": [{"kind": "text", "text": "旧脚本", "content": "旧脚本", "name": "脚本"}]},
                {"id": "fixed-audio", "type": "smart-material", "sourceKind": "input", "hypitInputLocked": True,
                 "images": [{"kind": "audio", "url": "/api/materials/fixed.wav", "name": "固定旁白"}]},
                {"id": "generator", "type": "smart-audio-generator", "runSettings": {"audioProvider": "fixture", "audioModel": "speech-v1"},
                 "promptDraftText": "普通画布固定正文", "promptDraftHtml": '先读 <span class="mention-image-token" data-kind="text" data-name="脚本" data-text="旧脚本缓存" data-node-id="script"><div><i></i></div><span>脚本</span></span> 再画'},
                {"id": "output", "type": "smart-hypit-output", "hypitSlot": "voice", "outputKind": "audio"},
            ],
            "connections": [
                {"from": "script", "to": "generator", "kind": "input"},
                {"from": "fixed-audio", "to": "generator", "kind": "input"},
                {"from": "generator", "to": "output", "kind": "input"},
            ],
        }
        original_html = canvas["nodes"][2]["promptDraftHtml"]
        original_prompt = canvas["nodes"][2]["promptDraftText"]

        prepared = prepare_hypit_task_canvas(canvas, "voice", {"prompt": "本次脚本"}, "output")
        task_nodes = {node["id"]: node for node in prepared["canvas"]["nodes"]}
        request = request_for(prepared["canvas"], task_nodes["generator"])

        self.assertEqual(request["kind"], "audio")
        self.assertEqual(task_nodes["script"]["images"][0]["text"], "本次脚本")
        self.assertEqual(task_nodes["script"]["images"][0]["content"], "本次脚本")
        self.assertEqual(task_nodes["fixed-audio"]["images"][0]["url"], "/api/materials/fixed.wav")
        self.assertEqual(task_nodes["generator"]["promptDraftHtml"], original_html)
        self.assertEqual(task_nodes["generator"]["promptDraftText"], original_prompt)
        self.assertEqual(request["inputs"]["reference_audio"], ["/api/materials/fixed.wav"])
        self.assertIn("本次脚本", request["prompt"])
        self.assertEqual(request["prompt"].count("本次脚本"), 1)
        self.assertEqual(canvas["nodes"][0]["images"][0]["text"], "旧脚本")

    def test_request_media_cannot_bypass_locked_material_through_generator_manual_refs(self):
        canvas = {
            "id": "hypit-settings", "kind": "smart", "revision": 2,
            "nodes": [
                {"id": "locked-audio", "type": "smart-material", "sourceKind": "input", "hypitInputLocked": True,
                 "images": [{"kind": "audio", "url": "/api/materials/fixed.wav"}]},
                {"id": "generator", "type": "smart-image-generator", "runSettings": {"provider_id": "fixture", "model": "image-v1"},
                 "promptDraftText": "固定需求"},
                {"id": "output", "type": "smart-hypit-output", "hypitSlot": "image", "outputKind": "image"},
            ],
            "connections": [
                {"from": "locked-audio", "to": "generator", "kind": "input"},
                {"from": "generator", "to": "output", "kind": "input"},
            ],
        }

        with self.assertRaisesRegex(ValueError, "锁定"):
            prepare_hypit_task_canvas(canvas, "image", {
                "references": [{"kind": "audio", "url": "/api/materials/request.wav", "role": "reference_audio"}],
            }, "output")
        self.assertNotIn("manualInputRefs", canvas["nodes"][1])

    def test_output_verification_returns_only_matching_results_but_rejects_wrong_or_unknown_only(self):
        values = verify_hypit_slot_results("image", [
            {"kind": "video", "url": "/api/results/clip"},
            {"kind": "image", "url": "/api/results/frame"},
            {"kind": "file", "url": "/api/results/unknown"},
        ])
        self.assertEqual([item["kind"] for item in values], ["image"])
        with self.assertRaisesRegex(ValueError, "没有返回可确认"):
            verify_hypit_slot_results("image", [{"kind": "file", "url": "/api/results/unknown"}])
        with self.assertRaisesRegex(ValueError, "没有返回可确认"):
            verify_hypit_slot_results("image", [{"kind": "video", "url": "/api/results/clip"}])

    def test_output_verification_keeps_audio_for_music_and_voice_semantic_slots(self):
        mixed = [
            {"kind": "text", "url": "/api/results/lyrics"},
            {"kind": "audio", "url": "/api/results/song.wav"},
        ]
        self.assertEqual(verify_hypit_slot_results("music", mixed), [mixed[1]])
        self.assertEqual(verify_hypit_slot_results("voice", mixed), [mixed[1]])

    def test_test_status_projection_requires_same_recipe_and_typed_success(self):
        canvas = flow_canvas()
        fingerprint = plan_hypit_slot(canvas, "image", "output")["recipe_fingerprint"]
        run = {
            "run_id": "run-current",
            "node_id": "generator",
            "capability_snapshot": {
                "hypit_output_test": True, "hypit_slot": "image", "output_node_id": "output",
                "recipe_fingerprint": fingerprint, "output_kind": "image",
            },
            "attempts": [{"status": "succeeded", "error": ""}],
        }

        passed = project_hypit_test_statuses(canvas, [run])
        self.assertEqual(passed["output"]["status"], "passed")
        self.assertTrue(passed["output"]["test_passed"])
        self.assertTrue(passed["output"]["current_recipe_matches"])

        stale = copy.deepcopy(run)
        stale["capability_snapshot"]["recipe_fingerprint"] = "0" * 64
        stale_status = project_hypit_test_statuses(canvas, [stale])["output"]
        self.assertFalse(stale_status["test_passed"])
        self.assertFalse(stale_status["current_recipe_matches"])

        wrong_kind = copy.deepcopy(run)
        wrong_kind["capability_snapshot"]["output_kind"] = "video"
        wrong_status = project_hypit_test_statuses(canvas, [wrong_kind])["output"]
        self.assertFalse(wrong_status["test_passed"])
        self.assertEqual(wrong_status["output_kind"], "video")


if __name__ == "__main__":
    unittest.main()
