#!/usr/bin/env python3
"""Canonical contract shared by every embedded-card-v1 artifact builder."""

import hashlib


CARD_RUNTIME_KIND = "embedded-card-v1"
CARD_RUNTIME_VERSION = "1.1.0"
ARTIFACT_BLOCK_SEPARATOR = "\n--QB-CARD-BLOCK--\n"
READY_ATTRIBUTE = "data-qb-card-ready"
READY_VALUE = "true"
# manifest 不得内联服务端图片地址。thumbnail_url 对应的整页缩略图能力已下线，
# 但历史脏 manifest 仍可能带它，因此保留在禁止项里。
FORBIDDEN_MANIFEST_IMAGE_FIELDS = frozenset(("card_snapshot_url", "thumbnail_url"))


def canonical_artifact_payload(template, style, manifest, runtime):
    """Return the exact UTF-8 payload used by skill_server for artifact identity."""
    return ARTIFACT_BLOCK_SEPARATOR.join(
        str(value or "").strip()
        for value in (template, style, manifest, runtime)
    )


def artifact_hash(template, style, manifest, runtime):
    payload = canonical_artifact_payload(template, style, manifest, runtime)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_manifest(manifest):
    """Validate the shared 1.1 manifest without returning or logging credentials."""
    if not isinstance(manifest, dict):
        raise ValueError("card manifest 必须是 object")
    forbidden = sorted(FORBIDDEN_MANIFEST_IMAGE_FIELDS.intersection(manifest))
    if forbidden:
        raise ValueError("card manifest 不得包含图片地址字段: %s" % ", ".join(forbidden))
    if manifest.get("kind") != CARD_RUNTIME_KIND:
        raise ValueError("card manifest kind 必须是 %s" % CARD_RUNTIME_KIND)
    if manifest.get("version") != CARD_RUNTIME_VERSION:
        raise ValueError("card manifest version 必须是 %s" % CARD_RUNTIME_VERSION)
    if manifest.get("aspect_ratio") != "4/3":
        raise ValueError('card manifest aspect_ratio 必须是 "4/3"')

    required = manifest.get("required_outputs")
    if not isinstance(required, list) or not required:
        raise ValueError("card manifest required_outputs 不能为空")
    normalized = [str(value or "").strip() for value in required]
    if any(not value for value in normalized) or len(set(normalized)) != len(normalized):
        raise ValueError("card manifest required_outputs 必须是非空且不重复的字符串")

    packages = manifest.get("packages")
    if packages is not None:
        if not isinstance(packages, list) or not packages:
            raise ValueError("card manifest packages 必须是非空数组")
        for package in packages:
            if not isinstance(package, dict) or not all(str(package.get(key) or "").strip() for key in ("endpoint", "package_id", "signature")):
                raise ValueError("card manifest packages 缺少 endpoint/package_id/signature")
    elif not all(str(manifest.get(key) or "").strip() for key in ("endpoint", "package_id", "signature")):
        raise ValueError("card manifest 缺少 endpoint/package_id/signature")
    return manifest


def validate_runtime_source(runtime):
    """Enforce the shared post-hydrate ready marker contract for every builder."""
    source = str(runtime or "")
    if "QBCardRuntimeV1" not in source:
        raise ValueError("card runtime 未暴露 QBCardRuntimeV1")
    if READY_ATTRIBUTE not in source or READY_VALUE not in source:
        raise ValueError("card runtime 未声明 hydrate ready 标记")
    return runtime
