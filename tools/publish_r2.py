"""构建并发布画布程序更新；不收录用户配置、密钥、素材或运行环境。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import zipfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from static.release_update import allowed_file, validate_package
from tools.check_regression import module_boundary_errors


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "canvas-releases/"


def allowed(path):
    return allowed_file(path)


def build(root, output):
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError("版本号不能用于安全的发布路径")
    notes = json.loads((root / "static/update-notes.json").read_text(encoding="utf-8"))
    if notes.get("version") != version:
        raise ValueError("更新说明与 VERSION 不一致")
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    files = sorted(p for p in files if p and allowed(p))
    for required in ("main.py", "model_capabilities.py", "project_storage.py", "studio_modules.py",
                     "VERSION", "requirements.txt"):
        if required not in files:
            raise ValueError(f"发布缺少 {required}")
    errors = module_boundary_errors(root, packaged_files=set(files))
    if errors:
        raise ValueError('\n'.join(errors))
    output.mkdir(parents=True, exist_ok=True)
    package = output / "update.zip"
    records = []
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            data = (root / name).read_bytes()
            archive.writestr(name, data)
            records.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {
        "schema_version": 1, "version": version,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip(),
        "package": PREFIX + version + "/update.zip",
        "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "bytes": package.stat().st_size, "files": records, "update_notes": notes,
        "requires_restart": True,
    }
    validate_package(package.read_bytes(), manifest)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def publish(output, manifest):
    import boto3
    from botocore.exceptions import ClientError
    bucket = os.environ["R2_BUCKET"]
    base = os.environ["R2_PUBLIC_URL"].rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("R2_PUBLIC_URL 必须是 HTTPS 地址")
    client = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT"], region_name="auto")
    def read(key):
        try:
            return json.loads(client.get_object(Bucket=bucket, Key=key)["Body"].read())
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                return None
            raise
    latest_key = PREFIX + "latest.json"
    old = read(latest_key)
    if old and old["version"] == manifest["version"]:
        if old.get("commit") != manifest["commit"]:
            raise ValueError("相同版本号对应不同提交，请先更新 VERSION")
        print("该版本已经发布，无需重复上传")
        return
    existing = read(PREFIX + manifest["version"] + "/manifest.json")
    if existing and existing.get("commit") != manifest["commit"]:
        raise ValueError("该版本目录已存在另一提交，禁止覆盖")
    client.upload_file(str(output / "update.zip"), bucket, manifest["package"], ExtraArgs={"ContentType": "application/zip", "CacheControl": "public,max-age=31536000,immutable"})
    manifest.update({"url": base + "/" + manifest["package"], "published_at": int(time.time()), "previous_version": old["version"] if old else None})
    body = json.dumps(manifest, ensure_ascii=False).encode()
    client.put_object(Bucket=bucket, Key=PREFIX + manifest["version"] + "/manifest.json", Body=body, ContentType="application/json")
    # 最后发布入口，客户端不会发现尚未传完的更新包。
    client.put_object(Bucket=bucket, Key=latest_key, Body=body, ContentType="application/json", CacheControl="no-store")
    keep = {manifest["version"], manifest["previous_version"]}
    cutoff = time.time() - 7 * 86400
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=PREFIX):
        for item in page.get("Contents", []):
            parts = item["Key"].split("/")
            if len(parts) == 3 and parts[1] not in keep and parts[2] in {"update.zip", "manifest.json"} and item["LastModified"].timestamp() < cutoff:
                client.delete_object(Bucket=bucket, Key=item["Key"])
    print(f"已发布 {manifest['version']}，保留当前版、上一版和七天内的旧文件")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    output = ROOT / "cache" / "release"
    result = build(ROOT, output)
    print(f"更新包：{output / 'update.zip'}，{result['bytes']} 字节，{len(result['files'])} 个文件")
    if args.publish:
        publish(output, result)
