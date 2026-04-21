#!/usr/bin/env python3
"""
从 MongoDB 同步 knowledge_card_v2 到本地 presets/cases_index.yaml。

默认读取：
- host: test.guanzhao12.com
- port: 27018
- db: quanLiang
- collection: knowledge_card_v2

认证优先级：
1. --uri
2. 环境变量 GZQ_MONGO_URI / QUANLIANG_MONGO_URI
3. --user/--password（password 也可来自环境变量 GZQ_MONGO_PASSWORD / QUANLIANG_MONGO_PASSWORD）
4. 交互式输入密码

示例：
    python -X utf8 scripts/update_cases_index.py --dry-run
    python -X utf8 scripts/update_cases_index.py
"""

import argparse
import getpass
import os
import re
from pathlib import Path
from urllib.parse import quote_plus

try:
    from pymongo import MongoClient
except ImportError as exc:  # pragma: no cover - 运行时依赖检查
    raise SystemExit(
        "缺少依赖 pymongo。请先安装后再运行：pip install pymongo"
    ) from exc


DEFAULT_HOST = "test.guanzhao12.com"
DEFAULT_PORT = 27018
DEFAULT_DB = "quanLiang"
DEFAULT_COLLECTION = "knowledge_card_v2"
DEFAULT_USER = "admin"
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT = SKILL_ROOT / "presets" / "cases_index.yaml"
URI_ENV_NAMES = ("GZQ_MONGO_URI", "QUANLIANG_MONGO_URI")
PASSWORD_ENV_NAMES = ("GZQ_MONGO_PASSWORD", "QUANLIANG_MONGO_PASSWORD")
HEADER_TEMPLATE = """# 知识卡片目录 — cases_index.yaml（{count} 张，每张一行）
# AI 在 Step 1a 一次性读完此文件，按 tags 匹配卡片
# 找到后调 getCardFormulas(card_ids) 拉取完整公式（支持多张）
#
# 格式：id | name | tags（逗号分隔）
# tags 含范式关键词，卡片里的资产名只是示例可替换
# 示例：用户问\"铜相关个股\" → 匹配 tags 含\"产业链筛选,相关性分析\"的卡片 → 替换资产
"""


def parse_args():
    parser = argparse.ArgumentParser(description="从 MongoDB 更新 presets/cases_index.yaml")
    parser.add_argument("--uri", help="完整 MongoDB URI，优先级最高")
    parser.add_argument("--host", default=DEFAULT_HOST, help="MongoDB host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MongoDB port")
    parser.add_argument("--db", default=DEFAULT_DB, help="MongoDB database name")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="MongoDB collection name")
    parser.add_argument("--user", default=DEFAULT_USER, help="MongoDB username")
    parser.add_argument("--password", help="MongoDB password")
    parser.add_argument("--name-field", default="name", help="卡片名称字段名")
    parser.add_argument("--tags-field", default="user_intent_tags", help="标签字段名")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出文件路径")
    parser.add_argument("--limit", type=int, help="仅拉取前 N 条记录，便于调试")
    parser.add_argument("--timeout-ms", type=int, default=10000, help="MongoDB 连接超时（毫秒）")
    parser.add_argument("--dry-run", action="store_true", help="只检查并打印摘要，不写文件")
    return parser.parse_args()


def collapse_text(value, replace_comma=False):
    text = "" if value is None else str(value)
    text = text.replace("\r", "\n")
    text = text.replace("\n", " ")
    text = text.replace("|", "／")
    if replace_comma:
        text = text.replace(",", "，")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_tags(raw_tags):
    if raw_tags is None:
        return []

    if isinstance(raw_tags, str):
        candidates = re.split(r"[,，;/；\n]+", raw_tags)
    elif isinstance(raw_tags, (list, tuple, set)):
        candidates = list(raw_tags)
    else:
        candidates = [raw_tags]

    result = []
    seen = set()
    for item in candidates:
        if isinstance(item, (list, tuple, set)):
            nested = list(item)
        else:
            nested = [item]
        for tag in nested:
            normalized = collapse_text(tag, replace_comma=True)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
    return result


def load_mongo_uri(args):
    if args.uri:
        return args.uri

    for env_name in URI_ENV_NAMES:
        env_value = os.getenv(env_name)
        if env_value:
            return env_value

    password = args.password
    if not password:
        for env_name in PASSWORD_ENV_NAMES:
            env_value = os.getenv(env_name)
            if env_value:
                password = env_value
                break

    if not password:
        prompt = "MongoDB password for {user}@{host}:{port}: ".format(
            user=args.user,
            host=args.host,
            port=args.port,
        )
        password = getpass.getpass(prompt)

    if not password:
        raise SystemExit("未提供 MongoDB 密码，无法继续。")

    return "mongodb://{user}:{password}@{host}:{port}/{db}".format(
        user=quote_plus(args.user),
        password=quote_plus(password),
        host=args.host,
        port=args.port,
        db=args.db,
    )


def read_existing_index(path):
    if not path.exists():
        return {}

    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(" | ", 2)
        if len(parts) != 3:
            continue
        card_id, name, tags_str = parts
        tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()]
        entries[card_id] = {"name": name.strip(), "tags": tags}
    return entries


