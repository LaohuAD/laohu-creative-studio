"""Isolated Chrome regressions for the script and novel project reader."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def browser_binary():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"), shutil.which("chromium"),
    ]
    return next((path for path in candidates if path and Path(path).is_file()), None)


CHROME = browser_binary()
NODE = shutil.which("node")


def sample_data():
    scene_body = "开场未分段🙂\n\n片段甲文本\n\n中间未分段\n\n片段乙文本\n\n结尾未分段"
    segment_a = "片段甲文本"
    segment_b = "片段乙文本"
    a_start = len(scene_body[:scene_body.index(segment_a)])
    b_start = len(scene_body[:scene_body.index(segment_b)])
    chapter = (
        "# 第一章\n\n普通正文，保留 & < > 字符。\n\n"
        "| 项目 | 描述 |\n| :--- | ---: |\n| 线索 | 表格仍可读 |\n\n"
        "<script>window.__manuscriptXss = true</script>\n\n"
        "[危险链接](javascript:window.__manuscriptXss=true) 与 [安全链接](https://example.com/story)。\n\n"
        "行内代码：`<img src=x onerror=alert(1)>`"
    )
    v1 = "# 早期设定\n\n主角起初谨慎。"
    v2 = "# 林青\n\n性格底色：沉着，遇事会先观察。\n\n故事阶段：起点。"
    return {
        "lock": threading.RLock(),
        "projects": [
            {"id": "script-fixture", "name": "隔离剧本作品", "module": "script", "revision": 1, "updated_at": 1791580800},
            {"id": "novel-fixture", "name": "隔离小说作品", "module": "novel", "revision": 1, "updated_at": 1791580800},
        ],
        "next_project": 1,
        "script": {
            "revision": 1, "state": "structured", "draft": "", "next_outline_id": 2,
            "archive": [],
            "episodes": [{"id": "episode-1", "title": "第 1 集", "outline_markdown": "", "outline_revision": 0, "outline_history": [], "scenes": [{
                "id": "scene-1", "title": "第 1 场", "body_markdown": scene_body, "scene_revision": 1,
                "content_sha256": hashlib.sha256(scene_body.encode("utf-8")).hexdigest(),
                "editable_markdown": scene_body,
                "segments": [
                    {"id": "segment-1", "title": "素材分段甲", "start": a_start, "end": a_start + len(segment_a)},
                    {"id": "segment-2", "title": "第二段", "start": b_start, "end": b_start + len(segment_b)},
                ],
            }]}],
        },
        "novel": {
            "revision": 1, "next_outline_id": 2,
            "archive": [],
            "chapter": {"id": "chapter-1", "title": "第一章", "volume_id": "volume-1", "body_markdown": chapter, "content_sha256": hashlib.sha256(chapter.encode("utf-8")).hexdigest(), "chapter_revision": 1, "outline_markdown": "", "outline_revision": 0, "outline_history": []},
            "volume": {"id": "volume-1", "title": "第一卷"},
            "volumes": [],
            "settings": {
                "categories": [
                    {"id": "characters", "title": {"zh": "人物", "en": "Characters"}},
                    {"id": "relationships", "title": {"zh": "关系与势力", "en": "Relationships & Factions"}},
                    {"id": "locations", "title": {"zh": "场景与地点", "en": "Locations"}},
                    {"id": "props", "title": {"zh": "道具与资源", "en": "Props & Resources"}},
                    {"id": "abilities", "title": {"zh": "能力与规则", "en": "Abilities & Rules"}},
                    {"id": "world", "title": {"zh": "世界设定", "en": "Worldbuilding"}},
                    {"id": "timeline", "title": {"zh": "事件与时间线", "en": "Events & Timeline"}},
                ],
                "entries": [
                    {"id": "character-linqing", "category_id": "characters", "title": "林青", "current_version_id": "version-2", "versions": [
                        {"id": "version-1", "story_version": 1, "use_state": "confirmed", "story_anchor": {"kind": "baseline"}, "edit_revision": 1, "body_markdown": v1, "history": []},
                        {"id": "version-2", "story_version": 2, "use_state": "draft", "story_anchor": {"kind": "unspecified"}, "edit_revision": 2, "body_markdown": v2,
                         "history": [{"revision": 1, "body_markdown": "# 林青\n\n性格底色：沉着。"}]},
                    ]},
                    {"id": "world-rules", "category_id": "world", "title": "世界规则", "current_version_id": "world-version-1", "versions": [
                        {"id": "world-version-1", "story_version": 1, "use_state": "draft", "story_anchor": {"kind": "unspecified"}, "edit_revision": 1, "body_markdown": "# 世界规则\n\n不自动补全设定。", "history": []},
                    ]},
                ],
            },
            "handoff": None,
        },
        "receipts": {}, "command_attempts": [], "view_requests": [], "fail_next_command": False, "conflict_next_command": False,
        "drop_next_command_response": False, "unknown_next_command_response": False,
        "empty_next_receipt_lookup": False, "not_found_next_receipt_lookup": False,
        "generation_attempts": [], "generation_operations": {}, "generations": {}, "get_requests": [], "get_responses": [],
        "settings_model_option_requests": [],
        "unknown_next_generation_response": False, "conflict_next_generation_apply": False,
    }
    data["novel"]["volumes"] = [{**data["novel"]["volume"], "chapters": [data["novel"]["chapter"]]}]


def safe_copy(value):
    return copy.deepcopy(value)


def next_outline_id(data, prefix):
    number = data["next_outline_id"]
    data["next_outline_id"] += 1
    return f"{prefix}-{number}"


def script_episode(data, item_id):
    return next((item for item in data["script"]["episodes"] if item["id"] == item_id), None)


def script_scene(data, item_id):
    for episode in data["script"]["episodes"]:
        scene = next((item for item in episode["scenes"] if item["id"] == item_id), None)
        if scene:
            return episode, scene
    return None, None


def script_segment(data, item_id):
    for episode in data["script"]["episodes"]:
        for scene in episode["scenes"]:
            segment = next((item for item in scene["segments"] if item["id"] == item_id), None)
            if segment:
                return episode, scene, segment
    return None, None, None


def novel_volumes(data):
    novel = data["novel"]
    if not novel.get("volumes"):
        novel["volumes"] = [{**novel["volume"], "chapters": [novel["chapter"]]}]
    return novel["volumes"]


def novel_volume(data, item_id):
    return next((item for item in novel_volumes(data) if item["id"] == item_id), None)


def novel_chapter(data, item_id):
    for volume in novel_volumes(data):
        chapter = next((item for item in volume["chapters"] if item["id"] == item_id), None)
        if chapter:
            return volume, chapter
    return None, None


def editable_script_scene(scene):
    return scene.get("editable_markdown", scene["body_markdown"])


def outline_record(project_id, project_revision, item, query):
    current = int(item.get("outline_revision", 0))
    requested = (query.get("outline_revision") or [""])[0]
    selected = current if requested == "" else int(requested)
    if selected == current:
        body = item.get("outline_markdown", "")
    else:
        historical = next((entry for entry in item.get("outline_history", []) if int(entry["revision"]) == selected), None)
        if historical is None: return None
        body = historical["body_markdown"]
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest() if body else ""
    return {"project_id": project_id, "revision": project_revision, "parent_id": item["id"],
            "outline_revision": selected, "current_outline_revision": current, "outline_sha256": digest,
            "outline_markdown": body, "selected_revision": "current" if selected == current else "history"}


def generation_source_fixture(data, module, scope, source_id):
    project_id = "script-fixture" if module == "script" else "novel-fixture"
    revision = data[module]["revision"]
    if module == "script" and scope in ("scene", "segment"):
        _episode, scene = script_scene(data, source_id) if scope == "scene" else (None, None)
        segment = None
        if scope == "segment":
            _episode, scene, segment = script_segment(data, source_id)
        if not scene: return None
        body = editable_script_scene(scene) if segment is None else scene["body_markdown"][segment["start"]:segment["end"]]
        return {"project_id": project_id, "revision": revision, "source_revision": scene["scene_revision"],
                "source_sha256": scene["content_sha256"], "body_markdown": body}
    if module == "script" and scope == "episode_outline":
        item = script_episode(data, source_id)
        if not item: return None
        body = item.get("outline_markdown", "")
        return {"project_id": project_id, "revision": revision, "source_revision": item.get("outline_revision", 0),
                "source_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest() if body else "", "body_markdown": body}
    if module == "novel" and scope == "chapter":
        _volume, item = novel_chapter(data, source_id)
        if not item: return None
        return {"project_id": project_id, "revision": revision, "source_revision": item["chapter_revision"],
                "source_sha256": item["content_sha256"], "body_markdown": item["body_markdown"]}
    if module == "novel" and scope == "chapter_outline":
        _volume, item = novel_chapter(data, source_id)
        if not item: return None
        body = item.get("outline_markdown", "")
        return {"project_id": project_id, "revision": revision, "source_revision": item.get("outline_revision", 0),
                "source_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest() if body else "", "body_markdown": body}
    return None


def replace_scene_from_editor(data, scene, edited):
    # Match the standalone-delimiter UI contract: separators become segment boundaries,
    # while only the Markdown portions remain in the scene blob and ranged segments.
    pieces = re.split(r"(?m)^[ \t]*---[ \t]*\r?$", edited.replace("\r\n", "\n").replace("\r", "\n"))
    pieces = [piece.strip("\n") for piece in pieces]
    raw = ""
    segments = []
    old_segments = scene.get("segments", [])
    old_chars = list(scene["body_markdown"])
    for index, piece in enumerate(pieces):
        if index:
            raw += "\n\n"
        start = len(raw)
        raw += piece
        end = len(raw)
        old_text = ""
        if index < len(old_segments):
            previous = old_segments[index]
            old_text = "".join(old_chars[previous["start"]:previous["end"]])
        stable_id = old_segments[index]["id"] if index < len(old_segments) and old_text == piece else next_outline_id(data["script"], "segment")
        title = old_segments[index]["title"] if index < len(old_segments) and old_text == piece else f"分段{index + 1}"
        segments.append({"id": stable_id, "title": title, "start": start, "end": end})
    scene["body_markdown"] = raw
    scene["content_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    scene["editable_markdown"] = edited.replace("\r\n", "\n").replace("\r", "\n")
    scene["segments"] = segments
    scene["scene_revision"] += 1


def apply_fixture_command(fixture, module, action, args):
    changed, created = [], {}
    if action == "batch":
        for operation in args.get("operations", []):
            nested_changed, nested_created = apply_fixture_command(fixture, module, operation["action"], operation["args"])
            changed.extend(nested_changed)
            created.update(nested_created)
        return changed, created
    if module == "script":
        script = fixture["script"]
        if action == "set_episode_outline":
            episode = script_episode(fixture, args["episode_id"])
            if not episode: raise AssertionError("missing target episode")
            episode.setdefault("outline_history", []).append({"revision": episode.get("outline_revision", 0), "body_markdown": episode.get("outline_markdown", "")})
            episode["outline_markdown"] = args["body_markdown"]
            episode["outline_revision"] = episode.get("outline_revision", 0) + 1
            changed.append(episode["id"])
        elif action == "set_draft":
            script["draft"] = args["body_markdown"]
            changed.append("script-draft")
        elif action == "create_episode":
            episode_id = next_outline_id(script, "episode")
            episode = {"id": episode_id, "title": args["title"], "outline_markdown": "", "outline_revision": 0, "outline_history": [], "scenes": []}
            episodes = script["episodes"]
            after = args.get("after_episode_id")
            index = next((i + 1 for i, item in enumerate(episodes) if item["id"] == after), len(episodes)) if after else len(episodes)
            episodes.insert(index, episode)
            if args.get("client_ref"): created[args["client_ref"]] = episode_id
            changed.append(episode_id)
        elif action == "create_scene":
            episode = script_episode(fixture, args["episode_id"])
            if not episode: raise AssertionError("missing parent episode")
            scene_id = next_outline_id(script, "scene")
            empty_segment_id = next_outline_id(script, "segment")
            scene = {"id": scene_id, "title": args["title"], "body_markdown": args["body_markdown"],
                     "content_sha256": hashlib.sha256(args["body_markdown"].encode("utf-8")).hexdigest(),
                     "editable_markdown": args["body_markdown"], "scene_revision": 1,
                     "segments": [{"id": empty_segment_id, "title": "分段 1", "start": 0, "end": 0}]}
            scenes = episode["scenes"]
            after = args.get("after_scene_id")
            index = next((i + 1 for i, item in enumerate(scenes) if item["id"] == after), len(scenes)) if after else len(scenes)
            scenes.insert(index, scene)
            if args.get("client_ref"): created[args["client_ref"]] = scene_id
            changed.extend([episode["id"], scene_id, empty_segment_id])
        elif action == "create_segment":
            _episode, scene = script_scene(fixture, args["scene_id"])
            if not scene: raise AssertionError("missing parent scene")
            segment_id = next_outline_id(script, "segment")
            segment = {"id": segment_id, "title": args["title"], "start": len(scene["body_markdown"]), "end": len(scene["body_markdown"])}
            segments = scene["segments"]
            after = args.get("after_segment_id")
            index = next((i + 1 for i, item in enumerate(segments) if item["id"] == after), len(segments)) if after else len(segments)
            segments.insert(index, segment)
            chars = list(scene["body_markdown"])
            pieces = ["".join(chars[item["start"]:item["end"]]) for item in segments]
            scene["editable_markdown"] = "\n\n---\n\n".join(pieces)
            if args.get("client_ref"): created[args["client_ref"]] = segment_id
            changed.extend([scene["id"], segment_id])
        elif action == "update_scene":
            episode, scene = script_scene(fixture, args["scene_id"])
            if not scene: raise AssertionError("missing target scene")
            previous = [item["id"] for item in scene["segments"]]
            replace_scene_from_editor(fixture, scene, args["body_markdown"])
            changed.extend([scene["id"]] + [item["id"] for item in scene["segments"] if item["id"] not in previous])
            if episode: changed.append(episode["id"])
        elif action == "replace_segment_text":
            _episode, scene, segment = script_segment(fixture, args["segment_id"])
            if not segment: raise AssertionError("missing target segment")
            chars = list(scene["body_markdown"])
            start, end = segment["start"], segment["end"]
            replacement = args["body_markdown"]
            delta = len(replacement) - (end - start)
            scene["body_markdown"] = "".join(chars[:start]) + replacement + "".join(chars[end:])
            scene["content_sha256"] = hashlib.sha256(scene["body_markdown"].encode("utf-8")).hexdigest()
            segment["end"] = start + len(replacement)
            for following in scene["segments"]:
                if following["id"] != segment["id"] and following["start"] >= end:
                    following["start"] += delta
                    following["end"] += delta
            scene["editable_markdown"] = "\n\n---\n\n".join("".join(list(scene["body_markdown"])[item["start"]:item["end"]]) for item in scene["segments"])
            scene["scene_revision"] += 1
            changed.extend([scene["id"], segment["id"]])
        elif action == "rename_item":
            kind, item_id = args["item_type"], args["item_id"]
            if kind == "episode": item = script_episode(fixture, item_id)
            elif kind == "scene": _episode, item = script_scene(fixture, item_id)
            elif kind == "segment": _episode, _scene, item = script_segment(fixture, item_id)
            else: item = None
            if not item: raise AssertionError("missing rename target")
            item["title"] = args["title"]
            changed.append(item_id)
        elif action == "delete_item":
            kind, item_id = args["item_type"], args["item_id"]
            include = args.get("include_descendants", False)
            if kind == "episode":
                collection = script["episodes"]
                item = script_episode(fixture, item_id)
                if item and item.get("scenes") and not include: raise AssertionError("parent delete must include descendants")
            elif kind == "scene":
                parent, item = script_scene(fixture, item_id)
                collection = parent["scenes"] if parent else []
                if item and item.get("segments") and not include: raise AssertionError("parent delete must include descendants")
            elif kind == "segment":
                _parent, scene, item = script_segment(fixture, item_id)
                collection = scene["segments"] if scene else []
            else:
                item = None; collection = []
            if not item: raise AssertionError("missing delete target")
            if kind == "segment":
                chars = list(scene["body_markdown"])
                start, end = item["start"], item["end"]
                removed_body = "".join(chars[start:end])
                scene["body_markdown"] = "".join(chars[:start] + chars[end:])
                scene["content_sha256"] = hashlib.sha256(scene["body_markdown"].encode("utf-8")).hexdigest()
                delta = end - start
                collection.remove(item)
                for remaining in collection:
                    if remaining["start"] >= end:
                        remaining["start"] -= delta
                        remaining["end"] -= delta
                scene["editable_markdown"] = "\n\n---\n\n".join(
                    "".join(list(scene["body_markdown"])[entry["start"]:entry["end"]]) for entry in collection)
                scene["scene_revision"] += 1
                script["archive"].append({"kind": kind, "item": safe_copy(item), "parent_id": scene["id"], "deleted_body": removed_body})
                changed.extend([scene["id"], item_id])
                return changed, created
            collection.remove(item)
            script["archive"].append({"kind": kind, "item": safe_copy(item)})
            changed.append(item_id)
        else:
            raise AssertionError(f"unsupported script command: {action}")
    else:
        novel = fixture["novel"]
        if action == "set_chapter_outline":
            _volume, chapter = novel_chapter(fixture, args["chapter_id"])
            if not chapter: raise AssertionError("missing target chapter")
            chapter.setdefault("outline_history", []).append({"revision": chapter.get("outline_revision", 0), "body_markdown": chapter.get("outline_markdown", "")})
            chapter["outline_markdown"] = args["body_markdown"]
            chapter["outline_revision"] = chapter.get("outline_revision", 0) + 1
            changed.append(chapter["id"])
        elif action == "update_chapter":
            _volume, chapter = novel_chapter(fixture, args["chapter_id"])
            if not chapter: raise AssertionError("missing target chapter")
            chapter["body_markdown"] = args["body_markdown"]
            chapter["content_sha256"] = hashlib.sha256(args["body_markdown"].encode("utf-8")).hexdigest()
            chapter["chapter_revision"] += 1
            changed.append(chapter["id"])
        elif action == "create_volume":
            volume_id = next_outline_id(novel, "volume")
            volume = {"id": volume_id, "title": args["title"], "chapters": []}
            volumes = novel_volumes(fixture)
            after = args.get("after_volume_id")
            index = next((i + 1 for i, item in enumerate(volumes) if item["id"] == after), len(volumes)) if after else len(volumes)
            volumes.insert(index, volume)
            if args.get("client_ref"): created[args["client_ref"]] = volume_id
            changed.append(volume_id)
        elif action == "create_chapter":
            volume = novel_volume(fixture, args["volume_id"])
            if not volume: raise AssertionError("missing parent volume")
            chapter_id = next_outline_id(novel, "chapter")
            chapter = {"id": chapter_id, "title": args["title"], "volume_id": volume["id"],
                       "body_markdown": args["body_markdown"],
                       "content_sha256": hashlib.sha256(args["body_markdown"].encode("utf-8")).hexdigest(),
                       "chapter_revision": 1, "outline_markdown": "", "outline_revision": 0, "outline_history": []}
            chapters = volume["chapters"]
            after = args.get("after_chapter_id")
            index = next((i + 1 for i, item in enumerate(chapters) if item["id"] == after), len(chapters)) if after else len(chapters)
            chapters.insert(index, chapter)
            if args.get("client_ref"): created[args["client_ref"]] = chapter_id
            changed.extend([volume["id"], chapter_id])
        elif action == "rename_item":
            kind, item_id = args["item_type"], args["item_id"]
            if kind == "volume": item = novel_volume(fixture, item_id)
            elif kind == "chapter": _volume, item = novel_chapter(fixture, item_id)
            else: item = None
            if not item: raise AssertionError("missing rename target")
            item["title"] = args["title"]
            changed.append(item_id)
        elif action == "delete_item":
            kind, item_id = args["item_type"], args["item_id"]
            include = args.get("include_descendants", False)
            if kind == "volume":
                collection = novel_volumes(fixture)
                item = novel_volume(fixture, item_id)
                if item and item.get("chapters") and not include: raise AssertionError("parent delete must include descendants")
            elif kind == "chapter":
                parent, item = novel_chapter(fixture, item_id)
                collection = parent["chapters"] if parent else []
            else:
                item = None; collection = []
            if not item: raise AssertionError("missing delete target")
            collection.remove(item)
            novel["archive"].append({"kind": kind, "item": safe_copy(item)})
            changed.append(item_id)
        elif action == "revise_setting_version":
            entry = next(item for item in novel["settings"]["entries"] if item["id"] == args["entry_id"])
            version = next(item for item in entry["versions"] if item["id"] == args["version_id"])
            version["history"].append({"revision": version["edit_revision"], "body_markdown": version["body_markdown"]})
            version["body_markdown"] = args["body_markdown"]
            version["edit_revision"] += 1
            changed.append(entry["id"])
        else:
            raise AssertionError(f"unsupported novel command: {action}")
    return changed, created


def rgba(value):
    raw = str(value).strip()
    if raw.startswith("#"):
        digits = raw[1:]
        if len(digits) in (3, 4): digits = "".join(character * 2 for character in digits)
        if len(digits) in (6, 8):
            parts = [int(digits[index:index + 2], 16) for index in range(0, len(digits), 2)]
            return parts[:3] + ([parts[3] / 255] if len(parts) == 4 else [1.0])
    values = [float(number) for number in re.findall(r"[\d.]+", str(value))]
    if len(values) < 3:
        raise AssertionError(f"无法解析浏览器颜色：{value}")
    return values[:3] + ([values[3]] if len(values) > 3 else [1.0])


def composite(foreground, background):
    fg, bg = rgba(foreground), rgba(background)
    alpha = fg[3]
    return [fg[i] * alpha + bg[i] * (1 - alpha) for i in range(3)]


def contrast_ratio(first, second):
    def luminance(color):
        linear = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4 for channel in [x / 255 for x in rgba(color)[:3]]]
        return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]
    high, low = sorted([luminance(first), luminance(second)], reverse=True)
    return (high + .05) / (low + .05)


def script_summary(data):
    script = data["script"]
    project = next(item for item in data["projects"] if item["id"] == "script-fixture")
    episodes = []
    for episode in script["episodes"]:
        episodes.append({"id": episode["id"], "title": episode["title"], "outline_revision": episode.get("outline_revision", 0), "outline_sha256": hashlib.sha256(episode.get("outline_markdown", "").encode("utf-8")).hexdigest() if episode.get("outline_markdown") else "", "scenes": [{
            "id": scene["id"], "title": scene["title"], "revision": scene["scene_revision"], "content_sha256": scene["content_sha256"], "segment_state": "structured" if scene["segments"] else "unsegmented",
            "segments": [{key: segment[key] for key in ("id", "title", "start", "end")} for segment in scene["segments"]],
        } for scene in episode["scenes"]]})
    return {"project": {"id": project["id"], "name": project["name"], "module": "script", "updated_at": project["updated_at"]},
            "revision": script["revision"], "state": script["state"], "directory": {"episodes": episodes},
            "statistics": {"episodes": len(episodes), "scenes": sum(len(item["scenes"]) for item in episodes),
                           "segments": sum(len(scene["segments"]) for episode in script["episodes"] for scene in episode["scenes"])} }


def novel_entry_summary(entry):
    return {"id": entry["id"], "category_id": entry["category_id"], "title": entry["title"],
            "current_version_id": entry["current_version_id"], "latest_version_id": entry["versions"][-1]["id"],
            "versions": [{key: version[key] for key in ("id", "story_version", "use_state", "story_anchor", "edit_revision")} for version in entry["versions"]]}


def novel_summary(data):
    novel = data["novel"]
    project = next(item for item in data["projects"] if item["id"] == "novel-fixture")
    volumes = novel_volumes(data)
    return {"project": {"id": project["id"], "name": project["name"], "module": "novel", "updated_at": project["updated_at"]},
            "revision": novel["revision"], "directory": {"volumes": [{"id": volume["id"], "title": volume["title"],
                "chapters": [{"id": chapter["id"], "title": chapter["title"], "revision": chapter["chapter_revision"], "content_sha256": chapter["content_sha256"], "outline_revision": chapter.get("outline_revision", 0), "outline_sha256": hashlib.sha256(chapter.get("outline_markdown", "").encode("utf-8")).hexdigest() if chapter.get("outline_markdown") else ""} for chapter in volume["chapters"]]} for volume in volumes]},
            "settings": {"categories": safe_copy(novel["settings"]["categories"]), "entries": [novel_entry_summary(entry) for entry in novel["settings"]["entries"]], "context_pins": []},
            "handoff": {"records": []}, "statistics": {"volumes": len(volumes), "chapters": sum(len(item["chapters"]) for item in volumes), "settings": len(novel["settings"]["entries"])} }


@unittest.skipUnless(CHROME and NODE, "需要本机 Chrome/Chromium 和 Node.js 执行隔离浏览器回归")
class StudioManuscriptBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validation = ROOT / ".cache" / "validation" / "studio-manuscripts"
        cls.tmp = ROOT / ".cache" / "tmp"
        cls.validation.mkdir(parents=True, exist_ok=True)
        cls.tmp.mkdir(parents=True, exist_ok=True)
        os.environ["TMPDIR"] = str(cls.tmp)
        cls.fixture = sample_data()
        fixture = cls.fixture

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT), **kwargs)

            def log_message(self, *_args):
                pass

            def _json(self, status, payload):
                if self.path.startswith("/api/"):
                    fixture["get_responses"].append({"path": urlsplit(self.path).path, "status": status,
                        "project": safe_copy(payload.get("project")) if isinstance(payload, dict) and "project" in payload else None})
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _view_page(self, module, scope, node_id, revision, blocks, query):
                try: offset = max(0, int((query.get("cursor") or ["0"])[0]))
                except ValueError: offset = 0
                try: limit = min(100, max(1, int((query.get("limit") or ["30"])[0])))
                except ValueError: limit = 30
                page = blocks[offset:offset + limit]
                has_more = offset + len(page) < len(blocks)
                next_cursor = str(offset + len(page)) if has_more else None
                fixture["view_requests"].append({"module": module, "scope": scope, "node_id": node_id, "cursor": (query.get("cursor") or [""])[0], "limit": limit})
                self._json(200, {"project_id": "script-fixture" if module == "script" else "novel-fixture", "revision": revision,
                    "scope": scope, "blocks": page, "has_more": has_more, "next_cursor": next_cursor})

            def do_GET(self):
                parsed = urlsplit(self.path)
                path, query = parsed.path, parse_qs(parsed.query)
                with fixture["lock"]:
                    fixture["get_requests"].append(path)
                    if path in ("/api/studio/scripts/settings-canvas", "/api/studio/novels/settings-canvas"):
                        module = "script" if "/scripts/" in path else "novel"
                        canvas_id = module + "-settings"
                        nodes = [
                            {"id": f"{module}-text-generator", "type": "smart-text-generator", "title": "文本生成",
                             "x": 120, "y": 150, "outputKind": "text",
                             "runSettings": {"textProvider": "fixture-provider", "textModel": "fixture-text-model"},
                             "promptDraftText": "用于设置验证的占位提示词"},
                            {"id": f"{module}-text-output", "type": "smart-hypit-output", "title": "文本输出",
                             "hypitSlot": "text", "outputKind": "text", "x": 560, "y": 150},
                        ]
                        self._json(200, {"id": canvas_id, "url": f"/static/smart-canvas.html?id={canvas_id}&mode={canvas_id}",
                            "canvas": {"id": canvas_id, "revision": 3,
                                "nodes": nodes,
                                "connections": [{"id": "fixture-edge", "from": f"{module}-text-generator", "to": f"{module}-text-output", "kind": "input"}]}})
                        return
                    if len(path.strip("/").split("/")) == 3 and path.startswith("/api/canvases/"):
                        canvas_id = path.split("/")[3]
                        if canvas_id in ("script-settings", "novel-settings"):
                            module = "script" if canvas_id == "script-settings" else "novel"
                            nodes = [
                                {"id": f"{module}-text-generator", "type": "smart-text-generator", "title": "文本生成",
                                 "x": 120, "y": 150, "outputKind": "text",
                                 "runSettings": {"textProvider": "fixture-provider", "textModel": "fixture-text-model"},
                                 "promptDraftText": "用于设置验证的占位提示词"},
                                {"id": f"{module}-text-output", "type": "smart-hypit-output", "title": "文本输出",
                                 "hypitSlot": "text", "outputKind": "text", "x": 560, "y": 150},
                            ]
                            self._json(200, {"canvas": {"id": canvas_id, "title": "Text optimization setup", "project": canvas_id,
                                "revision": 3, "updated_at": 1791580800, "nodes": nodes,
                                "connections": [{"id": "fixture-edge", "from": f"{module}-text-generator", "to": f"{module}-text-output", "kind": "input"}],
                                "settings": {}, "logs": [],
                                "viewport": {"x": 0, "y": 0, "scale": 1}}})
                            return
                    if len(path.strip("/").split("/")) == 4 and path.startswith("/api/canvases/") and path.endswith("/meta"):
                        canvas_id = path.split("/")[3]
                        if canvas_id in ("script-settings", "novel-settings"):
                            self._json(200, {"id": canvas_id, "revision": 3, "updated_at": 1791580800})
                            return
                    if path == "/api/studio/projects":
                        module = (query.get("module") or [""])[0]
                        self._json(200, {"projects": safe_copy([item for item in fixture["projects"] if item["module"] == module])})
                        return
                    if path == "/api/config":
                        self._json(200, {"api_providers": [{"id": "fixture-provider", "name": "Fixture Provider",
                            "protocol": "openai", "enabled": True, "chat_models": ["fixture-text-model"]}], "comfy_instances": []})
                        return
                    if path == "/api/model-capabilities":
                        profile = {"model_id": "fixture-text-model", "node_type": "text_generation", "operation": "chat",
                            "family_id": "fixture-text-family", "family_name": "Fixture Text", "variant_id": "chat",
                            "provider_id": "fixture-provider", "capability_provider_id": "fixture-provider",
                            "variant_name": "Chat", "validation_mode": "strict", "readiness": "ready",
                            "runnable": True, "selectable": True,
                            "inputs": {"prompt": {"media_type": "text", "min": 1, "max": 1, "role": "prompt"}}, "parameters": {}}
                        option = {"option_id": "opt-fixture-text", "connection_id": "fixture-provider",
                            "capability_provider_id": "fixture-provider", "catalog_model_id": "fixture-text-model",
                            "node_type": "text_generation", "operation": "chat", "region_id": "",
                            "validation_mode": "strict", "runnable": True, "selectable": True,
                            "inputs": profile["inputs"], "parameters": {}}
                        self._json(200, {"schema_version": 1, "catalog_revision": "text-optimization-fixture",
                            "providers": [{"id": "fixture-provider", "name": "Fixture Provider", "protocol": "openai",
                                "capability_provider_id": "fixture-provider", "models": [profile],
                                "families": [{"family_id": "fixture-text-family", "family_name": "Fixture Text",
                                    "node_type": "text_generation", "variants": [profile]}]}], "options": [option]})
                        return
                    if path == "/api/studio/model-options":
                        module = (query.get("module_id") or [""])[0]
                        slot = (query.get("slot_id") or [""])[0]
                        fixture["settings_model_option_requests"].append({"module_id": module, "slot_id": slot})
                        self._json(200, {"module_id": module, "slots": [{"id": slot}] if slot else [],
                            "catalog_revision": "text-optimization-fixture",
                            "options": [{"option_id": "opt-fixture-text", "connection_id": "fixture-provider",
                                "capability_provider_id": "fixture-provider", "catalog_model_id": "fixture-text-model",
                                "node_type": "text_generation", "operation": "chat", "region_id": ""}] if slot == "text" else []})
                        return
                    if path == "/api/model-pricing":
                        self._json(200, {"schema_version": 1, "entries": {}, "unit_definitions": {}})
                        return
                    if path == "/api/workflows":
                        self._json(200, {"workflows": []})
                        return
                    if path.startswith("/api/studio/projects/") and path.endswith("/connection"):
                        project_id = path.split("/")[4]
                        self._json(200, {"text": f"fixture connection for {project_id}; module={query.get('module', [''])[0]}"})
                        return
                    if path == "/api/studio/modules/script/preparation" or path == "/api/studio/modules/novel/preparation":
                        self._json(200, {"text": "fixture preparation instructions"})
                        return
                    parts = path.strip("/").split("/")
                    if len(parts) >= 4 and parts[:3] == ["api", "studio", "scripts"] and parts[3] == "script-fixture":
                        script = fixture["script"]
                        if len(parts) == 4:
                            self._json(200, script_summary(fixture)); return
                        if len(parts) == 6 and parts[4] == "scenes":
                            _episode, scene = script_scene(fixture, parts[5])
                            if not scene: self._json(404, {"detail": "fixture scene not found"}); return
                            body = scene["body_markdown"]
                            segments = []
                            for segment in scene["segments"]:
                                segments.append({**segment, "body_markdown": body[segment["start"]:segment["end"]], "source_sha256": scene["content_sha256"]})
                            self._json(200, {"project_id": "script-fixture", "revision": script["revision"], "scene": {
                                "id": scene["id"], "title": scene["title"], "revision": scene["scene_revision"],
                                "content_sha256": scene["content_sha256"], "body_markdown": body,
                                "editable_markdown": editable_script_scene(scene), "selected_revision": "current", "segments": segments}}); return
                        if len(parts) == 7 and parts[4] == "episodes" and parts[6] == "outline":
                            episode = script_episode(fixture, parts[5])
                            record = outline_record("script-fixture", script["revision"], episode, query) if episode else None
                            if record is None: self._json(404, {"detail": "fixture episode outline not found"})
                            else: self._json(200, record)
                            return
                        if len(parts) == 6 and parts[4] == "generations":
                            run = fixture["generations"].get(("script", parts[5]))
                            if not run: self._json(404, {"detail": "fixture generation not found"}); return
                            self._json(200, safe_copy(run["status_payload"])); return
                        if len(parts) == 5 and parts[4] == "view":
                            scope = (query.get("scope") or ["root"])[0]
                            node_id = (query.get("node_id") or [""])[0]
                            all_scenes = [(episode, scene) for episode in script["episodes"] for scene in episode["scenes"]]
                            if scope == "root" and script["state"] == "draft":
                                blocks = [{"id": "script-draft", "body_markdown": script["draft"]}]
                            elif scope == "segment":
                                episode, scene, segment = script_segment(fixture, node_id)
                                if segment:
                                    chars = list(scene["body_markdown"])
                                    blocks = [{"id": segment["id"], "title": segment["title"], "body_markdown": "".join(chars[segment["start"]:segment["end"]])}]
                                else: blocks = []
                            else:
                                if scope == "root": selected = all_scenes
                                elif scope == "episode":
                                    episode = script_episode(fixture, node_id)
                                    selected = [(episode, scene) for scene in episode["scenes"]] if episode else []
                                else:
                                    episode, scene = script_scene(fixture, node_id)
                                    selected = [(episode, scene)] if scene else []
                                blocks = [{"id": scene["id"], "title": scene["title"], "episode": {"id": episode["id"], "title": episode["title"]},
                                    "body_markdown": scene["body_markdown"], "editable_markdown": editable_script_scene(scene), "content_sha256": scene["content_sha256"], "revision": scene["scene_revision"], "segments": safe_copy(scene["segments"])}
                                    for episode, scene in selected]
                            self._view_page("script", scope, node_id, script["revision"], blocks, query); return
                    if len(parts) >= 4 and parts[:3] == ["api", "studio", "novels"] and parts[3] == "novel-fixture":
                        novel = fixture["novel"]
                        if len(parts) == 4:
                            self._json(200, novel_summary(fixture)); return
                        if len(parts) == 6 and parts[4] == "chapters":
                            _volume, chapter = novel_chapter(fixture, parts[5])
                            if not chapter: self._json(404, {"detail": "fixture chapter not found"}); return
                            self._json(200, {"project_id": "novel-fixture", "revision": novel["revision"], "chapter": {
                                "id": chapter["id"], "title": chapter["title"], "revision": chapter["chapter_revision"],
                                "content_sha256": chapter["content_sha256"], "body_markdown": chapter["body_markdown"]}}); return
                        if len(parts) == 7 and parts[4] == "chapters" and parts[6] == "outline":
                            _volume, chapter = novel_chapter(fixture, parts[5])
                            record = outline_record("novel-fixture", novel["revision"], chapter, query) if chapter else None
                            if record is None: self._json(404, {"detail": "fixture chapter outline not found"})
                            else: self._json(200, record)
                            return
                        if len(parts) == 5 and parts[4] == "manifest":
                            self._json(200, {"project": novel_summary(fixture)["project"], "revision": novel["revision"], "inventory": {}}); return
                        if len(parts) == 5 and parts[4] == "view":
                            scope = (query.get("scope") or ["root"])[0]
                            node_id = (query.get("node_id") or [""])[0]
                            volumes = novel_volumes(fixture)
                            if scope == "root": selected = [(volume, chapter) for volume in volumes for chapter in volume["chapters"]]
                            elif scope == "volume":
                                volume = novel_volume(fixture, node_id)
                                selected = [(volume, chapter) for chapter in volume["chapters"]] if volume else []
                            else:
                                volume, chapter = novel_chapter(fixture, node_id)
                                selected = [(volume, chapter)] if chapter else []
                            blocks = [{"id": chapter["id"], "title": chapter["title"], "volume": {"id": volume["id"], "title": volume["title"]}, "body_markdown": chapter["body_markdown"], "content_sha256": chapter["content_sha256"], "revision": chapter["chapter_revision"]}
                                for volume, chapter in selected]
                            self._view_page("novel", scope, node_id, novel["revision"], blocks, query); return
                        if len(parts) == 6 and parts[4] == "generations":
                            run = fixture["generations"].get(("novel", parts[5]))
                            if not run: self._json(404, {"detail": "fixture generation not found"}); return
                            self._json(200, safe_copy(run["status_payload"])); return
                        if len(parts) == 5 and parts[4] == "settings":
                            categories = safe_copy(novel["settings"]["categories"])
                            entries = novel["settings"]["entries"]
                            category = (query.get("category_id") or [""])[0]
                            if category:
                                entries = [item for item in entries if item["category_id"] == category]
                            page = [novel_entry_summary(item) for item in entries]
                            self._json(200, {"project_id": "novel-fixture", "revision": novel["revision"], "categories": categories,
                                "entries": page, "has_more": False, "next_cursor": None}); return
                        if len(parts) == 6 and parts[4] == "settings":
                            entry = next((item for item in novel["settings"]["entries"] if item["id"] == parts[5]), None)
                            if not entry:
                                self._json(404, {"detail": "fixture setting not found"}); return
                            version_id = (query.get("version_id") or [entry["current_version_id"]])[0]
                            version = next(item for item in entry["versions"] if item["id"] == version_id)
                            requested_revision = (query.get("edit_revision") or [""])[0]
                            selected_revision = int(requested_revision or version["edit_revision"])
                            body = version["body_markdown"] if selected_revision == version["edit_revision"] else next((item["body_markdown"] for item in version["history"] if item["revision"] == selected_revision), "")
                            summary = novel_entry_summary(entry)
                            selected = {key: version[key] for key in ("id", "story_version", "use_state", "story_anchor", "edit_revision")}
                            selected.update({"body_markdown": body, "selected_edit_revision": selected_revision})
                            self._json(200, {"project_id": "novel-fixture", "revision": novel["revision"], "entry": summary, "selected_version": selected}); return
                        if len(parts) == 7 and parts[4] == "settings" and parts[6] == "revisions":
                            entry = next(item for item in novel["settings"]["entries"] if item["id"] == parts[5])
                            version_id = (query.get("version_id") or [entry["current_version_id"]])[0]
                            version = next(item for item in entry["versions"] if item["id"] == version_id)
                            self._json(200, {"entry_id": entry["id"], "version_id": version_id, "current_edit_revision": version["edit_revision"],
                                "revisions": [{"revision": item["revision"]} for item in version["history"]]}); return
                        if len(parts) == 5 and parts[4] == "handoff":
                            self._json(200, {"project_id": "novel-fixture", "revision": novel["revision"], "exists": False, "record": None}); return
                    if len(parts) == 6 and parts[:3] == ["api", "studio", "scripts"] and parts[3] == "script-fixture" and parts[4] == "commands":
                        request_id = parts[5]
                        if fixture["not_found_next_receipt_lookup"]:
                            fixture["not_found_next_receipt_lookup"] = False
                            self._json(404, {"detail": "receipt not available yet"}); return
                        receipt = fixture["receipts"].get(request_id)
                        self._json(200 if receipt else 404, receipt or {"detail": "command not found"}); return
                    if len(parts) == 6 and parts[:3] == ["api", "studio", "novels"] and parts[3] == "novel-fixture" and parts[4] == "commands":
                        request_id = parts[5]
                        if fixture["not_found_next_receipt_lookup"]:
                            fixture["not_found_next_receipt_lookup"] = False
                            self._json(404, {"detail": "receipt not available yet"}); return
                        if fixture["empty_next_receipt_lookup"]:
                            fixture["empty_next_receipt_lookup"] = False
                            self._json(200, {}); return
                        receipt = fixture["receipts"].get(request_id)
                        self._json(200 if receipt else 404, receipt or {"detail": "command not found"}); return
                if path.startswith("/api/"):
                    self._json(200, {}); return
                super().do_GET()

            def do_PUT(self):
                path = urlsplit(self.path).path
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                parts = path.strip("/").split("/")
                if len(parts) == 3 and parts[:2] == ["api", "canvases"] and parts[2] in ("script-settings", "novel-settings"):
                    canvas_id = parts[2]
                    saved = {**payload, "id": canvas_id, "title": payload.get("title", "Text optimization setup"),
                        "project": canvas_id, "revision": int(payload.get("base_revision", 3)) + 1,
                        "updated_at": 1791580801, "node_schema_version": 7}
                    self._json(200, {"canvas": saved})
                    return
                self._json(404, {"detail": "fixture route not found"})

            def do_POST(self):
                path = urlsplit(self.path).path
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                with fixture["lock"]:
                    generation_prefixes = ("/api/studio/scripts/script-fixture/generations", "/api/studio/novels/novel-fixture/generations")
                    if path in generation_prefixes:
                        module = "script" if "/scripts/" in path else "novel"
                        module_id = module
                        project_id = "script-fixture" if module == "script" else "novel-fixture"
                        target = fixture[module]
                        if int(payload.get("base_revision", -1)) != int(target["revision"]):
                            self._json(409, {"detail": {"code": "revision_conflict", "message": "fixture project revision changed"}}); return
                        scope, source_id = payload.get("scope"), payload.get("source_id")
                        source = generation_source_fixture(fixture, module, scope, source_id)
                        request = payload.get("request") or {}
                        if (not source or not source["body_markdown"].strip()
                            or payload.get("expected_source_sha256") != source["source_sha256"]
                            or payload.get("expected_source_revision") != source["source_revision"]):
                            self._json(409, {"detail": {"code": "source_changed", "message": "fixture source revision changed"}}); return
                        if any(key in request for key in ("source", "source_text", "body_markdown", "text")):
                            self._json(400, {"detail": "source text must be loaded by the server"}); return
                        operation_id = payload.get("client_operation_id")
                        operation_key = (module, project_id, operation_id)
                        fixture["generation_attempts"].append({"module": module, "project_id": project_id, "payload": safe_copy(payload)})
                        prior = fixture["generation_operations"].get(operation_key)
                        if prior:
                            if prior["request"] != payload:
                                self._json(409, {"detail": {"code": "idempotency_conflict", "message": "operation payload changed"}}); return
                            run = prior
                        else:
                            run_id = f"fixture-run-{len(fixture['generations']) + 1}"
                            output_node_id = payload.get("output_node_id")
                            source_object_sha256 = hashlib.sha256(source["body_markdown"].encode("utf-8")).hexdigest()
                            result_id = f"fixture-result-{len(fixture['generations']) + 1}"
                            result_text = source["body_markdown"] + "\n\n优化结果"
                            common = {"run_id": run_id, "status": "succeeded", "slot": "text", "output_node_id": output_node_id,
                                "module_id": module_id, "project_id": project_id, "purpose": "optimize", "scope": scope,
                                "source_id": source_id, "client_operation_id": operation_id, "accepted_revision": source["revision"],
                                "source_revision": source["source_revision"], "source_sha256": source["source_sha256"],
                                "source_object_sha256": source_object_sha256, "settings_revision": 3,
                                "recipe_fingerprint": "fixture-recipe", "current_recipe_matches": True, "output_kind": "text",
                                "result_ids": [result_id], "media": [{"kind": "text", "resultId": result_id, "text": result_text}],
                                "steps": [], "error": None, "error_category": None}
                            run = {"request": safe_copy(payload), "status_payload": common,
                                "submit_payload": {key: common[key] for key in ("run_id", "status", "slot", "output_node_id", "module_id", "project_id", "purpose", "scope", "source_id", "client_operation_id", "accepted_revision", "source_revision", "source_sha256", "source_object_sha256", "settings_revision", "recipe_fingerprint")},
                                "result_text": result_text, "result_id": result_id, "apply_receipts": {}}
                            fixture["generation_operations"][operation_key] = run
                            fixture["generations"][(module, run_id)] = run
                        if fixture["unknown_next_generation_response"]:
                            fixture["unknown_next_generation_response"] = False
                            self._json(503, {"detail": "fixture response unavailable after accepted run"}); return
                        self._json(200, safe_copy(run["submit_payload"])); return
                    generation_match = re.fullmatch(r"/api/studio/(scripts/script-fixture|novels/novel-fixture)/generations/([^/]+)/apply", path)
                    if generation_match:
                        module = "script" if generation_match.group(1).startswith("scripts/") else "novel"
                        run = fixture["generations"].get((module, generation_match.group(2)))
                        if not run or payload.get("result_id") != run["result_id"]:
                            self._json(404, {"detail": "fixture run/result not found"}); return
                        request_id = payload.get("request_id")
                        if request_id in run["apply_receipts"]:
                            self._json(200, safe_copy(run["apply_receipts"][request_id])); return
                        if fixture["conflict_next_generation_apply"]:
                            fixture["conflict_next_generation_apply"] = False
                            source = generation_source_fixture(fixture, module, run["request"]["scope"], run["request"]["source_id"])
                            if module == "novel" and run["request"]["scope"] == "chapter":
                                _volume, chapter = novel_chapter(fixture, run["request"]["source_id"])
                                chapter["body_markdown"] += "\n远端新内容"
                                chapter["content_sha256"] = hashlib.sha256(chapter["body_markdown"].encode("utf-8")).hexdigest()
                                chapter["chapter_revision"] += 1
                            elif module == "script" and run["request"]["scope"] == "scene":
                                _episode, scene = script_scene(fixture, run["request"]["source_id"])
                                scene["body_markdown"] += "\n\n远端新内容"
                                scene["editable_markdown"] = scene["body_markdown"]
                                scene["content_sha256"] = hashlib.sha256(scene["body_markdown"].encode("utf-8")).hexdigest()
                                scene["scene_revision"] += 1
                            target = fixture[module]; target["revision"] += 1
                            project = next(item for item in fixture["projects"] if item["id"] == ("script-fixture" if module == "script" else "novel-fixture"))
                            project["revision"] = target["revision"]; project["updated_at"] += 1
                            self._json(409, {"detail": {"code": "source_changed", "message": "fixture source changed before apply"}}); return
                        scope, source_id = run["request"]["scope"], run["request"]["source_id"]
                        result_text = run["result_text"]
                        if module == "script" and scope == "episode_outline":
                            episode = script_episode(fixture, source_id)
                            episode["outline_history"].append({"revision": episode.get("outline_revision", 0), "body_markdown": episode.get("outline_markdown", "")})
                            episode["outline_markdown"] = result_text; episode["outline_revision"] = episode.get("outline_revision", 0) + 1
                        elif module == "script" and scope == "scene":
                            _episode, scene = script_scene(fixture, source_id)
                            replace_scene_from_editor(fixture, scene, result_text)
                            scene["content_sha256"] = hashlib.sha256(scene["body_markdown"].encode("utf-8")).hexdigest()
                        elif module == "script" and scope == "segment":
                            _episode, scene, segment = script_segment(fixture, source_id)
                            scene["body_markdown"] = result_text
                            scene["content_sha256"] = hashlib.sha256(result_text.encode("utf-8")).hexdigest()
                            scene["editable_markdown"] = result_text; scene["scene_revision"] += 1
                            segment["start"], segment["end"] = 0, len(result_text)
                        elif module == "novel" and scope == "chapter_outline":
                            _volume, chapter = novel_chapter(fixture, source_id)
                            chapter["outline_history"].append({"revision": chapter.get("outline_revision", 0), "body_markdown": chapter.get("outline_markdown", "")})
                            chapter["outline_markdown"] = result_text; chapter["outline_revision"] = chapter.get("outline_revision", 0) + 1
                        elif module == "novel" and scope == "chapter":
                            _volume, chapter = novel_chapter(fixture, source_id)
                            chapter["body_markdown"] = result_text; chapter["content_sha256"] = hashlib.sha256(result_text.encode("utf-8")).hexdigest()
                            chapter["chapter_revision"] += 1
                        target = fixture[module]; target["revision"] += 1
                        project_id = "script-fixture" if module == "script" else "novel-fixture"
                        project = next(item for item in fixture["projects"] if item["id"] == project_id)
                        project["revision"] = target["revision"]; project["updated_at"] += 1
                        receipt = {"request_id": request_id, "status": "succeeded", "project_id": project_id,
                            "revision": target["revision"], "changed_ids": [source_id], "created_ids": {}, "warnings": [],
                            "generation_run_id": run["status_payload"]["run_id"], "result_id": run["result_id"],
                            "source_scope": scope, "source_id": source_id, "source_sha256": run["status_payload"]["source_sha256"]}
                        run["apply_receipts"][request_id] = receipt
                        self._json(200, safe_copy(receipt)); return
                    if path == "/api/studio/projects":
                        project_id = "script-created-" + str(fixture["next_project"])
                        fixture["next_project"] += 1
                        project = {"id": project_id, "name": payload.get("name", "Fixture project"), "module": payload.get("module", "script"), "revision": 1, "updated_at": 1791580900}
                        fixture["projects"].append(project)
                        self._json(200, {"project": project}); return
                    if path in ("/api/studio/scripts/script-fixture/commands", "/api/studio/novels/novel-fixture/commands"):
                        module = "script" if "/scripts/" in path else "novel"
                        target = fixture[module]
                        request_id = payload["request_id"]
                        if request_id in fixture["receipts"]:
                            self._json(200, fixture["receipts"][request_id]); return
                        fixture["command_attempts"].append({"module": module, "payload": safe_copy(payload)})
                        if int(payload.get("expected_revision", 0)) != int(target["revision"]):
                            self._json(409, {"detail": {"code": "revision_conflict", "message": "fixture revision changed"}}); return
                        if fixture["fail_next_command"]:
                            fixture["fail_next_command"] = False
                            self._json(400, {"detail": "fixture save failure"}); return
                        if fixture["conflict_next_command"]:
                            fixture["conflict_next_command"] = False
                            target["revision"] += 1
                            fixture_project = next(item for item in fixture["projects"] if item["id"] == ("script-fixture" if module == "script" else "novel-fixture"))
                            fixture_project["revision"] = target["revision"]
                            fixture_project["updated_at"] += 1
                            self._json(409, {"detail": {"code": "revision_conflict", "message": "fixture revision changed before submit"}}); return
                        try:
                            changed, created = apply_fixture_command(fixture, module, payload["action"], payload["args"])
                        except (AssertionError, KeyError, ValueError) as error:
                            self._json(400, {"detail": str(error)}); return
                        target["revision"] += 1
                        fixture_project = next(item for item in fixture["projects"] if item["id"] == ("script-fixture" if module == "script" else "novel-fixture"))
                        fixture_project["revision"] = target["revision"]
                        fixture_project["updated_at"] += 1
                        receipt = {"request_id": request_id, "status": "succeeded", "project_id": "script-fixture" if module == "script" else "novel-fixture", "revision": target["revision"], "changed_ids": changed, "created_ids": created, "warnings": []}
                        fixture["receipts"][request_id] = receipt
                        if fixture["unknown_next_command_response"]:
                            fixture["unknown_next_command_response"] = False
                            fixture["not_found_next_receipt_lookup"] = True
                            self._json(503, {"detail": "fixture response unavailable after commit"}); return
                        if fixture["drop_next_command_response"]:
                            fixture["drop_next_command_response"] = False
                            fixture["empty_next_receipt_lookup"] = True
                            self._json(503, {"detail": "fixture response dropped after commit"}); return
                        self._json(200, receipt); return
                self._json(404, {"detail": "unknown isolated route"})

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.debug_port = cls._free_port()
        cls.profile = cls.tmp / f"studio-manuscript-browser-{os.getpid()}"
        cls.profile.mkdir(parents=True, exist_ok=False)
        cls.chrome = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--window-size=1440,1000", "--force-device-scale-factor=1",
            f"--user-data-dir={cls.profile}", f"--remote-debugging-port={cls.debug_port}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "TMPDIR": str(cls.tmp)})
        cls.browser_ws = cls._wait_for_browser_ws()
        node_script = r"""const readline=require('readline');