def fetch_cards(collection, name_field, tags_field, existing_entries=None, limit=None):
    projection = {"_id": 1, name_field: 1, tags_field: 1}
    cursor = collection.find({}, projection).sort("_id", 1)
    if limit:
        cursor = cursor.limit(limit)

    cards = []
    skipped_missing_name = []
    skipped_empty_tags = []
    fallback_to_existing_tags = []
    existing_entries = existing_entries or {}

    for doc in cursor:
        card_id = collapse_text(doc.get("_id"))
        name = collapse_text(doc.get(name_field))
        tags = normalize_tags(doc.get(tags_field))

        if not card_id or not name:
            skipped_missing_name.append(card_id or "<unknown>")
            continue

        if not tags:
            existing = existing_entries.get(card_id) or {}
            fallback_tags = list(existing.get("tags") or [])
            if fallback_tags:
                tags = fallback_tags
                fallback_to_existing_tags.append(card_id)

        if not tags:
            skipped_empty_tags.append(card_id)
            continue

        cards.append({"id": card_id, "name": name, "tags": tags})

    cards.sort(key=lambda item: item["id"])
    return cards, skipped_missing_name, skipped_empty_tags, fallback_to_existing_tags


def validate_cards(cards):
    if not cards:
        raise SystemExit("未获取到可写入的卡片，已停止，未覆盖现有文件。")

    seen = set()
    duplicates = []
    for card in cards:
        card_id = card["id"]
        if card_id in seen:
            duplicates.append(card_id)
        seen.add(card_id)
        if not card["name"]:
            raise SystemExit("存在空名称卡片：{0}".format(card_id))
        if not card["tags"]:
            raise SystemExit("存在空标签卡片：{0}".format(card_id))

    if duplicates:
        raise SystemExit("发现重复 card_id：{0}".format(", ".join(sorted(set(duplicates)))))


def build_output(cards):
    header = HEADER_TEMPLATE.format(count=len(cards)).rstrip()
    body = ["{id} | {name} | {tags}".format(
        id=card["id"],
        name=card["name"],
        tags=", ".join(card["tags"]),
    ) for card in cards]
    return header + "\n\n" + "\n".join(body) + "\n"


def validate_output(content, expected_count):
    count = 0
    for line in content.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split(" | ", 2)
        if len(parts) != 3:
            raise SystemExit("输出格式异常，无法解析行：{0}".format(line))
        count += 1
    if count != expected_count:
        raise SystemExit("输出行数校验失败：期望 {0}，实际 {1}".format(expected_count, count))


def summarize_diff(old_entries, new_cards):
    new_entries = {card["id"]: {"name": card["name"], "tags": card["tags"]} for card in new_cards}
    old_ids = set(old_entries)
    new_ids = set(new_entries)
    common_ids = old_ids & new_ids

    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    renamed = sorted(card_id for card_id in common_ids if old_entries[card_id]["name"] != new_entries[card_id]["name"])
    tags_changed = sorted(card_id for card_id in common_ids if old_entries[card_id]["tags"] != new_entries[card_id]["tags"])

    return {
        "old_count": len(old_entries),
        "new_count": len(new_entries),
        "added": added,
        "removed": removed,
        "renamed": renamed,
        "tags_changed": tags_changed,
    }


def print_summary(total_docs, cards, skipped_missing_name, skipped_empty_tags, fallback_to_existing_tags, diff, output_path, dry_run):
    print("MongoDB 文档总数: {0}".format(total_docs))
    print("可写入卡片数: {0}".format(len(cards)))
    print("跳过（空名称）: {0}".format(len(skipped_missing_name)))
    print("沿用旧标签: {0}".format(len(fallback_to_existing_tags)))
    print("跳过（空标签且无旧值）: {0}".format(len(skipped_empty_tags)))
    print("旧文件条数: {0}".format(diff["old_count"]))
    print("新文件条数: {0}".format(diff["new_count"]))
    print("新增卡片: {0}".format(len(diff["added"])))
    print("删除卡片: {0}".format(len(diff["removed"])))
    print("名称变化: {0}".format(len(diff["renamed"])))
    print("标签变化: {0}".format(len(diff["tags_changed"])))
    if fallback_to_existing_tags:
        print("沿用旧标签的 card_id（最多显示 10 条）: {0}".format(", ".join(fallback_to_existing_tags[:10])))
    if skipped_empty_tags:
        print("空标签已跳过（最多显示 10 条）: {0}".format(", ".join(skipped_empty_tags[:10])))
    if diff["added"]:
        print("新增 card_id（最多显示 10 条）: {0}".format(", ".join(diff["added"][:10])))
    if diff["removed"]:
        print("删除 card_id（最多显示 10 条）: {0}".format(", ".join(diff["removed"][:10])))
    if dry_run:
        print("DRY RUN：未写入文件 -> {0}".format(output_path))
    else:
        print("已写入文件 -> {0}".format(output_path))


def main():
    args = parse_args()
    output_path = Path(args.output).resolve()
    uri = load_mongo_uri(args)
    old_entries = read_existing_index(output_path)

    client = MongoClient(uri, serverSelectionTimeoutMS=args.timeout_ms)
    try:
        client.admin.command("ping")
        collection = client[args.db][args.collection]
        total_docs = collection.count_documents({})
        cards, skipped_missing_name, skipped_empty_tags, fallback_to_existing_tags = fetch_cards(
            collection=collection,
            name_field=args.name_field,
            tags_field=args.tags_field,
            existing_entries=old_entries,
            limit=args.limit,
        )
    finally:
        client.close()

    validate_cards(cards)

    content = build_output(cards)
    validate_output(content, len(cards))

    diff = summarize_diff(old_entries, cards)
    print_summary(
        total_docs=total_docs,
        cards=cards,
        skipped_missing_name=skipped_missing_name,
        skipped_empty_tags=skipped_empty_tags,
        fallback_to_existing_tags=fallback_to_existing_tags,
        diff=diff,
        output_path=output_path,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        return

    output_path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