const ws=new WebSocket(process.argv[1]); const input=readline.createInterface({input:process.stdin});
ws.onopen=()=>{console.log(JSON.stringify({ready:true}));input.on('line',line=>{const q=JSON.parse(line);const m={id:q.id,method:q.method,params:q.params||{}};if(q.sessionId)m.sessionId=q.sessionId;ws.send(JSON.stringify(m));});};
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id!==undefined)console.log(JSON.stringify({id:m.id,result:m.result||{},error:m.error||null}));};"""
        cls.cdp_process = subprocess.Popen([NODE, "-e", node_script, cls.browser_ws], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL, text=True, bufsize=1, env={**os.environ, "TMPDIR": str(cls.tmp)})
        if not json.loads(cls.cdp_process.stdout.readline() or "{}").get("ready"):
            cls.tearDownClass()
            raise unittest.SkipTest("未能建立隔离 Chrome CDP 会话")
        cls.cdp_request_id = 0
        cls.targets = []
        cls.fixture_source = (ROOT / "tests" / "browser" / "studio_manuscripts_fixture.js").read_text(encoding="utf-8")

    @classmethod
    def _free_port(cls):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    @classmethod
    def _wait_for_browser_ws(cls):
        import urllib.request
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cls.debug_port}/json/version", timeout=2) as response:
                    endpoint = json.loads(response.read().decode("utf-8")).get("webSocketDebuggerUrl")
                    if endpoint: return endpoint
            except Exception:
                time.sleep(0.1)
        raise unittest.SkipTest("Chrome 未提供调试端点")

    @classmethod
    def cdp(cls, method, params=None, session_id=None):
        cls.cdp_request_id += 1
        request_id = cls.cdp_request_id
        request = {"id": request_id, "method": method, "params": params or {}}
        if session_id: request["sessionId"] = session_id
        cls.cdp_process.stdin.write(json.dumps(request) + "\n")
        cls.cdp_process.stdin.flush()
        response = json.loads(cls.cdp_process.stdout.readline() or "{}")
        if response.get("id") != request_id or response.get("error"):
            raise AssertionError(f"CDP 调用失败：{response.get('error') or response}")
        return response.get("result", {})

    @classmethod
    def new_page(cls, url):
        target_id = cls.cdp("Target.createTarget", {"url": "about:blank"})["targetId"]
        session_id = cls.cdp("Target.attachToTarget", {"targetId": target_id, "flatten": True})["sessionId"]
        cls.targets.append((target_id, session_id))
        cls.cdp("Page.enable", session_id=session_id)
        cls.cdp("Runtime.enable", session_id=session_id)
        cls.cdp("Page.addScriptToEvaluateOnNewDocument", {"source": cls.fixture_source}, session_id=session_id)
        cls.cdp("Page.navigate", {"url": url}, session_id=session_id)
        page = {"target": target_id, "session": session_id}
        cls.wait(page, "document.readyState === 'complete' && !!document.body", 15)
        return page

    @classmethod
    def reset_test_origin_storage(cls, language="zh"):
        """Clear shared origin state and establish the default language before each test."""
        target_id = cls.cdp("Target.createTarget", {"url": "about:blank"})["targetId"]
        session_id = cls.cdp("Target.attachToTarget", {"targetId": target_id, "flatten": True})["sessionId"]
        page = {"target": target_id, "session": session_id}
        try:
            cls.cdp("Page.enable", session_id=session_id)
            cls.cdp("Runtime.enable", session_id=session_id)
            cls.cdp("Page.navigate", {"url": f"http://127.0.0.1:{cls.port}/static/index.html"}, session_id)
            cls.wait(page, "document.readyState === 'complete' && !!document.body", 15)
            cls.evaluate(page, "localStorage.clear();localStorage.setItem('studio_lang', " + json.dumps(language) + ")")
        finally:
            try:
                cls.cdp("Target.closeTarget", {"targetId": target_id})
            except Exception:
                pass

    @classmethod
    def evaluate(cls, page, expression):
        result = cls.cdp("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True}, page["session"])
        if result.get("exceptionDetails"):
            raise AssertionError(f"浏览器脚本异常：{result['exceptionDetails']}")
        remote = result.get("result", {})
        return remote.get("value")

    @classmethod
    def wait(cls, page, expression, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if cls.evaluate(page, f"!!({expression})"): return True
            except AssertionError:
                pass
            time.sleep(0.05)
        manuscript_debug = cls.evaluate(page, "({save:document.getElementById('smSaveState')?.textContent,error:document.getElementById('smEditorError')?.textContent,draft:document.getElementById('smMarkdownInput')?.value,inline:[...document.querySelectorAll('.sm-inline-input')].map(x=>({key:x.dataset.inlineKey,value:x.value,state:x.closest('.sm-inline-field')?.querySelector('.sm-inline-state')?.textContent,error:x.closest('.sm-inline-field')?.querySelector('.sm-inline-error')?.textContent})),buttons:[...document.querySelectorAll('#smRetrySaveButton,#smReloadConflictButton')].map(b=>({id:b.id,hidden:b.hidden}))})")
        with cls.fixture["lock"]:
            fixture_debug = {"novel_revision": cls.fixture["novel"]["revision"], "chapter": cls.fixture["novel"]["chapter"]["body_markdown"], "commands": safe_copy(cls.fixture["command_attempts"][-5:]), "requests": cls.fixture["get_requests"][-20:], "responses": cls.fixture["get_responses"][-10:]}
        raise AssertionError(f"浏览器等待超时：{expression}\nURL={cls.evaluate(page, 'location.href')}\ntitle={cls.evaluate(page, 'document.title')}\nbody={cls.evaluate(page, 'document.body?.innerText?.slice(0,500)')}\npage={manuscript_debug}\nfixture={fixture_debug}\nerrors={cls.evaluate(page, 'JSON.stringify(window.__studioManuscriptErrors||[])')}")

    @classmethod
    def set_editor_text(cls, page, value, composing=False):
        encoded = json.dumps(value, ensure_ascii=False)
        cls.evaluate(page, "(()=>{const field=document.querySelector('.sm-inline-input')||document.getElementById('smMarkdownInput');field.value=" + encoded + ";field.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:" + encoded + ",isComposing:" + ("true" if composing else "false") + "}));})()")

    @classmethod
    def set_inline_text(cls, page, key, value, composing=False):
        encoded_key = json.dumps(key)
        encoded_value = json.dumps(value, ensure_ascii=False)
        cls.evaluate(page, "(()=>{const field=[...document.querySelectorAll('.sm-inline-input')].find(x=>x.dataset.inlineKey===" + encoded_key + ");if(!field)throw new Error('inline field missing: '+" + encoded_key + ");field.value=" + encoded_value + ";field.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:" + encoded_value + ",isComposing:" + ("true" if composing else "false") + "}));})()")

    @classmethod
    def begin_edit(cls, page):
        if cls.evaluate(page, "!!document.querySelector('.sm-inline-input')"): return
        cls.wait(page, "!document.getElementById('smEditButton').hidden")
        cls.evaluate(page, "document.getElementById('smEditButton').click()")
        cls.wait(page, "!document.getElementById('smEditor').hidden && !!document.getElementById('smMarkdownInput')")

    @classmethod
    def press_escape(cls, page):
        cls.cdp("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape"}, page["session"])
        cls.cdp("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape"}, page["session"])

    @classmethod
    def screenshot(cls, page, name):
        cls.wait_visual_stable(page)
        data = cls.cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True}, page["session"])["data"]
        (cls.validation / name).write_bytes(__import__("base64").b64decode(data))

    @classmethod
    def screenshot_viewport(cls, page, name):
        cls.wait_visual_stable(page)
        data = cls.cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}, page["session"])["data"]
        (cls.validation / name).write_bytes(__import__("base64").b64decode(data))

    @classmethod
    def wait_visual_stable(cls, page, timeout=12):
        probe = """(()=>{
            const root=document.documentElement,body=document.body,frame=document.querySelector('iframe.active');
            const child=frame?.contentDocument,sidebar=document.querySelector('.sidebar');
            const finiteAnimations=[...document.getAnimations()].filter(a=>a.playState==='running'&&a.effect?.getComputedTiming().iterations!==Infinity).length;
            const rect=n=>{const r=n?.getBoundingClientRect();return r?[r.x,r.y,r.width,r.height].map(x=>Math.round(x*10)/10).join(','):''};
            const visible=getComputedStyle(body).visibility==='visible'&&!root.classList.contains('studio-route-booting');
            const opacity=frame?Number(getComputedStyle(frame).opacity):1;
            const childAnimations=child?[...child.getAnimations()].filter(a=>a.playState==='running'&&a.effect?.getComputedTiming().iterations!==Infinity).length:0;
            const ready=visible&&document.fonts?.status==='loaded'&&!document.querySelector('dialog[open],.studio-dialog-overlay')&&finiteAnimations===0&&opacity>=.99&&(!frame||(child?.readyState==='complete'&&child.fonts?.status==='loaded'&&getComputedStyle(child.body).visibility==='visible'&&childAnimations===0));
            const signature=[innerWidth,innerHeight,rect(body),rect(sidebar),rect(frame),opacity.toFixed(2),getComputedStyle(body).backgroundColor,child?.body?.clientWidth,child?.body?.clientHeight,finiteAnimations,childAnimations].join('|');
            return {ready,signature};
        })()"""
        deadline = time.monotonic() + timeout
        previous = None
        stable = 0
        while time.monotonic() < deadline:
            sample = cls.evaluate(page, probe)
            if sample and sample.get("ready") and sample.get("signature") == previous:
                stable += 1
                if stable >= 3:
                    return
            else:
                stable = 0
                previous = sample.get("signature") if sample else None
            time.sleep(0.1)
        raise AssertionError(f"截图前 UI 未稳定：{cls.evaluate(page, probe)}")

    @classmethod
    def tearDownClass(cls):
        for target_id, _session in getattr(cls, "targets", []):
            try: cls.cdp("Target.closeTarget", {"targetId": target_id})
            except Exception: pass
        try:
            if getattr(cls, "cdp_process", None):
                cls.cdp_process.terminate(); cls.cdp_process.wait(timeout=5)
            if getattr(cls, "chrome", None):
                cls.chrome.terminate(); cls.chrome.wait(timeout=10)
        except Exception:
            pass
        if getattr(cls, "server", None):
            cls.server.shutdown(); cls.server.server_close()
        shutil.rmtree(getattr(cls, "profile", ""), ignore_errors=True)

    def setUp(self):
        for target_id, _session in list(self.targets):
            try:
                self.cdp("Target.closeTarget", {"targetId": target_id})
            except Exception:
                pass
        self.targets.clear()
        lock = self.fixture["lock"]
        fresh = sample_data()
        with lock:
            self.fixture.clear()
            self.fixture.update(fresh)
            self.fixture["lock"] = lock
        self.reset_test_origin_storage("zh")

    def test_script_text_optimization_recovers_preview_and_applies_explicitly(self):
        origin = f"http://127.0.0.1:{self.port}"
        page = self.new_page(origin + "/static/script.html?id=script-fixture")
        self.wait(page, "document.getElementById('smProjectName').textContent==='隔离剧本作品'")
        self.evaluate(page, "localStorage.removeItem('studio-manuscript-optimization:script:script-fixture')")
        self.evaluate(page, "document.querySelector('[data-inline-optimize=\\\"script-scene:scene-1\\\"]').click()")
        self.wait(page, "!!document.querySelector('.sm-optimization-dialog')")
        self.evaluate(page, "document.querySelector('.sm-optimization-prompt').value='请让表达更清楚，保留原意。'")
        self.evaluate(page, "document.querySelector('.sm-optimization-actions button:nth-child(2)').click()")
        self.wait(page, "!document.querySelector('[aria-label=\\\"优化结果预览\\\"]').hidden && document.querySelector('[aria-label=\\\"优化结果预览\\\"]').value.includes('优化结果')", 10)
        with self.fixture["lock"]:
            self.assertEqual(len(self.fixture["generation_attempts"]), 1)
            request = self.fixture["generation_attempts"][0]["payload"]
            run = self.fixture["generations"][("script", "fixture-run-1")]
            self.assertEqual(request["base_revision"], 1)
            self.assertEqual(request["expected_source_revision"], 1)
            self.assertEqual(request["expected_source_sha256"], self.fixture["script"]["episodes"][0]["scenes"][0]["content_sha256"])
            self.assertEqual(request["output_node_id"], "script-text-output")
            self.assertEqual(run["submit_payload"]["accepted_revision"], 1)
            self.assertEqual(run["submit_payload"]["settings_revision"], 3)
            self.assertNotIn("system_prompt", request["request"])  # Keep the configured node system prompt.
            self.assertNotIn("source_text", request["request"])
            self.assertNotIn("body_markdown", request["request"])
            self.assertEqual(self.fixture["script"]["episodes"][0]["scenes"][0]["body_markdown"],
                             "开场未分段🙂\n\n片段甲文本\n\n中间未分段\n\n片段乙文本\n\n结尾未分段")
        stored = self.evaluate(page, "localStorage.getItem('studio-manuscript-optimization:script:script-fixture')")
        self.assertNotIn("sourceBody", stored)
        self.assertNotIn("resultText", stored)
        self.assertNotIn("优化结果", stored)
        self.assertIn("client_operation_id", stored)
        self.screenshot_viewport(page, "text-optimization-script-scene-preview.png")

        previous_time_origin = self.evaluate(page, "performance.timeOrigin")
        self.cdp("Page.reload", {}, page["session"])
        self.wait(page, f"performance.timeOrigin !== {previous_time_origin}")
        self.wait(page, "document.readyState==='complete' && !!document.querySelector('[data-inline-optimize=\\\"script-scene:scene-1\\\"]')")
        self.evaluate(page, "document.querySelector('[data-inline-optimize=\\\"script-scene:scene-1\\\"]').click()")
        self.wait(page, "!document.querySelector('[aria-label=\\\"优化结果预览\\\"]').hidden && document.querySelector('[aria-label=\\\"优化结果预览\\\"]').value.includes('优化结果')", 10)
        with self.fixture["lock"]:
            self.assertEqual(len(self.fixture["generation_attempts"]), 1)
            self.assertEqual(len(self.fixture["generations"]), 1)
        self.evaluate(page, "document.querySelector('.sm-optimization-actions button:nth-child(3)').click()")
        self.wait(page, "document.querySelector('[data-inline-key=\\\"script-scene:scene-1\\\"]').value.endsWith('优化结果')", 10)
        with self.fixture["lock"]:
            scene = self.fixture["script"]["episodes"][0]["scenes"][0]
            self.assertTrue(scene["body_markdown"].endswith("优化结果"))
            self.assertEqual(len(self.fixture["generations"][("script", "fixture-run-1")]["apply_receipts"]), 1)
        self.assertEqual(self.evaluate(page, "document.querySelector('.sm-optimization-status').textContent"), "已采用")

        self.evaluate(page, "document.querySelector('[data-scope=episode][data-node-id=episode-1]').click()")
        self.wait(page, "!document.getElementById('smDocumentTabs').hidden")
        self.evaluate(page, "document.getElementById('smDocumentTabOutline').click()")
        self.wait(page, "!!document.querySelector('[data-inline-key=\\\"script-episode-outline:episode-1\\\"]')")
        outline = "# 集纲样例\n\n保留正文之外的章纲。"
        self.set_inline_text(page, "script-episode-outline:episode-1", outline)
        self.wait(page, "document.getElementById('smRevisionLabel').textContent==='已保存'", 10)
        self.evaluate(page, "document.querySelector('[data-inline-optimize=\\\"script-episode-outline:episode-1\\\"]').click()")
        self.wait(page, "!!document.querySelector('.sm-optimization-dialog')")
        self.evaluate(page, "document.querySelector('.sm-optimization-prompt').value='理顺章纲表达。'")
        self.evaluate(page, "document.querySelector('.sm-optimization-actions button:nth-child(2)').click()")
        self.wait(page, "!document.querySelector('[aria-label=\\\"优化结果预览\\\"]').hidden && document.querySelector('[aria-label=\\\"优化结果预览\\\"]').value.includes('优化结果')", 10)
        with self.fixture["lock"]:
            self.assertEqual(self.fixture["script"]["episodes"][0]["outline_markdown"], outline)
            outline_request = self.fixture["generation_attempts"][-1]["payload"]
            self.assertEqual(outline_request["scope"], "episode_outline")
            self.assertEqual(outline_request["source_id"], "episode-1")
            self.assertEqual(outline_request["expected_source_revision"], 1)
            self.assertEqual(outline_request["base_revision"], self.fixture["script"]["revision"])
            self.assertEqual(self.fixture["generations"][("script", "fixture-run-2")]["submit_payload"]["settings_revision"], 3)
        self.evaluate(page, "document.querySelector('.sm-optimization-actions button:nth-child(3)').click()")
        self.wait(page, "document.querySelector('[data-inline-key=\\\"script-episode-outline:episode-1\\\"]').value.endsWith('优化结果')", 10)
        with self.fixture["lock"]:
            self.assertTrue(self.fixture["script"]["episodes"][0]["outline_markdown"].endswith("优化结果"))
            self.assertTrue(self.fixture["script"]["episodes"][0]["scenes"][0]["body_markdown"].endswith("优化结果"))

    def test_novel_text_optimization_recovers_unknown_submit_and_preserves_apply_conflict(self):
        origin = f"http://127.0.0.1:{self.port}"
        page = self.new_page(origin + "/static/novel.html?id=novel-fixture")
        self.wait(page, "document.getElementById('smProjectName').textContent==='隔离小说作品'")
        self.evaluate(page, "localStorage.removeItem('studio-manuscript-optimization:novel:novel-fixture')")
        with self.fixture["lock"]:
            self.fixture["unknown_next_generation_response"] = True
        original = self.fixture["novel"]["chapter"]["body_markdown"]
        self.evaluate(page, "document.querySelector('[data-inline-optimize=\\\"novel-chapter:chapter-1\\\"]').click()")
        self.wait(page, "!!document.querySelector('.sm-optimization-dialog')")
        self.evaluate(page, "document.querySelector('.sm-optimization-prompt').value='精简句子，不改变事实。'")
        self.evaluate(page, "document.querySelector('.sm-optimization-actions button:nth-child(2)').click()")
        self.wait(page, "document.querySelector('.sm-optimization-status').textContent.includes('同一请求')", 10)
        stored = self.evaluate(page, "localStorage.getItem('studio-manuscript-optimization:novel:novel-fixture')")
        self.assertNotIn(original, stored)
        self.assertNotIn("resultText", stored)

        self.cdp("Page.reload", {}, page["session"])
        self.wait(page, "document.readyState==='complete' && !!document.querySelector('[data-inline-optimize=\\\"novel-chapter:chapter-1\\\"]')")
        self.evaluate(page, "document.querySelector('[data-inline-optimize=\\\"novel-chapter:chapter-1\\\"]').click()")
        self.wait(page, "!document.querySelector('[aria-label=\\\"优化结果预览\\\"]').hidden && document.querySelector('[aria-label=\\\"优化结果预览\\\"]').value.includes('优化结果')", 10)
        with self.fixture["lock"]:
            self.assertEqual(len(self.fixture["generation_attempts"]), 2)
            operations = [record["payload"]["client_operation_id"] for record in self.fixture["generation_attempts"]]
            self.assertEqual(operations[0], operations[1])
            self.assertEqual(self.fixture["generation_attempts"][0]["payload"], self.fixture["generation_attempts"][1]["payload"])
            self.assertEqual(len(self.fixture["generations"]), 1)
            self.assertEqual(self.fixture["novel"]["chapter"]["body_markdown"], original)
            self.fixture["conflict_next_generation_apply"] = True
        apply_state = self.evaluate(page, "({disabled:document.querySelector('.sm-optimization-actions button:nth-child(3)').disabled,status:document.querySelector('.sm-optimization-status').textContent,source:document.querySelector('[aria-label=\\\"当前保存的原文\\\"]').value,result:document.querySelector('[aria-label=\\\"优化结果预览\\\"]').value})")
        self.assertFalse(apply_state["disabled"], apply_state)
        self.evaluate(page, "document.querySelector('.sm-optimization-actions button:nth-child(3)').click()")
        self.wait(page, "document.querySelector('.sm-optimization-actions button:nth-child(3)').disabled && document.querySelector('[aria-label=\\\"优化结果预览\\\"]').value.includes('优化结果')", 10)
        with self.fixture["lock"]:
            chapter = self.fixture["novel"]["chapter"]
            self.assertTrue(chapter["body_markdown"].endswith("远端新内容"))
            self.assertNotIn("优化结果", chapter["body_markdown"])
            self.assertEqual(self.fixture["generations"][("novel", "fixture-run-1")]["apply_receipts"], {})
        self.assertIn("原文已更新", self.evaluate(page, "document.querySelector('.sm-optimization-status').textContent"))
        self.screenshot_viewport(page, "text-optimization-novel-conflict-preview.png")

        self.evaluate(page, "document.querySelector('.sm-optimization-heading button').click()")
        self.evaluate(page, "document.querySelector('[data-scope=chapter][data-node-id=chapter-1]').click()")
        self.wait(page, "!document.getElementById('smDocumentTabs').hidden")
        self.evaluate(page, "document.getElementById('smDocumentTabOutline').click()")
        self.wait(page, "!!document.querySelector('[data-inline-key=\\\"novel-chapter-outline:chapter-1\\\"]')")
        outline = "本章的独立章纲。"
        self.set_inline_text(page, "novel-chapter-outline:chapter-1", outline)
        self.wait(page, "document.getElementById('smRevisionLabel').textContent==='已保存'", 10)
        with self.fixture["lock"]:
            self.assertEqual(self.fixture["novel"]["chapter"]["outline_markdown"], outline)
            self.assertEqual(self.fixture["novel"]["chapter"]["outline_revision"], 1)
        outline_page = self.new_page(origin + "/static/novel.html?id=novel-fixture")
        self.wait(outline_page, "document.getElementById('smProjectName').textContent==='隔离小说作品'")
        self.evaluate(outline_page, "document.querySelector('[data-scope=chapter][data-node-id=chapter-1]').click()")
        self.wait(outline_page, "!document.getElementById('smDocumentTabs').hidden")
        self.evaluate(outline_page, "document.getElementById('smDocumentTabOutline').click()")
        self.wait(outline_page, "document.querySelector('[data-inline-key=\\\"novel-chapter-outline:chapter-1\\\"]')?.value===" + json.dumps(outline, ensure_ascii=False))
        self.evaluate(outline_page, "document.getElementById('smLanguageButton').click()")
        self.wait(outline_page, "document.documentElement.lang==='en'")
        self.evaluate(outline_page, "document.querySelector('[data-inline-optimize=\\\"novel-chapter-outline:chapter-1\\\"]').click()")
        self.wait(outline_page, "!!document.querySelector('.sm-optimization-dialog')")
        self.assertEqual(self.evaluate(outline_page, "document.getElementById('smOptimizationTitle').textContent"), "Text optimization")
        self.evaluate(outline_page, "document.querySelector('.sm-optimization-prompt').value='Make this outline clearer.'")
        self.evaluate(outline_page, "document.querySelector('.sm-optimization-actions button:nth-child(2)').click()")
        self.wait(outline_page, "!document.querySelector('[aria-label=\\\"Optimized result preview\\\"]').hidden && document.querySelector('[aria-label=\\\"Optimized result preview\\\"]').value.includes('优化结果')", 10)
        with self.fixture["lock"]:
            outline_request = self.fixture["generation_attempts"][-1]["payload"]
            self.assertEqual(outline_request["scope"], "chapter_outline")
            self.assertEqual(outline_request["expected_source_revision"], 1)
            self.assertEqual(outline_request["base_revision"], self.fixture["novel"]["revision"])
            self.assertEqual(self.fixture["generations"][("novel", f"fixture-run-{len(self.fixture['generations'])}")]["submit_payload"]["settings_revision"], 3)
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True}, outline_page["session"])
        mobile = self.evaluate(outline_page, "(()=>{const dialog=document.querySelector('.sm-optimization-dialog'),rect=dialog.getBoundingClientRect();return{left:rect.left,right:rect.right,width:rect.width,client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,title:document.getElementById('smOptimizationTitle').textContent}})()")
        self.assertGreaterEqual(mobile["left"], 0)
        self.assertLessEqual(mobile["right"], mobile["client"])
        self.assertLessEqual(mobile["scroll"], mobile["client"])
        self.assertEqual(mobile["title"], "Text optimization")
        self.screenshot_viewport(outline_page, "text-optimization-novel-outline-mobile-390px-en.png")
        self.cdp("Emulation.clearDeviceMetricsOverride", session_id=outline_page["session"])

    def test_text_optimization_settings_open_shared_module_canvas(self):
        origin = f"http://127.0.0.1:{self.port}"
        page = self.new_page(origin + "/static/api-settings.html")
        self.wait(page, "!!document.getElementById('scriptSettingsNav') && !!document.getElementById('novelSettingsNav')", 15)
        order = self.evaluate(page, "(()=>{const ids=['articleSettingsNav','musicSettingsNav','scriptSettingsNav','novelSettingsNav'];return ids.map(id=>[...document.querySelectorAll('button')].indexOf(document.getElementById(id)));})()")
        self.assertEqual(order, sorted(order))
        self.evaluate(page, "document.getElementById('scriptSettingsNav').click()")
        self.wait(page, "!document.getElementById('scriptSettingsBlock').hidden && document.getElementById('scriptSettingsCanvasFrame').src.includes('id=script-settings')", 15)
        self.wait(page, "document.querySelector('#scriptSettingsCanvasFrame')?.contentDocument?.readyState==='complete'", 15)
        self.wait(page, "document.getElementById('scriptSettingsCanvasFrame')?.contentDocument?.querySelectorAll('.image-node').length===2", 15)
        self.assertEqual(self.evaluate(page, "new URL(document.getElementById('scriptSettingsCanvasFrame').src).searchParams.get('mode')"), "script-settings")
        graph = self.evaluate(page, "(()=>{const d=document.getElementById('scriptSettingsCanvasFrame').contentDocument;return {mode:d.documentElement.dataset.canvasMode,settings:d.documentElement.dataset.textOptimizationSettings,nodes:[...d.querySelectorAll('.image-node')].map(n=>n.dataset.id),outputs:[...d.querySelectorAll('.hypit-output-node')].map(n=>n.dataset.hypitSlot),edgeCount:d.querySelectorAll('svg.connection-layer .conn-line').length};})()")
        self.assertEqual(graph["mode"], "script-settings")
        self.assertEqual(graph["settings"], "true")
        self.assertEqual(graph["nodes"], ["script-text-generator", "script-text-output"],
            f"共享配置图应恢复 fixture 的真实文本节点：graph={graph}; requests={self.fixture['get_requests'][-15:]}; responses={self.fixture['get_responses'][-8:]}")
        self.assertEqual(graph["outputs"], ["text"])
        self.assertEqual(graph["edgeCount"], 1, f"隔离配置图应呈现实际文本生成器到文本输出的连线：{graph}")
        desktop_toolbar = self.evaluate(page, "(()=>{const d=document.getElementById('scriptSettingsCanvasFrame').contentDocument,t=d.getElementById('settingsCanvasToolbar').getBoundingClientRect(),title=d.getElementById('smartTitle').getBoundingClientRect();return {toolbar:{left:t.left,right:t.right,top:t.top,bottom:t.bottom},title:{left:title.left,right:title.right,top:title.top,bottom:title.bottom},scrollWidth:d.getElementById('settingsCanvasToolbar').scrollWidth,clientWidth:d.getElementById('settingsCanvasToolbar').clientWidth};})()")
        self.assertGreaterEqual(desktop_toolbar["toolbar"]["left"], desktop_toolbar["title"]["right"], f"桌面工具组不能覆盖配置图标题：{desktop_toolbar}")
        self.evaluate(page, "document.getElementById('scriptSettingsCanvasFrame').contentDocument.querySelector('.image-node[data-id=script-text-generator]').click()")
        self.wait(page, "document.getElementById('scriptSettingsCanvasFrame')?.contentDocument?.querySelector('.text-generation-params')", 12)
        with self.fixture["lock"]:
            self.assertEqual(self.fixture["settings_model_option_requests"], [{"module_id": "script", "slot_id": "text"}],
                "连接文本输出的文本生成节点只能读取 script/text 白名单候选")
        self.evaluate(page, "(()=>{const d=document.getElementById('scriptSettingsCanvasFrame').contentDocument;d.getElementById('hypitOutputDrawerToggle').click();return true})()")
        self.wait(page, "!document.getElementById('scriptSettingsCanvasFrame').contentDocument.getElementById('hypitOutputDrawer').hidden")
        visible_outputs = self.evaluate(page, "[...document.getElementById('scriptSettingsCanvasFrame').contentDocument.querySelectorAll('.hypit-output-drawer-list [data-hypit-slot]:not([hidden])')].map(n=>n.dataset.hypitSlot)")
        self.assertEqual(visible_outputs, ["text"], "剧本配置图的输出选择只允许文本")
        self.evaluate(page, "document.getElementById('scriptSettingsCanvasFrame').contentDocument.getElementById('hypitOutputDrawerToggle').click()")
        self.screenshot_viewport(page, "text-settings-script-shared-canvas.png")

        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True}, session_id=page["session"])
        self.wait(page, "document.documentElement.clientWidth===390 && document.getElementById('scriptSettingsCanvasFrame')?.contentDocument?.documentElement?.clientWidth<=900", 12)
        narrow = self.evaluate(page, "(()=>{const d=document.getElementById('scriptSettingsCanvasFrame').contentDocument,t=d.getElementById('settingsCanvasToolbar'),r=t.getBoundingClientRect(),title=d.getElementById('smartTitle').getBoundingClientRect();return {viewport:d.documentElement.clientWidth,toolbar:{left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,scrollWidth:t.scrollWidth,clientWidth:t.clientWidth,scrollLeft:t.scrollLeft},title:{top:title.top,bottom:title.bottom},buttons:[...t.querySelectorAll(':scope > button')].map(b=>({id:b.id,display:getComputedStyle(b).display,disabled:b.disabled})),settings:d.documentElement.dataset.textOptimizationSettings};})()")
        self.assertEqual(narrow["settings"], "true")
        self.assertGreater(narrow["toolbar"]["width"], 0, narrow)
        self.assertGreater(narrow["toolbar"]["scrollWidth"], narrow["toolbar"]["clientWidth"], "窄屏工具栏应横向滚动而不互相覆盖")
        self.assertGreaterEqual(narrow["toolbar"]["top"], narrow["title"]["bottom"], f"窄屏工具栏不能遮住配置图标题：{narrow}")
        display_by_id = {item["id"]: item["display"] for item in narrow["buttons"]}
        self.assertEqual(display_by_id.get("smartShortcutToggle"), "flex", f"窄屏快捷键入口仍可用：{narrow}")
        self.assertEqual(display_by_id.get("smartPriceToggle"), "flex", f"窄屏价格入口仍可用：{narrow}")
        self.evaluate(page, "(()=>{const d=document.getElementById('scriptSettingsCanvasFrame').contentDocument,t=d.getElementById('settingsCanvasToolbar');t.scrollLeft=t.scrollWidth;return true})()")
        final_toolbar_button = self.evaluate(page, "(()=>{const d=document.getElementById('scriptSettingsCanvasFrame').contentDocument,t=d.getElementById('settingsCanvasToolbar'),b=d.getElementById('assetToggle'),r=b.getBoundingClientRect(),p=d.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return {id:b.id,visible:r.left>=t.getBoundingClientRect().left&&r.right<=t.getBoundingClientRect().right,hit:p===b||b.contains(p),disabled:b.disabled};})()")
        self.assertEqual(final_toolbar_button, {"id": "assetToggle", "visible": True, "hit": True, "disabled": False}, f"滚动后末尾工具仍应能点击：{final_toolbar_button}")
        self.evaluate(page, "document.getElementById('scriptSettingsCanvasFrame').contentDocument.getElementById('settingsCanvasToolbar').scrollLeft=0")
        self.evaluate(page, "document.getElementById('scriptSettingsCanvasFrame').scrollIntoView({block:'center'})")
        self.screenshot_viewport(page, "text-settings-script-shared-canvas-mobile-390px.png")
        self.cdp("Emulation.clearDeviceMetricsOverride", session_id=page["session"])

    def test_unicode_character_count_tracks_drafts_and_all_pages(self):
        origin = f"http://127.0.0.1:{self.port}"
        special = (
            "# 中文A2\n\n正文 e\u0301🙂，？\n\n[可数链接](https://example.com/123)\n\n"
            "![不可数图片](https://image.example/45.png)\n\n`code_67`\n\n"
            "| 标题 | 数字 |\n|---|---|\n| 项2 | 字符 |\n\n- 第3项\n\n"
            "```js\nconst x1 = 2;\n```"
        )
        empty_markdown = "!!!，。🙂\n___\n---\n```\n🙂\n```"
        with self.fixture["lock"]:
            script = self.fixture["script"]
            script["episodes"] = [{"id": "episode-many", "title": "长剧集", "scenes": []}]
            for index in range(35):
                body = special if index == 0 else empty_markdown if index == 1 else "场次正文"
                script["episodes"][0]["scenes"].append({
                    "id": f"scene-{index + 1}", "title": f"第 {index + 1} 场", "body_markdown": body,
                    "content_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    "editable_markdown": body, "scene_revision": 1,
                    "segments": [{"id": f"segment-{index + 1}", "title": f"legacy title {index + 1}", "start": 0, "end": len(body)}],
                })
            novel = self.fixture["novel"]
            chapters = []
            for index in range(35):
                body = special if index == 0 else "章节正文"
                chapters.append({"id": f"chapter-{index + 1}", "title": f"第 {index + 1} 章", "volume_id": "volume-many",
                    "body_markdown": body, "content_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(), "chapter_revision": 1})
            novel["volume"] = {"id": "volume-many", "title": "长卷"}
            novel["chapter"] = chapters[0]
            novel["volumes"] = [{**novel["volume"], "chapters": chapters}]

        script_page = self.new_page(origin + "/static/script.html?id=script-fixture")
        self.wait(script_page, "document.getElementById('smProjectName').textContent==='隔离剧本作品'")
        if self.evaluate(script_page, "document.getElementById('smLanguageButton').textContent==='EN'"):
            self.evaluate(script_page, "document.getElementById('smLanguageButton').click()")
        self.wait(script_page, "document.getElementById('smCharacterCount').textContent==='字符数：168'", 10)
        self.wait(script_page, "document.querySelectorAll('.sm-inline-input').length===30 && !document.getElementById('smLoadMoreButton').hidden")
        self.assertEqual(self.evaluate(script_page, "document.querySelector('.sm-inline-input')?.value"), special)
        with self.fixture["lock"]:
            self.assertTrue(any(row["module"] == "script" and row["scope"] == "root" and row["cursor"] == "30" for row in self.fixture["view_requests"]))
        self.screenshot_viewport(script_page, "character-count-script-root.png")
        self.evaluate(script_page, "document.getElementById('smLoadMoreButton').click()")
        self.wait(script_page, "document.querySelectorAll('.sm-inline-input').length===35 && document.getElementById('smLoadMoreButton').hidden")
        self.assertEqual(self.evaluate(script_page, "document.getElementById('smCharacterCount').textContent"), "字符数：168")
        self.evaluate(script_page, "document.querySelector('[data-scope=episode]').click()")
        self.wait(script_page, "document.getElementById('smCharacterCount').textContent==='字符数：168'")
        self.evaluate(script_page, "document.querySelector('[data-scope=scene][data-node-id=scene-1]').click()")
        self.wait(script_page, "document.getElementById('smCharacterCount').textContent==='字符数：36'")
        self.evaluate(script_page, "document.querySelector('[data-scope=segment][data-node-id=segment-1]').click()")
        self.wait(script_page, "document.getElementById('smCharacterCount').textContent==='字符数：36'")
        self.evaluate(script_page, "document.querySelector('[data-scope=scene][data-node-id=scene-2]').click()")
        self.wait(script_page, "document.getElementById('smCharacterCount').textContent==='字符数：0'")

        # An unstructured root draft is also counted; the inline draft delta is visible before its debounce save.
        with self.fixture["lock"]:
            script["state"] = "draft"
            script["draft"] = "# 草稿\n\n中文123🙂"
            script["revision"] += 1
            next(item for item in self.fixture["projects"] if item["id"] == "script-fixture")["revision"] = script["revision"]
        self.evaluate(script_page, "document.querySelector('[data-scope=root]').click()")
        self.evaluate(script_page, "document.getElementById('smRefreshButton').click()")
        self.wait(script_page, "document.querySelector('.sm-inline-input[data-inline-key=\"script-draft:root\"]') && document.getElementById('smCharacterCount').textContent==='字符数：7'")
        self.set_inline_text(script_page, "script-draft:root", "# 草稿\n\n中文123🙂Z9")
        self.assertEqual(self.evaluate(script_page, "document.getElementById('smCharacterCount').textContent"), "字符数：9")
        self.wait(script_page, "document.getElementById('smRevisionLabel').textContent==='已保存' && document.getElementById('smCharacterCount').textContent==='字符数：9'", 8)

        novel_page = self.new_page(origin + "/static/novel.html?id=novel-fixture")
        self.wait(novel_page, "document.getElementById('smCharacterCount').textContent==='字符数：172'", 10)
        self.wait(novel_page, "document.querySelectorAll('.sm-inline-input').length===30 && !document.getElementById('smLoadMoreButton').hidden")
        with self.fixture["lock"]:
            self.assertTrue(any(row["module"] == "novel" and row["scope"] == "root" and row["cursor"] == "30" for row in self.fixture["view_requests"]))
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True}, novel_page["session"])
        narrow = self.evaluate(novel_page, "({width:document.getElementById('smCharacterCount').getBoundingClientRect().width,scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth})")
        self.assertGreater(narrow["width"], 0)
        self.assertLessEqual(narrow["scroll"], narrow["client"])
        self.screenshot_viewport(novel_page, "character-count-novel-mobile-390px.png")
        self.cdp("Emulation.clearDeviceMetricsOverride", session_id=novel_page["session"])
        self.screenshot_viewport(novel_page, "character-count-novel-root.png")
        # Load and cache the last page, update its clean bucket remotely, then return to a 30-row root view.
        self.evaluate(novel_page, "document.getElementById('smLoadMoreButton').click()")
        self.wait(novel_page, "document.querySelectorAll('.sm-inline-input').length===35")
        self.evaluate(novel_page, "document.querySelector('[data-scope=chapter][data-node-id=chapter-35]').click()")
        self.wait(novel_page, "document.querySelector('.sm-inline-input[data-inline-key=\"novel-chapter:chapter-35\"]')")
        with self.fixture["lock"]:
            novel["volumes"][0]["chapters"][-1]["body_markdown"] = "远端更新内容"
            novel["volumes"][0]["chapters"][-1]["content_sha256"] = hashlib.sha256("远端更新内容".encode("utf-8")).hexdigest()
            novel["revision"] += 1
            next(item for item in self.fixture["projects"] if item["id"] == "novel-fixture")["revision"] = novel["revision"]
        self.evaluate(novel_page, "document.querySelector('[data-scope=root]').click()")
        self.wait(novel_page, "document.getElementById('smCharacterCount').textContent==='字符数：174' && document.querySelectorAll('.sm-inline-input').length===30", 10)
        self.assertTrue(self.evaluate(novel_page, "!document.getElementById('smLoadMoreButton').hidden"))
        self.evaluate(novel_page, "document.querySelector('[data-scope=volume]').click()")
        self.wait(novel_page, "document.getElementById('smCharacterCount').textContent==='字符数：174'")
        self.evaluate(novel_page, "document.querySelector('[data-scope=chapter][data-node-id=chapter-1]').click()")
        self.wait(novel_page, "document.getElementById('smCharacterCount').textContent==='字符数：36'")
        self.assertEqual(self.evaluate(novel_page, "document.getElementById('smCharacterCount').title"),
            "统计正文中 Unicode 字母和数字；不计标点、空白、Markdown 语法或图片说明。")

        # IME drafts update the count immediately without entering the save path until composition ends.
        before = len(self.fixture["command_attempts"])
        self.evaluate(novel_page, "window.__studioManuscript.fireInlineComposition('novel-chapter:chapter-1','compositionstart')")
        self.set_inline_text(novel_page, "novel-chapter:chapter-1", empty_markdown, composing=True)
        self.assertEqual(self.evaluate(novel_page, "document.getElementById('smCharacterCount').textContent"), "字符数：0")
        time.sleep(0.9)
        self.assertEqual(len(self.fixture["command_attempts"]), before)
        self.evaluate(novel_page, "window.__studioManuscript.fireInlineComposition('novel-chapter:chapter-1','compositionend')")
        self.wait(novel_page, "document.getElementById('smRevisionLabel').textContent==='已保存' && document.getElementById('smCharacterCount').textContent==='字符数：0'", 8)
        self.evaluate(novel_page, "document.getElementById('smLanguageButton').click()")
        self.wait(novel_page, "document.getElementById('smCharacterCount').textContent==='Characters: 0'")
        self.assertTrue(self.evaluate(novel_page, "document.getElementById('smCharacterCount').hidden===false"))
        self.evaluate(novel_page, "document.querySelector('[data-sm-tab=settings]').click()")
        self.wait(novel_page, "document.getElementById('smCharacterCount').hidden")
        self.evaluate(novel_page, "document.querySelector('[data-sm-tab=text]').click()")
        self.wait(novel_page, "document.getElementById('smCharacterCount').textContent==='Characters: 0' && !document.getElementById('smCharacterCount').hidden")

    def test_episode_and_chapter_outlines_save_switch_and_isolate(self):
        origin = f"http://127.0.0.1:{self.port}"
        script_page = self.new_page(origin + "/static/script.html?id=script-fixture")
        self.wait(script_page, "document.getElementById('smProjectName').textContent==='隔离剧本作品'")
        self.assertTrue(self.evaluate(script_page, "document.getElementById('smDocumentTabs').hidden"))
        self.evaluate(script_page, "document.querySelector('[data-scope=episode][data-node-id=episode-1]').click()")
        self.wait(script_page, "!document.getElementById('smDocumentTabs').hidden && document.getElementById('smDocumentTabBody').getAttribute('aria-selected')==='true' && !!document.querySelector('.sm-inline-input[data-inline-key=\"script-scene:scene-1\"]')")
        script_body = self.evaluate(script_page, "document.querySelector('.sm-inline-input').value")
        body_count = self.evaluate(script_page, "document.getElementById('smCharacterCount').textContent")
        self.assertTrue(self.evaluate(script_page, "document.getElementById('smDocumentTabOutline').getAttribute('aria-selected')==='false'"))
        self.evaluate(script_page, "document.getElementById('smDocumentTabOutline').click()")
        self.wait(script_page, "document.querySelector('.sm-inline-input[data-inline-key=\"script-episode-outline:episode-1\"]') && document.getElementById('smCharacterCount').textContent==='字符数：0'")
        self.assertEqual(self.evaluate(script_page, "document.getElementById('smScopeTitle').textContent"), "第 1 集")
        episode_outline = "# 章纲A2\n\n- 冲突点：雨夜🙂"
        self.set_inline_text(script_page, "script-episode-outline:episode-1", episode_outline)
        self.assertEqual(self.evaluate(script_page, "document.getElementById('smCharacterCount').textContent"), "字符数：9")
        self.evaluate(script_page, "document.getElementById('smDocumentTabBody').click()")
        self.wait(script_page, "document.getElementById('smDocumentTabBody').getAttribute('aria-selected')==='true' && document.querySelector('.sm-inline-input[data-inline-key=\"script-scene:scene-1\"]')")
        self.wait(script_page, "document.getElementById('smCharacterCount').textContent===" + json.dumps(body_count, ensure_ascii=False))
        with self.fixture["lock"]:
            episode = script_episode(self.fixture, "episode-1")
            self.assertEqual(episode["outline_markdown"], episode_outline)
            self.assertEqual(episode["outline_revision"], 1)
            self.assertEqual(script_body, self.fixture["script"]["episodes"][0]["scenes"][0]["body_markdown"])
            outline_commands = [row["payload"] for row in self.fixture["command_attempts"] if row["payload"]["action"] == "batch" and any(op["action"] == "set_episode_outline" for op in row["payload"]["args"]["operations"])]
            self.assertEqual(len(outline_commands), 1)
            self.assertEqual(outline_commands[0]["args"]["operations"][0]["args"], {"episode_id": "episode-1", "body_markdown": episode_outline})

        # An unknown response keeps the outline pane and the exact draft until the same request is recovered.
        self.evaluate(script_page, "document.getElementById('smDocumentTabOutline').click()")
        self.wait(script_page, "document.querySelector('.sm-inline-input[data-inline-key=\"script-episode-outline:episode-1\"]')?.value===" + json.dumps(episode_outline, ensure_ascii=False))
        unknown_text = episode_outline + "\n\n复试B3"
        with self.fixture["lock"]: self.fixture["unknown_next_command_response"] = True
        before_commands = len(self.fixture["command_attempts"])
        self.set_inline_text(script_page, "script-episode-outline:episode-1", unknown_text)
        self.evaluate(script_page, "document.getElementById('smDocumentTabBody').click()")
        self.wait(script_page, "document.querySelector('[data-inline-retry=\"script-episode-outline:episode-1\"]')")
        self.assertTrue(self.evaluate(script_page, "document.getElementById('smDocumentTabOutline').getAttribute('aria-selected')==='true'"))
        self.assertEqual(self.evaluate(script_page, "document.querySelector('.sm-inline-input[data-inline-key=\"script-episode-outline:episode-1\"]').value"), unknown_text)
        request_id = self.fixture["command_attempts"][before_commands]["payload"]["request_id"]
        self.evaluate(script_page, "document.querySelector('[data-inline-retry=\"script-episode-outline:episode-1\"]').click()")
        self.wait(script_page, "document.getElementById('smRevisionLabel').textContent==='已保存' && document.querySelector('.sm-inline-input[data-inline-key=\"script-episode-outline:episode-1\"]')?.value===" + json.dumps(unknown_text, ensure_ascii=False))
        with self.fixture["lock"]:
            self.assertEqual(self.fixture["script"]["episodes"][0]["outline_markdown"], unknown_text)
            self.assertEqual(self.fixture["command_attempts"][before_commands]["payload"]["request_id"], request_id)
            self.assertEqual(sum(row["payload"]["request_id"] == request_id for row in self.fixture["command_attempts"]), 1)
        self.screenshot_viewport(script_page, "chapter-outline-script-episode.png")

        # A concurrent revision blocks switching and leaves the text available for explicit review.
        conflict_text = unknown_text + "\n\n本地草稿"
        with self.fixture["lock"]: self.fixture["conflict_next_command"] = True
        self.set_inline_text(script_page, "script-episode-outline:episode-1", conflict_text)
        self.evaluate(script_page, "document.getElementById('smDocumentTabBody').click()")
        self.wait(script_page, "document.querySelector('[data-inline-confirm=\"script-episode-outline:episode-1\"]') && document.querySelector('.sm-inline-input[data-inline-key=\"script-episode-outline:episode-1\"]')?.value===" + json.dumps(conflict_text, ensure_ascii=False))
        self.assertTrue(self.evaluate(script_page, "document.getElementById('smDocumentTabOutline').getAttribute('aria-selected')==='true'"))
        self.assertEqual(self.evaluate(script_page, "document.querySelector('.sm-inline-input[data-inline-key=\"script-episode-outline:episode-1\"]').value"), conflict_text)
        self.evaluate(script_page, "document.querySelector('[data-inline-confirm=\"script-episode-outline:episode-1\"]').click()")
        self.wait(script_page, "document.getElementById('smRevisionLabel').textContent==='已保存' && document.querySelector('.sm-inline-input[data-inline-key=\"script-episode-outline:episode-1\"]')?.value===" + json.dumps(conflict_text, ensure_ascii=False))

        # A second episode has an independent current outline, and returning to the first restores its saved value.
        with self.fixture["lock"]:
            script = self.fixture["script"]
            script["episodes"].append({"id": "episode-2", "title": "第 2 集", "outline_markdown": "第二集纲要B7", "outline_revision": 1, "outline_history": [], "scenes": []})
            script["revision"] += 1
            next(item for item in self.fixture["projects"] if item["id"] == "script-fixture")["revision"] = script["revision"]
        self.evaluate(script_page, "document.getElementById('smRefreshButton').click()")
        self.wait(script_page, "document.querySelector('[data-scope=episode][data-node-id=episode-2]')")
        self.evaluate(script_page, "document.querySelector('[data-scope=episode][data-node-id=episode-2]').click()")
        self.wait(script_page, "document.getElementById('smScopeTitle').textContent==='第 2 集' && !document.getElementById('smDocumentTabs').hidden")
        self.evaluate(script_page, "document.getElementById('smDocumentTabOutline').click()")
        self.wait(script_page, "document.querySelector('.sm-inline-input[data-inline-key=\"script-episode-outline:episode-2\"]')?.value==='第二集纲要B7'")
        self.assertNotEqual(self.evaluate(script_page, "document.querySelector('.sm-inline-input').value"), unknown_text)
        self.evaluate(script_page, "document.querySelector('[data-scope=episode][data-node-id=episode-1]').click()")
        self.wait(script_page, "document.getElementById('smScopeTitle').textContent==='第 1 集'")
        self.evaluate(script_page, "document.getElementById('smDocumentTabOutline').click()")
        self.wait(script_page, "document.querySelector('.sm-inline-input[data-inline-key=\"script-episode-outline:episode-1\"]')?.value===" + json.dumps(conflict_text, ensure_ascii=False))

        novel_page = self.new_page(origin + "/static/novel.html?id=novel-fixture")
        self.wait(novel_page, "document.getElementById('smProjectName').textContent==='隔离小说作品'")
        self.assertTrue(self.evaluate(novel_page, "document.getElementById('smDocumentTabs').hidden"))
        self.evaluate(novel_page, "document.querySelector('[data-scope=chapter][data-node-id=chapter-1]').click()")
        self.wait(novel_page, "!document.getElementById('smDocumentTabs').hidden && document.getElementById('smScopeTitle').textContent==='第一章'")
        novel_body_count = self.evaluate(novel_page, "document.getElementById('smCharacterCount').textContent")
        novel_body = self.evaluate(novel_page, "document.querySelector('.sm-inline-input').value")
        self.evaluate(novel_page, "document.getElementById('smDocumentTabOutline').click()")
        self.wait(novel_page, "document.querySelector('.sm-inline-input[data-inline-key=\"novel-chapter-outline:chapter-1\"]') && document.getElementById('smCharacterCount').textContent==='字符数：0'")
        chapter_outline = "## 章纲1🙂\n\n- 人物：林青，线索A2"
        self.set_inline_text(novel_page, "novel-chapter-outline:chapter-1", chapter_outline)
        self.assertEqual(self.evaluate(novel_page, "document.getElementById('smCharacterCount').textContent"), "字符数：11")
        self.evaluate(novel_page, "document.getElementById('smDocumentTabBody').click()")
        self.wait(novel_page, "document.getElementById('smDocumentTabBody').getAttribute('aria-selected')==='true' && document.querySelector('.sm-inline-input[data-inline-key=\"novel-chapter:chapter-1\"]')")
        self.wait(novel_page, "document.getElementById('smCharacterCount').textContent===" + json.dumps(novel_body_count, ensure_ascii=False))
        self.assertEqual(self.evaluate(novel_page, "document.querySelector('.sm-inline-input').value"), novel_body)
        with self.fixture["lock"]:
            chapter = self.fixture["novel"]["chapter"]
            self.assertEqual(chapter["outline_markdown"], chapter_outline)
            self.assertEqual(chapter["outline_revision"], 1)
            self.assertEqual(chapter["body_markdown"], novel_body)
        self.evaluate(novel_page, "document.getElementById('smDocumentTabOutline').click()")
        self.wait(novel_page, "document.querySelector('.sm-inline-input[data-inline-key=\"novel-chapter-outline:chapter-1\"]')?.value===" + json.dumps(chapter_outline, ensure_ascii=False))
        self.screenshot_viewport(novel_page, "chapter-outline-novel-chapter.png")

        with self.fixture["lock"]:
            novel = self.fixture["novel"]
            second = {"id": "chapter-2", "title": "第二章", "volume_id": "volume-1", "body_markdown": "第二章正文", "chapter_revision": 1,
                      "content_sha256": hashlib.sha256("第二章正文".encode("utf-8")).hexdigest(),
                      "outline_markdown": "第二章独立章纲C3", "outline_revision": 1, "outline_history": []}
            novel["volumes"][0]["chapters"].append(second)
            novel["revision"] += 1
            next(item for item in self.fixture["projects"] if item["id"] == "novel-fixture")["revision"] = novel["revision"]
        self.evaluate(novel_page, "document.getElementById('smRefreshButton').click()")
        self.wait(novel_page, "document.querySelector('[data-scope=chapter][data-node-id=chapter-2]')")
        self.evaluate(novel_page, "document.querySelector('[data-scope=chapter][data-node-id=chapter-2]').click()")
        self.wait(novel_page, "document.getElementById('smScopeTitle').textContent==='第二章'")
        self.evaluate(novel_page, "document.getElementById('smDocumentTabOutline').click()")
        self.wait(novel_page, "document.querySelector('.sm-inline-input[data-inline-key=\"novel-chapter-outline:chapter-2\"]')?.value==='第二章独立章纲C3'")
        self.assertNotEqual(self.evaluate(novel_page, "document.querySelector('.sm-inline-input').value"), chapter_outline)
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True}, novel_page["session"])
        mobile = self.evaluate(novel_page, "({tabs:document.getElementById('smDocumentTabs').getBoundingClientRect().width,scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth,outlineVisible:!document.getElementById('smDocumentTabOutline').hidden})")
        self.assertGreater(mobile["tabs"], 0)
        self.assertTrue(mobile["outlineVisible"])
        self.assertLessEqual(mobile["scroll"], mobile["client"])
        self.screenshot_viewport(novel_page, "chapter-outline-mobile-390px.png")
        self.cdp("Emulation.clearDeviceMetricsOverride", session_id=novel_page["session"])

    def test_lists_routes_reading_editing_sync_and_mobile_recovery(self):
        origin = f"http://127.0.0.1:{self.port}"
        index = self.new_page(origin + "/static/index.html")
        self.wait(index, "document.getElementById('nav-script') && document.getElementById('nav-novel')")
        order = self.evaluate(index, "(()=>{const n=document.querySelector('nav');return [...n.querySelectorAll('.nav-item')].map(x=>x.querySelector('[data-i18n]')?.getAttribute('data-i18n')||'').filter(Boolean)})()")
        self.assertLess(order.index("nav.music"), order.index("nav.script"))
        self.assertLess(order.index("nav.script"), order.index("nav.novel"))
        self.assertLess(order.index("nav.novel"), order.index("nav.assetManager"))
        self.evaluate(index, "document.getElementById('nav-script').click()")
        self.wait(index, "document.getElementById('frame-script').getAttribute('src')?.includes('script-list.html') && document.getElementById('frame-script').contentDocument?.body?.dataset?.studioModule==='script'")
        self.evaluate(index, "document.getElementById('nav-novel').click()")
        self.wait(index, "document.getElementById('frame-novel').contentDocument?.body?.dataset?.studioModule==='novel'")
        self.screenshot(index, "final-inline-main-menu-routes.png")

        script_list = self.new_page(origin + "/static/script-list.html")
        self.wait(script_list, "document.querySelector('[data-card-action=\"open\"]')")
        self.evaluate(script_list, "document.getElementById('studioNewProjectButton').click()")
        self.wait(script_list, "document.querySelector('.studio-dialog-input')")
        self.evaluate(script_list, "(()=>{const i=document.querySelector('.studio-dialog-input');i.value='浏览器隔离新剧本';document.querySelector('.studio-dialog-btn.primary').click()})()")
        self.wait(script_list, "[...document.querySelectorAll('.studio-project-card h3,.studio-project-card .studio-project-card-title')].some(x=>x.textContent.includes('浏览器隔离新剧本')) || document.body.innerText.includes('浏览器隔离新剧本')")
        self.evaluate(script_list, "window.__openedURL='';window.open=()=>({document:{set title(v){window.__openedTitle=v}},location:{set href(v){window.__openedURL=v}}});document.querySelector('[data-card-action=\"open\"]').click()")
        self.wait(script_list, "window.__openedURL.includes('/static/script.html?id=script-fixture')")
        connect_button = self.evaluate(script_list, "(()=>{const b=document.querySelector('[data-card-action=\"connect\"]');b.id='fixture-list-connect';b.focus();b.click();return b.id})()")
        self.wait(script_list, "document.getElementById('studioConnectionDialog')?.open")
        self.assertEqual(self.evaluate(script_list, "document.querySelector('#studioConnectionDialog textarea').value"), "fixture connection for script-fixture; module=script")
        self.evaluate(script_list, "document.querySelector('#studioConnectionDialog [data-close]').click()")
        self.wait(script_list, "document.activeElement.id==='fixture-list-connect'")
        self.assertEqual(self.evaluate(script_list, "document.activeElement.id"), connect_button)
        self.evaluate(script_list, "(()=>{const b=document.getElementById('studioPrepareButton');b.focus();b.click()})()")
        self.wait(script_list, "document.getElementById('studioConnectionDialog')?.open")
        self.assertEqual(self.evaluate(script_list, "document.querySelector('#studioConnectionDialog textarea').value"), "fixture preparation instructions")
        self.evaluate(script_list, "document.querySelector('#studioConnectionDialog [data-close]').click()")
        self.wait(script_list, "document.activeElement.id==='studioPrepareButton'")
        self.screenshot(script_list, "final-inline-script-project-list.png")

        novel_list = self.new_page(origin + "/static/novel-list.html")
        self.wait(novel_list, "document.body.dataset.studioModule==='novel' && document.getElementById('studioProjectGrid')")
        self.assertIn("隔离小说作品", self.evaluate(novel_list, "document.getElementById('studioProjectGrid').innerText"))
        self.screenshot(novel_list, "final-inline-novel-project-list.png")

        script_page = self.new_page(origin + "/static/script.html?id=script-fixture")
        self.wait(script_page, "document.getElementById('smProjectName').textContent==='隔离剧本作品'")
        self.wait(script_page, "document.querySelector('.sm-inline-input')?.value.includes('片段乙文本')")
        root_text = self.evaluate(script_page, "document.querySelector('.sm-inline-input')?.value||''")
        for phrase in ("开场未分段🙂", "片段甲文本", "中间未分段", "片段乙文本", "结尾未分段"):
            self.assertEqual(root_text.count(phrase), 1, phrase)
        tree_state = self.evaluate(script_page, "({breadcrumbHidden:document.getElementById('smBreadcrumb').hidden,editHidden:document.getElementById('smEditButton').hidden,scope:document.getElementById('smScopeTitle').textContent,sceneNested:!!document.querySelector('.sm-tree-nested-group > .sm-tree-row > [data-scope=scene]'),segmentNested:!!document.querySelector('.sm-tree-nested-group .sm-tree-children [data-scope=segment]'),duplicateLabels:document.querySelectorAll('.sm-script-block-heading,.sm-segment-heading,.sm-unsegmented-label').length})")
        self.assertTrue(tree_state["breadcrumbHidden"] and tree_state["editHidden"], tree_state)
        self.assertEqual(tree_state["scope"], "完整剧本")
        self.assertTrue(tree_state["sceneNested"] and tree_state["segmentNested"], tree_state)
        self.assertEqual(tree_state["duplicateLabels"], 0)
        initial_segment_labels = self.evaluate(script_page, "[...document.querySelectorAll('[data-scope=segment] span')].map(node=>node.textContent)")
        self.assertEqual(initial_segment_labels, ["第1段", "第2段"], initial_segment_labels)
        self.assertEqual([item["title"] for item in self.fixture["script"]["episodes"][0]["scenes"][0]["segments"]], ["素材分段甲", "第二段"])
        self.evaluate(script_page, "document.querySelector('[data-scope=segment][data-node-id=segment-2]').click()")
        self.wait(script_page, "document.getElementById('smScopeTitle').textContent==='第2段'")
        self.assertEqual(self.evaluate(script_page, "document.querySelector('.sm-inline-input').getAttribute('aria-label')"), "第2段")
        self.evaluate(script_page, "document.querySelector('[data-scope=root]').click()")
        self.wait(script_page, "document.querySelector('[data-scope=root][aria-current=page]')")
        self.evaluate(script_page, "document.querySelector('[data-scope=\"episode\"]').click()")
        self.wait(script_page, "document.querySelectorAll('.sm-inline-input').length===1 && document.querySelector('.sm-inline-input').value.includes('片段乙文本')")
        self.evaluate(script_page, "document.querySelector('[data-scope=\"segment\"][data-node-id=\"segment-1\"]').click()")
        self.wait(script_page, "document.querySelector('[data-scope=\"segment\"][aria-current=\"page\"]') && document.querySelector('.sm-inline-input')?.value.trim()==='片段甲文本'")
        selected_segment = self.evaluate(script_page, "document.querySelector('.sm-inline-input').value")
        self.assertIn("片段甲文本", selected_segment)
        self.assertNotIn("片段乙文本", selected_segment)
        self.begin_edit(script_page)
        self.set_editor_text(script_page, "片段甲已修订")
        self.wait(script_page, "document.getElementById('smRevisionLabel').textContent==='已保存' && document.querySelector('.sm-inline-input').value==='片段甲已修订'", 6)
        self.assertTrue(self.evaluate(script_page, "document.getElementById('smEditButton').hidden && !document.getElementById('smCopyButton').hidden"))
        self.set_editor_text(script_page, "片段甲已修订\n\n保存后继续输入的草稿。")
        self.evaluate(script_page, "document.getElementById('smEditButton').click();document.getElementById('smCopyButton').click()")
        self.assertEqual(self.evaluate(script_page, "document.querySelector('.sm-inline-input').value"), "片段甲已修订\n\n保存后继续输入的草稿。")
        self.wait(script_page, "document.getElementById('smRevisionLabel').textContent==='已保存'", 6)
        self.evaluate(script_page, "document.getElementById('smCopyButton').click()")
        self.wait(script_page, "document.getElementById('smCopyFeedback').textContent==='已复制'")
        self.assertEqual(self.evaluate(script_page, "window.__studioManuscriptClipboard"), "片段甲已修订\n\n保存后继续输入的草稿。")
        self.evaluate(script_page, "navigator.clipboard.writeText=async()=>{throw new Error('clipboard denied')};document.getElementById('smCopyButton').click()")
        self.wait(script_page, "document.getElementById('smCopyFeedback').classList.contains('error')")
        self.assertIn("权限", self.evaluate(script_page, "document.getElementById('smCopyFeedback').textContent"))
        self.evaluate(script_page, "navigator.clipboard.writeText=async value=>{window.__studioManuscriptClipboard=String(value)};document.getElementById('smCopyButton').click()")
        self.wait(script_page, "document.getElementById('smCopyFeedback').classList.contains('success')")
        self.screenshot(script_page, "final-inline-script-segment-reader.png")

        def open_outline_action(page, scope, node_id, action):
            selector = f'[data-outline-menu-toggle][data-outline-scope="{scope}"][data-outline-node-id="{node_id}"]'
            self.evaluate(page, f"document.querySelector({json.dumps(selector)}).click()")
            menu_selector = f'[data-outline-menu-action="{action}"][data-outline-scope="{scope}"][data-outline-node-id="{node_id}"]'
            self.wait(page, f"document.querySelector({json.dumps(menu_selector)})")
            self.evaluate(page, f"document.querySelector({json.dumps(menu_selector)}).click()")
            self.wait(page, "!document.getElementById('smOutlineDialog').hidden")

        # 目录操作经真实 Chrome 和 revisioned fixture API；创建定位只接受 receipt.created_ids[client_ref]。
        self.evaluate(script_page, "document.getElementById('smOutlineRootAdd').click()")
        self.wait(script_page, "!document.getElementById('smOutlineDialog').hidden")
        self.evaluate(script_page, "document.getElementById('smOutlineDialogInput').value='第二集';document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(script_page, "document.querySelector('[data-scope=episode][aria-current=page]')?.textContent.includes('第二集')")
        with self.fixture["lock"]:
            create_episode_payload = self.fixture["command_attempts"][-1]["payload"]
            create_episode_receipt = self.fixture["receipts"][create_episode_payload["request_id"]]
            episode_id = create_episode_receipt["created_ids"][create_episode_payload["args"]["client_ref"]]
        self.assertEqual(create_episode_payload["action"], "create_episode")
        self.assertEqual(create_episode_payload["args"]["title"], "第二集")
        self.assertEqual(self.evaluate(script_page, "document.querySelector('[data-scope=episode][aria-current=page]').dataset.nodeId"), episode_id)
        episode_menu_selector = f'[data-outline-menu-toggle][data-outline-scope="episode"][data-outline-node-id="{episode_id}"]'
        self.evaluate(script_page, f"document.querySelector({json.dumps(episode_menu_selector)}).click()")
        episode_rename_selector = f'[data-outline-menu-action="rename"][data-outline-scope="episode"][data-outline-node-id="{episode_id}"]'
        self.wait(script_page, f"document.querySelector({json.dumps(episode_rename_selector)})")
        self.screenshot(script_page, "final-inline-script-outline-row-menu.png")
        self.evaluate(script_page, f"document.querySelector({json.dumps(episode_rename_selector)}).click()")
        self.wait(script_page, "!document.getElementById('smOutlineDialog').hidden")
        self.screenshot(script_page, "final-inline-script-outline-rename-dialog.png")
        self.evaluate(script_page, "document.getElementById('smOutlineDialogInput').value='第二集：雨夜';document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(script_page, "document.querySelector('[data-scope=episode][aria-current=page]')?.textContent.includes('第二集：雨夜')")
        self.assertEqual(script_summary(self.fixture)["directory"]["episodes"][-1]["title"], "第二集：雨夜")

        open_outline_action(script_page, "episode", episode_id, "scene-child")
        # A revision conflict refreshes the directory but keeps the proposed name editable and the dialog closable.
        with self.fixture["lock"]: self.fixture["conflict_next_command"] = True
        self.evaluate(script_page, "document.getElementById('smOutlineDialogInput').value='雨夜门外';document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(script_page, "document.getElementById('smOutlineDialogError').textContent.includes('别处更新')")
        conflict_ui = self.evaluate(script_page, "({value:document.getElementById('smOutlineDialogInput').value,inputDisabled:document.getElementById('smOutlineDialogInput').disabled,closeDisabled:document.querySelector('[data-outline-dialog-close]').disabled})")
        self.assertEqual(conflict_ui, {"value": "雨夜门外", "inputDisabled": False, "closeDisabled": False})
        self.evaluate(script_page, "document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(script_page, "document.querySelector('[data-scope=scene][aria-current=page]')?.textContent.includes('雨夜门外')")
        with self.fixture["lock"]:
            create_scene_payload = self.fixture["command_attempts"][-1]["payload"]
            create_scene_receipt = self.fixture["receipts"][create_scene_payload["request_id"]]
            scene_id = create_scene_receipt["created_ids"][create_scene_payload["args"]["client_ref"]]
        self.assertEqual(create_scene_payload["action"], "create_scene")
        self.assertEqual(create_scene_payload["args"]["episode_id"], episode_id)
        self.assertEqual(create_scene_payload["args"]["body_markdown"], "")
        self.assertEqual(create_scene_receipt["revision"], create_scene_payload["expected_revision"] + 1)
        created_scene = script_scene(self.fixture, scene_id)[1]
        self.assertEqual(created_scene["content_sha256"], hashlib.sha256(b"").hexdigest())
        self.assertEqual(len(created_scene["segments"]), 1)
        self.assertEqual((created_scene["segments"][0]["start"], created_scene["segments"][0]["end"]), (0, 0))

        open_outline_action(script_page, "scene", scene_id, "segment-child")
        self.assertEqual(self.evaluate(script_page, "document.getElementById('smOutlineDialogInput').value"), "第2段")
        self.evaluate(script_page, "document.getElementById('smOutlineDialogInput').value='待写片段';document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(script_page, "document.querySelector('[data-scope=segment][aria-current=page]')?.textContent.includes('第2段')")
        with self.fixture["lock"]:
            create_segment_payload = self.fixture["command_attempts"][-1]["payload"]
            create_segment_receipt = self.fixture["receipts"][create_segment_payload["request_id"]]
            empty_segment_id = create_segment_receipt["created_ids"][create_segment_payload["args"]["client_ref"]]
        self.assertEqual(create_segment_payload["action"], "create_segment")
        self.assertEqual(create_segment_payload["args"], {"title": "待写片段", "client_ref": create_segment_payload["args"]["client_ref"], "scene_id": scene_id, "body_markdown": ""})
        self.assertEqual(len(script_scene(self.fixture, scene_id)[1]["segments"]), 2)
        self.assertEqual(self.evaluate(script_page, "document.querySelector('[data-scope=segment][aria-current=page]').dataset.nodeId"), empty_segment_id)

        # 场次编辑使用 editable_markdown；先自动保存，再打开目录动作，不丢仍在编辑框中的正文。
        scene_selector = f'[data-scope="scene"][data-node-id="{scene_id}"]'
        self.evaluate(script_page, f"document.querySelector({json.dumps(scene_selector)}).click()")
        self.wait(script_page, f"document.querySelector('.sm-inline-input[data-inline-key=\"script-scene:{scene_id}\"]')")
        self.begin_edit(script_page)
        edited_scene = "## 雨夜门外\n\n门外有人停下。\n\n---\n\n门内的灯忽然熄灭。"
        self.set_editor_text(script_page, edited_scene)
        scene_menu_selector = f'[data-outline-menu-toggle][data-outline-scope="scene"][data-outline-node-id="{scene_id}"]'
        self.evaluate(script_page, f"document.querySelector({json.dumps(scene_menu_selector)}).click()")
        scene_rename_selector = f'[data-outline-menu-action="rename"][data-outline-scope="scene"][data-outline-node-id="{scene_id}"]'
        self.wait(script_page, f"document.querySelector({json.dumps(scene_rename_selector)})")
        self.evaluate(script_page, f"document.querySelector({json.dumps(scene_rename_selector)}).click()")
        self.wait(script_page, "!document.getElementById('smOutlineDialog').hidden && document.getElementById('smEditor').hidden")
        self.wait(script_page, f"document.querySelector('.sm-inline-input[data-inline-key=\"script-scene:{scene_id}\"]')?.value.includes('门内的灯忽然熄灭')")
        with self.fixture["lock"]:
            scene_save_payload = next(operation for record in reversed(self.fixture["command_attempts"])
                if record["payload"]["action"] == "batch"
                for operation in record["payload"]["args"]["operations"] if operation["action"] == "update_scene")
            saved_scene = script_scene(self.fixture, scene_id)[1]
        self.assertEqual(scene_save_payload["args"]["body_markdown"], edited_scene)
        self.assertNotIn("invalidate_segments", scene_save_payload["args"])
        self.assertEqual(len(saved_scene["segments"]), 2)
        self.assertNotIn("---", saved_scene["body_markdown"])
        self.assertIn("---", saved_scene["editable_markdown"])
        self.assertEqual(saved_scene["content_sha256"], hashlib.sha256(saved_scene["body_markdown"].encode("utf-8")).hexdigest())
        self.assertEqual(self.evaluate(script_page, "document.querySelector('[data-scope=scene][aria-current=page]').dataset.nodeId"), scene_id)
        self.evaluate(script_page, "document.getElementById('smOutlineDialogInput').value='雨夜内景';document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(script_page, "document.querySelector('[data-scope=scene][aria-current=page]')?.textContent.includes('雨夜内景')")
        with self.fixture["lock"]:
            scene_segments = safe_copy(script_scene(self.fixture, scene_id)[1]["segments"])
        self.assertEqual(len(scene_segments), 2)
        # Segment labels ignore legacy/custom titles and use current order; a dirty scene must save before deletion.
        target_segment_id = scene_segments[1]["id"]
        self.evaluate(script_page, f"document.querySelector('[data-scope=segment][data-node-id=\\\"{target_segment_id}\\\"]').click()")
        self.wait(script_page, "document.getElementById('smScopeTitle').textContent==='第2段'")
        segment_menu_selector = f'[data-outline-menu-toggle][data-outline-scope="segment"][data-outline-node-id="{target_segment_id}"]'
        self.evaluate(script_page, f"document.querySelector({json.dumps(segment_menu_selector)}).click()")
        segment_delete_selector = f'[data-outline-menu-action="delete"][data-outline-scope="segment"][data-outline-node-id="{target_segment_id}"]'
        self.wait(script_page, f"document.querySelector({json.dumps(segment_delete_selector)})")
        self.assertFalse(self.evaluate(script_page, "!!document.querySelector('[data-outline-menu-action=rename][data-outline-scope=segment]')"))
        self.assertFalse(self.evaluate(script_page, "!!document.querySelector('[data-outline-menu-action=segment-child]')"))
        self.evaluate(script_page, f"document.querySelector({json.dumps(segment_delete_selector)}).click()")
        self.wait(script_page, "!document.getElementById('smOutlineDialog').hidden")
        self.wait(script_page, "document.activeElement.id==='smOutlineDialogSubmit'")
        self.assertEqual(self.evaluate(script_page, "document.getElementById('smScopeTitle').textContent"), "第2段")
        delete_dialog = self.evaluate(script_page, "({title:document.getElementById('smOutlineDialogTitle').textContent,message:document.getElementById('smOutlineDialogMessage').textContent,inputHidden:document.getElementById('smOutlineDialogInput').hidden,focusedConfirm:document.activeElement.id==='smOutlineDialogSubmit'})")
        self.assertIn("1段", delete_dialog["message"])
        self.assertIn("历史记录保留", delete_dialog["message"])
        self.assertIn("已导入画布的内容不会删除", delete_dialog["message"])
        self.assertTrue(delete_dialog["inputHidden"] and delete_dialog["focusedConfirm"], delete_dialog)
        self.screenshot(script_page, "final-delete-script-segment-confirm.png")
        with self.fixture["lock"]: command_count_before_cancel = len(self.fixture["command_attempts"])
        self.evaluate(script_page, "document.querySelector('[data-outline-dialog-cancel]').click()")
        self.wait(script_page, "document.getElementById('smOutlineDialog').hidden")
        with self.fixture["lock"]: self.assertEqual(len(self.fixture["command_attempts"]), command_count_before_cancel)
        self.evaluate(script_page, f"document.querySelector('[data-scope=scene][data-node-id=\\\"{scene_id}\\\"]').click()")
        self.wait(script_page, f"document.querySelector('.sm-inline-input[data-inline-key=\\\"script-scene:{scene_id}\\\"]')")
        draft_before_delete = "## 雨夜内景\n\n门外有人停下。\n\n---\n\n门内的灯忽然熄灭。\n\n删除前保留的草稿。"
        with self.fixture["lock"]: self.fixture["fail_next_command"] = True
        self.set_inline_text(script_page, "script-scene:" + scene_id, draft_before_delete)
        self.wait(script_page, "document.querySelector('[data-inline-retry]') && document.querySelector('.sm-inline-error')?.textContent.includes('fixture save failure')", 6)
        self.assertEqual(self.evaluate(script_page, f"document.querySelector('.sm-inline-input[data-inline-key=\\\"script-scene:{scene_id}\\\"]')?.value"), draft_before_delete)
        self.assertTrue(self.evaluate(script_page, "document.getElementById('smOutlineDialog').hidden"))
        # A later delete request first saves the preserved draft; only then may it ask for destructive confirmation.
        self.evaluate(script_page, f"document.querySelector({json.dumps(segment_menu_selector)}).click();document.querySelector({json.dumps(segment_delete_selector)}).click()")
        self.wait(script_page, "document.getElementById('smStatus').textContent.includes('已不存在') && document.getElementById('smRevisionLabel').textContent==='已保存'", 8)
        self.assertTrue(self.evaluate(script_page, "document.getElementById('smOutlineDialog').hidden"))
        self.assertIn("重新读取目录", self.evaluate(script_page, "document.getElementById('smStatus').textContent"))
        with self.fixture["lock"]:
            self.assertEqual(script_scene(self.fixture, scene_id)[1]["editable_markdown"], draft_before_delete)
            saved_segments_before_delete = safe_copy(script_scene(self.fixture, scene_id)[1]["segments"])
            self.assertEqual(self.fixture["command_attempts"][-1]["payload"]["action"], "batch")
            self.assertFalse(any(record["payload"]["action"] == "delete_item" and record["payload"]["args"].get("item_id") == target_segment_id
                                 for record in self.fixture["command_attempts"]))
        old_target_segment_id = target_segment_id
        target_segment_id = saved_segments_before_delete[1]["id"]
        self.assertNotEqual(target_segment_id, old_target_segment_id)
        segment_menu_selector = f'[data-outline-menu-toggle][data-outline-scope="segment"][data-outline-node-id="{target_segment_id}"]'
        segment_delete_selector = f'[data-outline-menu-action="delete"][data-outline-scope="segment"][data-outline-node-id="{target_segment_id}"]'
        open_outline_action(script_page, "segment", target_segment_id, "delete")
        self.assertIn("共 1段", self.evaluate(script_page, "document.getElementById('smOutlineDialogMessage').textContent"))
        with self.fixture["lock"]: command_count_before_cancel = len(self.fixture["command_attempts"])
        self.evaluate(script_page, "document.querySelector('[data-outline-dialog-cancel]').click()")
        self.wait(script_page, "document.getElementById('smOutlineDialog').hidden")
        with self.fixture["lock"]: self.assertEqual(len(self.fixture["command_attempts"]), command_count_before_cancel)
        self.evaluate(script_page, f"document.querySelector({json.dumps(segment_menu_selector)}).click();document.querySelector({json.dumps(segment_delete_selector)}).click()")
        self.wait(script_page, "!document.getElementById('smOutlineDialog').hidden")
        with self.fixture["lock"]: self.fixture["unknown_next_command_response"] = True
        self.evaluate(script_page, "document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(script_page, "document.getElementById('smOutlineDialogError').textContent.includes('无法确认')")
        with self.fixture["lock"]:
            delete_payload = self.fixture["command_attempts"][-1]["payload"]
            delete_receipt = self.fixture["receipts"][delete_payload["request_id"]]
            delete_attempts = len(self.fixture["command_attempts"])
        self.assertEqual(delete_payload["action"], "delete_item")
        self.assertEqual(delete_payload["args"], {"item_type": "segment", "item_id": target_segment_id, "include_descendants": False})
        self.evaluate(script_page, "document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(script_page, "document.getElementById('smOutlineDialog').hidden && document.querySelector('[data-scope=scene][aria-current=page]')")
        with self.fixture["lock"]:
            self.assertEqual(len(self.fixture["command_attempts"]), delete_attempts)
            self.assertEqual(self.fixture["command_attempts"][-1]["payload"]["request_id"], delete_payload["request_id"])
            self.assertEqual(delete_receipt["changed_ids"], [scene_id, target_segment_id])
            archived_segment = self.fixture["script"]["archive"][-1]
            self.assertEqual(archived_segment["kind"], "segment")
            self.assertEqual(archived_segment["item"]["title"], scene_segments[1]["title"])
            self.assertEqual(archived_segment["deleted_body"], "门内的灯忽然熄灭。\n\n删除前保留的草稿。")
            remaining_segment_ids = [item["id"] for item in script_scene(self.fixture, scene_id)[1]["segments"]]
        self.assertEqual(remaining_segment_ids, [saved_segments_before_delete[0]["id"]])
        self.assertEqual(self.evaluate(script_page, f"document.querySelector('[data-scope=segment][data-node-id=\\\"{remaining_segment_ids[0]}\\\"] span')?.textContent"), "第1段")
        self.assertEqual(self.evaluate(script_page, "document.querySelector('[data-scope=scene][aria-current=page]').dataset.nodeId"), scene_id)
        expected_scene_body = script_scene(self.fixture, scene_id)[1]["editable_markdown"]
        self.assertEqual(self.evaluate(script_page, f"document.querySelector('.sm-inline-input[data-inline-key=\\\"script-scene:{scene_id}\\\"]')?.value"), expected_scene_body)
        self.assertNotIn("门内的灯忽然熄灭", expected_scene_body)

        # 根范围以每个场次稳定 ID 分桶；两个场次在同一 batch 保存，IME 中不提交任何桶。
        self.evaluate(script_page, "document.querySelector('[data-scope=root]').click()")
        self.wait(script_page, "document.querySelector('[data-scope=root][aria-current=page]')")
        self.assertTrue(self.evaluate(script_page, "document.getElementById('smCopyFeedback').hidden"))
        self.wait(script_page, "document.querySelectorAll('.sm-inline-input').length===2")
        self.assertTrue(self.evaluate(script_page, "document.getElementById('smEditButton').hidden && document.getElementById('smBreadcrumb').hidden"))
        self.screenshot(script_page, "final-inline-script-default-editor-tree.png")
        before_batch = len(self.fixture["command_attempts"])
        self.set_inline_text(script_page, "script-scene:scene-1", "## 第一场\n\n根目录保存的第一场。")
        self.evaluate(script_page, "window.__studioManuscript.fireInlineComposition('script-scene:" + scene_id + "','compositionstart')")
        edited_scene = "## 雨夜门外\n\n门外有人停下。\n\n---\n\n门内的灯第三次熄灭。"
        self.set_inline_text(script_page, "script-scene:" + scene_id, edited_scene, composing=True)
        time.sleep(1.0)
        self.assertEqual(len(self.fixture["command_attempts"]), before_batch)
        self.evaluate(script_page, "window.__studioManuscript.fireInlineComposition('script-scene:" + scene_id + "','compositionend')")
        self.wait(script_page, "document.querySelectorAll('.sm-inline-input').length===2 && document.getElementById('smRevisionLabel').textContent==='已保存'", 7)
        with self.fixture["lock"]:
            batch_payload = next(record["payload"] for record in reversed(self.fixture["command_attempts"]) if record["payload"]["action"] == "batch")
            scene_one = script_scene(self.fixture, "scene-1")[1]
            scene_two = script_scene(self.fixture, scene_id)[1]
        self.assertEqual(batch_payload["expected_revision"] + 1, self.fixture["script"]["revision"])
        self.assertEqual({item["args"]["scene_id"] for item in batch_payload["args"]["operations"]}, {"scene-1", scene_id})
        self.assertEqual(scene_one["body_markdown"], "## 第一场\n\n根目录保存的第一场。")
        self.assertEqual(scene_two["editable_markdown"], edited_scene)
        self.assertNotIn("---", scene_two["body_markdown"])

        # Deleting a scene selects its actual parent episode, even when it is not the first episode.
        open_outline_action(script_page, "scene", scene_id, "delete")
        scene_delete_message = self.evaluate(script_page, "document.getElementById('smOutlineDialogMessage').textContent")
        self.assertIn("1场、2段", scene_delete_message)
        self.assertIn("正文将从当前作品移除", scene_delete_message)
        self.screenshot(script_page, "final-delete-script-scene-confirm.png")
        self.evaluate(script_page, "document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(script_page, "document.querySelector('[data-scope=episode][aria-current=page]')?.dataset.nodeId==='" + episode_id + "'")
        with self.fixture["lock"]:
            self.assertIsNone(script_scene(self.fixture, scene_id)[1])
            self.assertEqual(self.fixture["script"]["revision"], next(item["revision"] for item in self.fixture["projects"] if item["id"] == "script-fixture"))
            self.assertTrue(any(item["kind"] == "scene" and item["item"]["id"] == scene_id for item in self.fixture["script"]["archive"]))
        self.assertEqual(self.evaluate(script_page, "document.querySelector('[data-scope=episode][aria-current=page]').dataset.nodeId"), episode_id)

        # Recreate one scene, then cascade-delete its non-first episode with exact descendant counts.
        open_outline_action(script_page, "episode", episode_id, "scene-child")
        self.evaluate(script_page, "document.getElementById('smOutlineDialogInput').value='待移除场次';document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(script_page, "document.querySelector('[data-scope=scene][aria-current=page]')?.textContent.includes('待移除场次')")
        cascade_scene_id = self.evaluate(script_page, "document.querySelector('[data-scope=scene][aria-current=page]').dataset.nodeId")
        open_outline_action(script_page, "episode", episode_id, "delete")
        episode_delete_message = self.evaluate(script_page, "document.getElementById('smOutlineDialogMessage').textContent")
        self.assertIn("1集、1场、1段", episode_delete_message)
        self.assertIn("及其下级", episode_delete_message)
        self.screenshot(script_page, "final-delete-script-episode-confirm.png")
        with self.fixture["lock"]: self.fixture["unknown_next_command_response"] = True
        self.evaluate(script_page, "document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(script_page, "document.getElementById('smOutlineDialogError').textContent.includes('无法确认')")
        with self.fixture["lock"]:
            episode_delete_payload = self.fixture["command_attempts"][-1]["payload"]
            episode_delete_attempts = len(self.fixture["command_attempts"])
        self.assertEqual(episode_delete_payload["action"], "delete_item")
        self.assertEqual(episode_delete_payload["args"], {"item_type": "episode", "item_id": episode_id, "include_descendants": True})
        self.evaluate(script_page, "document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(script_page, "document.getElementById('smOutlineDialog').hidden && document.querySelector('[data-scope=root][aria-current=page]')")
        with self.fixture["lock"]:
            self.assertEqual(len(self.fixture["command_attempts"]), episode_delete_attempts)
            self.assertEqual(self.fixture["command_attempts"][-1]["payload"]["request_id"], episode_delete_payload["request_id"])
            self.assertIsNone(script_episode(self.fixture, episode_id))
            archived_episode = next(item for item in reversed(self.fixture["script"]["archive"]) if item["kind"] == "episode")
            self.assertEqual(archived_episode["item"]["scenes"][0]["id"], cascade_scene_id)
        self.assertEqual(self.evaluate(script_page, "document.querySelector('[data-scope=root][aria-current=page]').dataset.nodeId"), "")

        novel_page = self.new_page(origin + "/static/novel.html?id=novel-fixture")
        self.wait(novel_page, "document.getElementById('smProjectName').textContent==='隔离小说作品'")
        root_novel = self.evaluate(novel_page, "[...document.querySelectorAll('.sm-inline-input')].map(x=>x.value).join('\\n')")
        self.assertIn("第一章", root_novel)
        self.assertTrue(self.evaluate(novel_page, "document.getElementById('smEditButton').hidden"))
        self.evaluate(novel_page, "document.querySelector('[data-scope=\"volume\"]').click()")
        self.wait(novel_page, "document.querySelector('[data-scope=\"volume\"][aria-current=\"page\"]') && document.querySelector('.sm-inline-input')?.value.includes('普通正文')")
        self.evaluate(novel_page, "document.querySelector('[data-scope=\"chapter\"]').click()")
        self.wait(novel_page, "document.querySelector('[data-scope=\"chapter\"][aria-current=\"page\"]') && document.getElementById('smEditButton').hidden && document.querySelector('.sm-inline-input')?.value.includes('普通正文')")
        self.assertFalse(self.evaluate(novel_page, "document.getElementById('smContentHeading').hidden || !document.getElementById('smBreadcrumb').hidden"))
        self.assertTrue(self.evaluate(novel_page, "document.getElementById('smScopeTitle').textContent==='第一章' && !document.querySelector('#smReader h1,.sm-novel-section-heading')"))
        markdown_assertions = self.evaluate(novel_page, "(()=>{const r=document.getElementById('smReader'),text=r.querySelector('.sm-inline-input')?.value||'';return {fields:r.querySelectorAll('.sm-inline-input').length,scriptMarkup:text.includes('<script>window.__manuscriptXss = true</script>'),tableSource:text.includes('| 线索 | 表格仍可读 |'),unsafeLinkSource:text.includes('javascript:window.__manuscriptXss=true'),scripts:r.querySelectorAll('script').length,executed:!!window.__manuscriptXss}})()")
        self.assertEqual(markdown_assertions, {"fields": 1, "scriptMarkup": True, "tableSource": True, "unsafeLinkSource": True, "scripts": 0, "executed": False})
        self.screenshot(novel_page, "final-inline-novel-chapter-reader.png")

        # 设定库根页给出分类和条目索引；人物正文须由用户主动选中后才打开。
        self.evaluate(novel_page, "document.querySelector('[data-sm-tab=\"settings\"]').click()")
        self.wait(novel_page, "document.querySelector('[data-category-id=\"characters\"]') && document.querySelector('[data-setting-id=\"character-linqing\"]')")
        settings_root = self.evaluate(novel_page, "({title:document.getElementById('smScopeTitle').textContent,reader:document.getElementById('smReader').innerText,groups:document.querySelectorAll('.sm-settings-category-group').length,phaseButtons:[...document.querySelectorAll('button')].filter(b=>/新增.*版本|New.*version/.test(b.textContent)).length})")
        self.assertEqual(settings_root["title"], "设定库")
        self.assertNotIn("性格底色", settings_root["reader"])
        self.assertGreaterEqual(settings_root["groups"], 2)
        self.assertEqual(settings_root["phaseButtons"], 0)
        self.evaluate(novel_page, "document.querySelector('[data-setting-id=\"character-linqing\"]').click()")
        self.wait(novel_page, "document.getElementById('smReader').innerText.includes('性格底色')")
        self.assertIn("未指定", self.evaluate(novel_page, "document.getElementById('smVersionSelect').innerText"))
        self.assertEqual(self.evaluate(novel_page, "document.querySelectorAll('#smVersionSelect option').length"), 2)
        self.evaluate(novel_page, "document.getElementById('smVersionSelect').value='version-1';document.getElementById('smVersionSelect').dispatchEvent(new Event('change',{bubbles:true}))")
        self.wait(novel_page, "document.getElementById('smReader').innerText.includes('早期设定')")
        self.assertTrue(self.evaluate(novel_page, "document.getElementById('smEditButton').hidden"))
        self.evaluate(novel_page, "document.getElementById('smVersionSelect').value='version-2';document.getElementById('smVersionSelect').dispatchEvent(new Event('change',{bubbles:true}))")
        self.wait(novel_page, "document.getElementById('smReader').innerText.includes('性格底色')")
        self.begin_edit(novel_page)
        self.set_editor_text(novel_page, "# 林青\n\n性格底色：沉着，新增观察。")
        self.wait(novel_page, "document.getElementById('smReader').innerText.includes('新增观察')", 6)
        self.assertEqual(self.evaluate(novel_page, "document.querySelectorAll('#smVersionSelect option').length"), 2)
        self.assertFalse(self.evaluate(novel_page, "document.getElementById('smRevisionHistoryButton').hidden"))
        self.evaluate(novel_page, "document.getElementById('smRevisionHistoryButton').click()")
        self.wait(novel_page, "document.getElementById('smVersionLabel').textContent.includes('文字修订')")
        self.assertTrue(self.evaluate(novel_page, "document.getElementById('smEditButton').hidden"))
        history_options = self.evaluate(novel_page, "[...document.getElementById('smVersionSelect').options].map(option=>({value:option.value,label:option.textContent}))")
        self.assertEqual([item["value"] for item in history_options], ["3", "1", "2"])
        self.assertEqual(history_options[0]["label"], "当前修订 3")
        self.assertEqual(len({item["value"] for item in history_options}), len(history_options))
        self.evaluate(novel_page, "document.getElementById('smVersionSelect').value='2';document.getElementById('smVersionSelect').dispatchEvent(new Event('change',{bubbles:true}))")
        self.wait(novel_page, "document.getElementById('smReader').innerText.includes('故事阶段：起点')")
        option_state = self.evaluate(novel_page, "({value:document.getElementById('smVersionSelect').value,options:[...document.getElementById('smVersionSelect').options].map(o=>({value:o.value,label:o.textContent})),editHidden:document.getElementById('smEditButton').hidden})")
        self.assertEqual(option_state["value"], "2")
        self.assertEqual(option_state["options"][0], {"value": "3", "label": "当前修订 3"})
        self.assertEqual(option_state["options"][2], {"value": "2", "label": "文字修订 2"})
        self.assertTrue(option_state["editHidden"])
        self.evaluate(novel_page, "document.getElementById('smVersionSelect').value='1';document.getElementById('smVersionSelect').dispatchEvent(new Event('change',{bubbles:true}))")
        self.wait(novel_page, "document.getElementById('smReader').innerText.includes('性格底色：沉着。')")
        option_state = self.evaluate(novel_page, "({value:document.getElementById('smVersionSelect').value,options:[...document.getElementById('smVersionSelect').options].map(o=>({value:o.value,label:o.textContent})),editHidden:document.getElementById('smEditButton').hidden})")
        self.assertEqual(option_state["value"], "1")
        self.assertEqual(option_state["options"][0], {"value": "3", "label": "当前修订 3"})
        self.assertEqual(option_state["options"][1], {"value": "1", "label": "文字修订 1"})
        self.assertTrue(option_state["editHidden"])
        self.screenshot(novel_page, "final-inline-novel-settings-history.png")

        # 两个工作区切换后恢复原章节、搜索词和滚动位置。
        self.evaluate(novel_page, "document.querySelector('[data-sm-tab=\"text\"]').click()")
        self.wait(novel_page, "document.querySelector('[data-scope=\"chapter\"][aria-current=\"page\"]')")
        self.evaluate(novel_page, "document.getElementById('smMainContent').scrollTop=77;document.getElementById('smDirectorySearch').value='第一';document.getElementById('smDirectorySearch').dispatchEvent(new Event('input',{bubbles:true}))")
        self.evaluate(novel_page, "document.querySelector('[data-sm-tab=\"settings\"]').click()")
        self.wait(novel_page, "document.querySelector('[data-setting-id=\"character-linqing\"]')")
        self.evaluate(novel_page, "document.querySelector('[data-sm-tab=\"text\"]').click()")
        self.wait(novel_page, "document.querySelector('[data-scope=\"chapter\"][aria-current=\"page\"]')")
        restored = self.evaluate(novel_page, "({scope:document.querySelector('[data-scope][aria-current=\"page\"]')?.dataset.scope,search:document.getElementById('smDirectorySearch').value,scroll:document.getElementById('smMainContent').scrollTop})")
        self.assertEqual(restored["scope"], "chapter")
        self.assertEqual(restored["search"], "第一")
        self.assertGreaterEqual(restored["scroll"], 0)
        self.evaluate(novel_page, "(()=>{const t=document.getElementById('smTabText');t.focus();t.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}))})()")
        self.wait(novel_page, "document.getElementById('smTabSettings').getAttribute('aria-selected')==='true'")
        self.assertEqual(self.evaluate(novel_page, "({focus:document.activeElement.id,label:document.getElementById('smMainContent').getAttribute('aria-labelledby')})"), {"focus": "smTabSettings", "label": "smTabSettings"})
        self.evaluate(novel_page, "document.getElementById('smTabSettings').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}))")
        self.wait(novel_page, "document.getElementById('smTabText').getAttribute('aria-selected')==='true'")

        # 明暗主题保留配色身份；中英文标签切换；作品页工具栏仅保留三个共用图标。
        original_theme = self.evaluate(novel_page, "document.documentElement.dataset.studioTheme")
        original_appearance = self.evaluate(novel_page, "document.documentElement.dataset.studioAppearance")
        color_samples = self.evaluate(novel_page, "(async()=>{const root=document.documentElement,themeApi=window.StudioTheme,previous=themeApi.getPreference(),ids=['studio-violet','sunlit','vermilion','forest','classic'],out=[];for(const theme of ids)for(const appearance of ['light','dark']){themeApi.setPreference({version:1,themeId:theme,appearance});await new Promise(resolve=>setTimeout(resolve,180));const selected=document.querySelector('#smDirectory [aria-current=\"page\"]'),input=document.querySelector('.sm-inline-input'),tab=document.querySelector('.sm-tab.active'),style=n=>getComputedStyle(n);out.push({theme,appearance,rootAccentText:style(root).getPropertyValue('--studio-accent-text').trim(),bodyAccentText:style(document.body).getPropertyValue('--studio-accent-text').trim(),selectedText:style(selected).color,selectedWash:style(selected).backgroundColor,surface:style(document.querySelector('.sm-directory')).backgroundColor,inputText:style(input).color,inputSurface:style(input).backgroundColor,page:style(document.getElementById('smWorkspace')).backgroundColor,tabText:style(tab).color,tabPage:style(document.getElementById('smNovelTabs')).backgroundColor,focus:style(root).getPropertyValue('--studio-focus').trim()})}themeApi.setPreference(previous);return out})()")
        self.assertEqual(len(color_samples), 10)
        for sample in color_samples:
            selected_bg = composite(sample["selectedWash"], sample["surface"])
            input_bg = composite(sample["inputSurface"], sample["page"])
            for label, foreground, background in (("selected", sample["selectedText"], selected_bg), ("input", sample["inputText"], input_bg), ("tab", sample["tabText"], sample["tabPage"])):
                self.assertGreaterEqual(contrast_ratio(foreground, background), 4.5, f"{sample['theme']} {sample['appearance']} {label}: {foreground} / {background}; root={sample['rootAccentText']} body={sample['bodyAccentText']}")
            self.assertGreaterEqual(contrast_ratio(sample["focus"], sample["surface"]), 3.0, f"{sample['theme']} {sample['appearance']} focus")
        self.evaluate(novel_page, "document.getElementById('smThemeButton').click()")
        dark_state = self.evaluate(novel_page, "({theme:document.documentElement.dataset.studioTheme,appearance:document.documentElement.dataset.studioAppearance})")
        self.assertEqual(dark_state["theme"], original_theme)
        self.assertNotEqual(dark_state["appearance"], original_appearance)
        if dark_state["appearance"] != "dark":
            self.evaluate(novel_page, "document.getElementById('smThemeButton').click()")
        self.assertEqual(self.evaluate(novel_page, "document.documentElement.dataset.studioAppearance"), "dark")
        header_controls = self.evaluate(novel_page, "[...document.querySelector('.sm-toolbar-actions').querySelectorAll('button')].map(button=>button.id)")
        self.assertEqual(header_controls, ["smRefreshButton", "smLanguageButton", "smThemeButton"])
        self.assertEqual(self.evaluate(novel_page, "!!document.querySelector('#smBackButton,#smPrepareButton,#smConnectButton,#smInstructionsDialog')"), False)
        self.screenshot(novel_page, "final-inline-novel-dark-reader.png")
        self.evaluate(novel_page, "document.getElementById('smLanguageButton').click()")
        self.assertEqual(self.evaluate(novel_page, "document.documentElement.lang"), "en")
        self.evaluate(novel_page, "document.getElementById('smLanguageButton').click()")

        # Drawer remains reachable at 390px; Escape closes it and restores focus.
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True}, novel_page["session"])
        narrow = self.evaluate(novel_page, "({display:getComputedStyle(document.getElementById('smDirectoryToggle')).display,width:document.getElementById('smDirectoryToggle').getBoundingClientRect().width,scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth})")
        self.assertNotEqual(narrow["display"], "none")
        self.assertGreaterEqual(narrow["width"], 30)
        self.evaluate(novel_page, "document.getElementById('smDirectoryToggle').click()")
        self.assertTrue(self.evaluate(novel_page, "document.getElementById('smWorkspace').classList.contains('sm-drawer-open')"))
        self.press_escape(novel_page)
        self.wait(novel_page, "!document.getElementById('smWorkspace').classList.contains('sm-drawer-open')")
        self.assertEqual(self.evaluate(novel_page, "document.activeElement.id"), "smDirectoryToggle")
        self.screenshot(novel_page, "final-inline-novel-mobile-drawer-closed.png")
        self.cdp("Emulation.clearDeviceMetricsOverride", session_id=novel_page["session"])

        # 第二个标签保存后，第一个标签 clean 时自动刷新；dirty 草稿不被覆盖并收到 409。
        tab_a = self.new_page(origin + "/static/novel.html?id=novel-fixture")
        tab_b = self.new_page(origin + "/static/novel.html?id=novel-fixture")
        for page in (tab_a, tab_b):
            self.wait(page, "document.querySelector('.sm-inline-input')?.value.includes('普通正文')")
            self.evaluate(page, "document.querySelector('[data-scope=\"chapter\"]').click()")
            self.wait(page, "document.querySelector('[data-scope=\"chapter\"][aria-current=\"page\"]') && document.querySelector('.sm-inline-input')")
        self.begin_edit(tab_b)
        self.set_editor_text(tab_b, "# 第一章\n\n来自第二标签的更新。")
        self.wait(tab_b, "document.getElementById('smRevisionLabel').textContent==='已保存' && document.querySelector('.sm-inline-input')?.value.includes('来自第二标签的更新')", 6)
        self.cdp("Page.bringToFront", session_id=tab_a["session"])
        self.wait(tab_a, "document.querySelector('.sm-inline-input')?.value.includes('来自第二标签的更新')", 8)
        self.begin_edit(tab_a)
        self.evaluate(tab_a, "window.__studioManuscript.fireInlineComposition('novel-chapter:chapter-1','compositionstart')")
        self.set_editor_text(tab_a, "# 第一章\n\n保留的本地草稿。", composing=True)
        self.set_editor_text(tab_b, "# 第一章\n\n来自第二标签的第二次更新。")
        self.wait(tab_b, "document.getElementById('smRevisionLabel').textContent==='已保存' && document.querySelector('.sm-inline-input')?.value.includes('第二次更新')", 6)
        self.cdp("Page.bringToFront", session_id=tab_a["session"])
        self.evaluate(tab_a, "window.__studioManuscript.fireInlineComposition('novel-chapter:chapter-1','compositionend')")
        self.wait(tab_a, "document.querySelector('[data-inline-confirm]') && document.querySelector('.sm-inline-remote')?.textContent.includes('来自第二标签的第二次更新')", 6)
        self.assertIn("保留的本地草稿", self.evaluate(tab_a, "document.querySelector('.sm-inline-input').value"))
        self.evaluate(tab_a, "document.querySelector('[data-inline-copy]').click()")
        self.assertIn("保留的本地草稿", self.evaluate(tab_a, "window.__studioManuscriptClipboard"))
        self.evaluate(tab_a, "document.querySelector('[data-inline-confirm]').click()")
        self.wait(tab_a, "document.getElementById('smRevisionLabel').textContent==='已保存' && document.querySelector('.sm-inline-input').value.includes('保留的本地草稿')", 8)

        # 普通写入失败不会自动循环；用户可以显式重试且草稿保留。
        tab_fail = self.new_page(origin + "/static/novel.html?id=novel-fixture")
        self.wait(tab_fail, "document.querySelector('.sm-inline-input')?.value.includes('保留的本地草稿')")
        self.evaluate(tab_fail, "document.querySelector('[data-scope=\"chapter\"]').click()")
        self.wait(tab_fail, "document.querySelector('[data-scope=\"chapter\"][aria-current=\"page\"]') && document.querySelector('.sm-inline-input')")
        with self.fixture["lock"]: self.fixture["fail_next_command"] = True
        self.begin_edit(tab_fail)
        self.set_editor_text(tab_fail, "# 第一章\n\n等待显式重试。")
        self.wait(tab_fail, "document.querySelector('[data-inline-retry]') && document.querySelector('.sm-inline-error')", 6)
        attempts_after_failure = len(self.fixture["command_attempts"])
        time.sleep(1.8)
        self.assertEqual(len(self.fixture["command_attempts"]), attempts_after_failure)
        self.assertIn("等待显式重试", self.evaluate(tab_fail, "document.querySelector('.sm-inline-input').value"))
        self.evaluate(tab_fail, "document.querySelector('[data-inline-retry]').click()")
        self.wait(tab_fail, "document.getElementById('smRevisionLabel').textContent==='已保存' && document.querySelector('.sm-inline-input').value.includes('等待显式重试')", 6)

        # 服务端已提交但客户端响应丢失，空的 200 回执不能让草稿标记为已保存；重试沿用原 request_id。
        with self.fixture["lock"]: self.fixture["drop_next_command_response"] = True
        self.set_editor_text(tab_fail, "# 第一章\n\n提交已接受但回执待核实。")
        self.wait(tab_fail, "document.querySelector('[data-inline-retry]') && document.querySelector('.sm-inline-error').textContent.includes('保存结果暂时无法确认')", 6)
        self.assertIn("提交已接受但回执待核实", self.evaluate(tab_fail, "document.querySelector('.sm-inline-input').value"))
        attempts_before_receipt_retry = len(self.fixture["command_attempts"])
        request_id = self.fixture["command_attempts"][-1]["payload"]["request_id"]
        self.assertEqual(self.evaluate(tab_fail, "document.getElementById('smRevisionLabel').textContent"), "未保存")
        self.evaluate(tab_fail, "document.querySelector('[data-inline-retry]').click()")
        self.wait(tab_fail, "document.getElementById('smRevisionLabel').textContent==='已保存' && document.querySelector('.sm-inline-input').value.includes('提交已接受但回执待核实')", 6)
        self.assertEqual(len(self.fixture["command_attempts"]), attempts_before_receipt_retry)
        self.assertEqual(self.fixture["command_attempts"][-1]["payload"]["request_id"], request_id)

        # 聚焦但未编辑的字段遇到远端更新时先冻结旧值，读取最新正文后再允许续写。
        tab_clean = self.new_page(origin + "/static/novel.html?id=novel-fixture")
        tab_writer = self.new_page(origin + "/static/novel.html?id=novel-fixture")
        for page in (tab_clean, tab_writer):
            self.wait(page, "document.querySelector('.sm-inline-input')?.value.includes('提交已接受但回执待核实')")
            self.evaluate(page, "document.querySelector('[data-scope=\"chapter\"]').click()")
            self.wait(page, "document.querySelector('[data-scope=\"chapter\"][aria-current=\"page\"]') && document.querySelector('.sm-inline-input')")
        self.evaluate(tab_clean, "document.querySelector('.sm-inline-input').focus();document.querySelector('.sm-inline-input').setSelectionRange(6,6)")
        remote_body = "# 第一章\n\n另一标签保存的新正文。"
        self.set_inline_text(tab_writer, "novel-chapter:chapter-1", remote_body)
        self.wait(tab_writer, "document.getElementById('smRevisionLabel').textContent==='已保存'", 6)
        remote_revision = self.fixture["novel"]["revision"]
        self.cdp("Page.bringToFront", session_id=tab_clean["session"])
        self.wait(tab_clean, "document.querySelector('[data-inline-reload]') && document.querySelector('.sm-inline-remote')?.textContent.includes('另一标签保存的新正文')", 8)
        stale_value = self.evaluate(tab_clean, "document.querySelector('.sm-inline-input').value")
        self.assertIn("提交已接受但回执待核实", stale_value)
        self.assertNotIn("另一标签保存的新正文", stale_value)
        self.evaluate(tab_clean, "document.querySelector('[data-inline-reload]').click()")
        self.assertEqual(self.evaluate(tab_clean, "document.querySelector('.sm-inline-input').value"), remote_body)
        followup = remote_body + "\n\n聚焦更新后的补写。"
        self.set_inline_text(tab_clean, "novel-chapter:chapter-1", followup)
        self.wait(tab_clean, "document.getElementById('smRevisionLabel').textContent==='已保存'", 6)
        with self.fixture["lock"]:
            followup_payload = self.fixture["command_attempts"][-1]["payload"]
        self.assertEqual(followup_payload["expected_revision"], remote_revision)
        self.assertEqual(followup_payload["args"]["operations"][0]["args"]["body_markdown"], followup)

        novel_outline_page = self.new_page(origin + "/static/novel.html?id=novel-fixture")
        self.wait(novel_outline_page, "document.getElementById('smProjectName').textContent==='隔离小说作品'")
        self.evaluate(novel_outline_page, "document.getElementById('smOutlineRootAdd').click()")
        self.wait(novel_outline_page, "!document.getElementById('smOutlineDialog').hidden")
        with self.fixture["lock"]: self.fixture["unknown_next_command_response"] = True
        # Force an accepted command with a 503 response followed by a missing receipt lookup.
        self.evaluate(novel_outline_page, "document.getElementById('smOutlineDialogInput').value='第二卷';document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(novel_outline_page, "document.getElementById('smOutlineDialogError').textContent.includes('无法确认')")
        unknown_dialog = self.evaluate(novel_outline_page, "({value:document.getElementById('smOutlineDialogInput').value,inputDisabled:document.getElementById('smOutlineDialogInput').disabled,closeDisabled:document.querySelector('[data-outline-dialog-close]').disabled})")
        self.assertEqual(unknown_dialog, {"value": "第二卷", "inputDisabled": True, "closeDisabled": True})
        with self.fixture["lock"]:
            volume_attempt = self.fixture["command_attempts"][-1]["payload"]
            volume_receipt = self.fixture["receipts"][volume_attempt["request_id"]]
            volume_id = volume_receipt["created_ids"][volume_attempt["args"]["client_ref"]]
            volume_attempt_count = len(self.fixture["command_attempts"])
        self.assertEqual(volume_attempt["action"], "create_volume")
        self.assertEqual(volume_attempt["args"]["title"], "第二卷")
        self.evaluate(novel_outline_page, "document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(novel_outline_page, "document.querySelector('[data-scope=volume][aria-current=page]')?.textContent.includes('第二卷')")
        with self.fixture["lock"]:
            self.assertEqual(len(self.fixture["command_attempts"]), volume_attempt_count)
            self.assertEqual(self.fixture["command_attempts"][-1]["payload"]["request_id"], volume_attempt["request_id"])
            self.assertEqual(len(novel_volumes(self.fixture)), 2)
        self.assertEqual(self.evaluate(novel_outline_page, "document.querySelector('[data-scope=volume][aria-current=page]').dataset.nodeId"), volume_id)

        open_outline_action(novel_outline_page, "volume", volume_id, "rename")
        self.evaluate(novel_outline_page, "document.getElementById('smOutlineDialogInput').value='第二卷：开篇';document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(novel_outline_page, "document.querySelector('[data-scope=volume][aria-current=page]')?.textContent.includes('第二卷：开篇')")
        open_outline_action(novel_outline_page, "volume", volume_id, "chapter-child")
        self.evaluate(novel_outline_page, "document.getElementById('smOutlineDialogInput').value='第一章';document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(novel_outline_page, "document.querySelector('[data-scope=chapter][aria-current=page]')?.textContent.includes('第一章')")
        with self.fixture["lock"]:
            chapter_attempt = self.fixture["command_attempts"][-1]["payload"]
            chapter_receipt = self.fixture["receipts"][chapter_attempt["request_id"]]
            chapter_id = chapter_receipt["created_ids"][chapter_attempt["args"]["client_ref"]]
        self.assertEqual(chapter_attempt["action"], "create_chapter")
        self.assertEqual(chapter_attempt["args"]["volume_id"], volume_id)
        self.assertEqual(chapter_attempt["args"]["body_markdown"], "")
        self.assertEqual(self.evaluate(novel_outline_page, "document.querySelector('[data-scope=chapter][aria-current=page]').dataset.nodeId"), chapter_id)
        open_outline_action(novel_outline_page, "chapter", chapter_id, "rename")
        self.evaluate(novel_outline_page, "document.getElementById('smOutlineDialogInput').value='正文样例章';document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(novel_outline_page, "document.querySelector('[data-scope=chapter][aria-current=page]')?.textContent.includes('正文样例章')")
        self.assertEqual(novel_chapter(self.fixture, chapter_id)[1]["title"], "正文样例章")
        self.begin_edit(novel_outline_page)
        sample_chapter_body = "章节正文样例 A。\n\n章节正文样例 B。"
        self.set_editor_text(novel_outline_page, sample_chapter_body)
        self.wait(novel_outline_page, "document.getElementById('smRevisionLabel').textContent==='已保存' && document.querySelector('.sm-inline-input')?.value.includes('章节正文样例 B')", 6)
        self.assertEqual(novel_chapter(self.fixture, chapter_id)[1]["body_markdown"], sample_chapter_body)
        self.assertEqual(novel_chapter(self.fixture, chapter_id)[1]["content_sha256"], hashlib.sha256(sample_chapter_body.encode("utf-8")).hexdigest())
        self.screenshot(novel_outline_page, "final-inline-novel-default-editor-tree.png")
        self.screenshot(novel_outline_page, "final-inline-novel-volume-chapter-outline.png")

        # A leaf chapter confirmation names the chapter but does not imply descendants.
        open_outline_action(novel_outline_page, "chapter", "chapter-1", "delete")
        chapter_delete_message = self.evaluate(novel_outline_page, "document.getElementById('smOutlineDialogMessage').textContent")
        self.assertIn("共 1章", chapter_delete_message)
        self.assertNotIn("及其下级", chapter_delete_message)
        command_count_before_cancel = len(self.fixture["command_attempts"])
        self.evaluate(novel_outline_page, "document.querySelector('[data-outline-dialog-cancel]').click()")
        self.wait(novel_outline_page, "document.getElementById('smOutlineDialog').hidden")
        self.assertEqual(len(self.fixture["command_attempts"]), command_count_before_cancel)
        open_outline_action(novel_outline_page, "chapter", "chapter-1", "delete")
        self.screenshot(novel_outline_page, "final-delete-novel-chapter-confirm.png")
        self.evaluate(novel_outline_page, "document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(novel_outline_page, "document.querySelector('[data-scope=volume][aria-current=page]')?.dataset.nodeId==='volume-1'")
        with self.fixture["lock"]:
            self.assertIsNone(novel_chapter(self.fixture, "chapter-1")[1])
            self.assertTrue(any(item["kind"] == "chapter" and item["item"]["id"] == "chapter-1" for item in self.fixture["novel"]["archive"]))

        # 新的就近菜单在窄屏仍落于目录可视宽度内，并支持 Escape 还焦点。
        self.evaluate(novel_outline_page, "document.getElementById('smLanguageButton').click()")
        self.wait(novel_outline_page, "document.documentElement.lang==='en'")
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True}, novel_outline_page["session"])
        self.evaluate(novel_outline_page, "document.getElementById('smDirectoryToggle').click()")
        self.wait(novel_outline_page, "document.getElementById('smWorkspace').classList.contains('sm-drawer-open') && getComputedStyle(document.getElementById('smDirectoryPanel')).visibility==='visible'")
        volume_menu_selector = f'[data-outline-menu-toggle][data-outline-scope="volume"][data-outline-node-id="{volume_id}"]'
        self.evaluate(novel_outline_page, f"document.querySelector({json.dumps(volume_menu_selector)}).click()")
        self.wait(novel_outline_page, "(()=>{const m=document.querySelector('.sm-outline-menu');return m&&!m.hidden&&getComputedStyle(m).display!=='none'&&m.getBoundingClientRect().width>0})()")
        self.wait(novel_outline_page, "document.activeElement.closest('.sm-outline-menu [role=menuitem]')")
        menu_bounds = self.evaluate(novel_outline_page, "(()=>{const m=document.querySelector('.sm-outline-menu').getBoundingClientRect(),t=document.getElementById('smDirectory').getBoundingClientRect(),d=document.getElementById('smDirectoryPanel').getBoundingClientRect();return {left:m.left,right:m.right,treeLeft:t.left,treeRight:t.right,drawerLeft:d.left,drawerRight:d.right,viewport:document.documentElement.clientWidth}})()")
        self.assertGreaterEqual(menu_bounds["left"], menu_bounds["treeLeft"] - 1)
        self.assertLessEqual(menu_bounds["right"], menu_bounds["treeRight"] + 1)
        self.assertGreaterEqual(menu_bounds["left"], menu_bounds["drawerLeft"] - 1)
        self.assertLessEqual(menu_bounds["right"], menu_bounds["drawerRight"] + 1)
        self.assertGreaterEqual(menu_bounds["left"], -1)
        self.assertLessEqual(menu_bounds["right"], menu_bounds["viewport"] + 1)
        self.screenshot(novel_outline_page, "final-inline-mobile-outline-context-menu-390px.png")
        self.wait(novel_outline_page, "document.activeElement.closest('.sm-outline-menu [role=menuitem]')")
        self.press_escape(novel_outline_page)
        self.wait(novel_outline_page, "!document.querySelector('.sm-outline-menu')")
        escape_focus = self.evaluate(novel_outline_page, "({tag:document.activeElement.tagName,id:document.activeElement.id,scope:document.activeElement.dataset.outlineScope||null,nodeId:document.activeElement.dataset.outlineNodeId||null,expanded:document.querySelector('[data-outline-menu-toggle][data-outline-scope=volume]')?.getAttribute('aria-expanded'),drawerOpen:document.getElementById('smWorkspace').classList.contains('sm-drawer-open')})")
        self.assertEqual(escape_focus["nodeId"], volume_id, escape_focus)
        self.assertTrue(escape_focus["drawerOpen"], escape_focus)
        open_outline_action(novel_outline_page, "volume", volume_id, "delete")
        volume_delete_message = self.evaluate(novel_outline_page, "document.getElementById('smOutlineDialogMessage').textContent")
        self.assertIn("1 volume, 1 chapter", volume_delete_message)
        self.assertIn("and its descendants", volume_delete_message)
        self.assertIn("archived history will remain", volume_delete_message)
        dialog_bounds = self.evaluate(novel_outline_page, "(()=>{const r=document.getElementById('smOutlineDialogForm').getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:document.documentElement.clientWidth,height:document.documentElement.clientHeight}})()")
        self.assertGreaterEqual(dialog_bounds["left"], 0, dialog_bounds)
        self.assertLessEqual(dialog_bounds["right"], dialog_bounds["width"], dialog_bounds)
        self.assertGreaterEqual(dialog_bounds["top"], 0, dialog_bounds)
        self.assertLessEqual(dialog_bounds["bottom"], dialog_bounds["height"], dialog_bounds)
        self.screenshot(novel_outline_page, "final-delete-novel-volume-confirm-390px-en.png")
        self.evaluate(novel_outline_page, "document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(novel_outline_page, "document.getElementById('smOutlineDialog').hidden && document.querySelector('[data-scope=root][aria-current=page]')")
        with self.fixture["lock"]:
            self.assertIsNone(novel_volume(self.fixture, volume_id))
            archived_volume = next(item for item in reversed(self.fixture["novel"]["archive"]) if item["kind"] == "volume")
            self.assertEqual([item["id"] for item in archived_volume["item"]["chapters"]], [chapter_id])
        self.assertEqual(self.evaluate(novel_outline_page, "document.querySelector('[data-scope=root][aria-current=page]').dataset.nodeId"), "")
        self.cdp("Emulation.clearDeviceMetricsOverride", session_id=novel_outline_page["session"])

        # 截取隔离项目中的普通示例正文：全三层树、单一场名和默认可编辑场正文。
        open_outline_action(script_page, "episode", "episode-1", "scene-child")
        self.evaluate(script_page, "document.getElementById('smOutlineDialogInput').value='正文样例场';document.getElementById('smOutlineDialogForm').requestSubmit()")
        self.wait(script_page, "document.querySelector('[data-scope=scene][aria-current=page]')?.textContent.includes('正文样例场')")
        with self.fixture["lock"]:
            sample_scene_payload = self.fixture["command_attempts"][-1]["payload"]
            sample_scene_id = self.fixture["receipts"][sample_scene_payload["request_id"]]["created_ids"][sample_scene_payload["args"]["client_ref"]]
        sample_scene_body = "场次正文样例 A。\n\n---\n\n场次正文样例 B。"
        self.set_inline_text(script_page, "script-scene:" + sample_scene_id, sample_scene_body)
        self.wait(script_page, "['已保存','Saved'].includes(document.getElementById('smRevisionLabel').textContent) && document.querySelector('.sm-inline-input')?.value.includes('场次正文样例 B')", 6)
        self.assertEqual(script_scene(self.fixture, sample_scene_id)[1]["editable_markdown"], sample_scene_body)
        self.evaluate(script_page, "window.__manuscriptReloadMarker='before-reload'")
        self.cdp("Page.reload", session_id=script_page["session"])
        self.wait(script_page, "document.readyState==='complete' && window.__manuscriptReloadMarker===undefined", 10)
        sample_scene_selector = f'[data-scope="scene"][data-node-id="{sample_scene_id}"]'
        self.wait(script_page, "document.getElementById('smProjectName').textContent==='隔离剧本作品' && document.querySelector(" + json.dumps(sample_scene_selector) + ")")
        self.evaluate(script_page, f"document.querySelector({json.dumps(sample_scene_selector)}).click()")
        self.wait(script_page, f"document.querySelector('.sm-inline-input[data-inline-key=\"script-scene:{sample_scene_id}\"]')?.value.includes('场次正文样例 B')")
        self.screenshot(script_page, "final-inline-script-default-editor-tree.png")

        browser_errors = self.evaluate(novel_page, "window.__studioManuscriptErrors")
        self.assertEqual(browser_errors, [], browser_errors)
        self.assertEqual(self.evaluate(script_page, "window.__studioManuscriptErrors"), [])
        self.assertEqual(self.evaluate(novel_outline_page, "window.__studioManuscriptErrors"), [])
