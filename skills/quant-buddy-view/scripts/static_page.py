#!/usr/bin/env python3
r"""
静态页托管客户端 —— 把一份自包含 HTML 看板上传到对象存储，得到公开可分享链接。

对接接口文档：见 skill_server docs「静态页托管」对外接口文档。
工具说明文档：tools/static_page.md

静态页子命令（除直连 URL 验收外需 API Key）：
    new_asset_page  简单单一 A 股分析快速通道：直接生成并返回终态个股分析页
    new_page   首次会话先上传 iframe 友好的活页进度页，返回 page_id + 公开 url
    update_progress  更新同一个 page_id 的进度页 HTML；刷新由承接页面负责
    upload     上传 HTML，返回 page_id + 公开 url
    update     替换已有页面内容（URL / page_id 不变，已分享链接照常可用）
    publish_final  首链进度页最终发布封装：先进入 final_publish，失败时回写失败态
    publish_verified  fork 门禁、本地分级浏览器检查、同链接发布和公网冒烟的一体化封装
    interpret  读取既有 QuantBuddy 活页的定义与实时数据，供直接解读（不下载 HTML、不暴露凭证）
    interpret_csv  下载并解析 interpret 返回的 fast_query CSV 引用，供指标计算
    download   取回已发布页面的 HTML（再编辑用）：服务端鉴权返回 url，脚本直连 OSS 下载
    list       列出我的页面
    init_reply_metadata  为缺少 page_context / agent_reply_template 的旧页面初始化回复元数据
    revoke     撤销页面（删对象 + 标记失效，链接立即 404）
    tags       查询 upload/update 可用标签（scene 场景 / paradigm 范式；recommend 仅后台维护）
    autotag    LLM 自动识别页面的场景/范式标签并落库（dry_run 只读预览；force 忽略缓存重打）
    publish_community    将自己的 active 普通页发布到社区（内部受控打 recommend:社区 标签）
    unpublish_community  取消社区发布（移除固定 recommend:社区 标签）
    templates  列出范式卡活页（默认官方精选；recommend="all" 或 include_community=true 合并官方精选+社区）
    template   官方精选详情：标题/说明/关联公式包 + 公开下载链接（拿来克隆复用）
    direct_deliver  直达命中确定性执行：模板详情 → 单次实时查询 → direct_finalize
    direct_finalize  直达命中终态：校验模板 revision、实时查询证据和任务归属，返回交付 Trace
    fork_prepare  下载命中范式，自动脱敏凭证并生成 fork_manifest_v2/review/publish plan
    fork_validate 在浏览器验收前对工作 HTML 复用 publish_final 的 fork 门禁（不发布）
    retrofit_card_runtime  为已发布模板重建独立 card runtime artifact，可原链接写回
    verify_card_runtime  批量快速验收独立 card runtime artifact（下载 HTML + required_outputs + 独立 hydrate）

权限 / 权责（is_test 内部互通）：归属由 api_key（Bearer）认定。
  · 自己的页面（upload/update/download/list/revoke）：默认只能操作本人页面；
    is_test=true 的用户可 download / update 其他 is_test 用户的页面、并用 list 的
    scope=test_all 列出全部 test 用户页面。对普通（非 is_test）用户的页面一律 FORBIDDEN。
  · 官方精选（templates/template）：浏览 / 复制对**全体登录用户**开放，发现口径是后台
    推荐标签 recommend:官方精选；不再要求 is_template=true 或 template_status=published。
  · 官方精选标签、旧模板元数据、上下线、删除、把某个用户页转成旧公共模板都属于后台写操作，
    本 skill 侧默认只做「读取 + 复用」官方精选。已转 published template 的页面不支持本
    skill 侧写回；`retrofit_card_runtime` 命中 template 目标时返回明确的不支持写回结果。

参数传递（规避 PowerShell GBK 截断）：优先级 SP_PARAMS 环境变量 > @file > 命令行 JSON > stdin

upload 参数：
    {
      "html":        "HTML 全文（与 html_file 二选一）",
      "html_file":   "本地 HTML 文件路径（与 html 二选一；常用 build_dashboard 的产物）",
      "title":       "可选，不传则服务端从 <title> 抽取",
      "description": "可选，页面说明（≤1000 字，列表/详情展示用）",
      "ttl_days":    "可选，默认 365",
      "scene_tags":    "可选，场景标签（数组/逗号串/单值）；只能选已有，查无报 SCENE_TAG_NOT_FOUND",
      "paradigm_tags": "可选，范式标签（数组/逗号串/单值）；可选已有或现写新名自动入池(source=user)",
      "user_query": "可选，用户原始问题；用于 LLM 打标或显式标签来源溯源",
      "tagging_method": "可选，标签决策方式：manual / llm / migration / unknown；不要传 agent，LLM 自动识别请用 autotag",
      "tagging_source": "可选，标签来源系统：quant-buddy-view / growthX / skill_server / script / unknown",
      "tagging_meta": "可选，对象；高级标签来源审计，method/source/note 会透传服务端",
      "page_context": "可选，对象；当前活页用途、核心模块、主要输出、回复重点和能力限制",
      "agent_reply_template": "可选，对象；兼容 reply_template_v1/v2，template_ref 指向 reply-templates/ 稳定 id",
      "verify_card_runtime": "可选 true；上传前只验收 card runtime artifact，失败不上传"
    }
    标签：推荐标签仅后台维护，本脚本不暴露；范式标签现写即进共享池。
    先用 tags 子命令查询可用场景/范式：python scripts/static_page.py tags
new_asset_page 参数：asset 必填（A 股名称或代码）；user_query / ttl_days 可选。
    仅用于无定制内容、对比、多标的或指定额外产出的简单单股分析；trace begin 后可跳过 templates/new_page。
    成功会材料化证据并在命令内部确定性生成严格证据化回复，直接返回 agent_reply_markdown；
    stdout 不返回 data_sources 内容、HTML、Grant、signature 或内部 profile。
new_page 参数：title / message / current_step / page_status / steps / required_input 可选；正式 task 还必须在 templates(recommend="all") 后由 Agent 传 routing_decision：
    fork 用 {mode:"fork",source_template_id,reason_code}；unmatched 用 {mode:"unmatched",closest_template_id,reason_code,reason}。
    脚本核验候选属于本 task 并记录决定；默认接入公共 share shell，上传一个不自刷新的 iframe 活页进度页，并返回 page_id / url / progress。
update_progress 参数：page_id 必填；title / message / current_step / page_status / steps / required_input / change_note 可选；
    只 update 同一个 URL 的 HTML 内容；仅传 current_step 时会自动推导前序完成、当前进行中、后序待开始。
    change_note 不传时按状态、中文阶段标题和用户可见 message 自动生成，最长 200 字；显式传入时优先。
    必须等用户决定时用 page_status=waiting_input + required_input{id,prompt,options?,resume_step}；
    用户回复后复用同一 task_id/page_id，以 page_status=running 恢复。
    message 是用户可见文案，避免 HTML / 公式包 / 本地浏览器验收 / page_id 等工程词。
    不在页面里写自动刷新、跳转或 parent 通信。
publish_final 参数：同 update；推荐用于首链进度页的最终正式发布。
    会先把进度页推进到 final_publish；若正式 update 失败，会自动把同一 page_id 更新为 failed 进度页。
    正式版本未传 change_note 时默认记录“完成发布：正式活页内容已发布”；进度快照另行自动生成阶段描述。
    会在任何网络写入前复核 new_page 的 routing_decision；已选 fork 却没有 fork_prepare binding 时返回 ROUTING_RECONFIRM_REQUIRED。
    fork 一经记录便不能改判 unmatched；后续必须走 inherit / inherit_augment，继承不成立时在 fork 内走 Compose。
    复用在线模板时传 source_template_id + fork_manifest_file；前者继承回复骨架，后者证明来源 HTML 已下载并声明 fork 门禁；page_context 必须按最终用户活页重新生成。
    同一 task_id 执行过 fork_prepare 后，publish_final 会自动恢复已绑定的来源与 manifest；省略或改写参数不能绕过 fork 门禁。
    无法匹配专业骨架时使用 generic_live_page_delivery_v1；v2 hybrid 缺 page_context / hybrid_composition 时 fail-closed。
publish_verified 参数：同 publish_final，另传 validation_receipt_files；固定执行 fork_validate → fork-local → publish_final → public-smoke。发布前失败不写页面；发布后冒烟失败返回 published=true、verified=false 和最终 URL。
update 参数：page_id 必填；title / description / ttl_days / scene_tags / paradigm_tags /
    user_query / tagging_method / tagging_source / tagging_meta /
    page_context / agent_reply_template / verify_card_runtime 仅在传了才改
    （description 传空串=清空，不传保留原值；标签字段传 [] 清空、不传保留原标签）。
download 参数：
    {
      "page_id":  "要下载的页面（与 url 二选一）",
      "url":      "页面公开链接（与 page_id 二选一）",
      "save":     "可选，落盘路径（相对则相对 skill 根）；不传则把 html 直接放进返回 JSON",
      "final_response": "可选 true；仅在只读页面后直接回答时返回终态 contract，默认返回非终态 hint"
    }
    下载字节直连 OSS（public-read），不经服务端 → 不占服务端带宽。
tags 参数：{ "tag_type":可选("scene" 或 "paradigm") }；不传则同时返回 scene_tags / paradigm_tags。
init_reply_metadata 参数：{ "scope":"test_all", "dry_run":true, "page_ids":["page_xxx"], "max_pages":500 }；
    默认只 dry-run 扫描 is_test 可见页面，下载缺 page_context / agent_reply_template 的页面，
    根据现有 HTML、标题和标签推断回复元数据；dry_run=false 才用同一 HTML 写回初始化结果。
publish_community / unpublish_community 参数：{ "page_id":"page_xxx" }；仅 owner 可操作自己的 active 普通页。
templates 参数：{ "category":可选, "status":可选, "scene_tag_id":可选, "paradigm_tag_id":可选, "recommend_tag_id":可选, "recommend":可选("社区"/"all"/"both"), "include_community":可选 true, "page":1, "page_size":20 }；不传 recommend/include_community 时仍限定 recommend:官方精选；recommend="社区" 只查社区；recommend="all"/include_community=true 合并官方精选+社区（范式卡命中池，按 page_id 去重）。recommend_tag_id 是额外叠加筛选。
template  参数：{ "template_id":"tpl_xxx" }（或 "page_id":"page_xxx" 二选一）
direct_finalize 参数：{ "task_id":"本次 Trace task_id", "page_id":"page_xxx", "template_revision":"template 返回的 sha256" }
direct_deliver 参数：{ "task_id":"本次 Trace task_id", "page_id":"page_xxx", "template_revision":"templates 返回的 sha256" }
fork_prepare 参数：{ "task_id":"本次 Trace task_id", "source_template_id":"page_xxx", "target_page_id":"new_page 返回的目标 page_id", "output_dir":"output/forks/page_xxx", "target_asset":{"name":"目标标的名","code":"目标代码"}, "source_asset":可选{"name":"来源模板主资产名"}（多资产/指数类范式建议显式给）, "asset_replacements":可选覆盖映射, "minimum_target_package_count":可选, "minimum_target_grant_count":可选, "credential_count_reduction_reason":"数量下调时必填" }
  资产替换由 target_asset 驱动：来源主资产及其在页面中的实际代码写法由脚本自行推导，Agent 不需要（也无法）猜来源 HTML 里代码写成 SH600900 还是 600900.SH。asset_replacements 仅在需要额外文案替换或覆盖推导结果时才传。
verify_card_runtime 参数：{ "page_ids":["page_xxx"], "require_browser":true, "timeout_sec":180 }

用法示例：
    python scripts/static_page.py new_asset_page '{"task_id":"task_xxx","asset":"贵州茅台","user_query":"分析贵州茅台"}'
    python scripts/static_page.py new_page '{"task_id":"task_xxx","title":"贵州茅台估值质量分析","message":"正在确认活页方案","routing_decision":{"mode":"fork","source_template_id":"page_template_xxx","reason_code":"same_paradigm_different_asset","borrow_mode":"inherit"}}'
    python scripts/static_page.py update_progress '{"page_id":"page_xxx","current_step":"formula_validation","message":"正在验证实时数据"}'
    python scripts/static_page.py publish_final '{"page_id":"page_xxx","html_file":"output/pages/final.html","title":"贵州茅台估值质量分析","source_template_id":"page_template_xxx","fork_manifest_file":"output/forks/page_template_xxx/page_template_xxx.fork-manifest.json","require_agent_reply_template":true}'
    python scripts/static_page.py publish_verified '{"task_id":"task_xxx","page_id":"page_xxx","html_file":"output/pages/final.html","source_template_id":"page_template_xxx","fork_manifest_file":"output/forks/page_template_xxx/page_template_xxx.fork-manifest.json","validation_receipt_files":["receipt.json"]}'
    python scripts/static_page.py upload '{"html_file":"output/pages/dash.html","title":"沪深300异动看板"}'
    python scripts/static_page.py update '{"page_id":"page_xxx","html_file":"output/pages/dash.html"}'
    python scripts/static_page.py download '{"page_id":"page_xxx","save":"output/pages/back.html"}'
    python scripts/static_page.py list '{"page":1,"page_size":20}'
    python scripts/static_page.py list '{"scope":"test_all"}'   # 仅 is_test：列出全部 test 用户页面
    python scripts/static_page.py init_reply_metadata '{"scope":"test_all","dry_run":true}'
    python scripts/static_page.py revoke '{"page_id":"page_xxx"}'
    python scripts/static_page.py tags '{}'                                      # 查询可用场景/范式标签
    python scripts/static_page.py tags '{"tag_type":"scene"}'                 # 只查场景标签
    python scripts/static_page.py publish_community '{"page_id":"page_xxx"}'   # 发布到社区（全员可发现）
    python scripts/static_page.py unpublish_community '{"page_id":"page_xxx"}' # 取消社区发布
    python scripts/static_page.py templates '{"page":1,"page_size":20}'        # 浏览官方精选
    python scripts/static_page.py template  '{"template_id":"page_xxx"}'        # 官方精选详情/拿下载链接克隆
    python scripts/static_page.py direct_finalize '{"task_id":"task_xxx","page_id":"page_xxx","template_revision":"sha256"}'
    python scripts/static_page.py fork_prepare '{"task_id":"task_xxx","source_template_id":"page_xxx","target_page_id":"page_new","target_asset":{"name":"目标标的名","code":"目标代码"}}'
    python scripts/static_page.py verify_card_runtime '{"page_ids":["page_xxx","page_yyy"]}' # 快速批量验收 card artifact

输出：结果打印到 stdout（UTF-8），并写一份到临时目录 sp_out.txt。
读取型命令默认返回 agent_reply_hint（terminal=false）；来源模板 download_url 在 fork 分支不能当用户交付链接。direct 精确命中必须调用 `direct_finalize`，普通 published template 禁止用 `download(final_response:true)` 收口。
成功写入命令及 `direct_finalize` 返回 agent_reply_contract；`download(final_response:true)` 仅保留给普通自有页面的只读兼容。
contract.required=true 时，Agent 最终答复前必须读取本地回复模板，按模板格式输出并包含公开活页链接。
"""

import hashlib
import html as html_lib
from html.parser import HTMLParser
import io
import json
import copy
import os
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse as _up
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import compile_bespoke_page as CB
import common as C
import data_kernel_retrofit as DKR
import fork_runtime_contract as FRC
import fast_query_csv as FQCSV
import materialize_new_asset_csv as MNAC
import progress_page as PP
import qbs_job_lifecycle as QJL
import reply_data_evidence as RDE
import reply_template_registry as RTR
import session_complete as SC
import share_shell_contract as SSC
import single_stock_reply as SSR

_PATH = {
    "upload":    "/skill/uploadStaticPage",
    "update":    "/skill/updateStaticPage",
    "download":  "/skill/getPageDetail",
    "list":      "/skill/listPages",
    "revoke":    "/skill/revokeStaticPage",
    "image_upload": "/skill/uploadPageImage",
    "image_list": "/skill/listPageImages",
    "tags":      "/skill/listPageTags",
    "autotag":   "/skill/autoTagStaticPage",
    "publish_community":   "/skill/publishStaticPageToCommunity",
    "unpublish_community": "/skill/unpublishStaticPageFromCommunity",
    "templates": "/skill/listPages",
    "template":  "/skill/getPageDetail",
    "direct_finalize": "/skill/finalizeDirectPage",
    "new_asset_page": "/skill/newAssetPage",
}

_UPLOAD_TIMEOUT = 120
_DEFAULT_TIMEOUT = 60

# 服务端限制：单页 ≤ 2MB（这里只做一次本地早检，真正以服务端为准）
_MAX_HTML_BYTES = 2 * 1024 * 1024
_MAX_PAGE_IMAGE_BYTES = 5 * 1024 * 1024
_SHARE_POSTER_VERSION = "snapshot-tall-v1"
_SHARE_SHELL_CONTRACT = SSC.load_contract()
_SHARE_SHELL_VERSION = _SHARE_SHELL_CONTRACT["version"]
_SHARE_SHELL_REVISION = _SHARE_SHELL_CONTRACT["revision"]
_SHARE_SHELL_MARKERS = tuple(SSC.MARKERS)
_FORK_MANIFEST_VERSION_V1 = "fork_manifest_v1"
_FORK_MANIFEST_VERSION = FRC.MANIFEST_VERSION
_SUPPORTED_FORK_MANIFEST_VERSIONS = {
    _FORK_MANIFEST_VERSION_V1,
    _FORK_MANIFEST_VERSION,
}
_FORK_TASK_BINDING_VERSION = "fork_task_binding_v1"
_FORK_PREFLIGHT_SENTINEL = object()
_VIA_PUBLISH_WORKFLOW_SENTINEL = object()
# 只要 fork 涉及至少 1 个 package/grant 就必须走 publish_workflow.py：
# 低于这个数量时仓库里没有第二个"替换 marker/凭证"的工具，留豁免区间等于逼 Agent 自己写替换脚本。
_PUBLISH_WORKFLOW_REQUIRED_THRESHOLD = 1
_MANAGED_IMAGE_RE = re.compile(
    r"(?:https://pages\.quantbuddy\.cn)?/pages/assets/([^/\s\"')]+)/(asset_[0-9a-f]{24})\.webp",
    re.IGNORECASE,
)
_IMAGE_MARKER_RE = re.compile(r"__QB_IMAGE_[A-Z0-9_]+__")
_VALIDATION_RECEIPT_VERSION = "qb_validation_receipt_v1"
_GRANT_VALIDATION_RECEIPT_VERSION = "grant_validation_receipt_v1"
_QBS_HANDOFF_VALIDATION_RECEIPT_VERSION = "qbs_handoff_validation_receipt_v1"
_LIVE_DATA_ROUTE_RECEIPT_VERSION = "live_data_route_receipt_v1"
_LIVE_DATA_MODES = {"live", "static_content_only", "static_after_live_probe"}
_PRESERVE_HTML_QBS_LIVE_MODE = "preserve_html_qbs_live"
_LIVE_INDICATOR_VERSION = "v2"
_LIVE_INDICATOR_STYLE_V1 = """[data-qb-live-mode="live"][data-qb-live-tag~="qbs-formula-package"],
[data-qb-live-mode="live"][data-qb-live-tag~="qbs-data-grant"]{position:relative}
[data-qb-live-mode="live"][data-qb-live-tag~="qbs-formula-package"]::after,
[data-qb-live-mode="live"][data-qb-live-tag~="qbs-data-grant"]::after{position:absolute;top:8px;right:8px;z-index:2147483000;box-sizing:border-box;max-width:calc(100% - 16px);padding:4px 8px;border:1px solid rgba(16,185,129,.32);border-radius:999px;background:rgba(6,78,59,.92);box-shadow:0 2px 8px rgba(6,78,59,.18);color:#ecfdf5;font:600 11px/1.2 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;letter-spacing:.02em;white-space:nowrap;pointer-events:none}
[data-qb-live-mode="live"][data-qb-live-tag~="qbs-formula-package"]::after{content:"● LIVE · QBS 计算"}
[data-qb-live-mode="live"][data-qb-live-tag~="qbs-data-grant"]::after{content:"● LIVE · QBS 取数"}
@media(max-width:480px){[data-qb-live-mode="live"][data-qb-live-tag~="qbs-formula-package"]::after,[data-qb-live-mode="live"][data-qb-live-tag~="qbs-data-grant"]::after{top:6px;right:6px;max-width:calc(100% - 12px);padding:3px 6px;font-size:10px}}"""
_LIVE_INDICATOR_STYLE = """[data-qb-live-mode="live"][data-qb-live-tag~="qbs-formula-package"],
[data-qb-live-mode="live"][data-qb-live-tag~="qbs-data-grant"]{position:relative}
[data-qb-live-mode="live"][data-qb-live-tag~="qbs-formula-package"]::after,
[data-qb-live-mode="live"][data-qb-live-tag~="qbs-data-grant"]::after{position:absolute;top:6px;right:6px;z-index:2147483000;box-sizing:border-box;max-width:calc(100% - 12px);padding:2px 6px;border:1px solid rgba(100,116,139,.18);border-color:color-mix(in srgb,currentColor 16%,transparent);border-radius:999px;background:rgba(148,163,184,.08);background:color-mix(in srgb,currentColor 7%,transparent);box-shadow:none;color:inherit;opacity:.52;font:600 10px/1.2 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;letter-spacing:.04em;white-space:nowrap;pointer-events:auto;cursor:help;transition:opacity .16s ease,background-color .16s ease,border-color .16s ease}
[data-qb-live-mode="live"][data-qb-live-tag~="qbs-formula-package"]::after,
[data-qb-live-mode="live"][data-qb-live-tag~="qbs-data-grant"]::after{content:"● LIVE"}
[data-qb-live-mode="live"][data-qb-live-tag~="qbs-formula-package"]:hover::after{content:"QBS 实时计算，刷新时更新"}
[data-qb-live-mode="live"][data-qb-live-tag~="qbs-data-grant"]:hover::after{content:"QBS 实时取数，刷新时更新"}
[data-qb-live-mode="live"][data-qb-live-tag~="qbs-formula-package"]:hover::after,
[data-qb-live-mode="live"][data-qb-live-tag~="qbs-data-grant"]:hover::after{opacity:.86;background:rgba(148,163,184,.13);background:color-mix(in srgb,currentColor 11%,transparent);border-color:rgba(100,116,139,.26);border-color:color-mix(in srgb,currentColor 24%,transparent)}
@media(max-width:480px){[data-qb-live-mode="live"][data-qb-live-tag~="qbs-formula-package"]::after,[data-qb-live-mode="live"][data-qb-live-tag~="qbs-data-grant"]::after{top:5px;right:5px;max-width:calc(100% - 10px);padding:2px 5px;font-size:9px}}
@media(prefers-reduced-motion:reduce){[data-qb-live-mode="live"][data-qb-live-tag~="qbs-formula-package"]::after,[data-qb-live-mode="live"][data-qb-live-tag~="qbs-data-grant"]::after{transition:none}}"""
_LIVE_INDICATOR_STYLES = {
    "v1": _LIVE_INDICATOR_STYLE_V1,
    _LIVE_INDICATOR_VERSION: _LIVE_INDICATOR_STYLE,
}
_LIVE_INDICATOR_STYLE_TAG = (
    f'<style data-qb-live-indicator-runtime="{_LIVE_INDICATOR_VERSION}">\n'
    f'{_LIVE_INDICATOR_STYLE}\n'
    '</style>'
)
_PROGRESS_SHELL_THEME = {
    "chrome_bg": "#ffffff",
    "header_bg": "#ffffff",
    "footer_bg": "#ffffff",
    "accent": "#fe9c3c",
    "accent_strong": "#8f4e00",
    "line": "#d9e0ea",
    "ink": "#111c2d",
    "muted": "#45474c",
}
_PACKAGE_ISSUE_RE = re.compile(
    r"formula[_ -]?package|package_id|signature|公式包|签名|查无|失效|无效|not[_ -]?found|invalid",
    re.I,
)
_REPLY_TEMPLATE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_REPLY_TEMPLATE_FIELDS = ("version", "template_ref", "reply_scope", "output_format", "hybrid_composition")
_PAGE_CONTEXT_FIELDS = ("version", "summary", "core_sections", "primary_outputs", "reply_focus", "limitations")
_REPLY_CONTRACT_BINDING_FIELDS = ("version", "profile_ref", "revision", "managed_by")
_REPLY_TEMPLATE_VERSIONS = {"reply_template_v1", "reply_template_v2"}
_REPLY_SCOPES = {"full_answer", "hybrid"}
_HYBRID_COMPOSITION_VERSION = "hybrid_composition_v1"
_PAGE_CONTEXT_VERSION = "page_context_v1"
_PAGE_CONTEXT_OUTPUTS_DERIVED = "derived"
_PAGE_CONTEXT_OUTPUTS_LEGACY = "legacy"
_PAGE_CONTEXT_OUTPUTS_PROVENANCE = (_PAGE_CONTEXT_OUTPUTS_DERIVED, _PAGE_CONTEXT_OUTPUTS_LEGACY)
_FEISHU_GROUP_CHANNEL = "feishu-group"
_PAGES_PUBLIC_HOST = "pages.quantbuddy.cn"
_PLAYGROUND_PUBLIC_HOST = "www.quantbuddy.cn"
_MAX_REPLY_METADATA_BYTES = 8 * 1024
_MAX_PAGE_CONTEXT_BYTES = 8 * 1024
_MAX_PAGE_CONTEXT_TEXT = 1000
_MAX_PAGE_CONTEXT_ITEMS = 50
_MAX_PAGE_CONTEXT_ITEM = 128
_PAGE_CONTEXT_SENSITIVE_RE = re.compile(
    r"(?:\bapi[_ -]?key\b|\bbearer\s+[a-z0-9._-]+|\bsignature\s*[:=]|[a-zA-Z]:\\)",
    re.I,
)
_SINGLE_STOCK_VALUATION_REPLY_TEMPLATE = {
    "version": "reply_template_v2",
    "template_ref": "single_stock_valuation_quality_v1",
    "reply_scope": "full_answer",
    "output_format": "markdown",
}
_GENERIC_LIVE_PAGE_REPLY_TEMPLATE = {
    "version": "reply_template_v2",
    "template_ref": "generic_live_page_delivery_v1",
    "reply_scope": "full_answer",
    "output_format": "markdown",
}
_PRESERVE_HTML_QBS_LIVE_REPLY_TEMPLATE = {
    "version": "reply_template_v2",
    "template_ref": "preserve_html_qbs_live_delivery_v1",
    "reply_scope": "full_answer",
    "output_format": "markdown",
}
_REPLY_FOCUS = {
    "global_asset_bubble_monitor_v1": "先比较七个指数的区间位置与偏离度，再结合本轮实际返回的宏观压力变量解释结构性高温。",
    "market_event_impact_v1": "先给出事件结论，再解释传导链、受益受损方向和验证指标。",
    "sector_theme_opportunity_v1": "先判断主题所处阶段，再解释催化、产业链位置、风险和跟踪指标。",
    "single_stock_valuation_quality_v1": "先判断估值水位，再判断盈利与现金流质量，最后给出风险条件。",
    "single_stock_deep_dive_v1": "围绕公司画像、经营质量、估值、催化与风险形成完整个股结论。",
    "multi_asset_compare_v1": "使用同口径表格比较核心指标，明确相对优势、短板和适用场景。",
    "capital_flow_quant_signal_v1": "先概括信号与资金结构，再说明有效区间、失效条件和风险。",
    "fund_etf_bond_profile_v1": "先说明产品定位与风险收益特征，再解释持仓、流动性和适用场景。",
    "hk_us_overseas_asset_v1": "先说明海外资产核心驱动，再覆盖估值、汇率、流动性与事件风险。",
    "generic_live_page_delivery_v1": "概括活页用途、核心模块、当前可见结论、使用方法和能力边界。",
    "preserve_html_qbs_live_delivery_v1": "只说明本地 HTML 的结构保真、QBS 数据链替换、实时刷新状态和交付信息，不扩写业务研究结论。",
}
_PAGE_CONTEXT_SUMMARY = {
    "global_asset_bubble_monitor_v1": "用于持续监测七个全球主要股票指数的泡沫温度及利率、美元、波动率与流动性压力。",
    "market_event_impact_v1": "用于呈现宏观市场、事件影响与跨资产传导的实时分析活页。",
    "sector_theme_opportunity_v1": "用于呈现行业或主题强弱、标的池、催化与风险的实时分析活页。",
    "single_stock_valuation_quality_v1": "用于呈现单只上市公司的估值水位与财务质量分析活页。",
    "single_stock_deep_dive_v1": "用于呈现单只上市公司的经营、估值、资金与风险综合分析活页。",
    "multi_asset_compare_v1": "用于呈现多个标的或资产的同口径比较与风险收益分析活页。",
    "capital_flow_quant_signal_v1": "用于呈现资金结构、量化信号、策略表现与失效条件的实时活页。",
    "fund_etf_bond_profile_v1": "用于呈现基金、ETF或债券产品的收益、估值、持仓与风险活页。",
    "hk_us_overseas_asset_v1": "用于呈现港股、美股或海外资产的行情、财务、估值与事件活页。",
    "generic_live_page_delivery_v1": "用于呈现当前页面的核心模块、实时输出与能力边界。",
    "preserve_html_qbs_live_delivery_v1": "用于交付保持原页面结构和内容不变、仅将数据链替换为 QBS 的实时活页。",
}


def _record_url(record):
    if not isinstance(record, dict):
        return ""
    return record.get("download_url") or record.get("public_url") or record.get("url") or ""


def _delivery_policy():
    if str(C.SKILL_CHANNEL or "").strip().lower() != _FEISHU_GROUP_CHANNEL:
        return None
    return {
        "channel": _FEISHU_GROUP_CHANNEL,
        "emit_intermediate_url": False,
        "terminal_url_format": "quantbuddy_playground",
        "max_markdown_tables": 5,
    }


def _delivery_public_url(value):
    """Return the user-facing URL without changing the internal hosting URL."""
    url = str(value or "").strip()
    if not url or not _delivery_policy():
        return url
    try:
        parsed = _up.urlsplit(url)
    except ValueError:
        return url

    host = str(parsed.hostname or "").lower()
    if host == _PLAYGROUND_PUBLIC_HOST and parsed.path.startswith("/playground/"):
        return url
    if parsed.scheme.lower() != "https" or host != _PAGES_PUBLIC_HOST:
        return url

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 3 or parts[0] != "pages" or not parts[1] or not parts[2].endswith(".html"):
        return url
    page_id = parts[2][:-5]
    if not page_id:
        return url
    return _up.urlunsplit((
        "https",
        _PLAYGROUND_PUBLIC_HOST,
        f"/playground/{parts[1]}/{page_id}",
        parsed.query,
        parsed.fragment,
    ))


def _apply_delivery_policy(payload):
    if not isinstance(payload, dict):
        return payload
    policy = _delivery_policy()
    if policy:
        payload["delivery_policy"] = policy
    return payload


def _agent_reply_template_metadata(value):
    if not isinstance(value, dict):
        return value
    out = {k: value.get(k) for k in _REPLY_TEMPLATE_FIELDS if k in value}
    if isinstance(out.get("hybrid_composition"), dict):
        out["hybrid_composition"] = dict(out["hybrid_composition"])
    return out


def _page_context_metadata(value):
    if not isinstance(value, dict):
        return value
    out = {k: value.get(k) for k in _PAGE_CONTEXT_FIELDS if k in value}
    for key in ("core_sections", "primary_outputs"):
        if isinstance(out.get(key), list):
            out[key] = list(out[key])
    return out


def _reply_contract_binding_metadata(value):
    if not isinstance(value, dict):
        return value
    return {k: value.get(k) for k in _REPLY_CONTRACT_BINDING_FIELDS if k in value}


def _normalize_reply_contract_binding(value):
    if value is None or value == {}:
        return None, None
    if not isinstance(value, dict):
        return None, {"code": 1, "message": "reply_contract_binding 必须是对象、null 或空对象"}
    normalized = {
        "version": str(value.get("version") or "").strip(),
        "profile_ref": str(value.get("profile_ref") or "").strip(),
        "revision": str(value.get("revision") or "").strip(),
        "managed_by": str(value.get("managed_by") or "").strip(),
    }
    if normalized["version"] != "reply_contract_binding_v1":
        return None, {"code": 1, "message": "reply_contract_binding.version 目前只支持 reply_contract_binding_v1"}
    for key in ("profile_ref", "revision"):
        if not _REPLY_TEMPLATE_ID_RE.match(normalized[key]):
            return None, {"code": 1, "message": f"reply_contract_binding.{key} 必须是稳定 id"}
    if normalized["managed_by"] not in ("manual", "system"):
        return None, {"code": 1, "message": "reply_contract_binding.managed_by 只能是 manual 或 system"}
    return normalized, None


def _normalize_agent_reply_template(value, *, require_local_file=True):
    if value is None or value == {}:
        return None, None
    if not isinstance(value, dict):
        return None, {"code": 1, "message": "agent_reply_template 必须是对象、null 或空对象"}
    version = str(value.get("version") or "reply_template_v1").strip()
    template_ref = str(value.get("template_ref") or "").strip()
    reply_scope = str(value.get("reply_scope") or "").strip()
    output_format = str(value.get("output_format") or "").strip()
    if version not in _REPLY_TEMPLATE_VERSIONS:
        return None, {"code": 1, "message": "agent_reply_template.version 只支持 reply_template_v1 / reply_template_v2"}
    if not template_ref:
        return None, {"code": 1, "message": "agent_reply_template.template_ref 必填"}
    template_file = _reply_template_path(template_ref)
    if not template_file:
        return None, {
            "code": 1,
            "message": "agent_reply_template.template_ref 只能使用 reply-templates/ 下的稳定 id",
            "template_ref": template_ref,
        }
    if require_local_file and not os.path.isfile(template_file):
        return None, {
            "code": 1,
            "message": "agent_reply_template.template_ref 对应的本地回复模板不存在",
            "template_ref": template_ref,
            "template_file": template_file,
        }
    if reply_scope not in _REPLY_SCOPES:
        return None, {"code": 1, "message": "agent_reply_template.reply_scope 只能是 full_answer 或 hybrid"}
    if output_format != "markdown":
        return None, {"code": 1, "message": "agent_reply_template.output_format 目前只支持 markdown"}
    normalized = {
        "version": version,
        "template_ref": template_ref,
        "reply_scope": reply_scope,
        "output_format": output_format,
    }
    composition = value.get("hybrid_composition")
    if version == "reply_template_v2" and reply_scope == "hybrid":
        if not isinstance(composition, dict):
            return None, {"code": 1, "message": "reply_template_v2 的 hybrid 必须提供 hybrid_composition"}
        comp_version = str(composition.get("version") or _HYBRID_COMPOSITION_VERSION).strip()
        strategy_ref = str(composition.get("strategy_ref") or "").strip()
        prompt = str(composition.get("prompt") or "").strip()
        if comp_version != _HYBRID_COMPOSITION_VERSION:
            return None, {"code": 1, "message": "hybrid_composition.version 目前只支持 hybrid_composition_v1"}
        if not _REPLY_TEMPLATE_ID_RE.match(strategy_ref):
            return None, {"code": 1, "message": "hybrid_composition.strategy_ref 必须是稳定 id"}
        if not prompt or len(prompt) > 2000:
            return None, {"code": 1, "message": "hybrid_composition.prompt 必填且不超过 2000 字符"}
        normalized["hybrid_composition"] = {
            "version": comp_version,
            "strategy_ref": strategy_ref,
            "prompt": prompt,
        }
    elif version == "reply_template_v2" and composition is not None:
        return None, {"code": 1, "message": "full_answer 不应携带 hybrid_composition"}
    if len(json.dumps(normalized, ensure_ascii=False).encode("utf-8")) > _MAX_REPLY_METADATA_BYTES:
        return None, {"code": 1, "message": "agent_reply_template 总大小不能超过 8KB"}
    return normalized, None


def _normalize_page_context(value):
    if value is None or value == {}:
        return None, None
    if not isinstance(value, dict):
        return None, {"code": 1, "message": "page_context 必须是对象、null 或空对象"}
    version = str(value.get("version") or _PAGE_CONTEXT_VERSION).strip()
    if version != _PAGE_CONTEXT_VERSION:
        return None, {"code": 1, "message": "page_context.version 目前只支持 page_context_v1"}
    summary = str(value.get("summary") or "").strip()
    if not summary:
        return None, {"code": 1, "message": "page_context.summary 必填"}
    normalized = {"version": version, "summary": summary}
    for key in ("core_sections", "primary_outputs"):
        raw = value.get(key)
        if raw is None:
            continue
        if not isinstance(raw, list):
            return None, {"code": 1, "message": f"page_context.{key} 必须是字符串数组"}
        if len(raw) > _MAX_PAGE_CONTEXT_ITEMS:
            return None, {"code": 1, "message": f"page_context.{key} 最多 {_MAX_PAGE_CONTEXT_ITEMS} 项"}
        items = []
        for item in raw:
            text = str(item or "").strip()
            if not text or len(text) > _MAX_PAGE_CONTEXT_ITEM:
                return None, {"code": 1, "message": f"page_context.{key} 每项必须非空且不超过 {_MAX_PAGE_CONTEXT_ITEM} 字符"}
            if text not in items:
                items.append(text)
        normalized[key] = items
    for key in ("summary", "reply_focus", "limitations"):
        text = str(value.get(key) or "").strip()
        if key == "summary":
            text = summary
        if len(text) > _MAX_PAGE_CONTEXT_TEXT:
            return None, {"code": 1, "message": f"page_context.{key} 不能超过 {_MAX_PAGE_CONTEXT_TEXT} 字符"}
        if text:
            normalized[key] = text
    serialized = json.dumps(normalized, ensure_ascii=False)
    if _PAGE_CONTEXT_SENSITIVE_RE.search(serialized):
        return None, {"code": 1, "message": "page_context 不能包含凭证、Bearer token 或本地绝对路径"}
    if len(serialized.encode("utf-8")) > _MAX_PAGE_CONTEXT_BYTES:
        return None, {"code": 1, "message": "page_context 总大小不能超过 8KB"}
    return normalized, None


def _strip_html_text(value):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _page_headings(html):
    source = re.sub(
        r"<(script|style|template)\b[^>]*>.*?</\1>",
        " ",
        str(html or ""),
        flags=re.I | re.S,
    )
    headings = []
    for match in re.finditer(r"<h([2-3])\b([^>]*)>(.*?)</h\1>", source, re.I | re.S):
        attrs = match.group(2)
        if re.search(r"\bid\s*=\s*(['\"])sharePosterTitle\1", attrs, re.I):
            continue
        text = _strip_html_text(match.group(3))
        if text and text not in headings and len(text) <= _MAX_PAGE_CONTEXT_ITEM:
            headings.append(text)
        if len(headings) >= 8:
            break
    return headings


def _infer_page_context_from_publish_params(params, *, html=None, template_ref=None):
    params = params or {}
    sections = _page_headings(html)
    if not sections:
        sections = list(_tag_names(params.get("paradigm_tags")))[:5]
    if not sections:
        sections = ["核心判断", "关键指标", "风险与限制"]
    raw_outputs = params.get("primary_outputs") or params.get("required_outputs") or params.get("card_required_outputs")
    outputs = []
    if isinstance(raw_outputs, list):
        outputs = [str(item).strip() for item in raw_outputs if str(item).strip()][:_MAX_PAGE_CONTEXT_ITEMS]
    if not outputs:
        outputs = ["页面核心结论", "关键指标解释", "公开活页链接"]
    context = {
        "version": _PAGE_CONTEXT_VERSION,
        "summary": _PAGE_CONTEXT_SUMMARY.get(template_ref, _PAGE_CONTEXT_SUMMARY["generic_live_page_delivery_v1"]),
        "core_sections": sections,
        "primary_outputs": outputs,
        "reply_focus": _REPLY_FOCUS.get(template_ref, _REPLY_FOCUS["generic_live_page_delivery_v1"]),
        "limitations": "仅依据活页当前可用数据解释；结构性不存在的内容不展示，偶发缺值才标记为 --，不编造数据或提供保证性预测。",
    }
    normalized, error = _normalize_page_context(context)
    return None if error else normalized


def _tag_names(value):
    names = set()
    for item in value or []:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = ""
        if name:
            names.add(name)
    return names


def _infer_agent_reply_template_from_publish_params(params):
    """Infer only high-confidence reply-template routes from publish metadata.

    This is deliberately narrower than the Agent's semantic routing. It exists
    as a fail-safe for final publication, where silently returning a generic
    publish summary is worse than attaching the known reply contract.
    """
    if not isinstance(params, dict):
        return None
    scene_tags = _tag_names(params.get("scene_tags"))
    paradigm_tags = _tag_names(params.get("paradigm_tags"))
    text = " ".join(str(params.get(key) or "") for key in ("title", "description", "user_query"))
    # 横截面选股/榜单即使同时含 PE、ROE、盈利、估值，也不是“单只股票估值质量”页面。
    # 必须先截断到通用交付骨架，避免标题关键词把 TopN 页面误绑到七节单股回复合同。
    screening_signal = (
        any(token in text for token in ("选股", "榜单", "排行榜", "排名", "全A", "全 A", "因子筛选"))
        or re.search(r"TOP\s*(?:N|\d+)", text, flags=re.IGNORECASE) is not None
    )
    if screening_signal:
        return dict(_GENERIC_LIVE_PAGE_REPLY_TEMPLATE)
    valuation_signal = any(token in text for token in ("估值", "PE", "PB", "PCF", "市盈率", "市净率"))
    quality_signal = any(token in text for token in ("财务", "质量", "盈利", "ROE", "现金流", "负债率"))
    valuation_paradigm = bool(paradigm_tags & {"盈利质量", "价值陷阱"})
    comparative_signal = any(token in text for token in ("行业", "板块", "组合", "对比", "比较", "多资产"))
    if (valuation_paradigm or (valuation_signal and quality_signal)) and not comparative_signal:
        return dict(_SINGLE_STOCK_VALUATION_REPLY_TEMPLATE)
    routes = [
        ("market_event_impact_v1", ("宏观", "事件", "政策", "新规", "财报事件", "基差", "盘前")),
        ("multi_asset_compare_v1", ("对比", "比较", "同业", "组合", "多资产", "A/H", "溢价")),
        ("sector_theme_opportunity_v1", ("行业", "主题", "主线", "产业链", "赛道", "轮动", "拥挤度")),
        ("capital_flow_quant_signal_v1", ("资金", "量化", "信号", "动量", "多因子", "涨跌停", "RSRS", "异动")),
        ("fund_etf_bond_profile_v1", ("基金", "ETF", "债券", "转债", "固收")),
        ("hk_us_overseas_asset_v1", ("港股", "美股", "海外", "英伟达", "纳斯达克", "汇率")),
    ]
    for template_ref, tokens in routes:
        if any(token in text for token in tokens):
            return {
                "version": "reply_template_v2",
                "template_ref": template_ref,
                "reply_scope": "full_answer",
                "output_format": "markdown",
            }
    if "看标的" in scene_tags or any(token in text for token in ("个股", "股票", "公司", "深度分析")):
        return {
            "version": "reply_template_v2",
            "template_ref": "single_stock_deep_dive_v1",
            "reply_scope": "full_answer",
            "output_format": "markdown",
        }
    return dict(_GENERIC_LIVE_PAGE_REPLY_TEMPLATE)


def _bool_param(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _resolve_publish_agent_reply_template(params, *, html=None):
    resolved = dict(params or {})
    preserve_html_qbs_live = (
        str(resolved.get("transformation_mode") or "").strip() == _PRESERVE_HTML_QBS_LIVE_MODE
    )
    if preserve_html_qbs_live:
        # This migration is an implementation delivery, not a new research report.
        # Force the dedicated contract even if a caller supplied the generic fallback.
        resolved["agent_reply_template"] = dict(_PRESERVE_HTML_QBS_LIVE_REPLY_TEMPLATE)
    explicit_template = "agent_reply_template" in resolved
    explicit_clear = explicit_template and resolved.get("agent_reply_template") in (None, {})
    required = _bool_param(resolved.get("require_agent_reply_template"))
    if explicit_clear:
        if required:
            return resolved, {"mode": "explicit_clear", "source_template_id": ""}, {
                "code": 1,
                "message": "publish_final 同时要求 Agent 回复模板并显式清空 agent_reply_template，参数冲突",
            }
        return resolved, {"mode": "explicit_clear", "source_template_id": ""}, None

    meta, meta_error = _normalize_agent_reply_template(resolved.get("agent_reply_template"))
    if meta_error:
        return resolved, {"mode": "invalid", "source_template_id": ""}, meta_error
    mode = (
        _PRESERVE_HTML_QBS_LIVE_MODE
        if preserve_html_qbs_live
        else ("explicit" if isinstance(meta, dict) and meta.get("template_ref") else "")
    )
    source_template_id = "" if preserve_html_qbs_live else (
        resolved.get("source_template_id")
        or resolved.get("source_template_page_id")
        or ""
    )
    source_result = None

    source_record = {}
    if source_template_id:
        source_result = cmd_template({"page_id": source_template_id})
        if not (isinstance(source_result, dict) and source_result.get("code") == 0):
            source_message = (
                source_result.get("message")
                if isinstance(source_result, dict)
                else str(source_result or "")
            )
            return resolved, {
                "mode": "source_template_unavailable",
                "source_template_id": source_template_id,
            }, {
                "code": 1,
                "message": (
                    f"publish_final 无法读取 source_template_id={source_template_id}"
                    + (f": {source_message}" if source_message else "")
                ),
            }
        source_record = _template_record(source_result)
    if not mode and source_template_id:
        source_meta, source_meta_error = _normalize_agent_reply_template(source_record.get("agent_reply_template"))
        if not source_meta_error and isinstance(source_meta, dict) and source_meta.get("template_ref"):
            meta = source_meta
            mode = "source_template"

    if not mode:
        meta = _infer_agent_reply_template_from_publish_params(resolved)
        mode = "generic_fallback" if meta.get("template_ref") == "generic_live_page_delivery_v1" else "publish_metadata"

    if mode:
        resolved["agent_reply_template"] = meta

    explicit_page_context = "page_context" in resolved
    page_context, page_context_error = _normalize_page_context(resolved.get("page_context"))
    if page_context_error:
        return resolved, {"mode": mode or "invalid", "source_template_id": source_template_id}, page_context_error
    page_context_mode = "explicit" if page_context else ("explicit_clear" if explicit_page_context else "")
    if not explicit_page_context:
        page_context = _infer_page_context_from_publish_params(
            resolved,
            html=html,
            template_ref=meta.get("template_ref") if isinstance(meta, dict) else None,
        )
        if page_context:
            resolved["page_context"] = page_context
            page_context_mode = "regenerated"
    elif page_context:
        resolved["page_context"] = page_context

    if (
        isinstance(meta, dict)
        and meta.get("version") == "reply_template_v2"
        and meta.get("reply_scope") == "hybrid"
        and not page_context
    ):
        return resolved, {
            "mode": mode,
            "source_template_id": source_template_id,
            "page_context_mode": page_context_mode or "missing",
        }, {
            "code": 1,
            "message": "reply_template_v2 的 hybrid 正式发布必须提供当前活页重新生成的 page_context",
        }

    if required and not mode:
        error = {
            "code": 1,
            "message": "publish_final 要求 Agent 回复模板，但未能从参数、来源模板或页面 metadata 解析到模板",
            "source_template_id": source_template_id,
        }
        if isinstance(source_result, dict) and source_result.get("code") != 0:
            error["source_template"] = source_result
        return resolved, {"mode": "missing", "source_template_id": source_template_id}, error

    return resolved, {
        "mode": mode or "none",
        "source_template_id": source_template_id,
        "source_public_url": _record_url(source_record),
        "source_sha256": source_record.get("sha256") or "",
        "source_package_ids": source_record.get("package_ids") or [],
        "source_grant_ids": source_record.get("grant_ids") or [],
        "page_context_mode": page_context_mode or "none",
        "source_page_context_inherited": False,
    }, None


def _reply_template_path(template_ref):
    if not template_ref or not isinstance(template_ref, str):
        return ""
    if not _REPLY_TEMPLATE_ID_RE.match(template_ref):
        return ""
    return os.path.join(C.SKILL_ROOT, "reply-templates", template_ref + ".md")


def _agent_reply_template_contract(record, *, operation=None):
    if not isinstance(record, dict):
        return None
    meta, meta_error = _normalize_agent_reply_template(record.get("agent_reply_template"), require_local_file=False)
    if meta_error:
        return None
    meta = meta if isinstance(meta, dict) else {}
    template_ref = meta.get("template_ref") or ""
    template_file = _reply_template_path(template_ref)
    template_exists = bool(template_file and os.path.isfile(template_file))
    public_url = record.get("url") or record.get("public_url") or record.get("download_url") or ""
    page_context, _ = _normalize_page_context(record.get("page_context"))
    contract = {
        "terminal": True,
        "operation": operation or record.get("operation") or "",
        "page_id": record.get("page_id") or "",
        "required": bool(template_ref),
        "page_context": page_context,
        "public_url": _delivery_public_url(public_url),
        "require_page_id_in_reply": template_ref == "preserve_html_qbs_live_delivery_v1",
    }
    _apply_delivery_policy(contract)
    if template_ref:
        reply_render_policy = RTR.get_reply_render_policy(template_ref)
        contract.update({
            "template_ref": template_ref,
            "template_file": template_file,
            "template_exists": template_exists,
            "reply_scope": meta.get("reply_scope") or "full_answer",
            "output_format": meta.get("output_format") or "markdown",
            "hybrid_composition": meta.get("hybrid_composition"),
            "reply_render_policy": reply_render_policy,
            "final_response_required": "read_template_file_and_reply_in_template_format_plus_links",
            "final_response_steps": [
            "Read template_file before writing the final answer.",
            "Use that Markdown template as the final answer shape; do not replace it with a generic publish summary.",
            "Use page_context to understand what this page does; for hybrid replies also follow hybrid_composition.",
            "When reply_data_evidence_file is present, read that hash-bound evidence before drafting.",
            "Include public_url.",
            "When require_page_id_in_reply=true, include the exact page_id in the final reply.",
            "Use reply_data_availability to identify fields that actually exist in this delivery; every available template field must be rendered.",
            "For single_stock_deep_dive_v1 keep every required section heading from reply_render_policy; a section with no evidence must use its standard no-data sentence.",
            "When delivery_policy.max_markdown_tables is present, keep the complete reply within that Markdown table limit and render overflow structures as lists or inline text.",
            "Delete structurally unavailable rows and all-missing columns, but do not delete required section headings.",
            "Use -- only for an occasional missing value inside an otherwise valid structure.",
            "Never substitute turnover for capital flow or otherwise replace a missing metric with a different definition.",
            "Do not expose local file paths, api_key, signatures, or internal verification logs to the user.",
            "After validator returns valid=true, send its validated_markdown verbatim without compression or rewriting.",
            ],
        })
    return contract


def _agent_reply_template_hint(record, *, resource_role):
    if not isinstance(record, dict):
        return None
    meta, meta_error = _normalize_agent_reply_template(record.get("agent_reply_template"), require_local_file=False)
    hint = {
        "terminal": False,
        "resource_role": resource_role,
        "page_context": _normalize_page_context(record.get("page_context"))[0],
    }
    _apply_delivery_policy(hint)
    if not meta_error and isinstance(meta, dict) and meta.get("template_ref"):
        hint.update({
            "template_ref": meta.get("template_ref"),
            "reply_scope": meta.get("reply_scope") or "full_answer",
            "output_format": meta.get("output_format") or "markdown",
            "hybrid_composition": meta.get("hybrid_composition"),
        })
    if resource_role == "source_template":
        hint["source_template_id"] = (
            record.get("source_template_id")
            or record.get("template_id")
            or record.get("page_id")
            or ""
        )
    return hint


def _attach_agent_reply_hint(record, *, resource_role):
    if not isinstance(record, dict):
        return record
    hint = _agent_reply_template_hint(record, resource_role=resource_role)
    if hint:
        record["agent_reply_hint"] = hint
    record.pop("agent_reply_contract", None)
    record.pop("agent_reply_template_file", None)
    return record


def _attach_agent_reply_contract(record, *, operation=None):
    if not isinstance(record, dict):
        return record
    contract = _agent_reply_template_contract(record, operation=operation)
    if not contract:
        return record
    record["agent_reply_contract"] = contract
    if contract.get("required"):
        record["agent_reply_template_file"] = contract.get("template_file") or ""
    else:
        record.pop("agent_reply_template_file", None)
    if contract.get("required") and not contract.get("template_exists"):
        _append_warning(record, {
            "type": "agent_reply_template_missing",
            "message": "agent_reply_template 指向的本地回复模板文件不存在，最终回复无法按模板生成",
            "template_ref": contract.get("template_ref"),
            "template_file": contract.get("template_file"),
        })
    return record


def _attach_reply_data_contract(record, params):
    if not isinstance(record, dict) or not isinstance(params, dict):
        return record
    contract = record.get("agent_reply_contract")
    if not isinstance(contract, dict):
        return record
    for key in ("reply_data_evidence_file", "reply_data_evidence_sha256", "reply_data_availability"):
        if params.get(key) not in (None, ""):
            contract[key] = params[key]
            record[key] = params[key]
    return record


def _validate_agent_reply_template_param(params):
    if "agent_reply_template" not in params:
        return None
    _, error = _normalize_agent_reply_template(params.get("agent_reply_template"))
    return error


def _validate_page_context_param(params):
    if "page_context" not in params:
        return None
    _, error = _normalize_page_context(params.get("page_context"))
    return error


def _validate_reply_metadata_pair(params):
    template_error = _validate_agent_reply_template_param(params)
    if template_error:
        return template_error
    context_error = _validate_page_context_param(params)
    if context_error:
        return context_error
    if "reply_contract_binding" in params:
        _, binding_error = _normalize_reply_contract_binding(params.get("reply_contract_binding"))
        if binding_error:
            return binding_error
    template, _ = _normalize_agent_reply_template(params.get("agent_reply_template"))
    context, _ = _normalize_page_context(params.get("page_context"))
    if (
        template
        and template.get("version") == "reply_template_v2"
        and template.get("reply_scope") == "hybrid"
        and "page_context" in params
        and not context
    ):
        return {"code": 1, "message": "reply_template_v2 的 hybrid 必须同时提供非空 page_context"}
    return None


def _normalize_cover_response(out, *, reply_mode="none", resource_role="existing_page"):
    if not isinstance(out, dict):
        return out

    def attach_reply(record):
        if reply_mode == "terminal":
            _attach_agent_reply_contract(record)
        elif reply_mode == "hint":
            _attach_agent_reply_hint(record, resource_role=resource_role)

    attach_reply(out)
    data = out.get("data")
    if isinstance(data, dict):
        attach_reply(data)
        items = data.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    attach_reply(item)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                attach_reply(item)
    return out


def _template_record(out):
    if not isinstance(out, dict):
        return {}
    data = out.get("data")
    if isinstance(data, dict):
        for key in ("template", "item", "page"):
            if isinstance(data.get(key), dict):
                return data[key]
        return data
    return out

_SHELL_THEME_VARS = {
    "--qb-shell-bg",
    "--qb-shell-chrome-bg",
    "--qb-shell-header-bg",
    "--qb-shell-footer-bg",
    "--qb-shell-surface",
    "--qb-shell-panel",
    "--qb-shell-panel-2",
    "--qb-shell-line",
    "--qb-shell-ink",
    "--qb-shell-muted",
    "--qb-shell-dim",
    "--qb-shell-accent",
    "--qb-shell-accent-strong",
    "--qb-shell-green",
}


def _sub_count(pattern, repl, html, flags=re.S, count=0):
    html2, replaced = re.subn(pattern, repl, html, count=count, flags=flags)
    return html2, replaced


def _inject_before(pattern, insertion, html, flags=0):
    if insertion in html:
        return html, 0
    html2, count = re.subn(pattern, lambda m: insertion + "\n" + m.group(0), html, count=1, flags=flags)
    return html2, count


def _inject_after_body(insertion, html):
    if insertion in html:
        return html, 0
    html2, count = re.subn(
        r"<body\b[^>]*>",
        lambda m: m.group(0) + "\n" + insertion,
        html,
        count=1,
        flags=re.I,
    )
    return html2, count


def _hero_spacing_style():
    return """<style id="qb-retrofit-preserve-hero">
.share-card.qb-retrofit-qr-placeholder{visibility:hidden;min-height:171px;pointer-events:none}
</style>"""


def _script_inline(text):
    return "<script>\n" + text.strip() + "\n</script>"


def _shared_poster_js():
    return CB._read(os.path.join(CB.SHARED_DIR, "poster.js"))


def _shared_shell_js():
    return "\n".join([
        CB._read(os.path.join(CB.SHARED_DIR, "poster.js")).strip(),
        CB._read(os.path.join(CB.SHARED_DIR, "shell.js")).strip(),
    ])


def _current_share_shell_fragments():
    shell = CB._read(os.path.join(CB.SHARED_DIR, "shell.html"))
    return {
        "CSS": CB._style_inline(os.path.join(CB.SHARED_DIR, "shell.css"), "CSS"),
        "HEADER": CB._section(shell, "HEADER"),
        "RESEARCH_WAREHOUSE": CB._section(shell, "RESEARCH_WAREHOUSE"),
        "FOOTER": CB._section(shell, "FOOTER"),
        "MODAL": CB._section(shell, "MODAL"),
        "JS": CB._marked("JS", _script_inline(_shared_shell_js())),
    }


def _share_shell_artifact_hash_or_empty(html):
    try:
        return SSC.share_shell_artifact_hash(html)
    except ValueError:
        return ""


def _refresh_share_shell_markers(html):
    fragments = _current_share_shell_fragments()
    for name in _SHARE_SHELL_MARKERS:
        start = f"<!-- QB_SHELL_{name}_START -->"
        end = f"<!-- QB_SHELL_{name}_END -->"
        start_count = html.count(start)
        end_count = html.count(end)
        if start_count != 1 or end_count != 1:
            raise ValueError(
                "share shell 显式刷新失败："
                f"{name} marker 必须各命中 1 次，实际 start={start_count}, end={end_count}"
            )
        pattern = re.escape(start) + r"[\s\S]*?" + re.escape(end)
        html, count = re.subn(pattern, lambda _m, value=fragments[name]: value, html, count=1)
        if count != 1:
            raise ValueError(f"share shell 显式刷新失败：无法替换 {name} marker 区块")
    return html, [f"refreshed_shell_{name.lower()}" for name in _SHARE_SHELL_MARKERS]


def _share_runtime_is_current(html):
    return (
        "QB_SHARE_POSTER_VERSION" in html and _SHARE_POSTER_VERSION in html
        and "QB_SHARE_SHELL_VERSION" in html and _SHARE_SHELL_VERSION in html
        and "QB_SHARE_SHELL_REVISION" in html and f"REVISION = {_SHARE_SHELL_REVISION}" in html
    )


def _upgrade_share_poster_runtime(html):
    if _share_runtime_is_current(html):
        return html, 0, ""
    if "window.QBSharePoster" not in html and "window.QBShareShell" not in html:
        return html, 0, ""

    shared_js = _script_inline(_shared_shell_js())
    combined_re = (
        r"<script>\s*\(function\(\)\{.*?"
        r"window\.QBSharePoster\s*=.*?"
        r"window\.QBShareShell\s*=.*?"
        r"</script>"
    )
    html2, count = re.subn(combined_re, lambda _m: shared_js, html, count=1, flags=re.S)
    if count:
        return html2, count, "upgraded_share_runtime"

    poster_only = _script_inline(_shared_poster_js())
    html2, count = _inject_before(r"</body>", poster_only, html, flags=re.I)
    if count:
        return html2, count, "upgraded_share_poster"
    raise ValueError("公共页头页尾检查失败：无法升级分享海报运行时，HTML 缺少 </body>")


def _css_value(value):
    value = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3,8}", value):
        return value
    if re.fullmatch(r"rgba?\([0-9.,% ]+\)", value):
        return value
    if re.fullmatch(r"var\(--[a-zA-Z0-9_-]+\)", value):
        return value
    return ""


def _shell_theme_from_params(params):
    theme = params.get("theme") if isinstance(params.get("theme"), dict) else {}
    if not theme:
        return {}
    values = {}
    mapping = {
        "chrome_bg": "--qb-shell-chrome-bg",
        "bg": "--qb-shell-chrome-bg",
        "header_bg": "--qb-shell-header-bg",
        "footer_bg": "--qb-shell-footer-bg",
        "accent": "--qb-shell-accent",
        "accent_strong": "--qb-shell-accent-strong",
        "line": "--qb-shell-line",
        "ink": "--qb-shell-ink",
        "muted": "--qb-shell-muted",
    }
    for key, var_name in mapping.items():
        value = _css_value(theme.get(key))
        if value:
            values[var_name] = value
    return values


def _extract_existing_shell_theme(html):
    values = {}
    for name, value in re.findall(r"(--qb-shell-[a-z0-9-]+)\s*:\s*([^;{}]+)", html, flags=re.I):
        name = name.lower()
        if name in _SHELL_THEME_VARS:
            clean = _css_value(value)
            if clean:
                values[name] = clean
    return values


def _shell_theme_style(values):
    if not values:
        return ""
    lines = [f"  {name}: {values[name]};" for name in sorted(values)]
    return "<style id=\"qb-shell-theme\">\n:root {\n" + "\n".join(lines) + "\n}\n</style>"


def _install_shell_theme(html, params):
    if "id=\"qb-shell-theme\"" in html or "id='qb-shell-theme'" in html:
        return html, 0, ""
    explicit = _shell_theme_from_params(params)
    values = explicit or _extract_existing_shell_theme(html)
    style = _shell_theme_style(values)
    if not style:
        return html, 0, ""
    source = "inserted_shell_theme" if explicit else "preserved_shell_theme"
    token = "<!-- QB_SHARED_SHELL_CSS -->"
    if token in html:
        return html.replace(token, token + "\n" + style, 1), 1, source
    html, count = _inject_before(r"</head>", style, html, flags=re.I)
    return html, count, source


def _shell_bootstrap_script():
    return r"""<script id="qb-static-shell-guard">
(function(){
  if (window.__QB_STATIC_SHELL_GUARD__) return;
  window.__QB_STATIC_SHELL_GUARD__ = true;
  function text(v){ return String(v == null ? '' : v); }
  function summary(){
    if (window.BOOT && Array.isArray(BOOT.panels)) {
      var p = BOOT.panels.find(function(x){ return String(x.type || '').toLowerCase() === 'text'; });
      if (p && (p.text || p.content || p.description)) return text(p.text || p.content || p.description);
    }
    var hero = document.querySelector('header.share-shell h1, h1');
    return hero ? hero.innerText : (document.title || 'QuantBuddy 页面');
  }
  function posterData(){
    return {
      headline: document.title || 'QuantBuddy 页面',
      summary: summary(),
      metrics: [],
      sections: [],
      asof: (window.BOOT && BOOT.generatedAt) || ''
    };
  }
  async function refresh(){
    if (window.BOOT && BOOT.mode === 'live' && typeof window.fetchLive === 'function') return window.fetchLive();
    if (window.BOOT && typeof window.renderAll === 'function') return window.renderAll(BOOT.outputs || {});
  }
  document.addEventListener('DOMContentLoaded', function(){
    if (!window.QBShareShell || window.__QB_STATIC_SHELL_INIT__) return;
    window.__QB_STATIC_SHELL_INIT__ = true;
    QBShareShell.init({
      templateName: document.title || 'QuantBuddy 页面',
      title: function(){ return document.title || 'QuantBuddy 页面'; },
      subtitle: summary,
      asof: function(){ return (window.BOOT && BOOT.generatedAt) || ''; },
      onRefresh: refresh,
      getPosterData: posterData
    });
  });
})();
</script>"""


def _read_html(params):
    """从 html 或 html_file 取出 HTML 文本，返回 (html, err)。"""
    html = params.get("html")
    if not html and params.get("html_file"):
        path = params["html_file"]
        if not os.path.isabs(path):
            path = os.path.join(C.SKILL_ROOT, path)
        if not os.path.exists(path):
            return None, {"code": 1, "message": f"html_file 不存在: {path}"}
        with open(path, "r", encoding="utf-8-sig") as f:
            html = f.read()
    if not html:
        return None, {"code": 1, "message": "upload 需要 html 或 html_file 之一"}
    return html, None


def _result_message(out):
    if not isinstance(out, dict):
        return str(out)
    if out.get("message"):
        return str(out.get("message"))
    err = out.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or err)
    if err:
        return str(err)
    return json.dumps(out, ensure_ascii=False)[:500]


def _append_warning(out, warning):
    warnings = out.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    warnings.append(warning)
    out["warnings"] = warnings


def _has_shared_header(html):
    return bool(re.search(r"<header\b[^>]*\bdata-qb-share-shell(?:\s|=|>)", html, flags=re.I))


def _has_shared_footer(html):
    return bool(re.search(r"<footer\b[^>]*\bdata-qb-share-shell-footer(?:\s|=|>)", html, flags=re.I))


def _has_shared_shell_css(html):
    return bool(re.search(r"\.qb-head\s*\{", html) and re.search(r"\.qb-footer\s*\{", html))


def _has_shared_modal(html):
    return bool(re.search(r"id=[\"']sharePosterModal[\"']", html, flags=re.I))


def _has_research_warehouse_modal(html):
    return bool(re.search(r"id=[\"']researchWarehouseModal[\"']", html, flags=re.I))


def _ensure_share_shell(html, params):
    """Preflight static-page HTML so published pages always carry the public shell."""
    if str(params.get("transformation_mode") or "").strip() == _PRESERVE_HTML_QBS_LIVE_MODE:
        return html, {"checked": False, "skipped": True, "reason": "preserve_html_qbs_live"}
    if params.get("ensure_share_shell") is False:
        return html, {"checked": False, "skipped": True}

    actions = []
    refresh_share_shell = params.get("refresh_share_shell") is True
    had_shared_shell = (
        _has_shared_header(html)
        or "window.QBShareShell" in html
        or "<!-- QB_SHARED_SHELL_HEADER -->" in html
    )
    if refresh_share_shell:
        html, refresh_actions = _refresh_share_shell_markers(html)
        actions.extend(refresh_actions)

    html, n = _replace_old_body_qr(html, collapse=bool(params.get("collapse_qr_space")))
    if n:
        actions.append(f"cleaned_body_qr:{n}")

    html, n = _sub_count(
        r"<footer\b[^>]*class=[\"'][^\"']*\bsite-footer\b[^\"']*[\"'][^>]*>.*?</footer>",
        "",
        html,
        count=1,
    )
    if n:
        actions.append("removed_legacy_footer")

    html, n = _sub_count(
        r"\s*<script\b[^>]*src=[\"'][^\"']*(?:qrcode|QRCode)[^\"']*[\"'][^>]*>\s*</script>",
        "",
        html,
        flags=re.I,
    )
    if n:
        actions.append(f"removed_qrcode_script:{n}")

    html, n = _sub_count(
        r"\s*<div\b(?=[^>]*(?:id=[\"']qr[\"']|class=[\"'][^\"']*\bqr\b[^\"']*[\"']))[^>]*>[\s\S]*?手机扫码查看[\s\S]*?</div>",
        "",
        html,
        count=1,
    )
    if n:
        actions.append("removed_legacy_qr_div")

    html, n = _sub_count(
        r"\nfunction setupShareShell\(\) \{.*?\n\}\n\n(?=document\.addEventListener\('DOMContentLoaded')",
        "\n",
        html,
        count=1,
    )
    if n:
        actions.append("removed_legacy_setup")

    html, n = _sub_count(r"\s*setupShareShell\(\);\s*", "\n", html, flags=re.I)
    if n:
        actions.append(f"removed_legacy_setup_call:{n}")

    if not _has_shared_shell_css(html) and "<!-- QB_SHARED_SHELL_CSS -->" not in html:
        html, n = _inject_before(r"</head>", "<!-- QB_SHARED_SHELL_CSS -->", html, flags=re.I)
        if not n:
            raise ValueError("公共页头页尾检查失败：HTML 缺少 </head>，无法插入 share shell CSS")
        actions.append("inserted_shell_css")

    html, n, theme_action = _install_shell_theme(html, params)
    if n:
        actions.append(theme_action)

    if not _has_shared_header(html) and "<!-- QB_SHARED_SHELL_HEADER -->" not in html:
        html, n = _inject_after_body("<!-- QB_SHARED_SHELL_HEADER -->", html)
        if not n:
            raise ValueError("公共页头页尾检查失败：HTML 缺少 <body>，无法插入公共页头")
        actions.append("inserted_shell_header")

    if not _has_shared_footer(html) and "<!-- QB_SHARED_SHELL_FOOTER -->" not in html:
        html, n = _inject_before(r"</body>", "<!-- QB_SHARED_SHELL_FOOTER -->", html, flags=re.I)
        if not n:
            raise ValueError("公共页头页尾检查失败：HTML 缺少 </body>，无法插入公共页尾")
        actions.append("inserted_shell_footer")

    if not _has_shared_modal(html) and "<!-- QB_SHARED_SHELL_MODAL -->" not in html:
        html, n = _inject_before(r"</body>", "<!-- QB_SHARED_SHELL_MODAL -->", html, flags=re.I)
        if not n:
            raise ValueError("公共页头页尾检查失败：HTML 缺少 </body>，无法插入分享弹层")
        actions.append("inserted_shell_modal")

    if (
        not had_shared_shell
        and not _has_research_warehouse_modal(html)
        and "<!-- QB_SHARED_SHELL_RESEARCH_WAREHOUSE -->" not in html
    ):
        html, n = _inject_before(
            r"<!-- QB_SHARED_SHELL_MODAL -->|</body>",
            "<!-- QB_SHARED_SHELL_RESEARCH_WAREHOUSE -->",
            html,
            flags=re.I,
        )
        if not n:
            raise ValueError("公共页头页尾检查失败：HTML 缺少 </body>，无法插入投研仓弹层")
        actions.append("inserted_research_warehouse_modal")

    if "QRMini" not in html and "<!-- QB_SHARED_QR_MINI -->" not in html:
        html, n = _inject_before(r"</body>", "<!-- QB_SHARED_QR_MINI -->", html, flags=re.I)
        if not n:
            raise ValueError("公共页头页尾检查失败：HTML 缺少 </body>，无法插入 QR 运行时")
        actions.append("inserted_qr_runtime")

    if "window.QBShareShell" not in html and "<!-- QB_SHARED_SHELL_JS -->" not in html:
        html, n = _inject_before(r"</body>", "<!-- QB_SHARED_SHELL_JS -->", html, flags=re.I)
        if not n:
            raise ValueError("公共页头页尾检查失败：HTML 缺少 </body>，无法插入 share shell JS")
        actions.append("inserted_shell_js")

    if "QBShareShell.init" not in html and "qb-static-shell-guard" not in html:
        html, n = _inject_before(r"</body>", _shell_bootstrap_script(), html, flags=re.I)
        if not n:
            raise ValueError("公共页头页尾检查失败：HTML 缺少 </body>，无法插入公共 shell 初始化脚本")
        actions.append("inserted_shell_bootstrap")

    if refresh_share_shell or not had_shared_shell:
        html, n, runtime_action = _upgrade_share_poster_runtime(html)
        if n:
            actions.append(runtime_action)

    html = CB._compile(html, {"inline_qr_mini": True, "inline_data_kernel": True})
    try:
        before_kernel_refresh = html
        html, matched_by = DKR.retrofit_if_present(html)
        if matched_by and html != before_kernel_refresh:
            actions.append(f"refreshed_data_kernel:{matched_by}")
    except DKR.RetrofitError as exc:
        raise ValueError(f"数据内核刷新失败：{exc}") from exc
    problems = []
    if not _has_shared_header(html):
        problems.append("缺少公共页头 data-qb-share-shell")
    if not _has_shared_footer(html):
        problems.append("缺少公共页尾 data-qb-share-shell-footer")
    for token in ("手机扫码查看", "shareQrCanvas", "setupShareShell", "<footer class=\"site-footer\""):
        if token in html:
            problems.append(f"旧页面残留: {token}")
    if "QB_SHARED_" in html or "__QB_LOGO_SRC__" in html:
        problems.append("公共组件占位符未编译")
    if problems:
        raise ValueError("公共页头页尾检查失败：" + "；".join(problems))
    return html, {
        "checked": True,
        "actions": actions,
        "header": True,
        "footer": True,
        "refreshed": refresh_share_shell,
        "version": _SHARE_SHELL_VERSION if refresh_share_shell or not had_shared_shell else None,
        "revision": _SHARE_SHELL_REVISION if refresh_share_shell or not had_shared_shell else None,
        "artifact_hash": _share_shell_artifact_hash_or_empty(html),
    }


def _replace_old_body_qr(html, collapse=False):
    share_card_repl = ""
    if not collapse:
        share_card_repl = '<aside class="share-card qb-retrofit-qr-placeholder" aria-hidden="true"></aside>'

    def is_legacy_qr_card(chunk):
        return bool(re.search(
            r"shareQrCanvas|手机扫码查看|\bqr-frame\b|\bqr-fallback\b|qrcode",
            chunk,
            flags=re.I,
        ))

    replaced = 0

    def replace_share_card(match):
        nonlocal replaced
        chunk = match.group(0)
        if replaced or not is_legacy_qr_card(chunk):
            return chunk
        replaced = 1
        return share_card_repl

    html = re.sub(
        r"\s*<aside\b[^>]*class=[\"'][^\"']*\bshare-card\b[^\"']*[\"'][^>]*>.*?</aside>",
        replace_share_card,
        html,
        flags=re.S | re.I,
    )
    count = replaced
    if count and share_card_repl:
        html, _ = _inject_before(r"</head>", _hero_spacing_style(), html, flags=re.I)
    html, extra = _sub_count(
        r"\s*<[^>]+id=[\"']shareQrCanvas[\"'][^>]*>.*?</[^>]+>",
        "",
        html,
        flags=re.S | re.I,
        count=1,
    )
    return html, count + extra


def _server_mentions_package_issue(out):
    if not isinstance(out, dict):
        return False
    try:
        text = json.dumps(out, ensure_ascii=False)
    except Exception:
        text = str(out)
    return bool(_PACKAGE_ISSUE_RE.search(text))


def _iter_braced_blocks(text):
    """Yield balanced brace blocks while ignoring braces inside JS strings/comments."""
    text = text or ""
    stack = []
    quote = None
    escaped = False
    line_comment = False
    block_comment = False
    i = 0
    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if char == "*" and nxt == "/":
                block_comment = False
                i += 2
            else:
                i += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            i += 1
            continue
        if char in ("'", '"', "`"):
            quote = char
        elif char == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue
        elif char == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue
        elif char == "{":
            stack.append(i)
        elif char == "}" and stack:
            start = stack.pop()
            yield text[start:i + 1]
        i += 1


def _extract_package_credentials(html):
    return [
        {"package_id": item["credential_id"], "signature": item["signature"]}
        for item in FRC.discover_credential_pairs(html, reject_ambiguous=False)
        if item.get("kind") == "package"
    ]


def _extract_grant_credentials(html):
    return [
        {"grant_id": item["credential_id"], "signature": item["signature"]}
        for item in FRC.discover_credential_pairs(html, reject_ambiguous=False)
        if item.get("kind") == "grant"
    ]


def _signature_hashes(html):
    return sorted({
        hashlib.sha256(item["signature"].encode("utf-8")).hexdigest()
        for item in FRC.discover_credential_pairs(html, reject_ambiguous=False)
        if item.get("signature")
    })

def _replace_fork_metadata(value, replacements):
    """Apply the same asset substitutions used by fork HTML to publish metadata."""
    if isinstance(value, str):
        updated = value
        for source_value, target_value in sorted(
            (replacements or {}).items(), key=lambda item: len(str(item[0])), reverse=True
        ):
            source_text = str(source_value or "")
            if source_text:
                updated = updated.replace(source_text, str(target_value or ""))
        return updated
    if isinstance(value, list):
        return [_replace_fork_metadata(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_fork_metadata(item, replacements) for key, item in value.items()}
    return value


def _fork_metadata_residual_tokens(metadata, source_identity):
    serialized = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
    tokens = [source_identity.get("name")] + list(source_identity.get("present_code_variants") or [])
    return [str(token) for token in tokens if token and str(token) in serialized]


def _unique_strings(values):
    if values is None:
        return []
    if isinstance(values, str):
        values = [item.strip() for item in values.split(",")]
    elif not isinstance(values, (list, tuple, set)):
        values = [values]
    out = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _html_text(html):
    text = re.sub(r"(?is)<script\b[^>]*>.*?</script>", " ", html or "")
    text = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def _html_headings(html, *, levels=(1, 2, 3)):
    headings = []
    seen = set()
    level_pattern = "|".join(str(int(level)) for level in levels)
    pattern = rf"(?is)<h(?:{level_pattern})\b[^>]*>(.*?)</h(?:{level_pattern})>"
    for match in re.finditer(pattern, html or ""):
        text = _html_text(match.group(1))
        if text and text not in seen:
            seen.add(text)
            headings.append(text)
    return headings


def _template_required_outputs(record):
    outputs = list(_unique_strings(record.get("card_required_outputs") or []))
    for package in record.get("packages") or []:
        if not isinstance(package, dict):
            continue
        for read in package.get("reads") or []:
            if isinstance(read, dict):
                output = str(read.get("output") or "").strip()
                if output and output not in outputs:
                    outputs.append(output)
        for formula in package.get("formulas") or []:
            if not isinstance(formula, str) or "=" not in formula:
                continue
            output = formula.split("=", 1)[0].strip().strip('"\'')
            if output and re.match(r"^[^()\s+\-*/]+$", output) and output not in outputs:
                outputs.append(output)
    return outputs


# 公式里"引用具体标的"的常见函数：函数名(资产名/资产代码) 这种调用形态。
# getStaticPage/getTemplate 都会带回 formulas 原文（公式非隐私），fork 时不必再凭输出变量名反推——
# 但公式里可能混着"同业/行业对比"这类引用了别的资产的公式，不能被当成主资产公式直接照抄替换。
_ASSET_ARG_FORMULA_RE = re.compile(
    r"(?:取出|收盘价|开盘价|最高价|最低价|涨跌幅|成交额|成交量|换手率|总市值|流通市值)\(\s*([^()]{1,40}?)\s*\)"
)


def _template_formula_contract(record, primary_markers=None):
    """把模板 packages[].formulas 原样整理出来，供 fork 时参考改写（而不是凭输出名反推）。
    同时标出每条公式里引用了非主资产的标的（同业/行业对比一类），提醒 Agent 不能直接照抄。"""
    markers = {str(m).strip() for m in (primary_markers or []) if str(m).strip()}
    packages = []
    for package in record.get("packages") or []:
        if not isinstance(package, dict):
            continue
        package_id = str(package.get("package_id") or "").strip()
        if not package_id:
            continue
        formulas = [f for f in (package.get("formulas") or []) if isinstance(f, str) and f.strip()]
        other_asset_formulas = []
        for formula in formulas:
            refs = _unique_strings([
                arg.strip().strip('"\'')
                for arg in _ASSET_ARG_FORMULA_RE.findall(formula)
                if arg.strip().strip('"\'') and arg.strip().strip('"\'') not in markers
            ])
            if refs:
                other_asset_formulas.append({"formula": formula, "asset_refs": refs})
        packages.append({
            "package_id": package_id,
            "found": bool(package.get("found", True)),
            "status": package.get("status"),
            "formulas": formulas,
            "outputs": _unique_strings([
                f.split("=", 1)[0].strip().strip('"\'')
                for f in formulas if "=" in f
            ]),
            "other_asset_formulas": other_asset_formulas,
        })
    return packages


def _template_grant_contract(record):
    """把模板 grants[] 整理为 fork 可直接继承的数据授权合同。"""
    grants = []
    for grant in record.get("grants") or []:
        if not isinstance(grant, dict):
            continue
        grant_id = str(grant.get("grant_id") or "").strip()
        if not grant_id:
            continue
        grants.append({
            "source_grant_id": grant_id,
            "found": bool(grant.get("found", True)),
            "status": grant.get("status"),
            "kind": grant.get("kind"),
            "payload": grant.get("payload") if isinstance(grant.get("payload"), dict) else None,
        })
    return grants


def _command_string(argv):
    values = [str(value) for value in argv]
    return subprocess.list2cmdline(values) if os.name == "nt" else shlex.join(values)


def _fork_path(value, *, base=None):
    path = str(value or "").strip()
    if not path:
        return ""
    if os.path.isabs(path):
        return os.path.abspath(path)
    return os.path.abspath(os.path.join(base or C.SKILL_ROOT, path))


def _fork_task_id(params):
    params = params if isinstance(params, dict) else {}
    context = C.current_trace_context()
    return str(params.get("task_id") or context.get("task_id") or "").strip()


def _fork_binding_root(task_id=None):
    override = str(os.environ.get("QBV_FORK_BINDING_DIR") or "").strip()
    if override:
        return os.path.abspath(override)
    if str(task_id or "").strip():
        return str(C.task_temp_dir(task_id, create=True))
    return os.path.join(C.SKILL_ROOT, "output", "fork_task_bindings")


def _fork_binding_path(task_id):
    root = _fork_binding_root(task_id)
    if not os.environ.get("QBV_FORK_BINDING_DIR") and str(task_id or "").strip():
        return os.path.join(root, "fork-task-binding.json")
    digest = hashlib.sha256(str(task_id or "").encode("utf-8")).hexdigest()
    return os.path.join(root, digest + ".json")


def _write_fork_task_binding(binding):
    task_id = str((binding or {}).get("task_id") or "").strip()
    if not task_id:
        return None, {"code": 1, "message": "fork task binding 缺少 task_id"}
    root = _fork_binding_root(task_id)
    path = _fork_binding_path(task_id)
    os.makedirs(root, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".fork-binding-", suffix=".json", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(binding, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    except Exception as exc:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        return None, {"code": 1, "message": f"写入 fork task binding 失败: {exc}"}
    return path, None


def _read_fork_task_binding(task_id):
    task_id = str(task_id or "").strip()
    if not task_id:
        return None, "", None
    path = _fork_binding_path(task_id)
    if not os.path.isfile(path):
        return None, path, None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            binding = json.load(handle)
    except Exception as exc:
        return None, path, {"code": 1, "message": f"读取 fork task binding 失败: {exc}"}
    if not isinstance(binding, dict) or binding.get("version") != _FORK_TASK_BINDING_VERSION:
        return None, path, {"code": 1, "message": "fork task binding 版本无效"}
    if str(binding.get("task_id") or "") != task_id:
        return None, path, {"code": 1, "message": "fork task binding 的 task_id 不一致"}
    return binding, path, None


def _bind_fork_task(params, manifest, manifest_file):
    task_id = _fork_task_id(params)
    if not task_id:
        return {
            "mode": "not_bound",
            "reason": "task_id_missing",
            "instruction": "正式 fork 流程必须传 task_id，才能让 publish_final 自动恢复来源门禁",
        }, None
    previous, _, read_error = _read_fork_task_binding(task_id)
    if read_error:
        return None, read_error
    binding = {
        "version": _FORK_TASK_BINDING_VERSION,
        "status": "prepared",
        "task_id": task_id,
        "source_template_id": str(manifest.get("source_template_id") or ""),
        "fork_manifest_file": os.path.abspath(manifest_file),
        "source_html_sha256": str(manifest.get("source_html_sha256") or ""),
        "source_url": str(manifest.get("source_url") or ""),
        "target_asset": str(manifest.get("target_asset") or ""),
        "working_html_file": os.path.abspath(str(manifest.get("working_html_file") or "")),
        "revision": int((previous or {}).get("revision") or 0) + 1,
        "bound_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    if previous and previous.get("source_template_id") != binding["source_template_id"]:
        binding["previous_source_template_id"] = previous.get("source_template_id")
    binding_file, write_error = _write_fork_task_binding(binding)
    if write_error:
        return None, write_error
    return {
        "mode": "task_binding",
        "status": binding["status"],
        "task_id": task_id,
        "source_template_id": binding["source_template_id"],
        "binding_file": binding_file,
        "revision": binding["revision"],
        "working_html_file": binding["working_html_file"],
    }, None


def _apply_fork_task_binding(params):
    resolved = dict(params or {})
    task_id = _fork_task_id(resolved)
    binding, binding_file, read_error = _read_fork_task_binding(task_id)
    if read_error:
        return resolved, None, read_error
    if not binding:
        return resolved, {"mode": "none", "task_id": task_id}, None

    bound_source = str(binding.get("source_template_id") or "")
    bound_manifest_file = os.path.abspath(str(binding.get("fork_manifest_file") or ""))
    explicit_source = str(
        resolved.get("source_template_id")
        or resolved.get("source_template_page_id")
        or ""
    )
    if explicit_source and explicit_source != bound_source:
        return resolved, None, {
            "code": 1,
            "error": "FORK_TASK_BINDING_CONFLICT",
            "message": (
                f"task_id={task_id} 已绑定来源 {bound_source}，"
                f"publish_final 不能改为 {explicit_source}"
            ),
        }

    explicit_manifest_file = str(resolved.get("fork_manifest_file") or "").strip()
    if explicit_manifest_file:
        explicit_manifest_file = _fork_path(explicit_manifest_file)
        if explicit_manifest_file != bound_manifest_file:
            return resolved, None, {
                "code": 1,
                "error": "FORK_TASK_BINDING_CONFLICT",
                "message": "publish_final 的 fork_manifest_file 与 task_id 已绑定文件不一致",
            }

    inline_manifest = resolved.get("fork_manifest")
    if inline_manifest is not None:
        try:
            with open(bound_manifest_file, "r", encoding="utf-8") as handle:
                bound_manifest = json.load(handle)
        except Exception as exc:
            return resolved, None, {"code": 1, "message": f"读取 task_id 绑定 manifest 失败: {exc}"}
        if inline_manifest != bound_manifest:
            return resolved, None, {
                "code": 1,
                "error": "FORK_TASK_BINDING_CONFLICT",
                "message": "publish_final 的内联 fork_manifest 与 task_id 已绑定 manifest 不一致",
            }
        resolved.pop("fork_manifest", None)

    resolved["source_template_id"] = bound_source
    resolved["fork_manifest_file"] = bound_manifest_file
    return resolved, {
        "mode": "task_binding",
        "status": binding.get("status") or "prepared",
        "task_id": task_id,
        "source_template_id": bound_source,
        "binding_file": binding_file,
        "fork_manifest_file": bound_manifest_file,
        "source_injected": not bool(explicit_source),
        "manifest_injected": not bool(explicit_manifest_file),
        "revision": binding.get("revision") or 1,
    }, None


def _mark_fork_task_published(binding_resolution, *, page_id, public_url):
    if not isinstance(binding_resolution, dict) or binding_resolution.get("mode") != "task_binding":
        return binding_resolution, None
    task_id = str(binding_resolution.get("task_id") or "")
    binding, _, read_error = _read_fork_task_binding(task_id)
    if read_error or not binding:
        return binding_resolution, read_error or {"code": 1, "message": "fork task binding 发布后丢失"}
    binding["status"] = "published"
    binding["page_id"] = str(page_id or "")
    binding["public_url"] = str(public_url or "")
    binding["published_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    binding_file, write_error = _write_fork_task_binding(binding)
    if write_error:
        return binding_resolution, write_error
    out = dict(binding_resolution)
    out["status"] = "published"
    out["binding_file"] = binding_file
    out["page_id"] = binding["page_id"]
    return out, None


def _load_fork_manifest(params):
    inline = params.get("fork_manifest")
    manifest_file = params.get("fork_manifest_file")
    if isinstance(inline, dict):
        return dict(inline), "", None
    if not manifest_file:
        return None, "", {"code": 1, "message": "带 source_template_id 的 publish_final 必须提供 fork_manifest 或 fork_manifest_file"}
    path = _fork_path(manifest_file)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except Exception as exc:
        return None, path, {"code": 1, "message": f"读取 fork_manifest 失败: {exc}"}
    if not isinstance(manifest, dict):
        return None, path, {"code": 1, "message": "fork_manifest 必须是 JSON 对象"}
    return manifest, path, None


def _validate_fork_manifest(params, template_resolution, final_html):
    source_template_id = str((template_resolution or {}).get("source_template_id") or "")
    if not source_template_id:
        return None, None

    manifest, manifest_file, error = _load_fork_manifest(params)
    if error:
        return None, error
    manifest_version = str(manifest.get("version") or "")
    if manifest_version not in _SUPPORTED_FORK_MANIFEST_VERSIONS:
        supported = "/".join(sorted(_SUPPORTED_FORK_MANIFEST_VERSIONS))
        return None, {"code": 1, "message": f"fork_manifest.version 必须是 {supported}"}
    if str(manifest.get("source_template_id") or "") != source_template_id:
        return None, {"code": 1, "message": "fork_manifest 的 source_template_id 与 publish_final 不一致"}

    source_file = _fork_path(manifest.get("source_html_file"))
    expected_sha = str(manifest.get("source_html_sha256") or "").strip().lower()
    if not source_file or not os.path.isfile(source_file):
        return None, {"code": 1, "message": "fork_manifest 缺少可读取的 source_html_file"}
    try:
        with open(source_file, "r", encoding="utf-8") as handle:
            source_html = handle.read()
    except Exception as exc:
        return None, {"code": 1, "message": f"读取 fork 来源 HTML 失败: {exc}"}
    actual_sha = hashlib.sha256(source_html.encode("utf-8")).hexdigest()
    if not expected_sha or actual_sha != expected_sha:
        return None, {"code": 1, "message": "fork_manifest 的来源 HTML SHA256 校验失败"}
    template_sha = str((template_resolution or {}).get("source_sha256") or "").strip().lower()
    if template_sha and actual_sha != template_sha:
        return None, {"code": 1, "message": "fork 来源 HTML SHA256 与模板 metadata 不一致"}

    source_url = str((template_resolution or {}).get("source_public_url") or "").strip().rstrip("/")
    manifest_url = str(manifest.get("source_url") or "").strip().rstrip("/")
    if source_url and manifest_url and source_url != manifest_url:
        return None, {"code": 1, "message": "fork_manifest 的 source_url 与来源模板不一致"}

    manifest_packages = set(_unique_strings(manifest.get("source_package_ids")))
    manifest_grants = set(_unique_strings(manifest.get("source_grant_ids")))
    manifest_signature_hashes = set(_unique_strings(manifest.get("source_signature_sha256")))
    html_packages = {item["package_id"] for item in _extract_package_credentials(source_html)}
    html_grants = {item["grant_id"] for item in _extract_grant_credentials(source_html)}
    html_signature_hashes = set(_signature_hashes(source_html))
    source_packages = set((template_resolution or {}).get("source_package_ids") or [])
    source_grants = set((template_resolution or {}).get("source_grant_ids") or [])
    if source_packages and not source_packages.issubset(manifest_packages):
        return None, {"code": 1, "message": "fork_manifest 的来源 package_ids 与模板 metadata 不一致"}
    if source_grants and not source_grants.issubset(manifest_grants):
        return None, {"code": 1, "message": "fork_manifest 的来源 grant_ids 与模板 metadata 不一致"}
    if html_packages and not html_packages.issubset(manifest_packages):
        return None, {"code": 1, "message": "fork_manifest 未完整记录来源 HTML 的 package_ids"}
    if html_grants and not html_grants.issubset(manifest_grants):
        return None, {"code": 1, "message": "fork_manifest 未完整记录来源 HTML 的 grant_ids"}
    if html_signature_hashes != manifest_signature_hashes:
        return None, {"code": 1, "message": "fork_manifest 未完整记录来源 HTML 的 signature 指纹"}
    source_managed_images = manifest.get("source_managed_images") or []
    if not isinstance(source_managed_images, list):
        return None, {"code": 1, "message": "fork_manifest.source_managed_images 必须是数组"}
    for index, image in enumerate(source_managed_images):
        if not isinstance(image, dict):
            return None, {"code": 1, "message": f"fork_manifest.source_managed_images[{index}] 必须是对象"}
        image_file = _fork_path(image.get("image_file"))
        expected_image_sha = str(image.get("sha256") or "").lower()
        marker = str(image.get("marker") or "")
        if not image_file or not os.path.isfile(image_file) or not expected_image_sha or not marker:
            return None, {"code": 1, "message": f"fork_manifest.source_managed_images[{index}] 缺少文件/marker/hash"}
        with open(image_file, "rb") as handle:
            actual_image_sha = hashlib.sha256(handle.read()).hexdigest()
        if actual_image_sha != expected_image_sha:
            return None, {"code": 1, "message": f"fork 来源托管图片 SHA256 校验失败: {image.get('source_asset_id') or index}"}
    runtime_roles = manifest.get("runtime_roles") if manifest_version == _FORK_MANIFEST_VERSION else None
    source_package_count = (
        sum(isinstance(role, dict) and role.get("kind") == "package" for role in runtime_roles)
        if isinstance(runtime_roles, list) else len(manifest_packages)
    )
    source_grant_count = (
        sum(isinstance(role, dict) and role.get("kind") == "grant" for role in runtime_roles)
        if isinstance(runtime_roles, list) else len(manifest_grants)
    )
    try:
        minimum_packages = int(manifest.get("minimum_target_package_count", source_package_count) or 0)
        minimum_grants = int(manifest.get("minimum_target_grant_count", source_grant_count) or 0)
    except (TypeError, ValueError):
        return None, {"code": 1, "message": "fork_manifest 的最低 package/grant 数量必须是非负整数"}
    if minimum_packages < 0 or minimum_grants < 0:
        return None, {"code": 1, "message": "fork_manifest 的最低 package/grant 数量必须是非负整数"}
    reduction_reason = str(manifest.get("credential_count_reduction_reason") or "").strip()
    if (
        minimum_packages < source_package_count
        or minimum_grants < source_grant_count
    ) and not reduction_reason:
        return None, {
            "code": 1,
            "message": "fork_manifest 下调最低凭证数量时必须提供 credential_count_reduction_reason",
        }

    leaked_packages = sorted(package_id for package_id in manifest_packages if package_id in (final_html or ""))
    leaked_grants = sorted(grant_id for grant_id in manifest_grants if grant_id in (final_html or ""))
    leaked_signatures = sorted(set(_signature_hashes(final_html)) & manifest_signature_hashes)
    if leaked_packages or leaked_grants or leaked_signatures:
        leaked = leaked_packages + leaked_grants
        if leaked_signatures:
            leaked.append(f"signature({len(leaked_signatures)})")
        return None, {"code": 1, "message": "fork 目标 HTML 仍含来源凭证: " + ", ".join(leaked)}

    visible_text = _html_text(final_html)
    missing_sections = [
        section for section in _unique_strings(manifest.get("required_sections"))
        if section not in visible_text
    ]
    if missing_sections:
        return None, {"code": 1, "message": "fork 目标 HTML 缺少核心栏目: " + ", ".join(missing_sections)}

    required_outputs = _unique_strings(manifest.get("required_outputs"))
    package_output_check = None
    if required_outputs:
        endpoint = C.endpoint_of(C.load_config())
        package_output_check = _required_package_outputs_check(endpoint, final_html, required_outputs)
        if package_output_check.get("status") != "required_outputs_ok":
            missing_outputs = package_output_check.get("missing_outputs") or required_outputs
            return None, {
                "code": 1,
                "error": "FORK_REQUIRED_OUTPUTS_UNAVAILABLE",
                "message": "fork 最终公式包缺少必需输出: " + ", ".join(missing_outputs),
                "package_runtime_check": package_output_check,
            }

    leftover_markers = [
        marker for marker in _unique_strings(manifest.get("source_markers"))
        if marker in (final_html or "")
    ]
    if leftover_markers:
        return None, {"code": 1, "message": "fork 目标 HTML 仍含来源标的文案: " + ", ".join(leftover_markers)}

    if manifest.get("card_runtime_required"):
        required_tokens = ("data-qb-card-template", "data-qb-card-manifest", "data-qb-card-runtime")
        if any(token not in (final_html or "") for token in required_tokens):
            return None, {"code": 1, "message": "fork 来源包含 Card Runtime，但目标 HTML 未保留完整 artifact"}

    summary = {
        "version": manifest.get("version"),
        "manifest_file": manifest_file,
        "source_template_id": source_template_id,
        "source_url": manifest_url or source_url,
        "source_html_file": source_file,
        "source_html_sha256": actual_sha,
        "source_package_ids": sorted(manifest_packages),
        "source_grant_ids": sorted(manifest_grants),
        "source_signature_sha256": sorted(manifest_signature_hashes),
        "minimum_target_package_count": minimum_packages,
        "minimum_target_grant_count": minimum_grants,
        "credential_count_reduction_reason": reduction_reason,
        "required_sections": _unique_strings(manifest.get("required_sections")),
        "required_outputs": required_outputs,
        "package_runtime_check": package_output_check,
        "card_runtime_required": bool(manifest.get("card_runtime_required")),
        "source_managed_images": source_managed_images,
    }
    return summary, None


def _package_runtime_check(endpoint, html, *, force=False, publish_out=None):
    if not force and not _server_mentions_package_issue(publish_out):
        return {
            "status": "not_verifiable_by_publish_key",
            "reason": "publish response did not indicate formula-package verification was needed",
        }
    creds = _extract_package_credentials(html)
    if not creds:
        return {
            "status": "not_verifiable_by_publish_key",
            "reason": "no package_id + signature pair found in page html",
        }

    signatures_by_package = {}
    for cred in creds:
        signatures_by_package.setdefault(cred["package_id"], set()).add(cred["signature"])
    ambiguous = [
        {"package_id": package_id, "signature_count": len(signatures)}
        for package_id, signatures in sorted(signatures_by_package.items())
        if len(signatures) > 1
    ]
    if ambiguous:
        return {
            "status": "credential_ambiguity",
            "reason": "同一 package_id 在页面中声明了多个 signature",
            "ambiguous_packages": ambiguous,
        }

    import formula_package as FP
    packages = []
    all_ok = True
    for cred in creds:
        pkg = cred["package_id"]
        res = FP.query_package(endpoint, pkg, cred["signature"])
        ok = isinstance(res, dict) and res.get("code") == 0
        all_ok = all_ok and ok
        packages.append({
            "package_id": pkg,
            "ok": ok,
            "error": (res.get("error") or res.get("message")) if isinstance(res, dict) else str(res),
            "failures": res.get("failures") if isinstance(res, dict) else None,
        })
    return {
        "status": "query_with_signature_ok" if all_ok else "query_with_signature_failed",
        "packages": packages,
    }


def _required_package_outputs_check(endpoint, html, required_outputs):
    required = _unique_strings(required_outputs)
    creds = _extract_package_credentials(html)
    if not creds:
        return {
            "status": "package_credentials_missing",
            "available_outputs": [],
            "missing_outputs": required,
            "packages": [],
        }

    signatures_by_package = {}
    for cred in creds:
        signatures_by_package.setdefault(cred["package_id"], set()).add(cred["signature"])
    ambiguous = [
        {"package_id": package_id, "signature_count": len(signatures)}
        for package_id, signatures in sorted(signatures_by_package.items())
        if len(signatures) > 1
    ]
    if ambiguous:
        return {
            "status": "credential_ambiguity",
            "available_outputs": [],
            "missing_outputs": required,
            "ambiguous_packages": ambiguous,
            "packages": [],
        }

    import formula_package as FP
    available = set()
    packages = []
    all_ok = True
    for cred in creds:
        response = FP.query_package(endpoint, cred["package_id"], cred["signature"])
        ok = isinstance(response, dict) and response.get("code") == 0
        output_keys = sorted((response.get("outputs") or {}).keys()) if isinstance(response, dict) else []
        if ok:
            available.update(output_keys)
        all_ok = all_ok and ok
        packages.append({
            "package_id": cred["package_id"],
            "ok": ok,
            "output_count": len(output_keys),
            "error": (response.get("error") or response.get("message")) if isinstance(response, dict) else str(response),
        })
    missing = [output for output in required if output not in available]
    return {
        "status": "required_outputs_ok" if all_ok and not missing else (
            "required_outputs_missing" if all_ok else "query_with_signature_failed"
        ),
        "available_outputs": sorted(available),
        "missing_outputs": missing,
        "packages": packages,
    }



def _is_preserve_html_qbs_live(params):
    return str((params or {}).get("transformation_mode") or "").strip() == _PRESERVE_HTML_QBS_LIVE_MODE


def _publish_html_error(html):
    size = len(str(html or "").encode("utf-8"))
    if size > _MAX_HTML_BYTES:
        return {"code": 1, "message": f"HTML 体积 {size} 字节，超过单页上限 2MB（请精简内联数据/资源）"}
    head = str(html or "").lstrip()[:64].lower()
    if not (head.startswith("<!doctype html") or head.startswith("<html")):
        return {"code": 1, "message": "内容不是 HTML 文档（需以 <!doctype html> 或 <html> 开头）"}
    return None


def _publish_body(params, html, *, page_id=None, snapshot_stage=False):
    body = {"html": html}
    if page_id:
        body["page_id"] = page_id
    fields = (
        "title", "description", "ttl_days", "scene_tags", "paradigm_tags", "user_query",
        "tagging_method", "tagging_source", "tagging_meta", "page_context",
        "agent_reply_template", "reply_contract_binding", "trace_evidence",
    )
    if page_id:
        fields += ("change_note", "change_aspect")
    for key in fields:
        if params.get(key) is not None:
            body[key] = params[key]
    for key in ("page_context", "reply_contract_binding", "agent_reply_template"):
        if key in params and params.get(key) is None:
            body[key] = None
    if page_id:
        if snapshot_stage:
            body["change_note"] = "先发布本地 HTML 渲染快照，作为 QBS 转换保底"
        else:
            body.setdefault("change_note", "更新页面内容")
    return body


def _merge_preserve_response(base_out, newer_out, *, page_id=None):
    base = dict(base_out) if isinstance(base_out, dict) else {"code": 1, "message": str(base_out)}
    if isinstance(newer_out, dict):
        merged = dict(newer_out)
        for key in ("page_id", "public_url", "url"):
            if not merged.get(key) and base.get(key):
                merged[key] = base[key]
    else:
        merged = base
    if page_id and not merged.get("page_id"):
        merged["page_id"] = page_id
    return merged


def _finalize_preserve_response(
    out, *, params, validation, error, status, snapshot_published_first,
    source_html_fallback_published, publish_sequence, shell_check,
    reply_resolution=None, card_runtime_verification=None, endpoint=None,
    final_html=None,
):
    if not isinstance(out, dict):
        return out
    out["transformation_status"] = status
    out["source_html_fallback_published"] = bool(source_html_fallback_published and out.get("code") == 0)
    out["snapshot_published_first"] = bool(snapshot_published_first)
    out["source_snapshot_published"] = bool(snapshot_published_first)
    out["publish_sequence"] = list(publish_sequence or [])
    if validation:
        out["transformation_validation"] = validation
    if error:
        out["transformation_error"] = error
    if reply_resolution:
        out["agent_reply_template_resolution"] = reply_resolution
        if isinstance(params.get("agent_reply_template"), dict):
            out.setdefault("agent_reply_template", params["agent_reply_template"])
        if isinstance(params.get("page_context"), dict):
            out.setdefault("page_context", params["page_context"])
    out["share_shell"] = shell_check
    if card_runtime_verification:
        out["card_runtime_verification"] = card_runtime_verification
    if out.get("code") == 0 and final_html and endpoint and status in {"complete", "partial"}:
        out["_package_runtime_check"] = _package_runtime_check(
            endpoint,
            final_html,
            force=bool(params.get("verify_packages")),
            publish_out=out,
        )
    if out.get("code") == 0:
        _attach_agent_reply_contract(out, operation="update" if params.get("page_id") else "upload")
    return out


def _prepare_preserve_snapshot_stage(params):
    fallback, fallback_error = _prepare_preserve_html_fallback(params, None)
    if fallback_error:
        return None, None, fallback_error
    snapshot_html = fallback["html"]
    resolved_params, reply_resolution, reply_error = _resolve_publish_agent_reply_template(params, html=snapshot_html)
    if reply_error:
        return None, None, reply_error
    try:
        snapshot_html, shell_check = _ensure_share_shell(snapshot_html, resolved_params)
    except ValueError as exc:
        return None, None, {"code": 1, "message": str(exc)}
    html_error = _publish_html_error(snapshot_html)
    if html_error:
        return None, None, html_error
    metadata_error = _validate_reply_metadata_pair(resolved_params)
    if metadata_error:
        return None, None, metadata_error
    return {
        "params": resolved_params,
        "html": snapshot_html,
        "validation": fallback["validation"],
        "shell_check": shell_check,
    }, reply_resolution, None


def _prepare_preserve_live_stage(params, target_html, *, endpoint):
    validation, validation_error = _validate_transformation_contract(params, target_html, endpoint=endpoint)
    if validation_error:
        return None, validation, validation_error
    live_html, indicator = _inject_visible_live_indicator(target_html, validation.get("div_live_check"))
    validation = dict(validation)
    validation["visible_live_indicator"] = indicator
    try:
        live_html, shell_check = _ensure_share_shell(live_html, params)
    except ValueError as exc:
        return None, validation, {"code": 1, "error": "PRESERVE_HTML_SHELL_INVALID", "message": str(exc)}
    html_error = _publish_html_error(live_html)
    if html_error:
        return None, validation, html_error
    card_runtime_verification = _maybe_verify_card_runtime(live_html, params)
    if isinstance(card_runtime_verification, dict) and not card_runtime_verification.get("ok"):
        return None, validation, {
            "code": 1,
            "error": "PRESERVE_HTML_CARD_RUNTIME_INVALID",
            "message": card_runtime_verification.get("message") or "card runtime artifact 验收未通过",
            "card_runtime_verification": card_runtime_verification,
        }
    return {
        "html": live_html,
        "validation": validation,
        "shell_check": shell_check,
        "card_runtime_verification": card_runtime_verification,
    }, validation, None


def _preserve_live_update_error(response):
    safe = {}
    if isinstance(response, dict):
        for key in ("code", "error", "message"):
            if response.get(key) is not None:
                safe[key] = response.get(key)
    return _evidence_error(
        "PRESERVE_HTML_LIVE_UPDATE_FAILED",
        "快照已发布，但 QBS 增强版本写回失败；当前活页继续保留首次快照",
        details=safe,
    )


def _preserve_target_read_error(error):
    details = error if isinstance(error, dict) else {"message": str(error)}
    return _evidence_error(
        "PRESERVE_HTML_TARGET_READ_FAILED",
        "快照已发布，但 QBS 目标 HTML 缺失或不可读；当前活页继续保留首次快照",
        details=details,
    )


def _cmd_upload_preserve(params, *, endpoint, api_key):
    snapshot, reply_resolution, error = _prepare_preserve_snapshot_stage(params)
    if error:
        return error
    resolved_params = snapshot["params"]
    upload_body = _publish_body(resolved_params, snapshot["html"])
    snapshot_out = C.http_json(
        "POST", C.api_url(endpoint, _PATH["upload"]), C.headers(api_key), upload_body,
        timeout=_UPLOAD_TIMEOUT,
    )
    snapshot_ok = isinstance(snapshot_out, dict) and snapshot_out.get("code") == 0
    sequence = ["snapshot_upload"] if snapshot_ok else []
    if not snapshot_ok:
        return _finalize_preserve_response(
            snapshot_out, params=resolved_params, validation=snapshot["validation"], error=None,
            status="failed", snapshot_published_first=False,
            source_html_fallback_published=False, publish_sequence=sequence,
            shell_check=snapshot["shell_check"], reply_resolution=reply_resolution,
        )
    page_id = str(snapshot_out.get("page_id") or "").strip()
    target_html, target_error = _read_html(resolved_params)
    if target_error:
        return _finalize_preserve_response(
            snapshot_out, params=resolved_params, validation=snapshot["validation"],
            error=_preserve_target_read_error(target_error), status="failed",
            snapshot_published_first=True, source_html_fallback_published=True,
            publish_sequence=sequence, shell_check=snapshot["shell_check"],
            reply_resolution=reply_resolution,
        )
    live_stage, validation, validation_error = _prepare_preserve_live_stage(
        resolved_params, target_html, endpoint=endpoint
    )
    if validation_error or not page_id:
        if not validation_error:
            validation_error = _evidence_error(
                "PRESERVE_HTML_PAGE_ID_MISSING",
                "首次快照已上传，但服务端未返回 page_id，无法在同一链接继续 QBS 增强",
            )
        status = _preserve_fallback_status(resolved_params)
        return _finalize_preserve_response(
            snapshot_out, params=resolved_params, validation=snapshot["validation"], error=validation_error,
            status=status, snapshot_published_first=True,
            source_html_fallback_published=True, publish_sequence=sequence,
            shell_check=snapshot["shell_check"], reply_resolution=reply_resolution,
        )
    update_body = _publish_body(resolved_params, live_stage["html"], page_id=page_id)
    live_out = C.http_json(
        "POST", C.api_url(endpoint, _PATH["update"]), C.headers(api_key), update_body,
        timeout=_UPLOAD_TIMEOUT,
    )
    if not isinstance(live_out, dict) or live_out.get("code") != 0:
        return _finalize_preserve_response(
            snapshot_out, params=resolved_params, validation=snapshot["validation"],
            error=_preserve_live_update_error(live_out), status="failed",
            snapshot_published_first=True, source_html_fallback_published=True,
            publish_sequence=sequence + ["qbs_live_update_failed"],
            shell_check=snapshot["shell_check"], reply_resolution=reply_resolution,
        )
    status = validation.get("transformation_status") or "complete"
    final_out = _merge_preserve_response(snapshot_out, live_out, page_id=page_id)
    return _finalize_preserve_response(
        final_out, params=resolved_params, validation=validation, error=None, status=status,
        snapshot_published_first=True, source_html_fallback_published=(status == "partial"),
        publish_sequence=sequence + ["qbs_live_update"], shell_check=live_stage["shell_check"],
        reply_resolution=reply_resolution,
        card_runtime_verification=live_stage.get("card_runtime_verification"),
        endpoint=endpoint, final_html=live_stage["html"],
    )


def _cmd_update_preserve(params, *, endpoint, api_key):
    snapshot, reply_resolution, error = _prepare_preserve_snapshot_stage(params)
    if error:
        return error
    resolved_params = snapshot["params"]
    page_id = str(params.get("page_id") or "").strip()
    snapshot_body = _publish_body(resolved_params, snapshot["html"], page_id=page_id, snapshot_stage=True)
    snapshot_out = C.http_json(
        "POST", C.api_url(endpoint, _PATH["update"]), C.headers(api_key), snapshot_body,
        timeout=_UPLOAD_TIMEOUT,
    )
    snapshot_ok = isinstance(snapshot_out, dict) and snapshot_out.get("code") == 0
    sequence = ["snapshot_update"] if snapshot_ok else []
    if not snapshot_ok:
        return _finalize_preserve_response(
            snapshot_out, params=resolved_params, validation=snapshot["validation"], error=None,
            status="failed", snapshot_published_first=False,
            source_html_fallback_published=False, publish_sequence=sequence,
            shell_check=snapshot["shell_check"], reply_resolution=reply_resolution,
        )
    target_html, target_error = _read_html(resolved_params)
    if target_error:
        return _finalize_preserve_response(
            _merge_preserve_response(snapshot_out, None, page_id=page_id),
            params=resolved_params, validation=snapshot["validation"],
            error=_preserve_target_read_error(target_error), status="failed",
            snapshot_published_first=True, source_html_fallback_published=True,
            publish_sequence=sequence, shell_check=snapshot["shell_check"],
            reply_resolution=reply_resolution,
        )
    live_stage, validation, validation_error = _prepare_preserve_live_stage(
        resolved_params, target_html, endpoint=endpoint
    )
    if validation_error:
        status = _preserve_fallback_status(resolved_params)
        return _finalize_preserve_response(
            _merge_preserve_response(snapshot_out, None, page_id=page_id),
            params=resolved_params, validation=snapshot["validation"], error=validation_error,
            status=status, snapshot_published_first=True,
            source_html_fallback_published=True, publish_sequence=sequence,
            shell_check=snapshot["shell_check"], reply_resolution=reply_resolution,
        )
    live_body = _publish_body(resolved_params, live_stage["html"], page_id=page_id)
    live_out = C.http_json(
        "POST", C.api_url(endpoint, _PATH["update"]), C.headers(api_key), live_body,
        timeout=_UPLOAD_TIMEOUT,
    )
    if not isinstance(live_out, dict) or live_out.get("code") != 0:
        return _finalize_preserve_response(
            _merge_preserve_response(snapshot_out, None, page_id=page_id),
            params=resolved_params, validation=snapshot["validation"],
            error=_preserve_live_update_error(live_out), status="failed",
            snapshot_published_first=True, source_html_fallback_published=True,
            publish_sequence=sequence + ["qbs_live_update_failed"],
            shell_check=snapshot["shell_check"], reply_resolution=reply_resolution,
        )
    status = validation.get("transformation_status") or "complete"
    final_out = _merge_preserve_response(snapshot_out, live_out, page_id=page_id)
    return _finalize_preserve_response(
        final_out, params=resolved_params, validation=validation, error=None, status=status,
        snapshot_published_first=True, source_html_fallback_published=(status == "partial"),
        publish_sequence=sequence + ["qbs_live_update"], shell_check=live_stage["shell_check"],
        reply_resolution=reply_resolution,
        card_runtime_verification=live_stage.get("card_runtime_verification"),
        endpoint=endpoint, final_html=live_stage["html"],
    )

def cmd_upload(params):
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")

    if _is_preserve_html_qbs_live(params):
        return _cmd_upload_preserve(params, endpoint=endpoint, api_key=api_key)
    html, err = _read_html(params)
    if err:
        return err
    transformation_validation, transformation_error = _validate_transformation_contract(params, html, endpoint=endpoint)
    transformation_fallback = None
    if transformation_error:
        transformation_fallback, fallback_error = _prepare_preserve_html_fallback(params, transformation_error)
        if fallback_error:
            return fallback_error
        html = transformation_fallback["html"]
        transformation_validation = transformation_fallback["validation"]
    if (
        not transformation_fallback
        and transformation_validation
        and transformation_validation.get("mode") == _PRESERVE_HTML_QBS_LIVE_MODE
    ):
        html, visible_live_indicator = _inject_visible_live_indicator(
            html, transformation_validation.get("div_live_check")
        )
        transformation_validation = dict(transformation_validation)
        transformation_validation["visible_live_indicator"] = visible_live_indicator
    reply_resolution = None
    if not params.get("_suppress_agent_reply_fallback"):
        params, reply_resolution, reply_error = _resolve_publish_agent_reply_template(params, html=html)
        if reply_error:
            return reply_error
    try:
        html, shell_check = _ensure_share_shell(html, params)
    except ValueError as e:
        return {"code": 1, "message": str(e)}
    size = len(html.encode("utf-8"))
    if size > _MAX_HTML_BYTES:
        return {"code": 1, "message": f"HTML 体积 {size} 字节，超过单页上限 2MB（请精简内联数据/资源）"}
    head = html.lstrip()[:64].lower()
    if not (head.startswith("<!doctype html") or head.startswith("<html")):
        return {"code": 1, "message": "内容不是 HTML 文档（需以 <!doctype html> 或 <html> 开头）"}
    card_runtime_verification = _maybe_verify_card_runtime(html, params)
    if isinstance(card_runtime_verification, dict) and not card_runtime_verification.get("ok"):
        return {
            "code": 1,
            "message": card_runtime_verification.get("message") or "card runtime artifact 验收未通过",
            "card_runtime_verification": card_runtime_verification,
        }
    metadata_err = _validate_reply_metadata_pair(params)
    if metadata_err:
        return metadata_err

    body = {"html": html}
    for k in ("title", "description", "ttl_days", "scene_tags", "paradigm_tags", "user_query", "tagging_method", "tagging_source", "tagging_meta", "page_context", "agent_reply_template", "reply_contract_binding", "trace_evidence"):
        if params.get(k) is not None:
            body[k] = params[k]
    if "page_context" in params and params.get("page_context") is None:
        body["page_context"] = None
    if "reply_contract_binding" in params and params.get("reply_contract_binding") is None:
        body["reply_contract_binding"] = None
    if "agent_reply_template" in params and params.get("agent_reply_template") is None:
        body["agent_reply_template"] = None
    out = C.http_json("POST", C.api_url(endpoint, _PATH["upload"]),
                      C.headers(api_key), body, timeout=_UPLOAD_TIMEOUT)
    if isinstance(out, dict):
        if reply_resolution:
            out["agent_reply_template_resolution"] = reply_resolution
            if transformation_validation and transformation_validation.get("mode") == _PRESERVE_HTML_QBS_LIVE_MODE:
                if isinstance(params.get("agent_reply_template"), dict):
                    out.setdefault("agent_reply_template", params["agent_reply_template"])
                if isinstance(params.get("page_context"), dict):
                    out.setdefault("page_context", params["page_context"])
        _attach_transformation_outcome(
            out,
            params=params,
            validation=transformation_validation,
            error=transformation_error,
            fallback=transformation_fallback,
        )
        out["share_shell"] = shell_check
        if card_runtime_verification:
            out["card_runtime_verification"] = card_runtime_verification
        if not transformation_fallback and (out.get("code") == 0 or _server_mentions_package_issue(out)):
            out["_package_runtime_check"] = _package_runtime_check(
                endpoint,
                html,
                force=bool(params.get("verify_packages")),
                publish_out=out,
            )
        if out.get("code") == 0:
            _attach_agent_reply_contract(out, operation="upload")
    return out


def cmd_update(params):
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")

    if not params.get("page_id"):
        return {"code": 1, "message": "update 需要 page_id（要替换哪个已发布页面）"}

    if _is_preserve_html_qbs_live(params):
        return _cmd_update_preserve(params, endpoint=endpoint, api_key=api_key)
    html, err = _read_html(params)
    if err:
        return err
    transformation_validation, transformation_error = _validate_transformation_contract(params, html, endpoint=endpoint)
    transformation_fallback = None
    if transformation_error:
        transformation_fallback, fallback_error = _prepare_preserve_html_fallback(params, transformation_error)
        if fallback_error:
            return fallback_error
        html = transformation_fallback["html"]
        transformation_validation = transformation_fallback["validation"]
    if (
        not transformation_fallback
        and transformation_validation
        and transformation_validation.get("mode") == _PRESERVE_HTML_QBS_LIVE_MODE
    ):
        html, visible_live_indicator = _inject_visible_live_indicator(
            html, transformation_validation.get("div_live_check")
        )
        transformation_validation = dict(transformation_validation)
        transformation_validation["visible_live_indicator"] = visible_live_indicator
    reply_resolution = None
    if str(params.get("transformation_mode") or "").strip() == _PRESERVE_HTML_QBS_LIVE_MODE:
        params, reply_resolution, reply_error = _resolve_publish_agent_reply_template(params, html=html)
        if reply_error:
            return reply_error
    try:
        html, shell_check = _ensure_share_shell(html, params)
    except ValueError as e:
        return {"code": 1, "message": str(e)}
    size = len(html.encode("utf-8"))
    if size > _MAX_HTML_BYTES:
        return {"code": 1, "message": f"HTML 体积 {size} 字节，超过单页上限 2MB（请精简内联数据/资源）"}
    head = html.lstrip()[:64].lower()
    if not (head.startswith("<!doctype html") or head.startswith("<html")):
        return {"code": 1, "message": "内容不是 HTML 文档（需以 <!doctype html> 或 <html> 开头）"}
    card_runtime_verification = _maybe_verify_card_runtime(html, params)
    if isinstance(card_runtime_verification, dict) and not card_runtime_verification.get("ok"):
        return {
            "code": 1,
            "message": card_runtime_verification.get("message") or "card runtime artifact 验收未通过",
            "card_runtime_verification": card_runtime_verification,
        }
    metadata_err = _validate_reply_metadata_pair(params)
    if metadata_err:
        return metadata_err

    body = {"page_id": params["page_id"], "html": html}
    for k in ("title", "description", "ttl_days", "scene_tags", "paradigm_tags", "user_query", "tagging_method", "tagging_source", "tagging_meta", "page_context", "agent_reply_template", "reply_contract_binding", "change_note", "change_aspect", "trace_evidence"):
        if params.get(k) is not None:
            body[k] = params[k]
    body.setdefault("change_note", "更新页面内容")
    if "page_context" in params and params.get("page_context") is None:
        body["page_context"] = None
    if "reply_contract_binding" in params and params.get("reply_contract_binding") is None:
        body["reply_contract_binding"] = None
    if "agent_reply_template" in params and params.get("agent_reply_template") is None:
        body["agent_reply_template"] = None
    out = C.http_json("POST", C.api_url(endpoint, _PATH["update"]),
                      C.headers(api_key), body, timeout=_UPLOAD_TIMEOUT)
    if isinstance(out, dict):
        if reply_resolution:
            out["agent_reply_template_resolution"] = reply_resolution
            if transformation_validation and transformation_validation.get("mode") == _PRESERVE_HTML_QBS_LIVE_MODE:
                if isinstance(params.get("agent_reply_template"), dict):
                    out.setdefault("agent_reply_template", params["agent_reply_template"])
                if isinstance(params.get("page_context"), dict):
                    out.setdefault("page_context", params["page_context"])
        _attach_transformation_outcome(
            out,
            params=params,
            validation=transformation_validation,
            error=transformation_error,
            fallback=transformation_fallback,
        )
        out["share_shell"] = shell_check
        if card_runtime_verification:
            out["card_runtime_verification"] = card_runtime_verification
        if not transformation_fallback and (out.get("code") == 0 or _server_mentions_package_issue(out)):
            out["_package_runtime_check"] = _package_runtime_check(
                endpoint,
                html,
                force=bool(params.get("verify_packages")),
                publish_out=out,
            )
        if out.get("code") == 0:
            _attach_agent_reply_contract(out, operation="update")
    return out


def _progress_state_and_html(params):
    state = PP.build_state(params)
    render_params = dict(params or {})
    render_params["updated_at"] = state["updated_at"]
    return state, PP.render_progress_html(render_params)


_PROGRESS_CHANGE_NOTE_PREFIXES = {
    "running": "进度更新",
    "waiting_input": "等待输入",
    "done": "进度完成",
    "failed": "进度失败",
}


def _progress_change_note(state):
    state = state if isinstance(state, dict) else {}
    page_status = str(state.get("page_status") or "running").strip().lower()
    current_step = str(state.get("current_step") or "").strip()
    step_title = str(state.get("current_step_title") or current_step or "活页生成").strip()
    message = str(state.get("message") or "").strip()

    if current_step == "final_publish":
        prefix = {
            "running": "开始发布",
            "done": "完成发布",
            "failed": "发布失败",
        }.get(page_status, _PROGRESS_CHANGE_NOTE_PREFIXES.get(page_status, "进度更新"))
    else:
        prefix = _PROGRESS_CHANGE_NOTE_PREFIXES.get(page_status, "进度更新")

    note = f"{prefix}：{step_title}" if step_title else prefix
    if message and message != step_title:
        note += f"｜{message}"
    return note[:200]


def _validate_progress_params(params):
    if str((params or {}).get("page_status") or "running").strip().lower() != "waiting_input":
        return None
    required_input = params.get("required_input")
    required_fields = ("id", "prompt", "resume_step")
    missing = [
        field for field in required_fields
        if not isinstance(required_input, dict) or not str(required_input.get(field) or "").strip()
    ]
    if missing:
        return {
            "code": 1,
            "error": "PROGRESS_INPUT_REQUIRED",
            "message": "waiting_input 需要 required_input.id、prompt 和 resume_step",
            "missing": missing,
        }
    return None


def _evidence_error(error, message, **extra):
    return {"code": 1, "error": error, "message": message, **extra}


def _receipt_files(value):
    if isinstance(value, str):
        value = [value]
    return value if isinstance(value, list) else []


def _read_evidence_receipt(raw_path, label):
    if not str(raw_path or "").strip():
        return None, _evidence_error("DATA_EVIDENCE_RECEIPT_INVALID", f"{label} 缺少收据路径")
    path = _fork_path(raw_path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            receipt = json.load(handle)
    except Exception as exc:
        return None, _evidence_error("DATA_EVIDENCE_RECEIPT_INVALID", f"{label} 无法读取: {exc}", file=path)
    if not isinstance(receipt, dict):
        return None, _evidence_error("DATA_EVIDENCE_RECEIPT_INVALID", f"{label} 必须是 JSON 对象", file=path)
    return receipt, None


def _normalized_evidence_path(value):
    try:
        return os.path.normcase(os.path.abspath(_fork_path(value)))
    except Exception:
        return os.path.normcase(os.path.abspath(str(value or "")))


def _valid_formula_receipt(receipt, task_id):
    base_valid = (
        isinstance(receipt, dict)
        and receipt.get("version") == _VALIDATION_RECEIPT_VERSION
        and str(receipt.get("task_id") or "") == task_id
        and receipt.get("status") == "completed"
        and receipt.get("success") is True
        and not receipt.get("failures")
    )
    if not base_valid or "batch_receipts" not in receipt:
        return base_valid

    entries = receipt.get("batch_receipts")
    if (
        receipt.get("tool_name") != "validate_package_set"
        or not str(receipt.get("contract_fingerprint") or "").strip()
        or not isinstance(entries, list)
        or not entries
        or receipt.get("batch_count") != len(entries)
    ):
        return False

    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            return False
        raw_path = str(entry.get("file") or "").strip()
        expected_sha256 = str(entry.get("sha256") or "").strip().lower()
        if not raw_path or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            return False
        path_key = _normalized_evidence_path(raw_path)
        if path_key in seen:
            return False
        seen.add(path_key)
        child, error = _read_evidence_receipt(raw_path, "formula batch receipt")
        if error or "batch_receipts" in child or not _valid_formula_receipt(child, task_id):
            return False
        try:
            digest = hashlib.sha256(Path(_fork_path(raw_path)).read_bytes()).hexdigest()
        except OSError:
            return False
        if not secrets.compare_digest(digest, expected_sha256):
            return False

    outputs = receipt.get("outputs")
    expected_outputs_sha256 = str(receipt.get("outputs_sha256") or "").strip().lower()
    if not isinstance(outputs, list) or not re.fullmatch(r"[0-9a-f]{64}", expected_outputs_sha256):
        return False
    digest_source = json.dumps(outputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    actual_outputs_sha256 = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return secrets.compare_digest(actual_outputs_sha256, expected_outputs_sha256)

def _valid_grant_receipt(receipt, task_id):
    return (
        isinstance(receipt, dict)
        and receipt.get("version") == _GRANT_VALIDATION_RECEIPT_VERSION
        and str(receipt.get("task_id") or "") == task_id
        and receipt.get("status") == "completed"
        and receipt.get("success") is True
        and bool(str(receipt.get("contract_fingerprint") or "").strip())
    )


def _valid_qbs_handoff_receipt(receipt, task_id, turn_id):
    if not (
        isinstance(receipt, dict)
        and receipt.get("schema") == _QBS_HANDOFF_VALIDATION_RECEIPT_VERSION
        and receipt.get("version") == _QBS_HANDOFF_VALIDATION_RECEIPT_VERSION
        and str(receipt.get("task_id") or "") == task_id
        and str(receipt.get("turn_id") or "") == turn_id
        and receipt.get("source_skill_name") == "quant-buddy-skill"
        and receipt.get("kind") == "handoff_materialized"
        and receipt.get("status") == "completed"
        and receipt.get("success") is True
        and receipt.get("coverage") == "covered"
        and isinstance(receipt.get("row_count"), int)
        and receipt.get("row_count") > 0
        and bool(str(receipt.get("role") or "").strip())
        and bool(str(receipt.get("package_id") or "").strip())
        and bool(str(receipt.get("package_output") or "").strip())
    ):
        return False
    source_id_status = str(receipt.get("source_skill_id_status") or "").strip()
    if source_id_status not in {"available", "unavailable"}:
        return False
    if source_id_status == "available" and not str(receipt.get("source_skill_id") or "").strip():
        return False
    for key in ("contract_fingerprint", "reference_hash", "rows_sha256", "package_contract_fingerprint"):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(receipt.get(key) or "")):
            return False
    if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("package_signature_sha256") or "")):
        return False
    evidence_files = receipt.get("evidence_files")
    required = {"handoff", "materialized", "package_contract", "package_query", "package_manifest"}
    if not isinstance(evidence_files, dict) or set(evidence_files) != required:
        return False
    seen = set()
    for entry in evidence_files.values():
        if not isinstance(entry, dict):
            return False
        raw_path = str(entry.get("file") or "").strip()
        expected_sha256 = str(entry.get("sha256") or "").strip().lower()
        if not raw_path or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            return False
        path_key = _normalized_evidence_path(raw_path)
        if not path_key or path_key in seen:
            return False
        seen.add(path_key)
        try:
            actual_sha256 = hashlib.sha256(Path(_fork_path(raw_path)).read_bytes()).hexdigest()
        except OSError:
            return False
        if not secrets.compare_digest(actual_sha256, expected_sha256):
            return False
    return True


def _validate_route_identity(route, params):
    task_id = _fork_task_id(params)
    asset = str((params or {}).get("asset") or "").strip()
    if route.get("schema") != _LIVE_DATA_ROUTE_RECEIPT_VERSION or route.get("version") != _LIVE_DATA_ROUTE_RECEIPT_VERSION:
        return _evidence_error("LIVE_DATA_ROUTE_RECEIPT_INVALID", "路由收据 schema/version 无效")
    if str(route.get("task_id") or "") != task_id:
        return _evidence_error("LIVE_DATA_ROUTE_TASK_MISMATCH", "路由收据 task_id 与当前发布任务不一致")
    route_turn_id = str(route.get("turn_id") or "").strip()
    if route_turn_id:
        turn_id = str((params or {}).get("turn_id") or "").strip()
        if not turn_id or route_turn_id != turn_id:
            return _evidence_error("LIVE_DATA_ROUTE_TURN_MISMATCH", "路由收据 turn_id 与当前发布任务不一致")
    route_asset = str(route.get("asset") or "").strip()
    if asset and route_asset != asset:
        return _evidence_error("LIVE_DATA_ROUTE_ASSET_MISMATCH", "路由收据资产与当前页面资产不一致", expected_asset=asset, receipt_asset=route_asset)
    if route_asset and not asset:
        return _evidence_error("LIVE_DATA_ROUTE_ASSET_MISMATCH", "资产实时页面发布参数必须显式携带 asset", receipt_asset=route_asset)
    return None


def _validate_static_after_probe(params, route):
    identity_error = _validate_route_identity(route, params)
    if identity_error:
        return identity_error
    if route.get("status") != "static_fallback_allowed" or route.get("static_fallback_allowed") is not True or route.get("required_roles_complete") is not False:
        return _evidence_error("STATIC_FALLBACK_RECEIPT_INVALID", "静态回退只接受 status=static_fallback_allowed 的未完成实时路由收据")
    if route.get("selected_routes"):
        return _evidence_error("STATIC_FALLBACK_ROUTE_SUCCEEDED", "已有实时路线成功，禁止静态回退")
    required_roles = route.get("required_roles") if isinstance(route.get("required_roles"), list) else []
    attempted_roles = route.get("attempted_roles") if isinstance(route.get("attempted_roles"), list) else []
    if not required_roles or set(required_roles) != set(attempted_roles):
        return _evidence_error("STATIC_FALLBACK_PROBE_INCOMPLETE", "所有核心实时角色都必须完成探测后才能静态回退", required_roles=required_roles, attempted_roles=attempted_roles)
    attempts = route.get("attempts") if isinstance(route.get("attempts"), list) else []
    for role in required_roles:
        role_attempts = [item for item in attempts if isinstance(item, dict) and item.get("role") == role]
        if not role_attempts:
            return _evidence_error("STATIC_FALLBACK_PROBE_INCOMPLETE", f"核心角色 {role} 缺少探测记录")
        if any(item.get("status") == "success" for item in role_attempts):
            return _evidence_error("STATIC_FALLBACK_ROUTE_SUCCEEDED", f"核心角色 {role} 已有实时路线成功，禁止静态回退")
        if not all(item.get("status") == "failed" and item.get("error_class") == "data" for item in role_attempts):
            return _evidence_error("STATIC_FALLBACK_SYSTEM_BLOCKED", f"核心角色 {role} 含系统级阻塞或非数据失败，禁止静态回退")
    return None


def _validate_live_receipts(params, route, *, allow_partial=False):
    identity_error = _validate_route_identity(route, params)
    if identity_error:
        return identity_error
    required_roles = route.get("required_roles") if isinstance(route.get("required_roles"), list) else []
    attempted_roles = route.get("attempted_roles") if isinstance(route.get("attempted_roles"), list) else []
    selected = route.get("selected_routes") if isinstance(route.get("selected_routes"), list) else []
    selected_roles = {str(item.get("role") or "") for item in selected if isinstance(item, dict)}
    complete = (
        route.get("status") == "live"
        and route.get("required_roles_complete") is True
        and route.get("static_fallback_allowed") is False
    )
    partial = (
        allow_partial
        and route.get("status") == "incomplete"
        and route.get("required_roles_complete") is False
        and route.get("static_fallback_allowed") is False
    )
    if not complete and not partial:
        return _evidence_error(
            "LIVE_DATA_ROUTE_INCOMPLETE",
            "实时发布只接受完整 live 路由；preserve_html_qbs_live 额外允许已有成功路线的 incomplete 路由",
        )
    if not required_roles or set(required_roles) != set(attempted_roles) or not selected:
        return _evidence_error("LIVE_DATA_ROUTE_INCOMPLETE", "实时路由收据必须探测全部核心角色并选择至少一条成功实时路线")
    if complete and not set(required_roles).issubset(selected_roles):
        return _evidence_error("LIVE_DATA_ROUTE_INCOMPLETE", "selected_routes 未覆盖全部核心角色")
    if partial and (not selected_roles.issubset(set(required_roles)) or set(required_roles).issubset(selected_roles)):
        return _evidence_error("LIVE_DATA_ROUTE_INCOMPLETE", "partial 路由必须只选择已成功的部分核心角色，未成功角色继续使用快照")

    task_id = _fork_task_id(params)
    turn_id = str(params.get("turn_id") or "").strip()
    formula_files = _receipt_files(params.get("validation_receipt_files"))
    grant_files = _receipt_files(params.get("grant_validation_receipt_files"))
    handoff_files = _receipt_files(params.get("handoff_validation_receipt_files"))
    formula_receipts = {}
    grant_receipts = {}
    handoff_receipts = {}
    invalid = []
    for raw_path in formula_files:
        receipt, error = _read_evidence_receipt(raw_path, "formula receipt")
        path_key = _normalized_evidence_path(raw_path)
        if error or not _valid_formula_receipt(receipt, task_id):
            invalid.append({"file": str(raw_path), "kind": "formula"})
        else:
            formula_receipts[path_key] = receipt
    for raw_path in grant_files:
        receipt, error = _read_evidence_receipt(raw_path, "grant receipt")
        path_key = _normalized_evidence_path(raw_path)
        if error or not _valid_grant_receipt(receipt, task_id):
            invalid.append({"file": str(raw_path), "kind": "grant"})
        else:
            grant_receipts[path_key] = receipt
    for raw_path in handoff_files:
        receipt, error = _read_evidence_receipt(raw_path, "QBS handoff receipt")
        path_key = _normalized_evidence_path(raw_path)
        if error or not _valid_qbs_handoff_receipt(receipt, task_id, turn_id):
            invalid.append({"file": str(raw_path), "kind": "handoff_materialized"})
        else:
            handoff_receipts[path_key] = receipt
    if invalid:
        return _evidence_error("LIVE_DATA_RECEIPT_INVALID", "Grant/公式/QBS Handoff 验证收据无效、未完成或与当前 task_id/turn_id 不一致", invalid_receipts=invalid)

    selected_formula = set()
    selected_grant = set()
    selected_handoff = set()
    selected_receipt_paths = set()
    for index, item in enumerate(selected):
        if not isinstance(item, dict):
            return _evidence_error("LIVE_DATA_SELECTED_ROUTE_INVALID", f"selected_routes[{index}] 必须是对象")
        kind = str(item.get("kind") or "").strip()
        receipt_file = str(item.get("receipt_file") or "").strip()
        path_key = _normalized_evidence_path(receipt_file)
        if not path_key:
            return _evidence_error("LIVE_DATA_ROUTE_RECEIPT_MISSING", f"实时路线 {item.get('role')} 缺少 receipt_file")
        if path_key in selected_receipt_paths:
            return _evidence_error("LIVE_DATA_ROUTE_RECEIPT_REUSED", "每条 selected route 必须对应唯一验证收据", receipt_file=receipt_file)
        selected_receipt_paths.add(path_key)
        if kind == "formula":
            selected_formula.add(path_key)
            receipt = formula_receipts.get(path_key)
            if receipt is None:
                return _evidence_error("LIVE_DATA_ROUTE_RECEIPT_MISSING", f"公式路线 {item.get('role')} 缺少对应 qb_validation_receipt_v1")
        elif kind == "handoff_materialized":
            selected_handoff.add(path_key)
            receipt = handoff_receipts.get(path_key)
            if receipt is None:
                return _evidence_error("LIVE_DATA_ROUTE_RECEIPT_MISSING", f"QBS Handoff 路线 {item.get('role')} 缺少对应 qbs_handoff_validation_receipt_v1")
            if str(receipt.get("contract_fingerprint") or "") != str(item.get("contract_fingerprint") or ""):
                return _evidence_error("LIVE_DATA_ROUTE_FINGERPRINT_MISMATCH", f"QBS Handoff 路线 {item.get('role')} 的合同指纹与验证收据不一致")
            if str(receipt.get("role") or "").strip() != str(item.get("role") or "").strip():
                return _evidence_error("LIVE_DATA_ROUTE_ROLE_MISMATCH", f"QBS Handoff 路线 {item.get('role')} 的角色与验证收据不一致")
            if str(receipt.get("package_id") or "").strip() != str(item.get("package_id") or "").strip():
                return _evidence_error("LIVE_DATA_ROUTE_PACKAGE_MISMATCH", f"QBS Handoff 路线 {item.get('role')} 的 package_id 与验证收据不一致")
            if str(receipt.get("package_output") or "").strip() != str(item.get("output") or "").strip():
                return _evidence_error("LIVE_DATA_ROUTE_OUTPUT_MISMATCH", f"QBS Handoff 路线 {item.get('role')} 的输出与验证收据不一致")
        else:
            selected_grant.add(path_key)
            receipt = grant_receipts.get(path_key)
            if receipt is None:
                return _evidence_error("LIVE_DATA_ROUTE_RECEIPT_MISSING", f"Grant 路线 {item.get('role')} 缺少对应 grant_validation_receipt_v1")
            receipt_kind = str(receipt.get("kind") or "").strip()
            if not kind or receipt_kind != kind:
                return _evidence_error("LIVE_DATA_ROUTE_KIND_MISMATCH", f"Grant 路线 {item.get('role')} 的 kind 与验证收据不一致", selected_kind=kind, receipt_kind=receipt_kind)
            if str(receipt.get("contract_fingerprint") or "") != str(item.get("contract_fingerprint") or ""):
                return _evidence_error("LIVE_DATA_ROUTE_FINGERPRINT_MISMATCH", f"Grant 路线 {item.get('role')} 的合同指纹与验证收据不一致")
            receipt_role = str(receipt.get("role") or "").strip()
            if receipt_role and receipt_role != str(item.get("role") or "").strip():
                return _evidence_error("LIVE_DATA_ROUTE_ROLE_MISMATCH", f"Grant 路线 {item.get('role')} 的角色与验证收据不一致")
    if len(selected) != len(selected_receipt_paths):
        return _evidence_error("LIVE_DATA_RECEIPT_SET_MISMATCH", "selected_routes 必须与验证收据一一对应")
    if selected_formula != set(formula_receipts) or selected_grant != set(grant_receipts) or selected_handoff != set(handoff_receipts):
        return _evidence_error("LIVE_DATA_RECEIPT_SET_MISMATCH", "提交的 Grant/公式/QBS Handoff 收据必须与 selected_routes 逐项完全对应")
    return None


def _validate_publish_data_evidence(params, *, source_credential_count=0, allow_partial=False):
    params = params or {}
    if str(params.get("validation_not_required_reason") or "").strip():
        return _evidence_error("LEGACY_VALIDATION_WAIVER_FORBIDDEN", "自由文本 validation_not_required_reason 已停用；必须使用结构化 live_data_mode 和收据")
    mode = str(params.get("live_data_mode") or "").strip()
    if mode not in _LIVE_DATA_MODES:
        return _evidence_error("LIVE_DATA_MODE_REQUIRED", "发布必须显式指定 live、static_content_only 或 static_after_live_probe")
    if mode == "static_content_only":
        if source_credential_count:
            return _evidence_error(
                "STATIC_CONTENT_ONLY_SOURCE_LIVE_DATA",
                "来源页面包含 package/grant 实时凭证，不得声明为 static_content_only",
                source_credential_count=source_credential_count,
            )
        if params.get("market_data_required") is not False or str(params.get("asset") or "").strip():
            return _evidence_error("STATIC_CONTENT_ONLY_FORBIDDEN", "资产分析、行情、估值、财务或计算指标页面不得使用 static_content_only")
        if params.get("route_receipt_file") or _receipt_files(params.get("validation_receipt_files")) or _receipt_files(params.get("grant_validation_receipt_files")) or _receipt_files(params.get("handoff_validation_receipt_files")):
            return _evidence_error("STATIC_CONTENT_ONLY_EVIDENCE_CONFLICT", "纯静态模式不得混入实时路由或实时验证收据")
        return None
    route, error = _read_evidence_receipt(params.get("route_receipt_file"), "live data route receipt")
    if error:
        return _evidence_error("LIVE_DATA_ROUTE_RECEIPT_REQUIRED", "live/static_after_live_probe 模式必须提供可读取的 live_data_route_receipt_v1", details=error)
    if mode == "static_after_live_probe":
        return _validate_static_after_probe(params, route)
    return _validate_live_receipts(params, route, allow_partial=allow_partial)


class _PreserveHtmlParser(HTMLParser):
    """Capture user-owned DOM/layout/content while ignoring replaceable runtime code."""

    _IGNORED_CONTENT_TAGS = {"script", "style", "template", "noscript"}
    _IGNORED_TAGS = {"script", "style", "meta", "link", "base", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.dom = []
        self.text = []

    @staticmethod
    def _stable_attrs(attrs):
        stable = []
        for name, value in attrs:
            key = str(name or "").lower()
            # data-* and inline event handlers are allowed to change because
            # they are part of the data/runtime binding, not the page layout.
            if key.startswith("data-") or key.startswith("on"):
                continue
            stable.append((key, "" if value is None else str(value)))
        return tuple(sorted(stable))

    def handle_starttag(self, tag, attrs):
        name = str(tag or "").lower()
        if name in self._IGNORED_CONTENT_TAGS:
            self._ignored_depth += 1
        if self._ignored_depth or name in self._IGNORED_TAGS:
            return
        self.dom.append(("start", name, self._stable_attrs(attrs)))

    def handle_startendtag(self, tag, attrs):
        name = str(tag or "").lower()
        if self._ignored_depth or name in self._IGNORED_TAGS:
            return
        stable_attrs = self._stable_attrs(attrs)
        self.dom.append(("start", name, stable_attrs))
        self.dom.append(("end", name))

    def handle_endtag(self, tag):
        name = str(tag or "").lower()
        if name in self._IGNORED_CONTENT_TAGS:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if self._ignored_depth or name in self._IGNORED_TAGS:
            return
        self.dom.append(("end", name))

    def handle_data(self, data):
        if self._ignored_depth:
            return
        text = re.sub(r"\s+", " ", str(data or "")).strip()
        if text:
            self.text.append(text)


class _DivLiveTagParser(HTMLParser):
    """Inspect rendered div declarations without treating runtime text as HTML."""

    _IGNORED_CONTENT_TAGS = {"script", "style", "template", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._ignored_stack = []
        self.divs = []

    @staticmethod
    def _tag_tokens(value):
        return {
            token
            for token in re.split(r"[\s,]+", str(value or "").strip().lower())
            if token
        }

    def handle_starttag(self, tag, attrs):
        name = str(tag or "").lower()
        if self._ignored_stack:
            if name in self._IGNORED_CONTENT_TAGS:
                self._ignored_stack.append(name)
            return
        if name in self._IGNORED_CONTENT_TAGS:
            self._ignored_stack.append(name)
            return
        if name != "div":
            return
        attr_map = {}
        duplicate_attrs = set()
        for raw_name, raw_value in attrs:
            key = str(raw_name or "").lower()
            if key in attr_map:
                duplicate_attrs.add(key)
            attr_map[key] = "" if raw_value is None else str(raw_value)
        mode = str(attr_map.get("data-qb-live-mode") or "").strip().lower()
        self.divs.append({
            "index": len(self.divs),
            "mode": mode,
            "live_tags": sorted(self._tag_tokens(attr_map.get("data-qb-live-tag"))),
            "duplicate_attrs": sorted(duplicate_attrs),
        })

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        name = str(tag or "").lower()
        if name in self._IGNORED_CONTENT_TAGS and self._ignored_stack:
            self._ignored_stack.pop()

    def handle_endtag(self, tag):
        name = str(tag or "").lower()
        if self._ignored_stack and name == self._ignored_stack[-1]:
            self._ignored_stack.pop()


def _inspect_div_live_tags(html):
    parser = _DivLiveTagParser()
    parser.feed(html or "")
    parser.close()
    # 未声明 data-qb-live-mode 的区域就是快照静态区域，必须保持原 DOM，
    # 不再为了声明 static 而改写用户 HTML。只有显式 live 区域受 QBS tag 合同约束。
    invalid = [
        item for item in parser.divs
        if (item["mode"] and item["mode"] not in {"static", "live"})
        or "data-qb-live-mode" in item["duplicate_attrs"]
        or "data-qb-live-tag" in item["duplicate_attrs"]
        or (item["mode"] == "live" and not item["live_tags"])
        or (item["mode"] != "live" and bool(item["live_tags"]))
    ]
    formula_live = [
        item for item in parser.divs
        if item["mode"] == "live" and "qbs-formula-package" in item["live_tags"]
    ]
    grant_live = [
        item for item in parser.divs
        if item["mode"] == "live" and "qbs-data-grant" in item["live_tags"]
    ]
    unknown_live_tags = [
        item for item in parser.divs
        if item["mode"] == "live"
        and any(tag not in {"qbs-formula-package", "qbs-data-grant"} for tag in item["live_tags"])
    ]
    return {
        "div_count": len(parser.divs),
        "unmarked_static_div_count": sum(1 for item in parser.divs if not item["mode"]),
        "explicit_static_div_count": sum(1 for item in parser.divs if item["mode"] == "static"),
        "invalid_divs": invalid,
        "unknown_live_tag_divs": unknown_live_tags,
        "formula_live_div_count": len(formula_live),
        "grant_live_div_count": len(grant_live),
        "ok": not invalid and not unknown_live_tags,
    }


def _find_html_tag_end(html, start):
    quote = None
    index = start + 1
    while index < len(html):
        char = html[index]
        if quote:
            if char == quote:
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == ">":
            return index
        index += 1
    return -1


def _strip_div_runtime_attrs(attrs):
    """Remove the two QBV div runtime attributes while preserving other bytes."""
    output = []
    index = 0
    length = len(attrs)
    while index < length:
        token_start = index
        while index < length and attrs[index].isspace():
            index += 1
        if index >= length:
            output.append(attrs[token_start:])
            break
        name_start = index
        while index < length and not attrs[index].isspace() and attrs[index] not in "=/>":
            index += 1
        if index == name_start:
            output.append(attrs[token_start:index + 1])
            index += 1
            continue
        name = attrs[name_start:index].lower()
        while index < length and attrs[index].isspace():
            index += 1
        if index < length and attrs[index] == "=":
            index += 1
            while index < length and attrs[index].isspace():
                index += 1
            if index < length and attrs[index] in {'"', "'"}:
                quote = attrs[index]
                index += 1
                while index < length:
                    if attrs[index] == quote:
                        index += 1
                        break
                    index += 1
            else:
                while index < length and not attrs[index].isspace() and attrs[index] not in "/>":
                    index += 1
        if name not in {"data-qb-live-mode", "data-qb-live-tag"}:
            output.append(attrs[token_start:index])
    return "".join(output)


def _rewrite_div_start_tag_static(raw_tag):
    match = re.match(r"(?is)<\s*div\b", raw_tag or "")
    if not match:
        return raw_tag
    close_start = len(raw_tag) - 1
    if close_start < 0 or raw_tag[close_start] != ">":
        return raw_tag
    slash_index = close_start - 1
    while slash_index >= match.end() and raw_tag[slash_index].isspace():
        slash_index -= 1
    suffix_start = slash_index if slash_index >= match.end() and raw_tag[slash_index] == "/" else close_start
    attrs = raw_tag[match.end():suffix_start]
    cleaned = _strip_div_runtime_attrs(attrs)
    trimmed = cleaned.rstrip()
    trailing = cleaned[len(trimmed):]
    return (
        raw_tag[:match.end()]
        + trimmed
        + ' data-qb-live-mode="static"'
        + trailing
        + raw_tag[suffix_start:]
    )


def _mark_source_html_static(html):
    """Add a non-visual static declaration to every rendered div in source HTML."""
    source = str(html or "")
    output = []
    ignored_stack = []
    ignored_tags = {"script", "style", "template", "noscript"}
    index = 0
    while index < len(source):
        if source.startswith("<!--", index):
            end = source.find("-->", index + 4)
            end = len(source) if end < 0 else end + 3
            output.append(source[index:end])
            index = end
            continue
        if source[index] != "<":
            output.append(source[index])
            index += 1
            continue
        end = _find_html_tag_end(source, index)
        if end < 0:
            output.append(source[index:])
            break
        raw_tag = source[index:end + 1]
        identity = re.match(r"(?is)<\s*(/?)\s*([a-z][a-z0-9:-]*)\b", raw_tag)
        if not identity:
            output.append(raw_tag)
            index = end + 1
            continue
        closing = bool(identity.group(1))
        name = identity.group(2).lower()
        self_closing = bool(re.search(r"/\s*>$", raw_tag))
        if ignored_stack:
            if closing and name == ignored_stack[-1]:
                ignored_stack.pop()
            elif not closing and not self_closing and name in ignored_tags:
                ignored_stack.append(name)
            output.append(raw_tag)
        else:
            if not closing and not self_closing and name in ignored_tags:
                ignored_stack.append(name)
                output.append(raw_tag)
            elif not closing and name == "div":
                output.append(_rewrite_div_start_tag_static(raw_tag))
            else:
                output.append(raw_tag)
        index = end + 1
    return "".join(output)


def _preserve_html_signatures(html):
    parser = _PreserveHtmlParser()
    parser.feed(html or "")
    parser.close()
    return parser.dom, parser.text


def _style_attr_value(attrs, name):
    match = re.search(
        rf"(?is)(?:^|\s){re.escape(name)}\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
        attrs or "",
    )
    if not match:
        return None
    return next((value for value in match.groups() if value is not None), None)


def _standard_live_indicator_style_version(attrs, css):
    version = _style_attr_value(attrs, "data-qb-live-indicator-runtime")
    expected = _LIVE_INDICATOR_STYLES.get(version)
    if expected is None or str(css or "").strip() != expected:
        return None
    return version


def _is_standard_live_indicator_style(attrs, css):
    return _standard_live_indicator_style_version(attrs, css) is not None


def _live_indicator_style_count(html, *, version=None):
    return sum(
        1
        for match in re.finditer(r"(?is)<style\b(?P<attrs>[^>]*)>(?P<css>.*?)</style\s*>", html or "")
        if _standard_live_indicator_style_version(match.group("attrs"), match.group("css"))
        == (version or _LIVE_INDICATOR_VERSION)
    )


def _strip_standard_live_indicator_styles(html):
    def replace(match):
        if _is_standard_live_indicator_style(match.group("attrs"), match.group("css")):
            return ""
        return match.group(0)

    return re.sub(
        r"(?is)<style\b(?P<attrs>[^>]*)>(?P<css>.*?)</style\s*>",
        replace,
        str(html or ""),
    )


def _visible_live_indicator_result(html, div_live_check=None):
    div_check = div_live_check or _inspect_div_live_tags(html)
    formula_count = int(div_check.get("formula_live_div_count") or 0)
    grant_count = int(div_check.get("grant_live_div_count") or 0)
    return {
        "version": _LIVE_INDICATOR_VERSION,
        "enabled": _live_indicator_style_count(html) == 1 and (formula_count + grant_count) > 0,
        "formula_live_div_count": formula_count,
        "grant_live_div_count": grant_count,
    }


def _inject_visible_live_indicator(html, div_live_check=None):
    source = str(html or "")
    div_check = div_live_check or _inspect_div_live_tags(source)
    if not (div_check.get("formula_live_div_count") or div_check.get("grant_live_div_count")):
        return source, _visible_live_indicator_result(source, div_check)
    if _live_indicator_style_count(source) == 1:
        return source, _visible_live_indicator_result(source, div_check)
    source = _strip_standard_live_indicator_styles(source)
    head_close = re.search(r"(?is)</head\s*>", source)
    if head_close:
        source = source[:head_close.start()] + "\n" + _LIVE_INDICATOR_STYLE_TAG + "\n" + source[head_close.start():]
    else:
        body_open = re.search(r"(?is)<body\b", source)
        insert_at = body_open.start() if body_open else 0
        source = source[:insert_at] + _LIVE_INDICATOR_STYLE_TAG + "\n" + source[insert_at:]
    return source, _visible_live_indicator_result(source, div_check)


def _preserve_html_style_sha256(html):
    blocks = []
    for match in re.finditer(r"(?is)<style\b(?P<attrs>[^>]*)>(?P<css>.*?)</style\s*>", html or ""):
        if _is_standard_live_indicator_style(match.group("attrs"), match.group("css")):
            continue
        blocks.append(match.group("css").strip())
    canonical = "\n\n".join(blocks)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _has_qbs_runtime_call(html, *, packages, grants):
    source = html or ""
    package_runtime = bool(re.search(r"(?:\bQB\s*\.\s*(?:query|queryMany)\s*\(|/skill/queryFormulaPackage\b|\bqueryFormulaPackage\s*\()", source, flags=re.I))
    grant_runtime = bool(re.search(r"(?:\bQB\s*\.\s*queryGrant\s*\(|/skill/queryDataGrant\b|\bqueryDataGrant\s*\()", source, flags=re.I))
    return {
        "package_runtime": package_runtime if packages else None,
        "grant_runtime": grant_runtime if grants else None,
        "ok": (not packages or package_runtime) and (not grants or grant_runtime),
    }


def _has_live_refresh_binding(html):
    source = html or ""
    shell_refresh = bool(re.search(
        r"QBShareShell\s*\.\s*init\s*\(\s*\{[\s\S]{0,16000}?\bonRefresh\s*:\s*(?!null\b|undefined\b|false\b)",
        source,
        flags=re.I,
    ))
    marked_control = bool(re.search(r"\bdata-qb-live-refresh(?:\s|=|>)", source, flags=re.I))
    click_binding = bool(re.search(r"addEventListener\s*\(\s*['\"]click['\"]", source, flags=re.I))
    return {
        "share_shell_on_refresh": shell_refresh,
        "marked_refresh_control": marked_control,
        "click_binding": click_binding,
        "ok": shell_refresh or (marked_control and click_binding),
    }


def _validate_registered_qbs_credentials(endpoint, packages, grants):
    checks = []
    if packages:
        import formula_package as FP
        for item in packages:
            try:
                response = FP.query_package(endpoint, item["package_id"], item["signature"])
            except Exception as exc:
                response = {"code": 1, "error": "QUERY_EXCEPTION", "message": str(exc)}
            ok = isinstance(response, dict) and response.get("code") == 0
            checks.append({"kind": "package", "credential_id": item["package_id"], "ok": ok})
            if not ok:
                return checks, _evidence_error(
                    "PRESERVE_HTML_QBS_CREDENTIAL_QUERY_FAILED",
                    f"公式包 {item['package_id']} 无法用页面 signature 查询，拒绝把页面标记为 QBS 活页",
                    credential_kind="package",
                    credential_id=item["package_id"],
                    details=response,
                )
    if grants:
        import data_grant as DG
        for item in grants:
            try:
                response = DG.query_grant(endpoint, item["grant_id"], item["signature"])
            except Exception as exc:
                response = {"code": 1, "error": "QUERY_EXCEPTION", "message": str(exc)}
            ok = isinstance(response, dict) and response.get("code") == 0
            checks.append({"kind": "grant", "credential_id": item["grant_id"], "ok": ok})
            if not ok:
                return checks, _evidence_error(
                    "PRESERVE_HTML_QBS_CREDENTIAL_QUERY_FAILED",
                    f"Data Grant {item['grant_id']} 无法用页面 signature 查询，拒绝把页面标记为 QBS 活页",
                    credential_kind="grant",
                    credential_id=item["grant_id"],
                    details=response,
                )
    return checks, None



def _read_verified_html_file(path_value, sha_value, *, prefix, label):
    file_path = _fork_path(path_value)
    expected_sha256 = str(sha_value or "").strip().lower()
    if not file_path or not os.path.isfile(file_path):
        return None, _evidence_error(
            f"{prefix}_REQUIRED",
            f"preserve_html_qbs_live 必须提供可读取的 {label}",
            **{label: file_path},
        )
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        return None, _evidence_error(
            f"{prefix}_SHA256_REQUIRED",
            f"{label.replace('_file', '_sha256')} 必须是文件的 64 位 SHA256",
        )
    try:
        raw_bytes = Path(file_path).read_bytes()
        html = raw_bytes.decode("utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return None, _evidence_error(f"{prefix}_INVALID", f"读取 {label} 失败: {exc}")
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if not secrets.compare_digest(actual_sha256, expected_sha256):
        return None, _evidence_error(
            f"{prefix}_SHA256_MISMATCH",
            f"{label.replace('_file', '_sha256')} 与文件不一致",
            expected_sha256=expected_sha256,
            actual_sha256=actual_sha256,
        )
    return {
        "file": file_path,
        "html": html,
        "sha256": actual_sha256,
    }, None


def _read_verified_preserve_source(params):
    params = params if isinstance(params, dict) else {}
    source, error = _read_verified_html_file(
        params.get("source_html_file"),
        params.get("source_html_sha256"),
        prefix="PRESERVE_HTML_SOURCE",
        label="source_html_file",
    )
    if error:
        return None, error
    return {
        "source_file": source["file"],
        "source_html": source["html"],
        "source_html_sha256": source["sha256"],
    }, None


def _source_html_has_async_runtime(html):
    return bool(re.search(
        r"(?:\bfetch\s*\(|\baxios\s*(?:\.|\()|\bXMLHttpRequest\b|\bEventSource\s*\(|\bWebSocket\s*\()",
        html or "",
        flags=re.I,
    ))


def _read_verified_preserve_snapshot(params, source=None):
    params = params if isinstance(params, dict) else {}
    source = source or _read_verified_preserve_source(params)[0]
    snapshot_file = params.get("source_snapshot_html_file")
    snapshot_sha256 = params.get("source_snapshot_html_sha256")
    if snapshot_file or snapshot_sha256:
        snapshot, error = _read_verified_html_file(
            snapshot_file,
            snapshot_sha256,
            prefix="PRESERVE_HTML_SOURCE_SNAPSHOT",
            label="source_snapshot_html_file",
        )
        if error:
            return None, error
        return {
            "snapshot_file": snapshot["file"],
            "snapshot_html": snapshot["html"],
            "snapshot_html_sha256": snapshot["sha256"],
            "snapshot_kind": "rendered",
        }, None
    if source is None:
        source, source_error = _read_verified_preserve_source(params)
        if source_error:
            return None, source_error
    if _source_html_has_async_runtime(source["source_html"]):
        return None, _evidence_error(
            "PRESERVE_HTML_SOURCE_SNAPSHOT_REQUIRED",
            "来源 HTML 包含异步接口；必须先捕获渲染完成且已冻结旧脚本的页面快照，并传 source_snapshot_html_file/source_snapshot_html_sha256",
        )
    return {
        "snapshot_file": source["source_file"],
        "snapshot_html": source["source_html"],
        "snapshot_html_sha256": source["source_html_sha256"],
        "snapshot_kind": "source_static",
    }, None


def _preserve_fallback_status(params):
    route, error = _read_evidence_receipt((params or {}).get("route_receipt_file"), "live data route receipt")
    if error or not isinstance(route, dict):
        return "failed"
    selected = route.get("selected_routes") if isinstance(route.get("selected_routes"), list) else []
    if route.get("status") == "incomplete":
        return "partial"
    if selected and route.get("required_roles_complete") is not True:
        return "partial"
    return "failed"


def _prepare_preserve_html_fallback(params, transformation_error):
    if not _is_preserve_html_qbs_live(params):
        return None, transformation_error
    source, source_error = _read_verified_preserve_source(params)
    if source_error:
        return None, source_error
    snapshot, snapshot_error = _read_verified_preserve_snapshot(params, source=source)
    if snapshot_error:
        return None, snapshot_error
    # 快照保底必须字节语义不变：不注入 static tag、不注入 LIVE、不重做错误页。
    fallback_html = snapshot["snapshot_html"]
    return {
        "html": fallback_html,
        "status": _preserve_fallback_status(params),
        "validation": {
            "mode": _PRESERVE_HTML_QBS_LIVE_MODE,
            "source_html_file": source["source_file"],
            "source_html_sha256": source["source_html_sha256"],
            "source_snapshot_html_file": snapshot["snapshot_file"],
            "snapshot_html_sha256": snapshot["snapshot_html_sha256"],
            "snapshot_kind": snapshot["snapshot_kind"],
            "snapshot_preserved_byte_for_byte": True,
            "content_structure_preserved": True,
            "layout_preserved": True,
            "live_data_mode": "static_snapshot",
        },
    }, None


def _attach_transformation_outcome(out, *, params, validation, error, fallback):
    if not isinstance(out, dict):
        return
    if str((params or {}).get("transformation_mode") or "").strip() != _PRESERVE_HTML_QBS_LIVE_MODE:
        return
    out["transformation_status"] = fallback["status"] if fallback else "complete"
    out["source_html_fallback_published"] = bool(fallback and out.get("code") == 0)
    if validation:
        out["transformation_validation"] = validation
    if error:
        out["transformation_error"] = error

def _validate_transformation_contract(params, html, *, endpoint):
    """Fail closed for local HTML -> QBS live migration, without affecting static uploads."""
    params = params if isinstance(params, dict) else {}
    mode = str(params.get("transformation_mode") or "").strip()
    if not mode:
        return None, None
    if mode != _PRESERVE_HTML_QBS_LIVE_MODE:
        return None, _evidence_error(
            "TRANSFORMATION_MODE_UNSUPPORTED",
            f"transformation_mode 仅支持 {_PRESERVE_HTML_QBS_LIVE_MODE}",
        )
    if params.get("content_structure_preserved") is not True or params.get("layout_preserved") is not True:
        return None, _evidence_error(
            "PRESERVE_HTML_CONTRACT_REQUIRED",
            "preserve_html_qbs_live 必须显式声明 content_structure_preserved=true 且 layout_preserved=true",
        )
    if str(params.get("live_data_mode") or "").strip() != "live":
        return None, _evidence_error(
            "PRESERVE_HTML_LIVE_MODE_REQUIRED",
            "preserve_html_qbs_live 只允许 live_data_mode=live",
        )
    if params.get("ensure_share_shell") is True or params.get("refresh_share_shell") is True:
        return None, _evidence_error(
            "PRESERVE_HTML_SHELL_MUTATION_FORBIDDEN",
            "preserve_html_qbs_live 不允许自动注入或刷新 Share Shell；这会改变用户原始 DOM/CSS",
        )

    source, source_error = _read_verified_preserve_source(params)
    if source_error:
        return None, source_error
    source_file = source["source_file"]
    source_html = source["source_html"]
    actual_sha256 = source["source_html_sha256"]
    snapshot, snapshot_error = _read_verified_preserve_snapshot(params, source=source)
    if snapshot_error:
        return None, snapshot_error
    snapshot_html = snapshot["snapshot_html"]

    source_endpoints = _unique_strings(params.get("source_data_endpoints"))
    if not source_endpoints:
        return None, _evidence_error(
            "PRESERVE_HTML_SOURCE_ENDPOINTS_REQUIRED",
            "必须声明来源 HTML 使用的非 QBS 数据接口 source_data_endpoints",
        )
    missing_from_source = [value for value in source_endpoints if value not in source_html]
    still_in_target = [value for value in source_endpoints if value in (html or "")]
    if missing_from_source:
        return None, _evidence_error(
            "PRESERVE_HTML_SOURCE_ENDPOINT_NOT_FOUND",
            "source_data_endpoints 中的接口未在来源 HTML 出现",
            endpoints=missing_from_source,
        )
    if still_in_target:
        return None, _evidence_error(
            "PRESERVE_HTML_NON_QBS_ENDPOINT_REMAINS",
            "目标 HTML 仍引用来源非 QBS 接口，尚未完成 QBS 活页化",
            endpoints=still_in_target,
        )

    source_structure, source_content = _preserve_html_signatures(snapshot_html)
    target_structure, target_content = _preserve_html_signatures(html)
    if source_structure != target_structure:
        return None, _evidence_error(
            "PRESERVE_HTML_STRUCTURE_CHANGED",
            "目标 HTML 的非运行时 DOM 结构或稳定属性与来源 HTML 不一致；只允许替换数据获取和绑定逻辑",
            source_node_count=len(source_structure),
            target_node_count=len(target_structure),
        )
    if source_content != target_content:
        return None, _evidence_error(
            "PRESERVE_HTML_CONTENT_CHANGED",
            "目标 HTML 的可见静态正文与来源 HTML 不一致，不得删减、改写或简化用户内容",
            source_text_node_count=len(source_content),
            target_text_node_count=len(target_content),
        )
    source_style_sha256 = _preserve_html_style_sha256(snapshot_html)
    target_style_sha256 = _preserve_html_style_sha256(html)
    if source_style_sha256 != target_style_sha256:
        return None, _evidence_error(
            "PRESERVE_HTML_LAYOUT_CHANGED",
            "目标 HTML 的内联 CSS 与来源 HTML 不一致；preserve_html_qbs_live 不允许重做页面布局",
            source_style_sha256=source_style_sha256,
            target_style_sha256=target_style_sha256,
        )
    if _page_headings(snapshot_html) != _page_headings(html):
        return None, _evidence_error(
            "PRESERVE_HTML_HEADINGS_CHANGED",
            "目标 HTML 的标题层级文案与来源 HTML 不一致，不得简化用户内容",
        )

    evidence_error = _validate_publish_data_evidence(params, allow_partial=True)
    if evidence_error:
        return None, evidence_error
    route, route_error = _read_evidence_receipt(params.get("route_receipt_file"), "live data route receipt")
    if route_error:
        return None, route_error
    selected_routes = route.get("selected_routes") if isinstance(route.get("selected_routes"), list) else []
    needs_package = any(str(item.get("kind") or "") == "formula" for item in selected_routes if isinstance(item, dict))
    needs_grant = any(str(item.get("kind") or "") != "formula" for item in selected_routes if isinstance(item, dict))

    packages = _extract_package_credentials(html)
    grants = _extract_grant_credentials(html)
    if needs_package and not packages:
        return None, _evidence_error(
            "PRESERVE_HTML_FORMULA_PACKAGE_REQUIRED",
            "QBS 路由包含计算指标，但目标 HTML 没有公式包凭证",
        )
    if needs_grant and not grants:
        return None, _evidence_error(
            "PRESERVE_HTML_DATA_GRANT_REQUIRED",
            "QBS 路由包含直取数据，但目标 HTML 没有 Data Grant 凭证",
        )
    if not packages and not grants:
        return None, _evidence_error(
            "PRESERVE_HTML_QBS_CREDENTIALS_REQUIRED",
            "目标 HTML 必须包含已注册公式包或 Data Grant 的 credential/signature",
        )

    div_live_check = _inspect_div_live_tags(html)
    if not div_live_check["ok"]:
        return None, _evidence_error(
            "PRESERVE_HTML_DIV_LIVE_MODE_INVALID",
            "目标 HTML 的显式 live/static 声明含非法 mode、重复属性或未知 QBS live tag",
            div_live_check=div_live_check,
        )
    if needs_package and div_live_check["formula_live_div_count"] < 1:
        return None, _evidence_error(
            "PRESERVE_HTML_FORMULA_LIVE_TAG_REQUIRED",
            "公式包驱动的实时区域必须在 live div 上声明 data-qb-live-tag=qbs-formula-package",
            div_live_check=div_live_check,
        )
    if needs_grant and div_live_check["grant_live_div_count"] < 1:
        return None, _evidence_error(
            "PRESERVE_HTML_GRANT_LIVE_TAG_REQUIRED",
            "Data Grant 驱动的实时区域必须在 live div 上声明 data-qb-live-tag=qbs-data-grant",
            div_live_check=div_live_check,
        )

    runtime_check = _has_qbs_runtime_call(html, packages=packages, grants=grants)
    if not runtime_check["ok"]:
        return None, _evidence_error(
            "PRESERVE_HTML_QBS_RUNTIME_REQUIRED",
            "目标 HTML 有 QBS 凭证但没有对应 queryFormulaPackage/queryDataGrant 运行时调用",
            runtime_check=runtime_check,
        )
    refresh_check = _has_live_refresh_binding(html)
    if not refresh_check["ok"]:
        return None, _evidence_error(
            "PRESERVE_HTML_REFRESH_BINDING_REQUIRED",
            "目标 HTML 必须把刷新按钮或 Share Shell onRefresh 绑定到实时加载逻辑",
            refresh_check=refresh_check,
        )

    credential_checks, credential_error = _validate_registered_qbs_credentials(endpoint, packages, grants)
    if credential_error:
        return None, credential_error
    return {
        "mode": _PRESERVE_HTML_QBS_LIVE_MODE,
        "source_html_file": source_file,
        "source_html_sha256": actual_sha256,
        "source_snapshot_html_file": snapshot["snapshot_file"],
        "snapshot_html_sha256": snapshot["snapshot_html_sha256"],
        "snapshot_kind": snapshot["snapshot_kind"],
        "snapshot_preserved_byte_for_byte": True,
        "transformation_status": "complete" if route.get("required_roles_complete") is True else "partial",
        "content_structure_preserved": True,
        "layout_preserved": True,
        "source_data_endpoints_removed": source_endpoints,
        "package_ids": sorted({item["package_id"] for item in packages}),
        "grant_ids": sorted({item["grant_id"] for item in grants}),
        "runtime_check": runtime_check,
        "refresh_check": refresh_check,
        "credential_checks": credential_checks,
        "div_live_check": div_live_check,
    }, None


def _validate_progress_evidence(params):
    params = params or {}
    task_id = _fork_task_id(params)
    current_step = str(params.get("current_step") or "").strip()
    page_status = str(params.get("page_status") or "running").strip().lower()
    guarded_steps = {"package_register", "html_build", "verify", "final_publish"}
    if not task_id or current_step not in guarded_steps or page_status in ("failed", "waiting_input"):
        return None
    if str(params.get("validation_not_required_reason") or "").strip():
        return _evidence_error("LEGACY_VALIDATION_WAIVER_FORBIDDEN", "自由文本 validation_not_required_reason 已停用；必须提供结构化实时数据证据")
    if params.get("live_data_mode") or current_step == "final_publish":
        return _validate_publish_data_evidence(params)

    # package_register/html_build/verify 的既有公式验证进度仍接受公式收据；
    # final_publish 则必须升级为统一路由收据。
    receipt_files = _receipt_files(params.get("validation_receipt_files"))
    if not receipt_files:
        return _evidence_error("PROGRESS_EVIDENCE_REQUIRED", f"task_id={task_id} 推进到 {current_step} 前需要已完成的验证收据")
    invalid = []
    valid_count = 0
    for raw_path in receipt_files:
        receipt, error = _read_evidence_receipt(raw_path, "formula receipt")
        if error or not _valid_formula_receipt(receipt, task_id):
            invalid.append({"file": _fork_path(raw_path), "reason": "receipt must match task_id and be completed success with no failures"})
        else:
            valid_count += 1
    if invalid or valid_count == 0:
        return _evidence_error("PROGRESS_EVIDENCE_INVALID", "验证收据失败、仍在排队或与当前 task_id 不一致，拒绝推进进度", invalid_receipts=invalid)
    return None


def _progress_publish_payload(params, html, *, require_page_id=False, state=None):
    payload = {"html": html}
    if require_page_id:
        payload["page_id"] = params.get("page_id")
    payload["ensure_share_shell"] = params.get("ensure_share_shell", True)
    payload["theme"] = params.get("theme") if isinstance(params.get("theme"), dict) else dict(_PROGRESS_SHELL_THEME)
    payload["_suppress_agent_reply_fallback"] = True
    # 进度快照不是正式业务页面，显式空标签可阻止服务端对临时文案异步自动打标。
    payload["scene_tags"] = params.get("scene_tags") if "scene_tags" in params else []
    payload["paradigm_tags"] = params.get("paradigm_tags") if "paradigm_tags" in params else []

    for k in (
        "ttl_days",
        "scene_tags",
        "paradigm_tags",
        "user_query",
        "tagging_method",
        "tagging_source",
        "tagging_meta",
        "page_context",
        "agent_reply_template",
        "change_note",
        "change_aspect",
    ):
        if params.get(k) is not None:
            payload[k] = params[k]
    if params.get("title") is not None:
        payload["title"] = params["title"]
    elif not require_page_id:
        payload["title"] = "活页生成中"
    if params.get("description") is not None:
        payload["description"] = params["description"]
    elif not require_page_id:
        payload["description"] = "活页生成进度，最终内容会在同一个链接显示。"
    if require_page_id and params.get("change_note") is None:
        payload["change_note"] = _progress_change_note(state or PP.build_state(params))
    return payload


def _attach_progress_result(out, state, params=None):
    if isinstance(out, dict):
        _attach_agent_reply_hint(out, resource_role="existing_page")
        hint = out.get("agent_reply_hint") if isinstance(out.get("agent_reply_hint"), dict) else None
        if hint is not None:
            waiting = state.get("page_status") == "waiting_input"
            hint["interaction_required"] = waiting
            if waiting:
                required_input = state.get("required_input") or {}
                trace_context = C.current_trace_context()
                waiting_context = {
                    "required_input": required_input,
                    "task_id": (params or {}).get("task_id") or trace_context.get("task_id") or "",
                    "page_id": (params or {}).get("page_id") or out.get("page_id") or "",
                    "resume_step": required_input.get("resume_step") or state.get("current_step") or "",
                }
                if not _delivery_policy():
                    waiting_context["public_url"] = out.get("url") or out.get("public_url") or ""
                hint.update(waiting_context)
        out["progress"] = state
        out["steps"] = state.get("steps") or []
        out["progress_page"] = {
            "mode": "progress_snapshot",
            "refresh_owner": "host_page",
            "auto_refresh": False,
        }
    return out


_ROUTING_CREDENTIAL_VERSION = "routing_credential_v1"
_ROUTING_CREDENTIAL_FILE = "routing-credential.json"
_ROUTING_DECISION_VERSION = "routing_decision_v1"
_ROUTING_FORK_REASON_CODES = {
    "same_paradigm_different_asset",
    "same_paradigm_different_scope",
    "same_paradigm_augment_dimension",
    "user_requests_template_changes",
}
_ROUTING_UNMATCHED_REASON_CODES = {
    "no_relevant_candidate",
    "paradigm_mismatch",
    "page_shape_mismatch",
    "required_capability_missing",
    "user_requires_bespoke",
}
_FORK_BORROW_MODES = ("inherit", "inherit_augment", "compose")


def _routing_task_id(params):
    """路由门禁用的 task_id：先看显式参数，再看 QBV_TASK_ID 环境变量
    （Agent harness 跨进程传递 trace 的通道）。刻意不读进程内 ambient trace，
    避免单测里残留的全局 task_id 误触门禁。"""
    params = params if isinstance(params, dict) else {}
    return str(params.get("task_id") or os.environ.get("QBV_TASK_ID", "") or "").strip()


def _routing_credential_path(task_id, *, create_parent=False):
    return str(C.task_temp_path(task_id, _ROUTING_CREDENTIAL_FILE, create_parent=create_parent))


def _read_routing_credential(task_id):
    task_id = str(task_id or "").strip()
    if not task_id:
        return None, "", None
    try:
        path = _routing_credential_path(task_id)
    except (OSError, ValueError) as exc:
        return None, "", {"code": 1, "error": "ROUTING_CREDENTIAL_INVALID", "message": str(exc)}
    if not os.path.isfile(path):
        return None, path, None
    try:
        with open(path, encoding="utf-8") as handle:
            cred = json.load(handle)
    except (OSError, ValueError) as exc:
        return None, path, {
            "code": 1,
            "error": "ROUTING_CREDENTIAL_INVALID",
            "message": f"范式路由凭据读取失败：{exc}",
        }
    if not isinstance(cred, dict) or cred.get("version") != _ROUTING_CREDENTIAL_VERSION:
        return None, path, {
            "code": 1,
            "error": "ROUTING_CREDENTIAL_INVALID",
            "message": "范式路由凭据版本无效",
        }
    if str(cred.get("task_id") or "") != task_id:
        return None, path, {
            "code": 1,
            "error": "ROUTING_CREDENTIAL_INVALID",
            "message": "范式路由凭据不属于当前任务",
        }
    return cred, path, None


def _write_routing_credential_record(cred):
    task_id = str((cred or {}).get("task_id") or "").strip()
    if not task_id:
        return None, {"code": 1, "error": "ROUTING_CREDENTIAL_WRITE_FAILED", "message": "范式路由凭据缺少 task_id"}
    try:
        path = _routing_credential_path(task_id, create_parent=True)
        payload = (json.dumps(cred, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        _atomic_write_bytes(path, payload)
    except (OSError, ValueError) as exc:
        return None, {
            "code": 1,
            "error": "ROUTING_CREDENTIAL_WRITE_FAILED",
            "message": f"写入范式路由凭据失败：{exc}",
        }
    return path, None


def _write_routing_credential(task_id, recommend_scope, item_count, templates_full_sha256):
    """templates 成功后落盘一份范式路由凭据，供 new_page 门禁确认已查过完整范式池。
    仅记录非凭证信息（scope/数量/sha），失败时静默跳过：凭据缺失本身会被门禁拦下。"""
    task_id = str(task_id or "").strip()
    if not task_id:
        return
    cred = {
        "version": _ROUTING_CREDENTIAL_VERSION,
        "task_id": task_id,
        "recommend_scope": str(recommend_scope or ""),
        "item_count": int(item_count or 0),
        "templates_full_sha256": str(templates_full_sha256 or ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_routing_credential_record(cred)


def _routing_credential_error(params):
    """new_page 前置门禁：确认当前任务已用 recommend="all" 查过范式卡。
    无 task_id（legacy/单测/非任务流）时放行；否则要求凭据存在、属于本任务、scope=all。
    返回 error dict 拦截，None 放行。"""
    task_id = _routing_task_id(params)
    if not task_id:
        return None
    cred, _, read_error = _read_routing_credential(task_id)
    if read_error:
        return {
            "code": 1,
            "error": "ROUTING_TEMPLATES_REQUIRED",
            "message": read_error.get("message") or "范式路由凭据读取失败，请用当前 task_id 重新运行 templates(recommend=\"all\")。",
            "task_id": task_id,
        }
    if not cred:
        return {
            "code": 1,
            "error": "ROUTING_TEMPLATES_REQUIRED",
            "message": "建页前必须先查范式卡 templates(recommend=\"all\") 判定 fork/自建，禁止先 new_page 后补查模板造成自建惯性。",
            "task_id": task_id,
        }
    if str(cred.get("recommend_scope") or "") != "all":
        return {
            "code": 1,
            "error": "ROUTING_TEMPLATES_REQUIRED",
            "message": "只查了单一推荐池，请用 templates(recommend=\"all\") 合并官方精选+社区后再判定 fork/自建。",
            "task_id": task_id,
            "recommend_scope": str(cred.get("recommend_scope") or ""),
        }
    return None


def _routing_candidates(task_id, cred):
    try:
        path = str(C.task_temp_path(task_id, "templates-full.json"))
        with open(path, "rb") as handle:
            payload = handle.read()
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        expected_sha256 = str((cred or {}).get("templates_full_sha256") or "").strip().lower()
        if not expected_sha256 or actual_sha256 != expected_sha256:
            raise ValueError("templates 完整候选 SHA256 与路由凭据不一致")
        envelope = json.loads(payload.decode("utf-8-sig"))
        if envelope.get("version") != _TEMPLATES_FULL_RESULT_VERSION:
            raise ValueError("templates 完整候选版本无效")
        if str(envelope.get("task_id") or "") != task_id:
            raise ValueError("templates 完整候选不属于当前 task_id")
        items = _extract_template_items(envelope.get("result") or {})
        if items is None:
            raise ValueError("templates 完整候选缺少 data.items")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, {
            "code": 1,
            "error": "ROUTING_CANDIDATES_INVALID",
            "message": f"无法核验本次范式候选：{exc}",
        }

    index = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        hint = item.get("agent_reply_hint") if isinstance(item.get("agent_reply_hint"), dict) else {}
        source_id = str(
            hint.get("source_template_id")
            or item.get("template_id")
            or item.get("page_id")
            or ""
        ).strip()
        if not source_id:
            continue
        candidate = {
            "source_template_id": source_id,
            "snapshot": _compact_template_item(item),
        }
        for alias in (source_id, item.get("template_id"), item.get("page_id")):
            alias = str(alias or "").strip()
            if alias:
                index[alias] = candidate
    return {"item_count": len(items), "sha256": actual_sha256, "index": index}, None


_DIRECT_COVERAGE_SCOPES = (
    "page_context.core_sections", "page_context.primary_outputs", "page_context.summary",
    "card_required_outputs", "title", "description",
)
_DIRECT_AUTHORITATIVE_SCOPES = ("page_context.primary_outputs", "card_required_outputs")
_DIRECT_LEGACY_AUTHORITATIVE_SCOPES = ("card_required_outputs",)
_DIRECT_REASON_CODE = "direct_full_dimension_coverage"


def _direct_candidate_capabilities(snapshot):
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    page_context = snapshot.get("page_context") if isinstance(snapshot.get("page_context"), dict) else {}
    return {
        "page_context.core_sections": list(page_context.get("core_sections") or []),
        "page_context.primary_outputs": list(page_context.get("primary_outputs") or []),
        "page_context.summary": str(page_context.get("summary") or ""),
        "card_required_outputs": list(snapshot.get("card_required_outputs") or []),
        "title": str(snapshot.get("title") or ""),
        "description": str(snapshot.get("description") or ""),
    }


def _coverage_ref_matches(ref, capabilities, allowed_scopes):
    text = str(ref or "")
    if ":" not in text:
        return False, ""
    scope, token = (part.strip() for part in text.split(":", 1))
    if not scope or not token or scope not in allowed_scopes:
        return False, ""
    value = capabilities.get(scope)
    if isinstance(value, list):
        return token in value, scope
    return token in str(value or ""), scope


def _direct_gate_failure(error, message, source_template_id, capabilities, **extra):
    return {
        "code": 1,
        "error": error,
        "message": message,
        "valid_scopes": list(_DIRECT_COVERAGE_SCOPES),
        "candidate_capabilities": capabilities or {},
        "fork_aug_fallback": {
            "when": "任一用户维度不能由候选页真实能力覆盖时，保持 fork 路由并增强栏目",
            "routing_decision": {
                "mode": "fork", "source_template_id": source_template_id or "page_xxx",
                "reason_code": "same_paradigm_augment_dimension", "borrow_mode": "inherit_augment",
            },
            "next": "fork_prepare 传 augmentation_spec；继承不成立时在 fork 内降为 Compose，禁止改判 unmatched。",
        },
        **extra,
    }


def _validate_direct_delivery_routing(params):
    """Direct 三轴门禁：完整范式池候选（范式）、候选范围选择、逐维度真实能力证据。"""
    task_id = _routing_task_id(params)
    routing_error = _routing_credential_error(params)
    if routing_error:
        return None, routing_error
    cred, _, read_error = _read_routing_credential(task_id)
    if read_error or not cred:
        return None, read_error or _direct_gate_failure(
            "DIRECT_ROUTING_CREDENTIAL_INVALID",
            "无法读取本任务的范式路由凭据，请先运行 templates(recommend=all)。", "", {},
        )
    if str(cred.get("page_id") or "").strip():
        return None, {
            "code": 1, "error": "DIRECT_CONFLICTS_WITH_CREATED_PAGE",
            "message": "当前 task 已创建自有页面，不能再改走 direct。",
            "page_id": str(cred.get("page_id") or ""), "task_id": task_id,
        }
    candidates, candidates_error = _routing_candidates(task_id, cred)
    if candidates_error:
        return None, candidates_error
    page_id = str(params.get("page_id") or "").strip()
    candidate = candidates["index"].get(page_id)
    if not candidate:
        return None, {
            "code": 1, "error": "DIRECT_PAGE_NOT_IN_CANDIDATES",
            "message": "direct 的 page_id 必须来自本次完整范式候选池。",
            "page_id": page_id, "task_id": task_id,
        }
    snapshot = candidate["snapshot"]
    capabilities = _direct_candidate_capabilities(snapshot)
    check = params.get("dimension_check")
    if not isinstance(check, dict) or not isinstance(check.get("coverage"), list) or not check["coverage"]:
        return None, _direct_gate_failure(
            "DIRECT_DIMENSION_CHECK_REQUIRED",
            "direct_deliver 必须提交非空 dimension_check.coverage，逐条覆盖用户请求的全部分析维度。",
            candidate["source_template_id"], capabilities,
        )
    provenance = str(snapshot.get("metadata_provenance") or _PAGE_CONTEXT_OUTPUTS_LEGACY)
    authoritative = (
        _DIRECT_AUTHORITATIVE_SCOPES
        if provenance == _PAGE_CONTEXT_OUTPUTS_DERIVED
        else _DIRECT_LEGACY_AUTHORITATIVE_SCOPES
    )
    normalized = []
    for entry in check["coverage"]:
        if not isinstance(entry, dict) or not str(entry.get("dimension") or "").strip():
            return None, _direct_gate_failure(
                "DIRECT_DIMENSION_CHECK_REQUIRED", "coverage 每项必须包含非空 dimension 和 covered_by。",
                candidate["source_template_id"], capabilities,
            )
        dimension = str(entry["dimension"]).strip()
        refs = entry.get("covered_by")
        if not isinstance(refs, list) or not refs:
            return None, _direct_gate_failure(
                "DIRECT_COVERAGE_REF_REQUIRED", f"维度「{dimension}」缺少 covered_by 能力证据。",
                candidate["source_template_id"], capabilities, dimension=dimension,
            )
        matched_scopes, invalid = [], []
        for ref in refs:
            matched, scope = _coverage_ref_matches(ref, capabilities, _DIRECT_COVERAGE_SCOPES)
            if matched:
                matched_scopes.append(scope)
            else:
                invalid.append(ref)
        if invalid:
            return None, _direct_gate_failure(
                "DIRECT_COVERAGE_REF_INVALID",
                f"维度「{dimension}」引用了候选页不存在的能力：{invalid}。",
                candidate["source_template_id"], capabilities,
                dimension=dimension, invalid_refs=invalid,
            )
        if not any(scope in authoritative for scope in matched_scopes):
            return None, _direct_gate_failure(
                "DIRECT_COVERAGE_NEEDS_AUTHORITATIVE_REF",
                f"维度「{dimension}」只有标题/文案证据，缺少运行时输出证据。",
                candidate["source_template_id"], capabilities,
                dimension=dimension, authoritative_scopes=list(authoritative),
            )
        normalized.append({"dimension": dimension, "covered_by": [str(ref) for ref in refs]})

    decision = {
        "version": _ROUTING_DECISION_VERSION,
        "mode": "direct", "page_id": page_id,
        "source_template_id": candidate["source_template_id"],
        "reason_code": _DIRECT_REASON_CODE,
        "dimension_check": {"version": "dimension_check_v1", "coverage": normalized},
        "candidate_snapshot": snapshot,
        "templates_full_sha256": candidates["sha256"],
    }
    cred["routing_decision"] = decision
    cred["decision_revision"] = int(cred.get("decision_revision") or 0) + 1
    cred["decision_recorded_at"] = datetime.now(timezone.utc).isoformat()
    cred["status"] = "direct_delivering"
    binding_file, write_error = _write_routing_credential_record(cred)
    if write_error:
        return None, write_error
    return {
        "mode": "direct", "page_id": page_id,
        "source_template_id": candidate["source_template_id"],
        "reason_code": _DIRECT_REASON_CODE, "recorded": True,
        "revision": cred["decision_revision"], "binding_file": binding_file,
        "dimension_coverage_count": len(normalized),
    }, None


def _routing_decision_required_error(task_id):
    return {
        "code": 1,
        "error": "ROUTING_DECISION_REQUIRED",
        "message": "templates 后调用 new_page 必须显式提交 routing_decision，说明本次选择 fork 还是 unmatched；语义由 Agent 判断，脚本负责校验候选与留痕。",
        "task_id": task_id,
        "examples": {
            "fork": {
                "mode": "fork",
                "source_template_id": "page_xxx",
                "reason_code": "same_paradigm_different_asset",
                "borrow_mode": "inherit",
            },
            "unmatched": {
                "mode": "unmatched",
                "closest_template_id": "page_xxx",
                "reason_code": "required_capability_missing",
                "reason": "候选模板缺少用户要求的核心能力",
            },
        },
    }


def _validate_routing_decision(params):
    task_id = _routing_task_id(params)
    if not task_id:
        return None, None
    routing_error = _routing_credential_error(params)
    if routing_error:
        return None, routing_error
    decision = params.get("routing_decision")
    if not isinstance(decision, dict):
        return None, _routing_decision_required_error(task_id)

    cred, _, read_error = _read_routing_credential(task_id)
    if read_error or not cred:
        return None, read_error or _routing_decision_required_error(task_id)
    if str(cred.get("page_id") or "").strip():
        return None, {
            "code": 1,
            "error": "ROUTING_PAGE_ALREADY_CREATED",
            "message": "当前 task_id 已经创建过首链，请复用已记录的 page_id，不要重复 new_page。",
            "task_id": task_id,
            "page_id": str(cred.get("page_id") or ""),
        }
    candidates, candidates_error = _routing_candidates(task_id, cred)
    if candidates_error:
        return None, candidates_error

    mode = str(decision.get("mode") or "").strip().lower()
    reason_code = str(decision.get("reason_code") or "").strip()
    if mode == "direct":
        return None, {
            "code": 1,
            "error": "ROUTING_DIRECT_MUST_NOT_CREATE_PAGE",
            "message": "direct 命中不创建新页面，请使用 direct_deliver。",
        }
    if mode == "fork":
        source_id = str(decision.get("source_template_id") or "").strip()
        candidate = candidates["index"].get(source_id)
        if not source_id:
            return None, {"code": 1, "error": "ROUTING_SOURCE_TEMPLATE_REQUIRED", "message": "fork 必须提供 source_template_id"}
        if not candidate:
            return None, {
                "code": 1,
                "error": "ROUTING_SOURCE_NOT_IN_CANDIDATES",
                "message": "source_template_id 不属于本次 templates 候选",
                "source_template_id": source_id,
            }
        if reason_code not in _ROUTING_FORK_REASON_CODES:
            return None, {
                "code": 1,
                "error": "ROUTING_FORK_REASON_INVALID",
                "message": "fork 的 reason_code 不在允许范围",
                "allowed_reason_codes": sorted(_ROUTING_FORK_REASON_CODES),
            }
        borrow_mode = str(decision.get("borrow_mode") or "").strip().lower()
        if borrow_mode not in _FORK_BORROW_MODES:
            return None, {
                "code": 1,
                "error": "FORK_BORROW_MODE_REQUIRED",
                "message": "fork 必须声明 borrow_mode：inherit / inherit_augment / compose。",
                "allowed_borrow_modes": list(_FORK_BORROW_MODES),
            }
        return {
            "version": _ROUTING_DECISION_VERSION,
            "mode": "fork",
            "source_template_id": candidate["source_template_id"],
            "reason_code": reason_code,
            "borrow_mode": borrow_mode,
            "candidate_snapshot": candidate["snapshot"],
            "templates_full_sha256": candidates["sha256"],
        }, None

    if mode == "unmatched":
        closest_id = str(decision.get("closest_template_id") or "").strip()
        reason = str(decision.get("reason") or "").strip()
        candidate = candidates["index"].get(closest_id) if closest_id else None
        if candidates["item_count"] > 0 and not closest_id:
            return None, {
                "code": 1,
                "error": "ROUTING_CLOSEST_CANDIDATE_REQUIRED",
                "message": "存在范式候选时，unmatched 必须指出最接近的 closest_template_id 并说明实质能力缺口。",
            }
        if closest_id and not candidate:
            return None, {
                "code": 1,
                "error": "ROUTING_CLOSEST_CANDIDATE_INVALID",
                "message": "closest_template_id 不属于本次 templates 候选",
                "closest_template_id": closest_id,
            }
        if reason_code in _ROUTING_FORK_REASON_CODES:
            return None, {
                "code": 1,
                "error": "ROUTING_SCOPE_DIFFERENCE_REQUIRES_FORK",
                "message": "范式相同、仅标的或范围不同应选择 fork；如有实质能力缺口，请改用对应 unmatched reason_code 并说明原因。",
                "suggested_mode": "fork",
                "suggested_source_template_id": candidate["source_template_id"] if candidate else "",
            }
        if reason_code not in _ROUTING_UNMATCHED_REASON_CODES:
            return None, {
                "code": 1,
                "error": "ROUTING_UNMATCHED_REASON_INVALID",
                "message": "unmatched 的 reason_code 不在允许范围",
                "allowed_reason_codes": sorted(_ROUTING_UNMATCHED_REASON_CODES),
            }
        if candidates["item_count"] > 0 and not reason:
            return None, {
                "code": 1,
                "error": "ROUTING_UNMATCHED_REASON_REQUIRED",
                "message": "存在范式候选时，unmatched 必须说明最接近候选无法满足的核心要求。",
            }
        return {
            "version": _ROUTING_DECISION_VERSION,
            "mode": "unmatched",
            "closest_template_id": candidate["source_template_id"] if candidate else "",
            "reason_code": reason_code,
            "reason": reason,
            "candidate_snapshot": candidate["snapshot"] if candidate else None,
            "templates_full_sha256": candidates["sha256"],
        }, None

    return None, {
        "code": 1,
        "error": "ROUTING_MODE_INVALID",
        "message": "routing_decision.mode 只能是 fork 或 unmatched",
    }


def _record_routing_decision(params, decision, page_id):
    task_id = _routing_task_id(params)
    if not task_id or not decision:
        return {"mode": "legacy_untracked", "recorded": False}, None
    cred, _, read_error = _read_routing_credential(task_id)
    if read_error or not cred:
        return None, read_error or {
            "code": 1,
            "error": "ROUTING_CREDENTIAL_INVALID",
            "message": "记录 routing_decision 时范式路由凭据丢失",
        }
    cred["routing_decision"] = decision
    cred["page_id"] = str(page_id or "")
    cred["decision_revision"] = int(cred.get("decision_revision") or 0) + 1
    cred["decision_recorded_at"] = datetime.now(timezone.utc).isoformat()
    cred["status"] = "page_created"
    binding_file, write_error = _write_routing_credential_record(cred)
    if write_error:
        return None, write_error
    return {
        "mode": decision.get("mode"),
        "source_template_id": decision.get("source_template_id") or "",
        "closest_template_id": decision.get("closest_template_id") or "",
        "reason_code": decision.get("reason_code") or "",
        "recorded": True,
        "revision": cred["decision_revision"],
        "binding_file": binding_file,
    }, None


def _routing_next_step(task_id, page_id, decision):
    if (decision or {}).get("mode") == "fork":
        if decision.get("borrow_mode") == "compose":
            return {
                "action": "research_templates_then_fork_compose",
                "required_params": {
                    "task_id": task_id,
                    "source_template_id": decision.get("source_template_id") or "",
                    "target_page_id": str(page_id or ""),
                },
            }
        return {
            "action": "fork_prepare",
            "required_params": {
                "task_id": task_id,
                "source_template_id": decision.get("source_template_id") or "",
                "target_page_id": str(page_id or ""),
                "target_asset": "<当前目标标的>",
            },
        }
    return {"action": "build_dashboard_or_bespoke", "publish_command": "publish_final"}


def cmd_new_asset_page(params):
    params = dict(params or {})
    asset = str(params.get("asset") or "").strip()
    if not asset:
        return {
            "code": 1,
            "error": "NEW_ASSET_PAGE_PARAMS_REQUIRED",
            "message": "new_asset_page 需要 asset（要分析的 A 股、港股或美股名称或代码）",
        }

    trace_context = C.current_trace_context()
    task_id = str(params.get("task_id") or trace_context.get("task_id") or "").strip()
    if not task_id:
        return {
            "code": 1,
            "error": "NEW_ASSET_PAGE_PARAMS_REQUIRED",
            "message": "new_asset_page 需要 task_id（先运行 trace_context.py begin）",
        }

    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    body = {"task_id": task_id, "asset": asset}
    user_query = str(params.get("user_query") or trace_context.get("user_query") or "").strip()
    if user_query:
        body["user_query"] = user_query
    if params.get("ttl_days") is not None:
        body["ttl_days"] = params.get("ttl_days")

    out = C.http_json(
        "POST",
        C.api_url(endpoint, _PATH["new_asset_page"]),
        C.headers(api_key),
        body,
        timeout=_UPLOAD_TIMEOUT,
    )
    if not (isinstance(out, dict) and out.get("code") == 0):
        return out

    data_sources = out.get("data_sources")
    if not isinstance(data_sources, dict):
        return {
            "code": 1,
            "error": "NEW_ASSET_PAGE_DATA_SOURCES_REQUIRED",
            "message": "newAssetPage 成功响应缺少 data_sources，无法生成可核验的完整分析回复",
            "operation": "new_asset_page",
            "task_id": task_id,
            "page_id": out.get("page_id") or "",
        }

    try:
        source_artifact = MNAC.persist_data_sources(task_id, data_sources)
    except Exception:
        return {
            "code": 1,
            "error": "NEW_ASSET_PAGE_DATA_SOURCES_PERSIST_FAILED",
            "message": "newAssetPage data_sources 无法安全写入 task 临时目录",
            "operation": "new_asset_page",
            "task_id": task_id,
            "page_id": out.get("page_id") or "",
        }
    try:
        csv_result = MNAC.materialize(task_id, source_artifact["data_sources_file"])
    except MNAC.MaterializeError as exc:
        csv_result = MNAC.persist_failure_artifacts(
            task_id, [{"code": exc.code, "message": exc.message}]
        )
    except Exception:
        csv_result = MNAC.persist_failure_artifacts(
            task_id, [{"code": "CSV_MATERIALIZE_FAILED", "message": "CSV 材料化出现未预期错误"}]
        )

    template_meta = out.get("agent_reply_template")
    normalized_template, template_error = _normalize_agent_reply_template(template_meta, require_local_file=False)
    if (
        template_error
        or not normalized_template
        or normalized_template.get("template_ref") != "single_stock_deep_dive_v1"
    ):
        template_meta = {
            "version": "reply_template_v2",
            "template_ref": "single_stock_deep_dive_v1",
            "reply_scope": "full_answer",
            "output_format": "markdown",
        }
    else:
        template_meta = normalized_template

    safe_fields = (
        "page_id", "url", "title", "description", "asset", "source_page_id",
        "idempotent", "page_context", "expires_at",
    )
    result = {key: out[key] for key in safe_fields if key in out}
    result["warnings"] = MNAC.sanitize_warnings(out.get("warnings") or [])
    result.update({
        "code": 0,
        "operation": "new_asset_page",
        "task_id": task_id,
        "agent_reply_template": template_meta,
    })
    for warning in csv_result.get("warnings") or []:
        _append_warning(result, warning)

    try:
        reply_artifact = RDE.build_new_asset_page(
            task_id,
            "single_stock_deep_dive_v1",
            data_sources,
            csv_result,
        )
    except (OSError, ValueError, TypeError) as exc:
        C.cleanup_task_temp_files(task_id)
        return {
            "code": 1,
            "error": "NEW_ASSET_PAGE_REPLY_EVIDENCE_FAILED",
            "message": f"new_asset_page 回复证据生成失败：{exc}",
            "operation": "new_asset_page",
            "task_id": task_id,
            "page_id": out.get("page_id") or "",
        }
    available_fields = (
        (reply_artifact or {}).get("reply_data_availability", {}).get("available_template_fields") or []
    )
    if not reply_artifact or not available_fields:
        C.cleanup_task_temp_files(task_id)
        return {
            "code": 1,
            "error": "NEW_ASSET_PAGE_EVIDENCE_EMPTY",
            "message": "data_sources 未包含任何可核验回复字段，拒绝退化成单链接回复",
            "operation": "new_asset_page",
            "task_id": task_id,
            "page_id": out.get("page_id") or "",
            "warnings": result.get("warnings") or [],
        }

    _attach_agent_reply_contract(result, operation="new_asset_page")
    _attach_reply_data_contract(result, reply_artifact)
    result.update(source_artifact)
    for key in ("csv_manifest_file", "csv_evidence_file"):
        if csv_result.get(key):
            result[key] = csv_result[key]
    try:
        markdown = SSR.render(
            evidence_file=reply_artifact.get("reply_data_evidence_file"),
            evidence_sha256=reply_artifact.get("reply_data_evidence_sha256"),
            asset=result.get("asset"),
            public_url=(result.get("agent_reply_contract") or {}).get("public_url"),
        )
    except (OSError, ValueError, TypeError) as exc:
        C.cleanup_task_temp_files(task_id)
        return {
            "code": 1,
            "error": "NEW_ASSET_PAGE_REPLY_RENDER_FAILED",
            "message": f"new_asset_page 确定性报告生成失败：{exc}",
            "operation": "new_asset_page",
            "task_id": task_id,
            "page_id": out.get("page_id") or "",
        }
    markdown_sha256 = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    contract = result.get("agent_reply_contract") or {}
    for key in ("reply_data_evidence_file", "reply_data_evidence_sha256", "reply_data_availability"):
        contract.pop(key, None)
        result.pop(key, None)
    contract.pop("template_file", None)
    contract.pop("template_exists", None)
    result.pop("agent_reply_template_file", None)
    contract.update({
        "reply_ready": True,
        "reply_mode": "deterministic_single_stock_v1",
        "agent_reply_markdown_sha256": markdown_sha256,
        "final_response_required": "send_agent_reply_markdown_verbatim",
        "final_response_steps": [
            "Send the top-level agent_reply_markdown verbatim as the final answer.",
            "Do not read temporary evidence, draft a replacement, run reply validation, or invoke another tool.",
        ],
    })
    result.update({
        "reply_ready": True,
        "agent_reply_markdown": markdown,
        "agent_reply_markdown_sha256": markdown_sha256,
    })
    SC.report(
        task_id,
        public_url=contract.get("public_url") or "",
        user_query=user_query,
        operation="new_asset_page",
    )
    C.cleanup_task_temp_files(task_id)
    for key in ("data_sources_file", "data_sources_sha256", "csv_manifest_file", "csv_evidence_file"):
        result.pop(key, None)
    return result


def cmd_new_page(params):
    params = dict(params or {})
    routing_decision, routing_error = _validate_routing_decision(params)
    if routing_error:
        return routing_error
    params.pop("routing_decision", None)
    validation_error = _validate_progress_params(params)
    if validation_error:
        return validation_error
    state, html = _progress_state_and_html(params)
    payload = _progress_publish_payload(params, html, require_page_id=False, state=state)
    out = cmd_upload(payload)
    if not (isinstance(out, dict) and out.get("code") == 0):
        return out
    routing_binding, binding_error = _record_routing_decision(params, routing_decision, out.get("page_id"))
    if binding_error:
        binding_error["created_page_id"] = out.get("page_id") or ""
        binding_error["created_url"] = _record_url(out)
        return binding_error
    if routing_decision:
        out["routing_decision"] = routing_binding
        out["next_step"] = _routing_next_step(_routing_task_id(params), out.get("page_id"), routing_decision)
    return _attach_progress_result(out, state, params)


def cmd_update_progress(params):
    if not params.get("page_id"):
        return {"code": 1, "message": "update_progress 需要 page_id（要更新哪个进度页）"}
    validation_error = _validate_progress_params(params)
    if validation_error:
        return validation_error
    evidence_error = _validate_progress_evidence(params)
    if evidence_error:
        return evidence_error
    state, html = _progress_state_and_html(params)
    payload = _progress_publish_payload(params, html, require_page_id=True, state=state)
    out = cmd_update(payload)
    return _attach_progress_result(out, state, params)


def _publish_final_progress_params(params, *, page_status, message):
    progress_params = {
        "page_id": params.get("page_id"),
        "current_step": "final_publish",
        "page_status": page_status,
        "message": message,
    }
    for key in (
        "title",
        "theme",
        "steps",
        "ensure_share_shell",
        "page_context",
        "agent_reply_template",
        "task_id",
        "live_data_mode",
        "market_data_required",
        "asset",
        "route_receipt_file",
        "validation_receipt_files",
        "grant_validation_receipt_files",
        "handoff_validation_receipt_files",
        "turn_id",
        "validation_not_required_reason",
    ):
        if params.get(key) is not None:
            progress_params[key] = params[key]
    return progress_params


def _normalized_public_url(value):
    return str(value or "").strip().rstrip("/")


def _public_url_page_id(value):
    try:
        path = urllib.parse.urlparse(str(value or "")).path
    except Exception:
        return ""
    name = path.rsplit("/", 1)[-1]
    return name[:-5] if name.endswith(".html") else name


def _publish_final_validation_error(params, update_out, template_resolution, final_html):
    expected_page_id = str(params.get("page_id") or "")
    actual_page_id = str(update_out.get("page_id") or "")
    if actual_page_id != expected_page_id:
        return "publish_final 返回的 page_id 与首链 page_id 不一致"

    public_url = _record_url(update_out)
    if not public_url:
        return "publish_final 未返回最终 public_url"

    source_template_id = str((template_resolution or {}).get("source_template_id") or "")
    source_public_url = (template_resolution or {}).get("source_public_url") or ""
    if source_template_id and _public_url_page_id(public_url) == source_template_id:
        return "publish_final 错误返回了来源模板 URL"
    if source_public_url and _normalized_public_url(public_url) == _normalized_public_url(source_public_url):
        return "publish_final 错误返回了来源模板 URL"

    if _public_url_page_id(public_url) != expected_page_id:
        return "publish_final 返回的 public_url 不属于首链 page_id"

    first_page_url = params.get("first_page_url") or params.get("first_url")
    if first_page_url and _normalized_public_url(public_url) != _normalized_public_url(first_page_url):
        return "publish_final 返回的 public_url 与首链 URL 不一致"

    template = params.get("agent_reply_template") if isinstance(params.get("agent_reply_template"), dict) else {}
    template_ref = template.get("template_ref") or ""
    source_packages = set((template_resolution or {}).get("source_package_ids") or [])
    source_grants = set((template_resolution or {}).get("source_grant_ids") or [])
    final_packages = set(update_out.get("package_ids") or [])
    final_grants = set(update_out.get("grant_ids") or [])
    leaked_packages = sorted(final_packages & source_packages)
    leaked_grants = sorted(final_grants & source_grants)
    if leaked_packages or leaked_grants:
        return "fork 发布后仍含来源凭证: " + ", ".join(leaked_packages + leaked_grants)
    fork_manifest = (template_resolution or {}).get("fork_manifest") or {}
    minimum_packages = int(fork_manifest.get("minimum_target_package_count") or 0)
    minimum_grants = int(fork_manifest.get("minimum_target_grant_count") or 0)
    if len(final_packages) < minimum_packages or len(final_grants) < minimum_grants:
        return (
            "fork 目标实时凭证能力缩水: "
            f"package {len(final_packages)}/{minimum_packages}, "
            f"grant {len(final_grants)}/{minimum_grants}"
        )

    html_requires_live_data = bool(_extract_package_credentials(final_html)) or any(
        token in str(final_html or "")
        for token in ("queryFormulaPackage", "package_id", "packageId", "grant_id", "grantId")
    )
    professional_live = _bool_param(params.get("require_live_data")) or (
        bool(source_template_id)
        and template_ref != "generic_live_page_delivery_v1"
        and html_requires_live_data
    )
    if professional_live:
        if not final_packages and not final_grants:
            return "专业实时模板发布后缺少用户页面自己的 package_ids 或 grant_ids"
    return ""


def _routing_publish_error(error, message, *, page_id="", **extra):
    out = {
        "code": 1,
        "error": error,
        "message": message,
        "recoverable": True,
    }
    if page_id:
        out["page_id"] = page_id
    out.update(extra)
    return out


def _compose_binding_publish_state(cred, page_id):
    binding = cred.get("fork_binding") if isinstance(cred.get("fork_binding"), dict) else None
    if not binding or binding.get("kind") != "compose":
        return None, None
    path = str(binding.get("compose_binding_file") or "")
    expected = str(binding.get("compose_binding_sha256") or "")
    try:
        actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        return None, _routing_publish_error(
            "COMPOSE_BINDING_MISSING", f"Compose 借鉴收据读取失败：{exc}", page_id=page_id,
        )
    if not expected or actual != expected:
        return None, _routing_publish_error(
            "COMPOSE_BINDING_STALE", "Compose 借鉴收据已变化，请重新运行 fork_compose。", page_id=page_id,
        )
    return {**binding, "compose_binding_sha256": expected}, None


def _check_publish_routing_consistency(params, fork_task_binding, routing_override=None):
    task_id = _routing_task_id(params)
    if not task_id:
        return {"checked": False, "mode": "legacy_untracked"}, None
    cred, _, read_error = _read_routing_credential(task_id)
    if read_error:
        return None, read_error
    decision = cred.get("routing_decision") if isinstance((cred or {}).get("routing_decision"), dict) else None
    if not cred or not decision:
        # 兼容升级前已经创建的首链，以及不经 new_page 的旧发布调用。
        return {"checked": False, "mode": "legacy_untracked"}, None

    page_id = str(params.get("page_id") or "")
    bound_page_id = str(cred.get("page_id") or "")
    if bound_page_id and bound_page_id != page_id:
        return None, _routing_publish_error(
            "ROUTING_PAGE_CONFLICT",
            "publish_final 的 page_id 与 new_page 路由记录不一致。",
            page_id=page_id,
            expected_page_id=bound_page_id,
        )

    fork_bound = isinstance(fork_task_binding, dict) and fork_task_binding.get("mode") == "task_binding"
    decision_mode = str(decision.get("mode") or "").strip().lower()
    if decision_mode == "fork":
        if routing_override is not None:
            return None, _routing_publish_error(
                "ROUTING_OVERRIDE_NOT_ALLOWED",
                "fork 一经判定不能改判 unmatched；请继续 inherit/inherit_augment，或在 fork 内转 Compose。",
                page_id=page_id,
                allowed_actions=["fork_prepare", "fork_compose"],
            )
        if fork_bound:
            expected_source = str(decision.get("source_template_id") or "")
            actual_source = str(fork_task_binding.get("source_template_id") or "")
            if expected_source and actual_source != expected_source:
                return None, _routing_publish_error(
                    "ROUTING_FORK_SOURCE_CONFLICT",
                    "fork_prepare 绑定的来源模板与 new_page 路由决定不一致。",
                    page_id=page_id,
                    expected_source_template_id=expected_source,
                    actual_source_template_id=actual_source,
                )
            return {
                "checked": True,
                "decision_mode": "fork",
                "effective_mode": "fork",
                "source_template_id": actual_source,
                "decision_revision": int(cred.get("decision_revision") or 1),
            }, None

        compose_binding, compose_error = _compose_binding_publish_state(cred, page_id)
        if compose_error:
            return None, compose_error
        if compose_binding:
            expected_source = str(decision.get("source_template_id") or "")
            actual_source = str(compose_binding.get("source_template_id") or "")
            if expected_source and expected_source != actual_source:
                return None, _routing_publish_error(
                    "ROUTING_FORK_SOURCE_CONFLICT", "Compose 绑定来源与 fork 路由来源不一致。", page_id=page_id,
                )
            return {
                "checked": True, "decision_mode": "fork", "effective_mode": "fork",
                "borrow_mode": "compose", "source_template_id": actual_source,
                "compose_binding_sha256": compose_binding["compose_binding_sha256"],
                "decision_revision": int(cred.get("decision_revision") or 1),
            }, None

        return None, _routing_publish_error(
            "ROUTING_RECONFIRM_REQUIRED",
            "当前任务已锁定 fork，但尚未建立继承或 Compose 绑定。fork 不能改判 unmatched。",
            page_id=page_id,
            routing_decision=decision,
            allowed_actions=["fork_prepare", "fork_compose"],
        )

    if decision_mode == "unmatched":
        if routing_override is not None:
            return None, _routing_publish_error(
                "ROUTING_OVERRIDE_NOT_APPLICABLE",
                "当前路由已经是 unmatched，不需要 routing_override。",
                page_id=page_id,
            )
        return {
            "checked": True,
            "decision_mode": "unmatched",
            "effective_mode": "fork" if fork_bound else "unmatched",
            "source_template_id": (
                str(fork_task_binding.get("source_template_id") or "") if fork_bound else ""
            ),
            "decision_revision": int(cred.get("decision_revision") or 1),
        }, None

    return None, _routing_publish_error(
        "ROUTING_DECISION_INVALID",
        "路由记录中的 mode 无效，拒绝据此发布。",
        page_id=page_id,
    )


def cmd_publish_final(params):
    params = dict(params or {})
    if not params.get("page_id"):
        return {"code": 1, "message": "publish_final 需要 page_id（要发布到哪个活页链接）"}

    routing_override = params.pop("routing_override", None)
    params, fork_task_binding, binding_error = _apply_fork_task_binding(params)
    if binding_error:
        binding_error.setdefault("page_id", params.get("page_id"))
        binding_error["fork_task_binding"] = {
            "mode": "error",
            "task_id": _fork_task_id(params),
        }
        return binding_error

    routing_consistency, routing_error = _check_publish_routing_consistency(
        params,
        fork_task_binding,
        routing_override=routing_override,
    )
    if routing_error:
        routing_error.setdefault("page_id", params.get("page_id"))
        return routing_error

    final_html, final_html_error = _read_html(params)
    if final_html_error:
        return final_html_error
    params, template_resolution, template_error = _resolve_publish_agent_reply_template(params, html=final_html)
    if template_error:
        return template_error
    preflight = params.pop("_fork_preflight", None)
    preflight_sentinel = params.pop("_fork_preflight_sentinel", None)
    if preflight_sentinel is _FORK_PREFLIGHT_SENTINEL and isinstance(preflight, dict):
        actual_html_sha256 = hashlib.sha256(final_html.encode("utf-8")).hexdigest()
        if preflight.get("html_sha256") != actual_html_sha256:
            return {
                "code": 1,
                "error": "FORK_PREFLIGHT_STALE",
                "message": "fork HTML 在浏览器预检后发生变化，拒绝发布",
                "page_id": params.get("page_id"),
            }
        fork_manifest_resolution = dict(preflight.get("fork_manifest_validation") or {})
        fork_manifest_resolution.pop("ok", None)
        fork_manifest_error = None
    else:
        fork_manifest_resolution, fork_manifest_error = _validate_fork_manifest(
            params,
            template_resolution,
            final_html,
        )
    if fork_manifest_error:
        fork_manifest_error.setdefault("page_id", params.get("page_id"))
        if isinstance(fork_task_binding, dict) and fork_task_binding.get("mode") == "task_binding":
            fork_manifest_error["fork_task_binding"] = fork_task_binding
        fork_manifest_error["fork_manifest_validation"] = {
            "ok": False,
            "source_template_id": (template_resolution or {}).get("source_template_id") or "",
        }
        return fork_manifest_error
    if fork_manifest_resolution:
        template_resolution["fork_manifest"] = fork_manifest_resolution

    running_message = (
        params.get("progress_message")
        or params.get("final_publish_message")
        or params.get("publish_message")
        or "正在完成活页生成"
    )
    progress_update = cmd_update_progress(_publish_final_progress_params(
        params,
        page_status="running",
        message=running_message,
    ))

    final_update_params = dict(params)
    if final_update_params.get("change_note") is None:
        final_update_params["change_note"] = "完成发布：正式活页内容已发布"
    update_out = cmd_update(final_update_params)
    if isinstance(update_out, dict) and update_out.get("code") == 0:
        validation_error = _publish_final_validation_error(
            params,
            update_out,
            template_resolution,
            final_html,
        )
        if validation_error:
            update_out.pop("agent_reply_contract", None)
            update_out.pop("agent_reply_template_file", None)
        else:
            _attach_agent_reply_contract(update_out, operation="publish_final")
            _attach_reply_data_contract(update_out, params)
            update_out["progress_update"] = progress_update
            update_out["agent_reply_template_resolution"] = template_resolution
            if isinstance(routing_consistency, dict) and routing_consistency.get("checked"):
                update_out["routing_consistency"] = routing_consistency
            if fork_manifest_resolution:
                update_out["fork_manifest_validation"] = {
                    "ok": True,
                    **fork_manifest_resolution,
                }
            if isinstance(fork_task_binding, dict) and fork_task_binding.get("mode") == "task_binding":
                fork_task_binding, binding_status_error = _mark_fork_task_published(
                    fork_task_binding,
                    page_id=update_out.get("page_id"),
                    public_url=_record_url(update_out),
                )
                update_out["fork_task_binding"] = fork_task_binding
                if binding_status_error:
                    _append_warning(update_out, {
                        "type": "fork_task_binding_status_update_failed",
                        "message": binding_status_error.get("message") or str(binding_status_error),
                    })
            update_out["publish_final"] = {
                "progress_step": "final_publish",
                "final_html_published": True,
            }
            if not (isinstance(progress_update, dict) and progress_update.get("code") == 0):
                _append_warning(update_out, {
                    "type": "progress_update_failed",
                    "message": _result_message(progress_update),
                })
            return update_out
    else:
        validation_error = ""

    failure_message = (
        params.get("failure_message")
        or params.get("progress_failure_message")
        or "活页生成遇到问题，请稍后重试。"
    )
    failed_update = cmd_update_progress(_publish_final_progress_params(
        params,
        page_status="failed",
        message=failure_message,
    ))
    message = validation_error or "正式活页发布失败"
    if isinstance(failed_update, dict) and failed_update.get("code") == 0:
        message += "，已回写失败进度页"
    else:
        message += "，且失败进度页回写未成功"

    return {
        "code": 1,
        "message": message,
        "page_id": params.get("page_id"),
        "update": update_out,
        "progress_update": progress_update,
        "progress_failed_update": failed_update,
        "publish_final": {
            "progress_step": "final_publish",
            "final_html_published": False,
        },
    }


def _verified_trace_evidence(params, *, browser_precheck_passed):
    receipts = params.get("validation_receipt_files")
    if isinstance(receipts, str):
        receipts = [receipts]
    handoff_receipts = params.get("handoff_validation_receipt_files")
    if isinstance(handoff_receipts, str):
        handoff_receipts = [handoff_receipts]
    receipt_count = (len(receipts) if isinstance(receipts, list) else 0) + (len(handoff_receipts) if isinstance(handoff_receipts, list) else 0)
    expected_skills = ["quant-buddy-view"]
    if receipt_count:
        expected_skills.append("quant-buddy-skill")
    return {
        "expected_skills": expected_skills,
        "validation_receipt_count": receipt_count,
        "browser_profile": "fork-local+public-smoke",
        "browser_precheck_passed": bool(browser_precheck_passed),
    }


def cmd_publish_verified(params):
    if not params.get("page_id"):
        return {"code": 1, "error": "PAGE_ID_REQUIRED", "message": "publish_verified 需要 page_id"}
    target = params.get("html_file")
    temp_path = None
    if not target and params.get("html") is not None:
        fd, temp_path = tempfile.mkstemp(prefix="qbv_publish_verified_", suffix=".html")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(str(params.get("html") or ""))
        target = temp_path
    if not target:
        return {"code": 1, "error": "HTML_REQUIRED", "message": "publish_verified 需要 html 或 html_file"}

    stages = {}
    timings = {}
    try:
        started = time.perf_counter()
        stages["fork_validate"] = cmd_fork_validate(dict(params))
        timings["fork_validate_ms"] = round((time.perf_counter() - started) * 1000)
        if not (isinstance(stages["fork_validate"], dict) and stages["fork_validate"].get("code") == 0):
            return {"code": 1, "published": False, "verified": False, "stages": stages, "timing": timings}

        fork_validation = stages["fork_validate"].get("fork_manifest_validation") or {}
        via_publish_workflow = params.pop("_via_publish_workflow", None) is _VIA_PUBLISH_WORKFLOW_SENTINEL
        credential_count = len(fork_validation.get("source_package_ids") or []) + len(fork_validation.get("source_grant_ids") or [])
        if credential_count >= _PUBLISH_WORKFLOW_REQUIRED_THRESHOLD and not via_publish_workflow:
            return {
                "code": 1,
                "error": "PUBLISH_WORKFLOW_REQUIRED",
                "message": (
                    f"该 fork 页面涉及 {credential_count} 个 package/grant（>= {_PUBLISH_WORKFLOW_REQUIRED_THRESHOLD}），"
                    "禁止手工分步调用 publish_verified；必须改用一次 scripts/publish_workflow.py 完成验证/注册/marker替换/发布。"
                ),
                "credential_count": credential_count,
                "stages": stages,
            }
        data_evidence_error = _validate_publish_data_evidence(params, source_credential_count=credential_count)
        if data_evidence_error:
            return {**data_evidence_error, "published": False, "verified": False, "stages": stages, "timing": timings}
        stages["live_data_evidence"] = {
            "code": 0,
            "live_data_mode": params.get("live_data_mode"),
            "route_receipt_file": params.get("route_receipt_file"),
        }
        card_runtime = bool(params.get("card_runtime_required") or fork_validation.get("card_runtime_required"))
        started = time.perf_counter()
        stages["local_browser"] = _run_page_verifier(target, "fork-local", card_runtime=card_runtime)
        timings["local_browser_ms"] = round((time.perf_counter() - started) * 1000)
        if not (isinstance(stages["local_browser"], dict) and stages["local_browser"].get("code") == 0):
            return {"code": 1, "published": False, "verified": False, "stages": stages, "timing": timings}

        publish_params = dict(params)
        publish_params["trace_evidence"] = _verified_trace_evidence(params, browser_precheck_passed=True)
        publish_params["_fork_preflight_sentinel"] = _FORK_PREFLIGHT_SENTINEL
        publish_params["_fork_preflight"] = {
            "html_sha256": stages["fork_validate"].get("html_sha256"),
            "fork_manifest_validation": stages["fork_validate"].get("fork_manifest_validation") or {},
        }
        started = time.perf_counter()
        stages["publish_final"] = cmd_publish_final(publish_params)
        timings["publish_final_ms"] = round((time.perf_counter() - started) * 1000)
        published = isinstance(stages["publish_final"], dict) and stages["publish_final"].get("code") == 0
        if not published:
            return {"code": 1, "published": False, "verified": False, "stages": stages, "timing": timings}

        public_url = _record_url(stages["publish_final"])
        started = time.perf_counter()
        stages["public_smoke"] = _run_page_verifier(public_url, "public-smoke", card_runtime=card_runtime)
        timings["public_smoke_ms"] = round((time.perf_counter() - started) * 1000)
        verified = isinstance(stages["public_smoke"], dict) and stages["public_smoke"].get("code") == 0
        result = {
            "code": 0 if verified else 1,
            "published": True,
            "verified": verified,
            "page_id": params.get("page_id"),
            "public_url": _delivery_public_url(public_url),
            "stages": stages,
            "timing": timings,
        }
        if verified:
            contract = stages["publish_final"].get("agent_reply_contract")
            if isinstance(contract, dict):
                result_contract = {**contract, "operation": "publish_verified"}
                if _delivery_policy():
                    result_contract["public_url"] = _delivery_public_url(
                        result_contract.get("public_url") or public_url
                    )
                    _apply_delivery_policy(result_contract)
                result["agent_reply_contract"] = result_contract
                for key in ("reply_data_evidence_file", "reply_data_evidence_sha256", "reply_data_availability"):
                    if result_contract.get(key) not in (None, ""):
                        result[key] = result_contract[key]
            if stages["publish_final"].get("agent_reply_template_file"):
                result["agent_reply_template_file"] = stages["publish_final"]["agent_reply_template_file"]
            if isinstance(result.get("agent_reply_contract"), dict):
                try:
                    result.update(_write_agent_reply_artifacts(params.get("task_id"), result))
                except (OSError, ValueError) as exc:
                    result.update({
                        "code": 1,
                        "verified": False,
                        "contract_artifact_error": str(exc),
                    })
        if result.get("code") == 0 and result.get("published") is True and result.get("verified") is True:
            result["qbv_job_lifecycle"] = QJL.complete_job_from_publish_result(params, result)
        return result
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _atomic_write_bytes(path, data_bytes):
    """把 data_bytes 原子写入 path：同目录 mkstemp + os.replace，避免半写被读到。
    写入/替换失败时清理临时文件并把异常原样抛出，交由调用方 fail-closed。"""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".qbv-tmp-", suffix=".part", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _redact_persisted_secrets(value):
    """Return a JSON-safe copy with execution-only validator env values removed.

    ``reply_validation_env`` may contain the task owner's API key so an in-process
    caller can pass it to the one-shot validator. It must never cross a CLI or
    persisted-report boundary. Keep only variable names plus an explicit redacted
    marker so operators can see which environment must be forwarded.
    """
    if isinstance(value, list):
        return [_redact_persisted_secrets(item) for item in value]
    if not isinstance(value, dict):
        return value

    sanitized = {}
    for key, item in value.items():
        if key == "reply_validation_env":
            names = sorted(
                str(name).strip()
                for name in (item.keys() if isinstance(item, dict) else [])
                if str(name).strip()
            )
            sanitized[key] = {name: "[REDACTED]" for name in names}
            if names:
                sanitized["reply_validation_env_keys"] = names
            continue
        sanitized[key] = _redact_persisted_secrets(item)
    return sanitized


def _publish_verified_cli_result(result, task_id):
    result = result if isinstance(result, dict) else {"code": 1, "message": str(result)}
    persisted_result = _redact_persisted_secrets(result)
    report_file = str(C.task_temp_path(task_id, "publish-verified-report.json", create_parent=True))
    with open(report_file, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(persisted_result, handle, ensure_ascii=False, indent=2)

    stage_summaries = {}
    for name, stage in (persisted_result.get("stages") or {}).items():
        if not isinstance(stage, dict):
            continue
        stage_summaries[name] = {
            key: stage[key]
            for key in ("code", "error", "message", "verification_profile", "page_id", "url", "target")
            if stage.get(key) not in (None, "")
        }
    summary = {
        key: persisted_result[key]
        for key in (
            "code", "published", "verified", "page_id", "public_url", "timing",
            "agent_reply_contract_file", "agent_reply_contract_sha256",
            "reply_draft_file", "reply_validation_params_file", "reply_validation_command",
            "reply_validation_env", "reply_validation_env_keys",
            "reply_data_evidence_file", "reply_data_evidence_sha256", "reply_data_availability",
            "agent_reply_template_file", "contract_artifact_error", "qbv_job_lifecycle",
        )
        if persisted_result.get(key) is not None
    }
    summary["stages"] = stage_summaries
    summary["full_report_file"] = report_file
    return summary


def cmd_fork_validate(params):
    params, fork_task_binding, binding_error = _apply_fork_task_binding(params)
    if binding_error:
        return binding_error
    final_html, final_html_error = _read_html(params)
    if final_html_error:
        return final_html_error
    params, template_resolution, template_error = _resolve_publish_agent_reply_template(params, html=final_html)
    if template_error:
        return template_error
    validation, validation_error = _validate_fork_manifest(params, template_resolution, final_html)
    if validation_error:
        validation_error["fork_manifest_validation"] = {
            "ok": False,
            "source_template_id": (template_resolution or {}).get("source_template_id") or "",
        }
        return validation_error
    manifest_validation = ({"ok": True, **validation} if validation else {
        "ok": True,
        "required": False,
        "mode": "unmatched",
    })
    image_validation, image_error = _validate_fork_images(final_html, params.get("page_id"))
    if image_error:
        image_error["fork_manifest_validation"] = manifest_validation
        return image_error
    return {
        "code": 0,
        "message": "发布前 HTML 门禁校验通过，可以进入浏览器验收",
        "fork_manifest_validation": manifest_validation,
        "fork_task_binding": fork_task_binding,
        "html_sha256": hashlib.sha256(final_html.encode("utf-8")).hexdigest(),
        "image_validation": image_validation,
    }


def _fetch_oss(url):
    """直连 OSS 拉取页面 HTML（public-read，无需鉴权），返回 (text, err)。"""
    req = urllib.request.Request(url, method="GET")
    try:
        with C._NO_PROXY_OPENER.open(req, timeout=_DEFAULT_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace"), None
    except Exception as e:
        return None, {"code": 1, "message": f"从 OSS 下载失败: {e}", "url": url}


def _fetch_public_bytes(url):
    req = urllib.request.Request(url, headers={"Accept": "image/webp,image/*"}, method="GET")
    try:
        with C._NO_PROXY_OPENER.open(req, timeout=_DEFAULT_TIMEOUT) as resp:
            return resp.read(), None
    except Exception as exc:
        return None, {"code": 1, "error": "PAGE_ASSET_NOT_AVAILABLE", "message": f"下载来源托管图片失败: {exc}", "url": url}


def _upgrade_runtime_share_poster_contract(html):
    source = str(html or "")
    pattern = re.compile(r'<img\b(?=[^>]*\bid\s*=\s*["\']sharePosterImage["\'])[^>]*>', re.I)

    repairs = 0

    def replace(match):
        nonlocal repairs
        tag = match.group(0)
        if re.search(r"\bdata-qb-runtime-src\b", tag, re.I):
            return tag
        self_closing = bool(re.search(r"/\s*>$", tag))
        repairs += 1
        body = re.sub(r"/?\s*>$", "", tag).rstrip()
        closing = " />" if self_closing else ">"
        return f"{body} data-qb-runtime-src{closing}"

    upgraded = pattern.sub(replace, source, count=1)
    return upgraded, repairs


def _prepare_fork_managed_images(html, output_dir):
    assets_dir = os.path.join(output_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    download_cache = {}
    manifest_images = []
    occurrence = 0

    def replace(match):
        nonlocal occurrence
        occurrence += 1
        source_page_id, asset_id = match.group(1), match.group(2)
        source_url = f"https://pages.quantbuddy.cn/pages/assets/{source_page_id}/{asset_id}.webp"
        if source_url not in download_cache:
            payload, error = _fetch_public_bytes(source_url)
            if error:
                raise RuntimeError(json.dumps(error, ensure_ascii=False))
            if not (payload and len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"):
                raise RuntimeError(json.dumps({
                    "code": 1,
                    "error": "PAGE_ASSET_NOT_AVAILABLE",
                    "message": f"来源托管图片不是有效 WebP: {asset_id}",
                    "url": source_url,
                }, ensure_ascii=False))
            image_file = os.path.join(assets_dir, f"{asset_id}.webp")
            with open(image_file, "wb") as handle:
                handle.write(payload)
            download_cache[source_url] = {
                "image_file": image_file,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        marker = f"__QB_IMAGE_FORK_{occurrence:03d}_{asset_id[6:14].upper()}__"
        cached = download_cache[source_url]
        manifest_images.append({
            "name": f"fork-image-{occurrence}",
            "logical_name": f"fork-{asset_id[6:18]}",
            "source_page_id": source_page_id,
            "source_asset_id": asset_id,
            "source_url": source_url,
            "image_file": cached["image_file"],
            "marker": marker,
            "sha256": cached["sha256"],
        })
        return marker

    try:
        working = _MANAGED_IMAGE_RE.sub(replace, str(html or ""))
    except RuntimeError as exc:
        try:
            return None, None, json.loads(str(exc))
        except json.JSONDecodeError:
            return None, None, {"code": 1, "error": "PAGE_ASSET_NOT_AVAILABLE", "message": str(exc)}
    return working, manifest_images, None


def _validate_fork_images(html, page_id):
    text = str(html or "")
    markers = sorted(set(_IMAGE_MARKER_RE.findall(text)))
    if markers:
        return None, {"code": 1, "error": "UNRESOLVED_IMAGE_MARKER", "message": "fork HTML 仍含未解析图片 marker: " + ", ".join(markers)}
    insecure = re.findall(r"(?:src\s*=\s*[\"']|url\(\s*[\"']?)(http://[^\"')\s]+)", text, re.IGNORECASE)
    if insecure:
        return None, {"code": 1, "error": "HTTP_IMAGE_FORBIDDEN", "message": "图片必须使用 HTTPS: " + ", ".join(sorted(set(insecure)))}
    managed = [{"page_id": m.group(1), "asset_id": m.group(2), "url": m.group(0)} for m in _MANAGED_IMAGE_RE.finditer(text)]
    cross = [item for item in managed if str(item["page_id"]) != str(page_id or "")]
    if cross:
        return None, {"code": 1, "error": "CROSS_PAGE_ASSET_REFERENCE", "message": "fork HTML 引用了其他 page_id 的托管图片: " + ", ".join(sorted({item["asset_id"] for item in cross}))}
    if managed:
        listed = cmd_image_list({"page_id": page_id})
        if not (isinstance(listed, dict) and listed.get("code") == 0):
            return None, {"code": 1, "error": "PAGE_ASSET_CHECK_FAILED", "message": "无法校验目标页面托管图片", "image_list": listed}
        active = {str(item.get("asset_id")) for item in (listed.get("list") or []) if item.get("status") == "active"}
        missing = sorted({item["asset_id"] for item in managed if item["asset_id"] not in active})
        if missing:
            return None, {"code": 1, "error": "PAGE_ASSET_NOT_AVAILABLE", "message": "托管图片不存在或已撤销: " + ", ".join(missing)}
    image_urls = re.findall(r"<img\b[^>]*\bsrc\s*=\s*[\"'](https://[^\"']+)[\"']", text, re.IGNORECASE)
    image_urls += re.findall(r"url\(\s*[\"']?(https://[^\"')\s]+)", text, re.IGNORECASE)
    external = sorted({url for url in image_urls if not _MANAGED_IMAGE_RE.fullmatch(url)})
    warnings = [{"type": "external_https_image", "url": url} for url in external]
    return {"managed_asset_ids": sorted({item["asset_id"] for item in managed}), "external_image_warnings": warnings}, None


def cmd_interpret(params):
    """Read an existing live page and its current runtime data without fetching page HTML."""
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    url = str(params.get("url") or "").strip()
    if not url:
        return {"code": 1, "error": "PAGE_URL_REQUIRED", "message": "interpret 需要 QuantBuddy 页面 url"}
    query = _up.urlencode({"url": url, "need_data": "true"})
    return C.http_json(
        "GET",
        C.api_url(endpoint, _PATH["download"]) + "?" + query,
        C.headers(api_key),
        timeout=_UPLOAD_TIMEOUT,
    )


def cmd_interpret_csv(params):
    """Hydrate CSV references from the immediately preceding interpret response."""
    source_file = str(params.get("source_file") or os.path.join(tempfile.gettempdir(), "sp_out.txt")).strip()
    try:
        with open(source_file, "r", encoding="utf-8") as handle:
            response = json.load(handle)
    except FileNotFoundError:
        return {"code": 1, "error": "INTERPRET_RESULT_NOT_FOUND", "message": "未找到 interpret 结果；请先运行 interpret，或传 source_file"}
    except (OSError, json.JSONDecodeError) as exc:
        return {"code": 1, "error": "INTERPRET_RESULT_INVALID", "message": f"无法读取 interpret 结果：{exc}"}

    if not (isinstance(response, dict) and response.get("code") == 0):
        return {"code": 1, "error": "INTERPRET_RESULT_INVALID", "message": "source_file 必须是成功的 interpret JSON 响应"}
    response_data = response.get("data")
    bundle = response_data.get("interpretation_bundle") if isinstance(response_data, dict) else None
    if not isinstance(bundle, dict):
        return {"code": 1, "error": "INTERPRET_RESULT_INVALID", "message": "source_file 缺少 interpretation_bundle；请使用 need_data=true 的 interpret 结果"}
    grants = ((bundle.get("runtime_data") or {}).get("grants") or [])
    if not isinstance(grants, list):
        return {"code": 1, "error": "INTERPRET_RESULT_INVALID", "message": "interpretation_bundle.runtime_data.grants 格式无效"}

    hydrated, skipped, failures = [], [], []
    timeout = max(1, min(120, int(params.get("timeout", 20))))
    for grant in grants:
        data = grant.get("data") if isinstance(grant, dict) else None
        if not (isinstance(data, dict) and str(data.get("mode") or "").lower() == "csv"):
            skipped.append(grant.get("grant_id") if isinstance(grant, dict) else None)
            continue
        try:
            # hydrate_fast_query_data 保留 csv_fields/csv_url，同时新增可直接计算的 results/series。
            grant["data"] = FQCSV.download_and_hydrate(data, timeout=timeout)
            hydrated.append(grant.get("grant_id"))
        except FQCSV.CsvHydrationError as exc:
            failures.append({"grant_id": grant.get("grant_id"), "code": "CSV_HYDRATE_FAILED", "message": str(exc), "retryable": bool(exc.retryable)})

    bundle["csv_hydration"] = {
        "hydrated_grant_ids": hydrated,
        "skipped_grant_ids": [item for item in skipped if item],
        "failures": failures,
    }
    if failures:
        bundle.setdefault("warnings", []).extend({"type": "data_grant", **item} for item in failures)
    return response


def cmd_download(params):
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")

    if not params.get("page_id") and not params.get("url"):
        return {"code": 1, "message": "download 需要 page_id 或 url 之一"}

    # 1) 服务端鉴权 → 拿到公开 url + 元信息（不含字节）
    qs_pairs = [(k, params[k]) for k in ("page_id", "url") if params.get(k)]
    meta_url = C.api_url(endpoint, _PATH["download"]) + "?" + _up.urlencode(qs_pairs)
    raw_meta = C.http_json("GET", meta_url, C.headers(api_key), timeout=_DEFAULT_TIMEOUT)
    if not (isinstance(raw_meta, dict) and raw_meta.get("code") == 0 and isinstance(raw_meta.get("data"), dict)):
        return raw_meta
    meta = raw_meta["data"]
    download_url = meta.get("download_url") or meta.get("public_url") or meta.get("url")
    if not download_url:
        return {"code": 1, "error": "PAGE_DOWNLOAD_URL_REQUIRED", "message": "页面详情未返回下载链接"}

    # 2) 客户端直连 OSS 下载 HTML（不经服务端，省带宽）
    html, err = _fetch_oss(download_url)
    if err:
        return err

    # 3) 校验完整性（与服务端记录的 sha256 比对）
    sha = hashlib.sha256(html.encode("utf-8")).hexdigest()
    sha_ok = (not meta.get("sha256")) or sha == meta.get("sha256")

    out = {
        "code": 0,
        "page_id": meta.get("page_id"),
        "owner": meta.get("owner"),
        "title": meta.get("title"),
        "description": meta.get("description"),
        "url": meta.get("url"),
        "size": len(html.encode("utf-8")),
        "sha256": sha,
        "sha256_match": sha_ok,
        "is_live": bool(meta.get("is_live")),
        "package_ids": meta.get("package_ids") or [],
        "grant_ids": meta.get("grant_ids") or [],
        "page_context": meta.get("page_context"),
        "agent_reply_template": meta.get("agent_reply_template"),
        "reply_contract_binding": meta.get("reply_contract_binding"),
        "status": meta.get("status"),
        "community_status": meta.get("community_status") or "none",
        "scene_tags": meta.get("scene_tags") or [],
        "paradigm_tags": meta.get("paradigm_tags") or [],
        "recommend_tags": meta.get("recommend_tags") or [],
        "expires_at": meta.get("expires_at"),
    }

    # 4) 落盘或回传 html
    save = params.get("save")
    if save:
        path = save if os.path.isabs(save) else os.path.join(C.SKILL_ROOT, save)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        out["saved_to"] = path
    else:
        out["html"] = html
    if _bool_param(params.get("final_response")):
        return _attach_agent_reply_contract(out, operation="download")
    return _attach_agent_reply_hint(out, resource_role="existing_page")


def cmd_list(params):
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    qs_pairs = [("mode", "mine"), ("page", params.get("page", 1)), ("page_size", params.get("page_size", 20))]
    url = C.api_url(endpoint, _PATH["list"]) + "?" + _up.urlencode(qs_pairs)
    return _normalize_cover_response(
        C.http_json("GET", url, C.headers(api_key), timeout=_DEFAULT_TIMEOUT),
        reply_mode="hint",
        resource_role="existing_page",
    )


def _valid_page_context(value):
    normalized, error = _normalize_page_context(value)
    return normalized if not error else None


def _valid_agent_reply_template(value):
    normalized, error = _normalize_agent_reply_template(value)
    return normalized if not error else None


def _reply_metadata_missing(record):
    missing = []
    if not _valid_page_context(record.get("page_context")):
        missing.append("page_context")
    if not _valid_agent_reply_template(record.get("agent_reply_template")):
        missing.append("agent_reply_template")
    return missing


def _iter_reply_metadata_targets(params):
    explicit_ids = params.get("page_ids") or params.get("pages")
    if explicit_ids:
        if isinstance(explicit_ids, str):
            explicit_ids = [item.strip() for item in re.split(r"[\s,]+", explicit_ids) if item.strip()]
        for page_id in explicit_ids:
            yield {"page_id": page_id}
        return

    scope = params.get("scope", "test_all")
    page_size = int(params.get("page_size", 50))
    max_pages = int(params.get("max_pages", 500))
    page = int(params.get("page", 1))
    seen = 0
    while seen < max_pages:
        batch = cmd_list({"scope": scope, "page": page, "page_size": min(page_size, max_pages - seen)})
        if not (isinstance(batch, dict) and batch.get("code") == 0):
            yield {"error": batch, "page": page}
            return
        data = batch.get("data") or {}
        items = data.get("items") or []
        if not items:
            return
        for item in items:
            seen += 1
            yield item
            if seen >= max_pages:
                return
        total = int(data.get("total") or 0)
        if page * page_size >= total:
            return
        page += 1


def _infer_reply_metadata_for_record(record, html):
    params = {
        "title": record.get("title") or "",
        "description": record.get("description") or "",
        "scene_tags": record.get("scene_tags") or [],
        "paradigm_tags": record.get("paradigm_tags") or [],
    }
    resolved, resolution, error = _resolve_publish_agent_reply_template(params, html=html)
    if error:
        return None, resolution, error
    metadata = {
        "page_context": resolved.get("page_context"),
        "agent_reply_template": resolved.get("agent_reply_template"),
    }
    error = _validate_reply_metadata_pair(metadata)
    if error:
        return None, resolution, error
    return metadata, resolution, None


def _compact_reply_metadata_plan(page_id, record, missing, metadata, resolution, *, status):
    template = metadata.get("agent_reply_template") if isinstance(metadata, dict) else {}
    context = metadata.get("page_context") if isinstance(metadata, dict) else {}
    return {
        "page_id": page_id,
        "title": record.get("title") or "",
        "owner": record.get("owner") or record.get("user_name") or "",
        "status": status,
        "missing": missing,
        "template_ref": template.get("template_ref") if isinstance(template, dict) else "",
        "page_context_summary": context.get("summary") if isinstance(context, dict) else "",
        "resolution": resolution,
    }


def cmd_init_reply_metadata(params):
    dry_run = params.get("dry_run", True)
    if isinstance(dry_run, str):
        dry_run = dry_run.strip().lower() not in ("0", "false", "no", "off")
    force = _bool_param(params.get("force"))
    include_revoked = _bool_param(params.get("include_revoked"))

    results = []
    scanned = 0
    planned = 0
    updated = 0
    failed = 0
    skipped = 0

    for seed in _iter_reply_metadata_targets(params):
        if seed.get("error"):
            failed += 1
            results.append({"status": "failed", "message": "列表读取失败", "page": seed.get("page"), "result": seed.get("error")})
            break
        page_id = seed.get("page_id")
        if not page_id:
            skipped += 1
            continue
        scanned += 1
        if seed.get("status") == "revoked" and not include_revoked:
            skipped += 1
            results.append({"page_id": page_id, "status": "skipped_revoked"})
            continue
        missing = ["page_context", "agent_reply_template"] if force else _reply_metadata_missing(seed)
        if not missing:
            skipped += 1
            results.append({"page_id": page_id, "status": "skipped_current"})
            continue

        downloaded = cmd_download({"page_id": page_id})
        if not (isinstance(downloaded, dict) and downloaded.get("code") == 0):
            failed += 1
            results.append({"page_id": page_id, "status": "failed", "stage": "download", "result": downloaded})
            continue
        if not force:
            missing = _reply_metadata_missing(downloaded)
            if not missing:
                skipped += 1
                results.append({"page_id": page_id, "status": "skipped_current"})
                continue

        metadata, resolution, error = _infer_reply_metadata_for_record(downloaded, downloaded.get("html") or "")
        if error:
            failed += 1
            results.append({"page_id": page_id, "status": "failed", "stage": "infer", "message": error.get("message"), "result": error})
            continue
        planned += 1
        plan = _compact_reply_metadata_plan(page_id, downloaded, missing, metadata, resolution, status="planned" if dry_run else "updating")
        if dry_run:
            results.append(plan)
            continue

        update_params = {
            "page_id": page_id,
            "html": downloaded.get("html") or "",
            "title": downloaded.get("title") or "",
            "page_context": metadata["page_context"],
            "agent_reply_template": metadata["agent_reply_template"],
            "ensure_share_shell": False,
        }
        if downloaded.get("description") is not None:
            update_params["description"] = downloaded.get("description")
        update = cmd_update(update_params)
        ok = isinstance(update, dict) and update.get("code") == 0
        if ok:
            updated += 1
            results.append({**plan, "status": "updated", "url": update.get("url")})
        else:
            failed += 1
            results.append({**plan, "status": "failed", "stage": "update", "result": update})

    return {
        "code": 0 if failed == 0 else 1,
        "dry_run": dry_run,
        "scope": params.get("scope", "test_all"),
        "scanned": scanned,
        "planned": planned,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }


def cmd_revoke(params):
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    if not params.get("page_id"):
        return {"code": 1, "message": "revoke 需要 page_id"}
    body = {"page_id": params["page_id"]}
    return C.http_json("POST", C.api_url(endpoint, _PATH["revoke"]),
                       C.headers(api_key), body, timeout=_DEFAULT_TIMEOUT)


def _http_multipart(url, api_key, fields, file_field, file_bytes, file_name, file_type):
    """发一个 multipart/form-data POST（带文件的接口用，如页面图片上传）。

    common.http_json 只发 JSON，无法带文件；这里手搓 multipart 包体，复用同一套
    无代理 opener / 版本渠道头 / 错误体兜底解析。
    """
    boundary = "----qbview" + hashlib.sha1(os.urandom(16)).hexdigest()[:16]
    crlf = b"\r\n"
    buf = io.BytesIO()
    for k, v in (fields or {}).items():
        buf.write(b"--" + boundary.encode() + crlf)
        buf.write(f'Content-Disposition: form-data; name="{k}"'.encode() + crlf + crlf)
        buf.write(str(v).encode("utf-8") + crlf)
    buf.write(b"--" + boundary.encode() + crlf)
    buf.write(f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"'.encode() + crlf)
    buf.write(f"Content-Type: {file_type}".encode() + crlf + crlf)
    buf.write(file_bytes + crlf)
    buf.write(b"--" + boundary.encode() + b"--" + crlf)

    hdrs = C.headers(api_key)
    hdrs["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=buf.getvalue(), headers=hdrs, method="POST")
    try:
        with C._NO_PROXY_OPENER.open(req, timeout=_UPLOAD_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"code": e.code, "success": False,
                    "error": {"message": getattr(e, "reason", str(e))}}
    except Exception as e:
        return {"code": 1, "success": False, "error": {"message": str(e)}}


def _resolve_local_image_file(params):
    image_file = params.get("image_file") or params.get("image") or params.get("file")
    if not image_file:
        return None, {"code": 1, "error": "IMAGE_REQUIRED", "message": "image_file 必填"}
    path = os.path.abspath(os.path.expanduser(str(image_file)))
    if not os.path.isfile(path):
        return None, {"code": 1, "error": "IMAGE_REQUIRED", "message": f"image_file 不存在: {path}"}
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        return None, {"code": 1, "error": "BAD_IMAGE_TYPE", "message": "image_file 扩展名仅支持 PNG/JPEG/WebP"}
    size = os.path.getsize(path)
    if size > _MAX_PAGE_IMAGE_BYTES:
        return None, {"code": 1, "error": "IMAGE_TOO_LARGE", "message": f"原始图片 {size} 字节，超过 5MB 上限"}
    return path, None


def cmd_image_upload(params):
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    page_id = str(params.get("page_id") or "").strip()
    logical_name = str(params.get("logical_name") or "").strip()
    task_id = str(params.get("task_id") or C.current_trace_context().get("task_id") or "").strip()
    if not page_id:
        return {"code": 1, "error": "PAGE_ID_REQUIRED", "message": "image_upload 需要 page_id"}
    if not logical_name:
        return {"code": 1, "error": "LOGICAL_NAME_REQUIRED", "message": "image_upload 需要 logical_name"}
    if not task_id:
        return {"code": 1, "error": "TRACE_CONTEXT_REQUIRED", "message": "image_upload 需要 task_id"}
    path, error = _resolve_local_image_file(params)
    if error:
        return error
    with open(path, "rb") as handle:
        image_bytes = handle.read()
    ext = os.path.splitext(path)[1].lower()
    content_type = "image/jpeg" if ext in (".jpg", ".jpeg") else ("image/webp" if ext == ".webp" else "image/png")
    return _http_multipart(
        C.api_url(endpoint, _PATH["image_upload"]),
        api_key,
        {"page_id": page_id, "logical_name": logical_name, "task_id": task_id},
        "file",
        image_bytes,
        os.path.basename(path),
        content_type,
    )


def cmd_image_list(params):
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    page_id = str(params.get("page_id") or "").strip()
    if not page_id:
        return {"code": 1, "error": "PAGE_ID_REQUIRED", "message": "image_list 需要 page_id"}
    url = C.api_url(endpoint, _PATH["image_list"]) + "?" + _up.urlencode({"page_id": page_id})
    return C.http_json("GET", url, C.headers(api_key), timeout=_DEFAULT_TIMEOUT)


def cmd_tags(params):
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    qs_pairs = []
    if params.get("tag_type"):
        qs_pairs.append(("tag_type", params["tag_type"]))
    url = C.api_url(endpoint, _PATH["tags"])
    if qs_pairs:
        url += "?" + _up.urlencode(qs_pairs)
    return C.http_json("GET", url, C.headers(api_key), timeout=_DEFAULT_TIMEOUT)


def cmd_autotag(params):
    """LLM 自动打标：page_id → 给已上传页打标；html/html_file → 上传前预打标（自动 dry_run）。"""
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    page_id = params.get("page_id")
    html = params.get("html")
    html_file = params.get("html_file")
    if not page_id and not html and not html_file:
        return {"code": 1, "message": "autotag 需要 page_id（给已上传页打标），或 html/html_file（上传前预打标，自动 dry_run）"}
    body = {}
    if page_id:
        body["page_id"] = page_id
    else:
        if html_file:
            path = html_file if os.path.isabs(html_file) else os.path.join(C.SKILL_ROOT, html_file)
            if not os.path.exists(path):
                return {"code": 1, "message": f"html_file 不存在: {path}"}
            with open(path, "r", encoding="utf-8") as f:
                html = f.read()
        body["html"] = html
        body["dry_run"] = True  # 无 page 只能预打标（服务端也会强制）
    # 显式传的 dry_run / force 透传（服务端兼容 bool / "true"）
    for k in ("dry_run", "force"):
        if params.get(k) is not None:
            body[k] = params[k]
    # LLM 调用可能较慢，用上传超时（120s）
    return C.http_json("POST", C.api_url(endpoint, _PATH["autotag"]),
                       C.headers(api_key), body, timeout=_UPLOAD_TIMEOUT)


def _cmd_community(params, path_key, label):
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    if not params.get("page_id"):
        return {"code": 1, "message": f"{label} 需要 page_id"}
    body = {"page_id": params["page_id"]}
    return C.http_json("POST", C.api_url(endpoint, _PATH[path_key]),
                       C.headers(api_key), body, timeout=_DEFAULT_TIMEOUT)


def cmd_publish_community(params):
    return _cmd_community(params, "publish_community", "publish_community")


def cmd_unpublish_community(params):
    return _cmd_community(params, "unpublish_community", "unpublish_community")


def _templates_query(endpoint, api_key, params, recommend=None):
    qs_pairs = [("mode", "public"), ("page", params.get("page", 1)), ("page_size", params.get("page_size", 20))]
    # 服务端默认限定 recommend:官方精选；*_tag_id / category / status 只做叠加筛选。
    for k in ("category", "status", "scene_tag_id", "paradigm_tag_id", "recommend_tag_id"):
        if params.get(k):
            qs_pairs.append((k, params[k]))
    if recommend:
        qs_pairs.append(("recommend", recommend))
    url = C.api_url(endpoint, _PATH["templates"]) + "?" + _up.urlencode(qs_pairs)
    return C.http_json("GET", url, C.headers(api_key), timeout=_DEFAULT_TIMEOUT)


def _merge_template_items(base, extra):
    """把 extra 响应里的 items 合并进 base（按 page_id/template_id 去重，base 优先）。"""
    if not (isinstance(base, dict) and isinstance(extra, dict)):
        return base
    bdata, edata = base.get("data"), extra.get("data")
    if not (isinstance(bdata, dict) and isinstance(edata, dict)):
        return base
    bitems, eitems = bdata.get("items"), edata.get("items")
    if not (isinstance(bitems, list) and isinstance(eitems, list)):
        return base
    seen = {it.get("page_id") or it.get("template_id") for it in bitems if isinstance(it, dict)}
    seen.discard(None)
    for it in eitems:
        if not isinstance(it, dict):
            continue
        key = it.get("page_id") or it.get("template_id")
        if key and key in seen:
            continue
        bitems.append(it)
        if key:
            seen.add(key)
    return base


_TEMPLATES_FULL_RESULT_VERSION = "templates_full_result_v1"
_TEMPLATE_SUMMARY_DESCRIPTION_LIMIT = 80


def _write_templates_full_result(task_id, normalized, item_count):
    """把 templates 完整候选（含 agent_reply_hint/page_context）原子落盘到 task-scoped 临时文件。
    文件名匹配 qbv_<safe_task>_*.json，可被 common.cleanup_task_temp_files 自动清理。
    返回 (full_path, sha256, byte_len)；task_id 缺失或写入失败时抛异常，调用方负责 fail-closed。"""
    safe_task = re.sub(r"[^0-9A-Za-z._-]+", "_", str(task_id or "")).strip("._-")
    if not safe_task:
        raise ValueError("templates 完整候选落盘需要非空 task_id（先调用 trace_context.py begin）")
    envelope = {
        "version": _TEMPLATES_FULL_RESULT_VERSION,
        "task_id": str(task_id),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "item_count": item_count,
        "result": normalized,
    }
    payload = json.dumps(envelope, ensure_ascii=False, indent=2).encode("utf-8")
    sha256 = hashlib.sha256(payload).hexdigest()
    final_path = str(C.task_temp_path(task_id, "templates-full.json", create_parent=True))
    _atomic_write_bytes(final_path, payload)
    return final_path, sha256, len(payload)


def _compact_template_item(item):
    """把单条候选精简成路由判断所需的最小字段集：字段可裁剪/description 可截断，
    但调用方必须保证每条候选都产出一条摘要（不允许按 top-N 丢条目）。
    标签复用既有 _tag_names（约532行，返回去重 set），排序后转 list 以便 JSON 序列化。
    page_context 与 card_required_outputs 是 direct 三轴判断的能力证据，必须随摘要下发。"""
    if not isinstance(item, dict):
        return {}
    description = item.get("description") or ""
    if len(description) > _TEMPLATE_SUMMARY_DESCRIPTION_LIMIT:
        description = description[:_TEMPLATE_SUMMARY_DESCRIPTION_LIMIT] + "…(完整文本见 full_result_file)"
    hint = item.get("agent_reply_hint") if isinstance(item.get("agent_reply_hint"), dict) else {}
    page_context = item.get("page_context") if isinstance(item.get("page_context"), dict) else {}
    summary = str(page_context.get("summary") or "")
    if len(summary) > _TEMPLATE_SUMMARY_DESCRIPTION_LIMIT:
        summary = summary[:_TEMPLATE_SUMMARY_DESCRIPTION_LIMIT] + "…"
    return {
        "template_id": item.get("template_id"),
        "page_id": item.get("page_id"),
        "title": item.get("title"),
        "category": item.get("category"),
        "description": description,
        "download_url": item.get("download_url") or item.get("public_url") or item.get("url"),
        "template_revision": item.get("template_revision"),
        "is_template": item.get("is_template"),
        "template_status": item.get("template_status"),
        "scene_tags": sorted(_tag_names(item.get("scene_tags"))),
        "paradigm_tags": sorted(_tag_names(item.get("paradigm_tags"))),
        "recommend_tags": sorted(_tag_names(item.get("recommend_tags"))),
        "source_template_id": hint.get("source_template_id") or item.get("template_id") or item.get("page_id") or "",
        "page_context": {
            "summary": summary,
            "core_sections": _unique_strings(page_context.get("core_sections"))[:8],
            "primary_outputs": _unique_strings(page_context.get("primary_outputs"))[:8],
        },
        "card_required_outputs": _unique_strings(item.get("card_required_outputs"))[:16],
        "metadata_provenance": _template_metadata_provenance(page_context),
    }


def _template_metadata_provenance(page_context):
    provenance = str((page_context or {}).get("outputs_provenance") or "").strip()
    return provenance if provenance in _PAGE_CONTEXT_OUTPUTS_PROVENANCE else _PAGE_CONTEXT_OUTPUTS_LEGACY


def _extract_template_items(normalized):
    """从 _normalize_cover_response 处理后的响应里取出 items 列表；结构不符合预期时返回 None（调用方 fail-closed）。"""
    if not isinstance(normalized, dict):
        return None
    data = normalized.get("data")
    if not isinstance(data, dict):
        return None
    items = data.get("items")
    if not isinstance(items, list):
        return None
    return items


def cmd_templates(params):
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    # 新版服务端一次完成官方精选和社区的联合查询、去重、排序与分页。
    recommend = params.get("recommend") or "all"
    normalized = _normalize_cover_response(
        _templates_query(endpoint, api_key, params, recommend=recommend),
        reply_mode="hint",
        resource_role="source_template",
    )

    # 查询本身失败（网络错误/后端非 0）：原样透传，不进入落盘改造，保持既有失败语义。
    if not (isinstance(normalized, dict) and normalized.get("code") == 0):
        return normalized

    items = _extract_template_items(normalized)
    if items is None:
        return {
            "code": 1,
            "error": "TEMPLATES_RESPONSE_SHAPE_UNEXPECTED",
            "message": "templates 返回结构不含预期的 data.items 列表，无法安全生成摘要，禁止据此判断 unmatched",
        }

    task_id = str(params.get("task_id") or C.current_trace_context().get("task_id") or "").strip()
    try:
        full_path, sha256, _byte_len = _write_templates_full_result(task_id, normalized, len(items))
    except Exception as exc:
        return {
            "code": 1,
            "error": "TEMPLATES_PERSIST_FAILED",
            "message": f"范式候选完整结果落盘失败：{exc}；未落盘前禁止继续路由判断，也不要把完整结果直接打印",
        }

    # 只有未收窄的 public 全池可作为 fork/自建前置；单池浏览仍可用，但不能满足 routing gate。
    rec_norm = str(recommend).strip().lower()
    recommend_scope = "all" if rec_norm in ("", "all", "both", "官方精选+社区") else ("community" if rec_norm in ("社区", "community") else "official")
    _write_routing_credential(task_id, recommend_scope, len(items), sha256)

    items_summary = [_compact_template_item(it) for it in items]
    data = normalized.get("data") or {}
    return {
        "code": 0,
        "item_count": len(items),
        "items_summary": items_summary,
        "full_result_file": full_path,
        "full_result_sha256": sha256,
        "page": data.get("page"),
        "page_size": data.get("page_size"),
        "total": data.get("total"),
        "routing_note": (
            "路由判据三轴：①范式匹配 ②标的/股票池/指数/市场范围一致 ③用户请求的每个维度"
            "都有候选页真实能力证据。三轴齐备才可 direct；缺维度走 fork + "
            "same_paradigm_augment_dimension，范围不同走 fork，无范式才走 unmatched。"
        ),
    }


_INTENT_PROFILE_VERSION = "intent_profile_v1"
_INTENT_PROFILE_FILE = "intent-profile.json"
_INTENT_ASSET_SCOPE_KINDS = ("single_asset", "sector", "index", "market")


def _task_receipt_path(task_id, name, *, create=False):
    root = C.task_temp_dir(task_id, create=create)
    path = Path(root) / "receipts" / name
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def cmd_intent_profile(params):
    task_id = _routing_task_id(params)
    if not task_id:
        return {"code": 1, "error": "QBV_TRACE_CONTEXT_REQUIRED", "message": "intent_profile 需要 task_id。"}
    scope = params.get("asset_scope")
    if not isinstance(scope, dict) or str(scope.get("kind") or "") not in _INTENT_ASSET_SCOPE_KINDS:
        return {
            "code": 1, "error": "INTENT_ASSET_SCOPE_REQUIRED",
            "message": f"asset_scope.kind 必填，取值 {list(_INTENT_ASSET_SCOPE_KINDS)}。",
        }
    if scope["kind"] in ("sector", "index") and not str(scope.get("name") or "").strip():
        return {"code": 1, "error": "INTENT_ASSET_SCOPE_REQUIRED", "message": "sector/index 必须提供 name。"}
    raw_dimensions = params.get("dimensions")
    if not isinstance(raw_dimensions, list) or not raw_dimensions:
        return {"code": 1, "error": "INTENT_DIMENSIONS_REQUIRED", "message": "dimensions 必须是非空数组。"}
    dimensions = []
    for entry in raw_dimensions:
        if not isinstance(entry, dict):
            return {"code": 1, "error": "INTENT_DIMENSIONS_REQUIRED", "message": "dimensions 每项必须是对象。"}
        user_term = str(entry.get("user_term") or "").strip()
        platform_dimensions = _unique_strings(entry.get("platform_dimensions"))
        method_terms = _unique_strings(entry.get("method_terms"))
        if not user_term or not platform_dimensions or not method_terms:
            return {
                "code": 1, "error": "INTENT_LAYER_MAPPING_REQUIRED",
                "message": "每个维度必须同时声明 user_term、platform_dimensions 和 method_terms。",
            }
        dimensions.append({
            "user_term": user_term,
            "restated": str(entry.get("restated") or "").strip(),
            "platform_dimensions": platform_dimensions,
            "method_terms": method_terms,
            "output_type": str(entry.get("output_type") or "").strip(),
        })
    profile = {
        "version": _INTENT_PROFILE_VERSION, "task_id": task_id,
        "page_type": str(params.get("page_type") or "").strip(),
        "asset_scope": {
            "kind": scope["kind"], "name": str(scope.get("name") or "").strip(),
            "market": str(scope.get("market") or "").strip(),
        },
        "dimensions": dimensions, "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    raw = json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    profile["profile_sha256"] = hashlib.sha256(raw).hexdigest()
    path = _task_receipt_path(task_id, _INTENT_PROFILE_FILE, create=True)
    _atomic_write_bytes(str(path), (json.dumps(profile, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return {
        "code": 0, "operation": "intent_profile", "task_id": task_id,
        "profile_file": str(path), "profile_sha256": profile["profile_sha256"],
        "dimension_count": len(dimensions),
        "platform_dimensions": sorted({x for item in dimensions for x in item["platform_dimensions"]}),
        "method_terms": sorted({x for item in dimensions for x in item["method_terms"]}),
    }


def _read_intent_profile(task_id):
    if not task_id:
        return None
    path = _task_receipt_path(task_id, _INTENT_PROFILE_FILE)
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return profile if isinstance(profile, dict) and profile.get("version") == _INTENT_PROFILE_VERSION else None


_RESEARCH_DIGEST_VERSION = "research_digest_v1"
_RESEARCH_DIGEST_FILE = "research-digest.json"
_RESEARCH_MAX_TEMPLATES = 5
_RESEARCH_INCLUDE_KINDS = ("layout", "style", "script", "contract")
_RESEARCH_CREDENTIAL_RE = re.compile(r"(signature|__QBV_|Bearer\s|sk-[A-Za-z0-9]{16,})", re.I)
_SCRIPT_BLOCK_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.S | re.I)
_STYLE_BLOCK_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
_RENDER_FN_RE = re.compile(r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\([^)]{0,160}\)\s*\{", re.I)
_RENDER_FN_KEYWORDS = ("query", "fetch", "render", "hydrate", "draw", "refresh", "outputs", "table", "card")
_SECTION_TAG_RE = re.compile(r"<(/?)section\b[^>]*>", re.I)
_CLASS_ATTR_RE = re.compile(r"\bclass\s*=\s*[\"']([^\"']+)[\"']", re.I)


def _extract_balanced_block(text, start, limit=8000):
    brace = text.find("{", start)
    if brace < 0:
        return ""
    depth, quote, index = 0, None, brace
    while index < min(len(text), brace + limit):
        char = text[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
        index += 1
    return ""


def _render_snippets(html):
    scripts = "\n".join(_SCRIPT_BLOCK_RE.findall(str(html or "")))
    out, seen = [], set()
    for match in _RENDER_FN_RE.finditer(scripts):
        name = match.group(1)
        if name in seen or not any(word in name.lower() for word in _RENDER_FN_KEYWORDS):
            continue
        code = _extract_balanced_block(scripts, match.start())
        if code and not _RESEARCH_CREDENTIAL_RE.search(code):
            out.append({"function": name, "code": code, "chars": len(code)})
            seen.add(name)
        if len(out) >= 12:
            break
    return out


def _section_blocks(html, known_outputs=()):
    text, blocks, cursor = str(html or ""), [], 0
    for opening in _SECTION_TAG_RE.finditer(text):
        if opening.group(1) or opening.start() < cursor:
            continue
        depth, end = 0, None
        for tag in _SECTION_TAG_RE.finditer(text, opening.start()):
            depth += -1 if tag.group(1) else 1
            if depth == 0:
                end = tag.end()
                break
        if end is None:
            continue
        cursor, outer = end, text[opening.start():end]
        if _RESEARCH_CREDENTIAL_RE.search(outer):
            continue
        attrs = opening.group(0)
        identity = re.search(r"(?:data-sec|id)\s*=\s*[\"']([^\"']+)[\"']", attrs, re.I)
        heading = re.search(r"<h[1-4][^>]*>(.*?)</h[1-4]>", outer, re.S | re.I)
        title = re.sub(r"<[^>]+>", "", heading.group(1)).strip() if heading else ""
        classes = _unique_strings([token for value in _CLASS_ATTR_RE.findall(outer) for token in value.split()])
        blocks.append({
            "sec_id": identity.group(1).strip() if identity else (title or f"section_{len(blocks)+1}"),
            "title": title, "classes": classes,
            "consumes_outputs": [name for name in _unique_strings(known_outputs) if name in outer],
            "html": outer, "chars": len(outer),
        })
    return blocks


def _style_kit(html, classes):
    wanted, out = set(classes or []), []
    for sheet in _STYLE_BLOCK_RE.findall(str(html or "")):
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", sheet, re.S):
            selector, body = match.group(1).strip(), match.group(0).strip()
            if selector.startswith(":root") or any(x in wanted for x in re.findall(r"\.([A-Za-z_][\w-]*)", selector)):
                out.append({"selector": re.sub(r"\s+", " ", selector), "css": body})
    return out


def _research_template_entry(page_id, include):
    detail = cmd_template({"page_id": page_id})
    if not (isinstance(detail, dict) and detail.get("code") == 0):
        return None, detail
    record = _template_record(detail)
    url = record.get("download_url") or record.get("public_url") or record.get("url") or ""
    if not url:
        return None, {"code": 1, "error": "RESEARCH_TEMPLATE_URL_MISSING", "message": f"候选 {page_id} 缺少公开 URL。"}
    html, error = _fetch_oss(url)
    if error:
        return None, error
    try:
        runtime = FRC.build_runtime_artifacts(html, record)
    except FRC.ForkRuntimeError as exc:
        return None, exc.as_dict()
    material = str(runtime.get("working_html") or "")
    material = re.sub(r"__QBV_[A-Za-z0-9_]+__", "QB_CREDENTIAL_PLACEHOLDER", material)
    roles = (runtime.get("review") or {}).get("roles") or []
    packages = [{
        "role_id": r.get("role_id"), "formulas": list(r.get("source_formulas") or []),
        "reads": copy.deepcopy(r.get("readonly_output_contract") or []),
        "required_outputs": list(r.get("required_outputs") or []),
    } for r in roles if isinstance(r, dict) and r.get("kind") == "package"]
    grants = [{
        "role_id": r.get("role_id"), "grant_kind": r.get("grant_kind"),
        "payload_shape": copy.deepcopy(r.get("readonly_contract_summary") or {}),
    } for r in roles if isinstance(r, dict) and r.get("kind") == "grant"]
    known_outputs = [x for package in packages for x in package["required_outputs"]]
    blocks = _section_blocks(material, known_outputs)
    entry = {"page_id": page_id, "title": str(record.get("title") or ""), "layout_skeleton": _page_headings(html)}
    if "layout" in include:
        entry["section_blocks"] = blocks
    if "style" in include:
        entry["style_kit"] = _style_kit(material, [x for block in blocks for x in block["classes"]])
    if "script" in include:
        entry["script_kit"] = _render_snippets(material)
    if "contract" in include:
        entry.update({"packages": packages, "grants": grants})
    return entry, None


def _compose_borrowable_refs(entry):
    refs = []
    for block in entry.get("section_blocks") or []:
        refs.extend([f"section:{block.get('sec_id')}", f"heading:{block.get('title')}"])
    refs.extend(f"heading:{x}" for x in entry.get("layout_skeleton") or [])
    refs.extend(f"snippet:{x.get('function')}" for x in entry.get("script_kit") or [])
    refs.extend(f"output:{x}" for p in entry.get("packages") or [] for x in p.get("required_outputs") or [])
    refs.extend(f"grant:{x.get('grant_kind')}" for x in entry.get("grants") or [] if x.get("grant_kind"))
    return _unique_strings([x for x in refs if not x.endswith(":")])


def cmd_research_templates(params):
    task_id = _routing_task_id(params)
    if not task_id:
        return {"code": 1, "error": "QBV_TRACE_CONTEXT_REQUIRED", "message": "research_templates 需要 task_id。"}
    raw_ids = params.get("template_ids") or params.get("page_ids") or []
    page_ids = _unique_strings([raw_ids] if isinstance(raw_ids, str) else raw_ids)
    if not page_ids:
        return {"code": 1, "error": "RESEARCH_TEMPLATE_IDS_REQUIRED", "message": "需要 template_ids。"}
    if len(page_ids) > _RESEARCH_MAX_TEMPLATES:
        return {"code": 1, "error": "RESEARCH_TEMPLATE_LIMIT_EXCEEDED", "limit": _RESEARCH_MAX_TEMPLATES}
    raw_include = params.get("include")
    include = _unique_strings([raw_include] if isinstance(raw_include, str) else raw_include) if raw_include else list(_RESEARCH_INCLUDE_KINDS)
    if any(x not in _RESEARCH_INCLUDE_KINDS for x in include):
        return {"code": 1, "error": "RESEARCH_INCLUDE_INVALID", "allowed": list(_RESEARCH_INCLUDE_KINDS)}
    templates, warnings = [], []
    for page_id in page_ids:
        entry, error = _research_template_entry(page_id, include)
        if error:
            warnings.append({"page_id": page_id, "error": error.get("error"), "message": error.get("message")})
        elif entry:
            templates.append(entry)
    if not templates:
        return {"code": 1, "error": "RESEARCH_DIGEST_EMPTY", "warnings": warnings}
    digest = {
        "version": _RESEARCH_DIGEST_VERSION, "task_id": task_id,
        "purpose": str(params.get("purpose") or ""), "include": include,
        "templates": templates, "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    canonical = json.dumps(digest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if _RESEARCH_CREDENTIAL_RE.search(canonical.decode("utf-8")):
        return {"code": 1, "error": "RESEARCH_DIGEST_CREDENTIAL_LEAK", "message": "选材摘要疑似包含凭证。"}
    digest["digest_sha256"] = hashlib.sha256(canonical).hexdigest()
    path = _task_receipt_path(task_id, _RESEARCH_DIGEST_FILE, create=True)
    _atomic_write_bytes(str(path), (json.dumps(digest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return {
        "code": 0, "operation": "research_templates", "task_id": task_id,
        "digest_file": str(path), "digest_sha256": digest["digest_sha256"],
        "template_count": len(templates), "warnings": warnings,
        "templates_summary": [{
            "page_id": x["page_id"], "title": x["title"],
            "borrowable_refs": _compose_borrowable_refs(x),
        } for x in templates],
    }


_COMPOSE_BINDING_VERSION = "compose_binding_v1"
_COMPOSE_BINDING_FILE = "compose-binding.json"
_COMPOSE_BORROW_LEVELS = ("layout", "layout+style", "layout+style+script", "formula", "grant_shape", "indicator", "original")


def cmd_fork_compose(params):
    task_id = _routing_task_id(params)
    if not task_id:
        return {"code": 1, "error": "QBV_TRACE_CONTEXT_REQUIRED", "message": "fork_compose 需要 task_id。"}
    cred, _, read_error = _read_routing_credential(task_id)
    if read_error:
        return read_error
    decision = (cred or {}).get("routing_decision") if isinstance((cred or {}).get("routing_decision"), dict) else {}
    if decision.get("mode") != "fork":
        return {"code": 1, "error": "COMPOSE_ROUTING_REQUIRED", "message": "fork_compose 只服务已锁定 fork 的任务。"}
    source = str(params.get("source_template_id") or decision.get("source_template_id") or "").strip()
    if source != str(decision.get("source_template_id") or ""):
        return {"code": 1, "error": "ROUTING_FORK_SOURCE_CONFLICT", "message": "Compose 来源与 fork 路由来源不一致。"}
    digest_path = _task_receipt_path(task_id, _RESEARCH_DIGEST_FILE)
    try:
        digest = json.loads(digest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"code": 1, "error": "COMPOSE_DIGEST_REQUIRED", "message": "先运行 research_templates。"}
    declared_sha, actual_sha = str(params.get("research_digest_sha256") or ""), str(digest.get("digest_sha256") or "")
    if not declared_sha or declared_sha != actual_sha:
        return {"code": 1, "error": "COMPOSE_DIGEST_STALE", "actual_digest_sha256": actual_sha}
    entries = {str(x.get("page_id") or ""): x for x in digest.get("templates") or [] if isinstance(x, dict)}
    entry = entries.get(source)
    if not entry:
        return {"code": 1, "error": "COMPOSE_SOURCE_NOT_IN_DIGEST", "available_template_ids": sorted(entries)}
    modules = ((params.get("borrow_plan") or {}).get("modules") if isinstance(params.get("borrow_plan"), dict) else None)
    if not isinstance(modules, list) or not modules:
        return {"code": 1, "error": "COMPOSE_BORROW_PLAN_REQUIRED", "borrowable_refs": _compose_borrowable_refs(entry)}
    borrowable, provenance, claimed, borrowed_count = set(_compose_borrowable_refs(entry)), [], set(), 0
    for module in modules:
        if not isinstance(module, dict) or str(module.get("borrow_level") or "") not in _COMPOSE_BORROW_LEVELS:
            return {"code": 1, "error": "COMPOSE_BORROW_PLAN_INVALID"}
        name, level = str(module.get("module") or "").strip(), str(module.get("borrow_level") or "")
        dimension = str(module.get("dimension") or "").strip()
        if dimension:
            claimed.add(dimension)
        if level == "original":
            if not str(module.get("analysis_role") or "").strip() or not str(module.get("rationale") or "").strip():
                return {"code": 1, "error": "COMPOSE_ORIGINAL_RATIONALE_REQUIRED", "module": name}
            provenance.append({"module": name, "dimension": dimension, "borrow_level": level})
            continue
        borrowed_from = module.get("borrowed_from") if isinstance(module.get("borrowed_from"), dict) else {}
        ref = str(borrowed_from.get("ref") or "").strip()
        if ref not in borrowable or str(borrowed_from.get("page_id") or source) != source:
            return {"code": 1, "error": "COMPOSE_BORROW_REF_INVALID", "invalid_ref": ref, "borrowable_refs": sorted(borrowable)}
        borrowed_count += 1
        provenance.append({
            "module": name, "dimension": dimension, "borrow_level": level,
            "borrowed_from": {"page_id": source, "ref": ref},
            "adaptation": str(module.get("adaptation") or "").strip(),
        })
    if not borrowed_count:
        return {
            "code": 1, "error": "COMPOSE_ZERO_BORROW", "recoverable": True,
            "message": "Compose 必须真实借鉴至少一个模板条目；fork 不能改判 unmatched。",
            "borrowable_refs": sorted(borrowable),
        }
    declared_dimensions = [str(x.get("user_term") or "").strip() for x in ((_read_intent_profile(task_id) or {}).get("dimensions") or [])]
    unclaimed = [x for x in declared_dimensions if x and x not in claimed]
    if unclaimed:
        return {"code": 1, "error": "COMPOSE_DIMENSION_UNCLAIMED", "unclaimed_dimensions": unclaimed}
    downgraded_from = str(params.get("downgraded_from") or "").strip()
    downgrade_reason = str(params.get("downgrade_reason") or "").strip()
    if downgraded_from and downgraded_from not in ("inherit", "inherit_augment"):
        return {"code": 1, "error": "COMPOSE_DOWNGRADE_INVALID"}
    if downgraded_from and not downgrade_reason:
        return {"code": 1, "error": "COMPOSE_DOWNGRADE_REASON_REQUIRED"}
    binding = {
        "version": _COMPOSE_BINDING_VERSION, "task_id": task_id,
        "page_id": str(cred.get("page_id") or params.get("page_id") or ""),
        "source_template_id": source, "research_digest_file": str(digest_path),
        "research_digest_sha256": actual_sha, "downgraded_from": downgraded_from,
        "downgrade_reason": downgrade_reason, "borrow_provenance": provenance,
        "borrowed_module_count": borrowed_count,
        "original_module_count": len(provenance) - borrowed_count,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _task_receipt_path(task_id, _COMPOSE_BINDING_FILE, create=True)
    payload = (json.dumps(binding, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write_bytes(str(path), payload)
    binding_sha = hashlib.sha256(payload).hexdigest()
    cred["fork_binding"] = {
        "kind": "compose", "source_template_id": source,
        "compose_binding_file": str(path), "compose_binding_sha256": binding_sha,
        "borrow_provenance": provenance, "bound_at": binding["generated_at"],
    }
    if downgraded_from:
        history = cred.get("routing_history") if isinstance(cred.get("routing_history"), list) else []
        history.append({
            "at": binding["generated_at"], "mode": "fork",
            "borrow_mode_from": downgraded_from, "borrow_mode_to": "compose", "reason": downgrade_reason,
        })
        cred["routing_history"] = history
        cred["decision_revision"] = int(cred.get("decision_revision") or 0) + 1
    decision["borrow_mode"] = "compose"
    cred["routing_decision"], cred["status"] = decision, "compose_bound"
    _, write_error = _write_routing_credential_record(cred)
    if write_error:
        return write_error
    return {
        "code": 0, "operation": "fork_compose", "task_id": task_id,
        "borrow_mode": "compose", "source_template_id": source,
        "compose_binding_file": str(path), "compose_binding_sha256": binding_sha,
        "borrowed_module_count": borrowed_count,
        "original_module_count": binding["original_module_count"],
        "borrow_provenance": provenance,
    }


def cmd_template(params):
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    tid = params.get("template_id") or params.get("page_id")
    if not tid:
        return {"code": 1, "message": "template 需要 template_id 或 page_id"}
    url = C.api_url(endpoint, _PATH["template"]) + "?" + _up.urlencode([("page_id", tid)])
    raw = C.http_json("GET", url, C.headers(api_key), timeout=_DEFAULT_TIMEOUT)
    if not (isinstance(raw, dict) and raw.get("code") == 0 and isinstance(raw.get("data"), dict)):
        return raw
    return _normalize_cover_response(
        {"code": 0, **raw["data"]},
        reply_mode="hint",
        resource_role="source_template",
    )


def cmd_direct_finalize(params):
    cfg = C.load_config_require_key()
    endpoint, api_key = C.endpoint_of(cfg), cfg.get("api_key", "")
    task_id = str(params.get("task_id") or C.current_trace_context().get("task_id") or "").strip()
    page_id = str(params.get("page_id") or "").strip()
    template_revision = str(params.get("template_revision") or "").strip()
    if not task_id or not page_id or not template_revision:
        return {
            "code": 1,
            "error": "DIRECT_FINALIZE_PARAMS_REQUIRED",
            "message": "direct_finalize 需要 task_id、page_id、template_revision",
        }
    out = C.http_json(
        "POST",
        C.api_url(endpoint, _PATH["direct_finalize"]),
        C.headers(api_key),
        {
            "task_id": task_id,
            "page_id": page_id,
            "template_revision": template_revision,
        },
        timeout=_DEFAULT_TIMEOUT,
    )
    if not (isinstance(out, dict) and out.get("code") == 0):
        return out
    required = {
        "task_id": out.get("task_id"),
        "page_id": out.get("page_id"),
        "public_url": out.get("public_url") or out.get("url"),
        "template_revision": out.get("template_revision"),
        "delivery_trace_id": out.get("delivery_trace_id"),
    }
    missing = [key for key, value in required.items() if not value]
    if missing or required["task_id"] != task_id or required["page_id"] != page_id:
        return {
            "code": 1,
            "error": "DIRECT_FINALIZE_INCOMPLETE",
            "message": "direct_finalize 成功响应缺少强终态字段或任务归属不一致",
            "missing": missing,
        }
    out["operation"] = "direct_finalize"
    _attach_agent_reply_contract(out, operation="direct_finalize")
    contract = out.get("agent_reply_contract") if isinstance(out.get("agent_reply_contract"), dict) else None
    if contract and _delivery_policy():
        out["public_url"] = contract.get("public_url") or out.get("public_url") or out.get("url") or ""
    return out


def _direct_credential_map(items, id_key):
    grouped = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get(id_key) or "").strip()
        signature = str(item.get("signature") or "").strip()
        if not item_id or not signature:
            continue
        grouped.setdefault(item_id, set()).add(signature)
    return grouped


def _direct_query_package(package_id, signature):
    import formula_package as FP
    return FP.cmd_query({
        "package_id": package_id,
        "signature": signature,
        "result_mode": "summary",
        "direct": True,
    })


def _direct_query_grant(grant_id, signature):
    import data_grant as DG
    return DG.cmd_query({"grant_id": grant_id, "signature": signature})


def _redact_direct_payload(value):
    """Remove capability credentials before persisting direct grant evidence locally."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in {"api_key", "authorization", "bearer", "access_token"} or normalized.startswith("signature"):
                continue
            out[key] = _redact_direct_payload(item)
        return out
    if isinstance(value, list):
        return [_redact_direct_payload(item) for item in value]
    return value


def _direct_leaf_field_paths(value, prefix="", limit=200):
    """Return stable leaf field names only; list positions use [] and values never escape."""
    paths = []

    def visit(item, current):
        if len(paths) >= limit:
            return
        if isinstance(item, dict):
            for key, child in item.items():
                normalized = str(key).strip().lower().replace("-", "_")
                if normalized in {"api_key", "authorization", "bearer", "access_token"} or normalized.startswith("signature"):
                    continue
                next_path = f"{current}.{key}" if current else str(key)
                visit(child, next_path)
            return
        if isinstance(item, list):
            next_path = current + "[]" if current else "[]"
            for child in item:
                visit(child, next_path)
                if len(paths) >= limit:
                    break
            return
        if current and current not in paths:
            paths.append(current)

    visit(_redact_direct_payload(value), prefix)
    return sorted(paths)[:limit]


def _direct_reply_data_availability(package_results, grant_results):
    formula_outputs = {}
    for item in package_results or []:
        if not isinstance(item, dict):
            continue
        package_id = str(item.get("package_id") or "").strip()
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        outputs = result.get("outputs") if isinstance(result.get("outputs"), dict) else {}
        if package_id:
            formula_outputs[package_id] = sorted(str(name) for name in outputs if str(name).strip())

    grant_paths = {}
    for item in grant_results or []:
        if not isinstance(item, dict):
            continue
        grant_id = str(item.get("grant_id") or "").strip()
        if grant_id:
            grant_paths[grant_id] = _direct_leaf_field_paths(item.get("result"), limit=200)

    return {
        "version": "reply_data_availability_v1",
        "formula_outputs_by_package": formula_outputs,
        "grant_field_paths_by_grant": grant_paths,
    }


def _write_direct_grant_result(task_id, grant_id, result):
    safe_grant = re.sub(r"[^0-9A-Za-z._-]+", "_", str(grant_id or "")).strip("._-") or "grant"
    path = str(C.task_temp_path(task_id, f"grant-{safe_grant}.json", create_parent=True))
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(_redact_direct_payload(result), handle, ensure_ascii=False, indent=2)
    return path


def _write_agent_reply_artifacts(task_id, finalized):
    """Persist the exact terminal contract and hash-bound one-shot validator inputs."""
    safe_task = re.sub(r"[^0-9A-Za-z._-]+", "_", str(task_id or "")).strip("._-")
    contract = finalized.get("agent_reply_contract") if isinstance(finalized, dict) else None
    if not safe_task or not isinstance(contract, dict) or contract.get("terminal") is not True:
        raise ValueError("缺少可持久化的 terminal agent_reply_contract")

    temp_root = C.task_temp_dir(task_id, create=True)
    contract_file = str(temp_root / "agent-contract.json")
    draft_file = str(temp_root / "reply-draft.md")
    params_file = str(temp_root / "reply-validate.json")
    contract_bytes = json.dumps(contract, ensure_ascii=False, indent=2).encode("utf-8")
    contract_sha256 = hashlib.sha256(contract_bytes).hexdigest()
    with open(contract_file, "wb") as handle:
        handle.write(contract_bytes)
    validator_params = {
        "contract_file": contract_file,
        "contract_sha256": contract_sha256,
        "draft_file": draft_file,
        "task_id": str(task_id),
        "cleanup_task_id": str(task_id),
    }
    with open(params_file, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(validator_params, handle, ensure_ascii=False, indent=2)
    # 默认 config.json/config.local.json 由 validator 子进程自行发现，绝不能把默认 key 返回给 Agent。
    # 只有调用方显式覆盖了本次任务身份时，才保留进程内 env 合同；CLI/持久化边界仍会统一脱敏。
    # 无论哪种情况都禁止把 key 拼进命令串或参数文件。
    validation_env = {}
    explicit_api_key = str(getattr(C, "_API_KEY_OVERRIDE", None) or "").strip()
    if explicit_api_key:
        validation_env["QBV_API_KEY"] = explicit_api_key
    return {
        "agent_reply_contract_file": contract_file,
        "agent_reply_contract_sha256": contract_sha256,
        "reply_draft_file": draft_file,
        "reply_validation_params_file": params_file,
        "reply_validation_command": _command_string([sys.executable, os.path.join(C.SCRIPT_DIR, "validate_agent_reply.py"), f"@{params_file}"]),
        "reply_validation_env": validation_env,
    }


def _write_direct_reply_artifacts(task_id, finalized):
    return _write_agent_reply_artifacts(task_id, finalized)


def _direct_failure(code, message, **extra):
    return {"code": 1, "error": code, "message": message, **extra}


def _run_direct_deliver(task_id, page_id, expected_revision):
    template_result = cmd_template({"task_id": task_id, "page_id": page_id})
    if not (isinstance(template_result, dict) and template_result.get("code") == 0):
        return template_result
    record = _template_record(template_result)
    current_revision = str(record.get("template_revision") or "").strip()
    if not current_revision or current_revision != expected_revision:
        return _direct_failure(
            "TEMPLATE_CHANGED",
            "模板已变化，请重新查询范式卡后再交付",
            current_template_revision=current_revision or None,
        )

    public_url = _record_url(record)
    if not public_url:
        return _direct_failure("DIRECT_TEMPLATE_URL_MISSING", "直达模板缺少公开 URL")
    html, fetch_error = _fetch_oss(public_url)
    if fetch_error:
        return fetch_error

    package_ids = _unique_strings(record.get("package_ids"))
    grant_ids = _unique_strings(record.get("grant_ids"))
    package_credentials = _direct_credential_map(_extract_package_credentials(html), "package_id")
    grant_credentials = _direct_credential_map(_extract_grant_credentials(html), "grant_id")
    missing_package_ids = sorted(item for item in package_ids if len(package_credentials.get(item, set())) != 1)
    missing_grant_ids = sorted(item for item in grant_ids if len(grant_credentials.get(item, set())) != 1)
    if missing_package_ids or missing_grant_ids:
        return _direct_failure(
            "DIRECT_DATA_EVIDENCE_MISSING",
            "模板当前实时凭证不完整或存在歧义，未执行取数与 finalize",
            missing_package_ids=missing_package_ids,
            missing_grant_ids=missing_grant_ids,
        )

    package_results = []
    for package_id in package_ids:
        signature = next(iter(package_credentials[package_id]))
        result = _direct_query_package(package_id, signature)
        if not (isinstance(result, dict) and result.get("code") == 0):
            return _direct_failure(
                "DIRECT_DATA_QUERY_FAILED",
                "公式包实时查询失败，未执行 finalize",
                failed_kind="formula_package",
                failed_id=package_id,
                result=_redact_direct_payload(result),
            )
        package_results.append({"package_id": package_id, "result": _redact_direct_payload(result)})

    grant_results = []
    grant_query_results = []
    for grant_id in grant_ids:
        signature = next(iter(grant_credentials[grant_id]))
        result = _direct_query_grant(grant_id, signature)
        if not (isinstance(result, dict) and result.get("code") == 0):
            return _direct_failure(
                "DIRECT_DATA_QUERY_FAILED",
                "数据授权实时查询失败，未执行 finalize",
                failed_kind="data_grant",
                failed_id=grant_id,
                result=_redact_direct_payload(result),
            )
        redacted_result = _redact_direct_payload(result)
        grant_query_results.append({"grant_id": grant_id, "result": redacted_result})
        grant_results.append({
            "grant_id": grant_id,
            "result_file": _write_direct_grant_result(task_id, grant_id, result),
        })

    template_meta = record.get("agent_reply_template") if isinstance(record.get("agent_reply_template"), dict) else {}
    template_ref = str(template_meta.get("template_ref") or "").strip()
    reply_evidence_contract = {}
    if RDE.get_policy(template_ref):
        try:
            reply_evidence_contract = RDE.build_direct(
                task_id, template_ref, package_results, grant_query_results
            ) or {}
        except (OSError, ValueError, TypeError) as exc:
            return _direct_failure("DIRECT_REPLY_EVIDENCE_FAILED", str(exc))
        if not reply_evidence_contract.get("reply_data_evidence_file"):
            return _direct_failure(
                "DIRECT_REPLY_EVIDENCE_FAILED", "严格回复模板未生成证据产物"
            )

    finalized = cmd_direct_finalize({
        "task_id": task_id,
        "page_id": page_id,
        "template_revision": current_revision,
    })
    if not (isinstance(finalized, dict) and finalized.get("code") == 0):
        return finalized

    out = dict(finalized)
    out["operation"] = "direct_finalize"
    out["orchestration"] = "direct_deliver"
    contract = out.get("agent_reply_contract")
    if isinstance(contract, dict):
        if reply_evidence_contract:
            for key, value in reply_evidence_contract.items():
                contract[key] = value
                out[key] = value
        else:
            contract["reply_data_availability"] = _direct_reply_data_availability(
                package_results, grant_query_results
            )
    out["direct_data_evidence"] = {
        "package_results": package_results,
        "grant_results": grant_results,
        "package_query_count": len(package_results),
        "grant_query_count": len(grant_results),
    }
    out.update(_write_direct_reply_artifacts(task_id, out))
    return out


def _direct_job_lineage(params, task_id):
    """Recover optional QBS Job identity without coupling standalone QBV to QBS."""
    persisted = C.read_task_trace_context(task_id) if task_id else {}
    handoff_context = persisted.get("handoff_context") if isinstance(persisted, dict) else None
    has_explicit_job = any(
        str(params.get(key) or "").strip()
        for key in ("qbv_job_id", "qbv_job_file", "job_file")
    )
    has_handoff = (
        isinstance(handoff_context, dict)
        and handoff_context.get("schema_version") == "qbs_qbv_handoff_v1"
    )
    if not has_explicit_job and not has_handoff:
        return None
    return {
        "turn_id": str(
            params.get("turn_id")
            or C.current_trace_context().get("turn_id")
            or persisted.get("current_turn_id")
            or ""
        ).strip(),
        "handoff_context": handoff_context if has_handoff else None,
    }


def _complete_direct_job(params, task_id, result):
    """Close a QBS-created Job after a strong direct_finalize terminal contract."""
    lineage = _direct_job_lineage(params, task_id)
    if lineage is None:
        return result
    contract = result.get("agent_reply_contract") if isinstance(result.get("agent_reply_contract"), dict) else {}
    terminal_verified = (
        result.get("operation") == "direct_finalize"
        and result.get("orchestration") == "direct_deliver"
        and contract.get("terminal") is True
        and contract.get("page_id") == result.get("page_id")
        and contract.get("public_url") == result.get("public_url")
    )
    terminal_result = {
        "code": result.get("code"),
        "published": terminal_verified,
        "verified": terminal_verified,
        "page_id": result.get("page_id"),
        "public_url": result.get("public_url"),
    }
    lifecycle_params = dict(params)
    lifecycle_params["task_id"] = task_id
    if lineage.get("turn_id"):
        lifecycle_params["turn_id"] = lineage["turn_id"]
    result["qbv_job_lifecycle"] = QJL.complete_job_from_publish_result(
        lifecycle_params, terminal_result
    )
    return result


def cmd_direct_deliver(params):
    """Execute the evidence-producing portion of a direct delivery exactly once.

    Except for feishu-group, the caller must already have emitted the selected
    template URL to the user. The feishu-group channel waits for the terminal
    contract and emits only its playground URL.
    This command intentionally owns template detail loading, credential extraction,
    one query per current package/grant, and the single terminal finalize call.
    """
    previous_context = C.current_trace_context()
    task_id = str(params.get("task_id") or previous_context.get("task_id") or "").strip()
    page_id = str(params.get("page_id") or "").strip()
    expected_revision = str(params.get("template_revision") or "").strip()
    if not task_id or not page_id or not expected_revision:
        return _direct_failure(
            "DIRECT_DELIVER_PARAMS_REQUIRED",
            "direct_deliver 需要 task_id、page_id、template_revision",
        )
    context_params = {"task_id": task_id, "user_query": previous_context.get("user_query")}
    explicit_turn_id = str(params.get("turn_id") or "").strip()
    if not explicit_turn_id and str(previous_context.get("task_id") or "").strip() == task_id:
        explicit_turn_id = str(previous_context.get("turn_id") or "").strip()
    if explicit_turn_id:
        context_params["turn_id"] = explicit_turn_id
    C.configure_trace_context(context_params)
    try:
        routing_record, routing_error = _validate_direct_delivery_routing(params)
        if routing_error:
            return routing_error
        result = _run_direct_deliver(task_id, page_id, expected_revision)
        if isinstance(result, dict) and result.get("code") == 0:
            result["routing_decision_recorded"] = routing_record
            result = _complete_direct_job(params, task_id, result)
        return result
    finally:
        # configure_trace_context（不是 set_trace_context）：恢复原 Trace Context 时同样不能把
        # 当前已生效的 api_key 覆盖清空——这次临时切换全程本就没改过它。
        C.configure_trace_context({
            "task_id": previous_context.get("task_id"),
            "turn_id": previous_context.get("turn_id"),
            "user_query": previous_context.get("user_query"),
            "previous_turn_id": previous_context.get("previous_turn_id"),
            "agent_model": previous_context.get("agent_model"),
        })


def _exchange_for_code(code):
    code = str(code or "")
    if code.startswith(("4", "8")):
        return "BJ"
    if code.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


_TARGET_IDENTITY_RE = re.compile(
    r"^\s*(?P<name>[^\s(（]*?)\s*[（(]?\s*"
    r"(?:(?P<ex1>SH|SZ|BJ|HK)\s*[:：.．]?\s*)?"
    r"(?P<num>\d{4,6})"
    r"(?:\s*[.．]\s*(?P<ex2>SH|SZ|BJ))?"
    r"\s*[）)]?\s*$",
    re.I,
)
_US_TICKER_RE = re.compile(r"^\s*(?P<name>.*?)\s*[（(]?\s*(?P<code>[A-Z]{1,6}\.[NOA])\s*[）)]?\s*$", re.I)


def _parse_target_asset(target_asset):
    """把 Agent 传来的 target_asset 归一成 {name, code, exchange, raw}。

    Agent 会用各种写法表达同一只股票：`"工业富联(SH:601138)"` / `"工业富联 SH601138"` /
    `"601138.SH"` / `"工业富联"` / `{"name":...,"code":...}`。fork 的语义就是换标的，所以
    这个参数本来就该驱动替换，而不是像以前那样只被记进 manifest。
    """
    name = code = exchange = ""
    raw = ""
    if isinstance(target_asset, dict):
        raw = str(target_asset.get("raw") or "").strip()
        name = str(target_asset.get("name") or target_asset.get("symbol") or "").strip()
        code = str(target_asset.get("code") or target_asset.get("ticker") or "").strip()
        if not (name or code) and raw:
            return _parse_target_asset(raw)
    elif target_asset is not None:
        raw = str(target_asset).strip()
        text = raw
        match = _TARGET_IDENTITY_RE.match(text)
        us_match = _US_TICKER_RE.match(text)
        if match:
            name = (match.group("name") or "").strip()
            exchange = (match.group("ex1") or match.group("ex2") or "").strip().upper()
            code = match.group("num")
        elif us_match:
            name = (us_match.group("name") or "").strip()
            code = us_match.group("code").strip().upper()
        else:
            name = text
    if code and not exchange:
        head = re.match(r"^(SH|SZ|BJ|HK)", code, re.I)
        tail = re.search(r"[.．](SH|SZ|BJ)$", code, re.I)
        if head:
            exchange = head.group(1).upper()
        elif tail:
            exchange = tail.group(1).upper()
    digits = re.sub(r"\D", "", code)
    if exchange and re.fullmatch(r"\d{4,6}", digits):
        code = digits
    return {"name": name, "code": code, "exchange": exchange, "raw": raw or name or code}


def _assets_db_dir():
    """Resolve QBS assets_db through the shared exact active-skill resolver."""
    resolution = C.resolve_qbs_skill_root()
    root = resolution.get("root")
    if root is None:
        call_script = resolution.get("call_script")
        return os.path.join(str(call_script.parent.parent if call_script else ""), "presets", "assets_db")
    return os.path.join(str(root), "presets", "assets_db")


def _normalize_ticker(code):
    """把 601138.SH / SH:601138 / sh601138 统一成 SH601138；美股 AAPL.O 保留点号原样。"""
    text = str(code or "").strip().upper().replace("：", ":").replace("．", ".")
    if re.fullmatch(r"[A-Z]{1,6}\.[NOA]", text):
        return text
    text = text.replace(":", "").replace(".", "").replace(" ", "")
    match = re.fullmatch(r"(\d{4,6})(SH|SZ|BJ|HK)", text)
    if match:
        return match.group(2) + match.group(1)
    return text


def _lookup_asset_name_by_ticker(code):
    """按代码反查资产名。查不到/资产库缺失一律返回 ""，绝不因此让 fork 失败。

    只做 ticker→name 这一个方向：实测 10553 条 ticker 零冲突，而 name→ticker 有 195 条
    跨市场同名（如「民生银行」同时是 SH600016 和 HK1988），反方向不可靠。
    """
    key = _normalize_ticker(code)
    if not key:
        return ""
    candidates = [key]
    if key.isdigit():
        candidates = [prefix + key for prefix in ("SH", "SZ", "BJ", "HK")]
    try:
        directory = _assets_db_dir()
        for filename in sorted(os.listdir(directory)):
            if not filename.endswith((".yaml", ".yml")):
                continue
            with open(os.path.join(directory, filename), "r", encoding="utf-8") as handle:
                for line in handle:
                    if "|" not in line:
                        continue
                    parts = [part.strip() for part in line.split("|")]
                    if len(parts) >= 3 and parts[0] in ("stock", "index", "future") and parts[2] in candidates:
                        return parts[1]
    except OSError:
        return ""
    return ""


def _code_variant_candidates(code, exchange=""):
    """枚举同一个代码在页面里可能的书写形态（长度降序，供掩码扫描使用）。"""
    digits = re.sub(r"\D", "", str(code or ""))
    if not re.fullmatch(r"\d{6}", digits):
        text = str(code or "").strip()
        return [text] if text else []
    market = (exchange or _exchange_for_code(digits)).upper()
    variants = [
        f"{market}{digits}", f"{market.lower()}{digits}",
        f"{digits}.{market}", f"{digits}.{market.lower()}",
        f"{market}:{digits}", f"{market}.{digits}",
        digits,
    ]
    return sorted(_unique_strings(variants), key=len, reverse=True)


def _source_code_variants_present(code, html, exchange=""):
    """只返回**确实出现在来源 HTML 里**的代码写法，这样后续替换永远不会「找不到替换项」。

    必须按长度降序 + 命中即掩码：裸 600900 是 SH600900 的子串，直接 count 会把同一处
    重复统计成两处，进而把一个其实并不独立存在的写法当成必须替换项——这正是线上那次
    「未在来源 HTML 找到替换项: 600900.SH」连撞三次的同类陷阱。
    """
    probe = str(html or "")
    present = []
    for candidate in _code_variant_candidates(code, exchange):
        if candidate and probe.count(candidate):
            present.append(candidate)
            probe = probe.replace(candidate, "\x00" * len(candidate))
    return present


def _derive_source_asset_identity(record, source_html, hint=None):
    """确定来源模板的主资产：Agent 显式指定优先，其次按公式标的词频自动推导。

    Agent 优先是有意的——个股/指数/多资产范式语义差别太大，没法用一套代码统一判定主资产。
    自动推导只在「词频唯一最高且该名字出现在标题里」时才认为可信，否则 fail-closed。
    """
    formulas = [
        formula
        for package in (record.get("packages") or [])
        if isinstance(package, dict)
        for formula in (package.get("formulas") or [])
    ]
    counter = Counter()
    for formula in formulas:
        counter.update(FRC.formula_asset_refs(formula))
    title = str(record.get("title") or "")
    description = str(record.get("description") or "")

    codes = []
    for grant in (record.get("grants") or []):
        if not isinstance(grant, dict):
            continue
        payload = grant.get("payload")
        if payload is None:
            continue
        for token in re.findall(r"(?:SH|SZ|BJ|HK)\d{4,6}|\d{6}\.(?:SH|SZ|BJ)|[A-Z]{1,6}\.[NOA]",
                                json.dumps(payload, ensure_ascii=False), re.I):
            codes.append(token)

    hint_parsed = _parse_target_asset(hint) if hint else None
    if hint_parsed and (hint_parsed.get("name") or hint_parsed.get("code")):
        name = hint_parsed.get("name") or ""
        code = hint_parsed.get("code") or (codes[0] if codes else "")
        exchange = hint_parsed.get("exchange") or ""
        if not name and code:
            name = _lookup_asset_name_by_ticker(code)
        peers = [token for token in counter if token != name]
        return {
            "name": name,
            "code": code,
            "exchange": exchange,
            "peers": peers,
            "confident": bool(name and name in source_html),
            "reason": "agent_specified" if name and name in source_html else "agent_specified_name_absent_in_html",
            "candidates": [token for token, _ in counter.most_common()],
            "present_code_variants": _source_code_variants_present(code, source_html, exchange) if code else [],
        }

    ranked = counter.most_common()
    top = [token for token, count in ranked if ranked and count == ranked[0][1]]
    name = top[0] if len(top) == 1 else ""
    if not ranked:
        reason = "no_formula_asset_tokens"
    elif len(top) > 1:
        reason = "multiple_top_candidates"
    elif name not in title and name not in description:
        reason = "top_candidate_not_in_title"
        name = ""
    elif name not in source_html:
        reason = "top_candidate_not_in_html"
        name = ""
    else:
        reason = "derived_from_formulas"

    code = ""
    exchange = ""
    for token in codes:
        parsed = _parse_target_asset(token)
        if _source_code_variants_present(parsed.get("code"), source_html, parsed.get("exchange")):
            code, exchange = parsed.get("code"), parsed.get("exchange")
            break
    return {
        "name": name,
        "code": code,
        "exchange": exchange,
        "peers": [token for token, _ in ranked if token != name],
        "confident": bool(name),
        "reason": reason,
        "candidates": [token for token, _ in ranked],
        "present_code_variants": _source_code_variants_present(code, source_html, exchange) if code else [],
    }


def _derive_asset_replacements(identity, target, source_html):
    """由「来源身份 + 目标身份」派生替换映射，只包含来源 HTML 里真实存在的写法。"""
    derived = {}
    if identity.get("name") and target.get("name") and identity["name"] != target["name"]:
        derived[identity["name"]] = target["name"]
    source_code = identity.get("code")
    target_code = target.get("code")
    if source_code and target_code:
        target_market = (target.get("exchange") or "").upper()
        source_digits = re.sub(r"\D", "", source_code)
        target_digits = re.sub(r"\D", "", target_code)
        if re.fullmatch(r"\d{6}", source_digits) and re.fullmatch(r"\d{6}", target_digits):
            if not target_market:
                target_market = _exchange_for_code(target_digits)
            source_market = (identity.get("exchange") or _exchange_for_code(source_digits)).upper()
            mapping = {
                f"{source_market}{source_digits}": f"{target_market}{target_digits}",
                f"{source_market.lower()}{source_digits}": f"{target_market.lower()}{target_digits}",
                f"{source_digits}.{source_market}": f"{target_digits}.{target_market}",
                f"{source_digits}.{source_market.lower()}": f"{target_digits}.{target_market.lower()}",
                f"{source_market}:{source_digits}": f"{target_market}:{target_digits}",
                f"{source_market}.{source_digits}": f"{target_market}.{target_digits}",
                source_digits: target_digits,
            }
            for variant in _source_code_variants_present(source_code, source_html, identity.get("exchange")):
                if variant in mapping:
                    derived[variant] = mapping[variant]
        elif source_code in source_html:
            derived[source_code] = target_code
    return derived


def _fork_identity_error(error_code, message, identity, target, source_template_id):
    """所有资产身份类失败都必须自带答案：把已探测到的来源身份和可照抄的正确调用一并返回。"""
    example = {
        "task_id": "task_xxx",
        "source_template_id": source_template_id,
        "target_page_id": "page_xxx",
        "target_asset": {"name": target.get("name") or "目标资产名", "code": target.get("code") or "目标资产代码"},
    }
    if not identity.get("confident"):
        example["source_asset"] = {
            "name": (identity.get("candidates") or ["来源模板主资产名"])[0],
            "code": identity.get("code") or "来源资产代码",
        }
    return {
        "code": 1,
        "error": error_code,
        "message": message,
        "detected_source_asset": {
            "name": identity.get("name") or "",
            "candidates": identity.get("candidates") or [],
            "code": identity.get("code") or "",
            "code_forms_in_source_html": identity.get("present_code_variants") or [],
            "reason": identity.get("reason") or "",
        },
        "target_asset_parsed": {"name": target.get("name") or "", "code": target.get("code") or ""},
        "example_params": example,
    }


def _expand_asset_replacements(replacements, html=""):
    """自动补全代码大小写/交易所前后缀等常见变体。html 非空时，只补那些确实出现在来源 HTML 里的
    变体——fork_prepare 随后会对每一项做「找不到就拒绝」的强校验，若在这里无脑补全一个来源 HTML
    根本不含的变体（如模板只写 SH600900，却自动多补一个 600900.SH），会导致明明只是自动推测出的
    变体、却把整次 fork_prepare 拖累到失败。不传 html（如单测）时保持旧的无条件补全行为。"""
    expanded = dict(replacements or {})
    for source, target in list(expanded.items()):
        source_code = str(source or "").strip()
        target_code = str(target or "").strip()
        if not (re.fullmatch(r"\d{6}", source_code) and re.fullmatch(r"\d{6}", target_code)):
            continue
        source_exchange = _exchange_for_code(source_code)
        target_exchange = _exchange_for_code(target_code)
        variants = {
            f"{source_exchange}{source_code}": f"{target_exchange}{target_code}",
            f"{source_exchange.lower()}{source_code}": f"{target_exchange.lower()}{target_code}",
            f"{source_code}.{source_exchange}": f"{target_code}.{target_exchange}",
            f"{source_exchange}.{source_code}": f"{target_exchange}.{target_code}",
        }
        for variant, replacement in variants.items():
            if variant in expanded:
                continue
            if html and variant not in html:
                continue
            expanded[variant] = replacement
    return expanded


def cmd_fork_prepare(params):
    source_template_id = params.get("source_template_id") or params.get("template_id") or params.get("page_id")
    if not source_template_id:
        return {"code": 1, "message": "fork_prepare 需要 source_template_id（或 template_id/page_id）"}

    # fork_prepare 是一次性、task-scoped 的来源绑定。重复执行会覆盖 manifest/review，
    # 尤其容易在第二次未重传 augmentation_spec 时静默丢掉新增栏目。
    task_id = _fork_task_id(params)
    if task_id:
        previous, _, read_error = _read_fork_task_binding(task_id)
        if read_error:
            return read_error
        if previous and previous.get("status") == "prepared":
            previous_source = str(previous.get("source_template_id") or "")
            force_rebuild = _bool_param(params.get("force_rebuild"))
            rebuild_reason = str(params.get("rebuild_reason") or "").strip()
            if not force_rebuild:
                return {
                    "code": 1,
                    "error": "FORK_ALREADY_BOUND",
                    "message": (
                        f"本 task 已完成 fork_prepare 绑定（来源 {previous_source}）。"
                        "改公式或业务决策请使用 fork_review_update；确需从来源整体重建时，"
                        "传 force_rebuild:true 并填写 rebuild_reason。"
                    ),
                    "recoverable": True,
                    "binding": {
                        "source_template_id": previous_source,
                        "revision": previous.get("revision"),
                        "working_html_file": previous.get("working_html_file"),
                    },
                }
            if not rebuild_reason:
                return {
                    "code": 1,
                    "error": "FORK_REBUILD_REASON_REQUIRED",
                    "message": "force_rebuild:true 时必须填写 rebuild_reason，说明为何不能用 fork_review_update。",
                }
            if previous_source and previous_source != str(source_template_id):
                return {
                    "code": 1,
                    "error": "FORK_SOURCE_TEMPLATE_CHANGED",
                    "message": (
                        f"本 task 已绑定来源 {previous_source}，不能改为 {source_template_id}。"
                        "如需换来源模板，请创建新 task。"
                    ),
                    "recoverable": True,
                    "binding": {"source_template_id": previous_source},
                }

    template_result = cmd_template({"page_id": source_template_id})
    if not (isinstance(template_result, dict) and template_result.get("code") == 0):
        return template_result
    record = _template_record(template_result)

    asset_replacements_param = params.get("asset_replacements") or {}
    if not isinstance(asset_replacements_param, dict):
        return {"code": 1, "message": "fork_prepare.asset_replacements 必须是对象"}
    target_identity = _parse_target_asset(params.get("target_asset"))

    source_url = record.get("download_url") or record.get("public_url") or record.get("url") or ""
    if not source_url:
        return {"code": 1, "message": "来源范式没有 download_url/public_url，无法准备 fork"}

    source_html, error = _fetch_oss(source_url)
    if error:
        return error
    source_sha = hashlib.sha256(source_html.encode("utf-8")).hexdigest()

    # 资产身份必须在拿到来源 HTML 之后才能定：只有此刻才知道代码在页面里究竟写成
    # SH600900 还是 600900.SH 还是裸 600900。以前把这件事推给 Agent 去猜，是让它对着
    # 一个自己从没见过、且流程明令禁止读取的文件做判断——线上因此连撞三次后退回自建。
    if not target_identity.get("name") and target_identity.get("code"):
        target_identity["name"] = _lookup_asset_name_by_ticker(target_identity["code"])
    source_identity = _derive_source_asset_identity(record, source_html, hint=params.get("source_asset"))

    derived_replacements = {}
    # 同标的改版判定：推导出的主资产同名，或目标资产名本就出现在来源标题/描述里
    # （后者覆盖「模板没有 packages、推导不出主资产」的纯静态改版）。
    source_title = str(record.get("title") or "") + " " + str(record.get("description") or "")
    same_asset = bool(
        target_identity.get("name")
        and (
            source_identity.get("name") == target_identity["name"]
            or target_identity["name"] in source_title
        )
    )
    if same_asset or not (target_identity.get("name") or target_identity.get("code")):
        pass  # 同标的改版 / 未声明目标资产的纯静态改造：不做资产替换
    elif not source_identity.get("confident"):
        if not asset_replacements_param:
            return _fork_identity_error(
                "FORK_SOURCE_ASSET_AMBIGUOUS",
                "无法唯一确定来源模板的主资产（多资产/指数类范式常见）。"
                "请显式传 source_asset 指明来源模板的主资产，或直接传 asset_replacements。"
                "detected_source_asset 里已给出探测到的候选资产名与来源 HTML 中真实存在的代码写法。",
                source_identity, target_identity, str(source_template_id),
            )
    elif not target_identity.get("name"):
        return _fork_identity_error(
            "TARGET_ASSET_NAME_REQUIRED",
            f"来源模板主资产是「{source_identity.get('name')}」，但 target_asset 只给了代码、"
            "资产库也没反查到对应名称，无法替换页面标题与正文文案。"
            "请按 example_params 传 target_asset:{\"name\":...,\"code\":...}。",
            source_identity, target_identity, str(source_template_id),
        )
    else:
        derived_replacements = _derive_asset_replacements(source_identity, target_identity, source_html)

    safe_id = re.sub(r"[^0-9A-Za-z._-]+", "_", str(source_template_id)).strip("._-") or "source"
    default_output_dir = (
        str(C.task_temp_dir(task_id, create=True)) if task_id
        else os.path.join("output", "forks", safe_id)
    )
    output_dir = _fork_path(params.get("output_dir") or default_output_dir)
    os.makedirs(output_dir, exist_ok=True)
    source_html_file = _fork_path(params.get("html_file") or f"{safe_id}.source.html", base=output_dir)
    working_html_file = _fork_path(params.get("working_html_file") or f"{safe_id}.fork.html", base=output_dir)
    manifest_file = _fork_path(params.get("manifest_file") or f"{safe_id}.fork-manifest-v2.json", base=output_dir)
    review_file = _fork_path(params.get("review_file") or f"{safe_id}.fork-review.json", base=output_dir)
    publish_plan_file = _fork_path(params.get("publish_plan_file") or f"{safe_id}.publish-plan.json", base=output_dir)
    prepared_html_file = _fork_path(params.get("prepared_html_file") or f"{safe_id}.published.html", base=output_dir)
    review_update_params_file = _fork_path(params.get("review_update_params_file") or f"{safe_id}.fork-review-update.json", base=output_dir)
    review_receipt_file = _fork_path(params.get("review_receipt_file") or f"{safe_id}.fork-review-receipt.json", base=output_dir)
    for path in (source_html_file, working_html_file, manifest_file, review_file, publish_plan_file, prepared_html_file, review_update_params_file, review_receipt_file):
        os.makedirs(os.path.dirname(path) or output_dir, exist_ok=True)
    with open(source_html_file, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source_html)

    # 派生映射打底，Agent 显式传的 asset_replacements 覆盖同名 key（向后兼容 + 额外文案替换）。
    replacements = dict(derived_replacements)
    replacements.update(_expand_asset_replacements(asset_replacements_param, source_html))
    fork_source_html, runtime_share_poster_contract_repairs = _upgrade_runtime_share_poster_contract(source_html)
    image_marker_html, source_managed_images, image_error = _prepare_fork_managed_images(fork_source_html, output_dir)
    if image_error:
        return image_error
    try:
        runtime = FRC.build_runtime_artifacts(
            image_marker_html,
            record,
            replacements=replacements,
            primary_sources=(
                list(_unique_strings(params.get("source_markers")))
                + list(replacements.keys())
                + [token for token in [source_identity.get("name")] + list(source_identity.get("present_code_variants") or []) if token]
            ),
            augmentation_spec=params.get("augmentation_spec"),
        )
    except FRC.ForkRuntimeError as exc:
        return exc.as_dict()

    source_signature_hashes = _signature_hashes(source_html)
    if set(source_signature_hashes) != set(runtime.get("source_signature_sha256") or []):
        return {
            "code": 1,
            "error": "SOURCE_CREDENTIAL_UNPAIRED",
            "message": "来源 HTML 存在未被 package/grant 合同配对的 signature",
        }

    working_html = runtime["working_html"]
    replacement_audit = []
    for source_value, target_value in sorted(replacements.items(), key=lambda item: len(str(item[0])), reverse=True):
        source_text = str(source_value or "")
        target_text = str(target_value or "")
        if not source_text:
            return {"code": 1, "message": "fork_prepare.asset_replacements 不允许空来源值"}
        count = working_html.count(source_text)
        if count == 0 and not _bool_param(params.get("allow_missing_replacements")):
            return {"code": 1, "message": f"fork_prepare 未在来源 HTML 找到替换项: {source_text}"}
        working_html = working_html.replace(source_text, target_text)
        replacement_audit.append({"source": source_text, "target": target_text, "count": count})

    # 建页时就把关，而不是等发布成功后再回头比对：一旦主资产还有残留，这里直接失败。
    # 同业资产不在检查范围内——它们本来就该留到 review 阶段由 target_slots 决策替换。
    if not same_asset and source_identity.get("name") and derived_replacements:
        residual = [
            token for token in [source_identity["name"]] + list(source_identity.get("present_code_variants") or [])
            if token and token in working_html
        ]
        if residual:
            return {
                "code": 1,
                "error": "FORK_SOURCE_ASSET_RESIDUAL",
                "message": (
                    f"替换后来源资产「{source_identity['name']}」仍残留在页面中："
                    f"{residual}。已在写出工作 HTML 前中止，避免发布后才发现残留模板文案。"
                ),
                "residual_tokens": residual,
                "replacement_audit": replacement_audit,
            }

    with open(working_html_file, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(working_html)

    context = record.get("page_context") if isinstance(record.get("page_context"), dict) else {}
    active_packages = [role for role in runtime["runtime_roles"] if role.get("kind") == "package"]
    active_grants = [role for role in runtime["runtime_roles"] if role.get("kind") == "grant"]
    reduction_reason = str(params.get("credential_count_reduction_reason") or "").strip()
    # record.get("package_ids"/"grant_ids") 是模板声明的完整凭证清单，可能包含这份来源 HTML
    # 里根本没嵌入/没发现的凭证（模板元数据残留、或该页面变体没实际用到）。之前这里直接把
    # 声明的清单和 runtime 实际发现的清单取并集写进 manifest，会掩盖"声明了但没找到"的差异，
    # 让 agent 误以为凭证都拿到了，直到 publish_workflow 最后一步才因公式数超限报错。
    undiscovered_packages = [
        value for value in _unique_strings(record.get("package_ids"))
        if value not in runtime["source_package_ids"]
    ]
    undiscovered_grants = [
        value for value in _unique_strings(record.get("grant_ids"))
        if value not in runtime["source_grant_ids"]
    ]
    if (undiscovered_packages or undiscovered_grants) and not reduction_reason:
        return {
            "code": 1,
            "error": "SOURCE_PACKAGE_UNDISCOVERED",
            "message": (
                "模板声明的公式包/Grant 未在来源 HTML 中找到对应凭证，可能是模板元数据残留或该页面变体未实际使用。"
                "若确认这些凭证本就不该随本次 fork 携带，请提供 credential_count_reduction_reason 后重试。"
            ),
            "undiscovered_package_ids": undiscovered_packages,
            "undiscovered_grant_ids": undiscovered_grants,
        }
    source_packages = list(runtime["source_package_ids"])
    source_grants = list(runtime["source_grant_ids"])
    source_h2 = [heading for heading in _html_headings(source_html, levels=(2,)) if heading not in ("分享海报",)]
    required_sections = _unique_strings(params.get("required_sections") or source_h2)
    runtime_required_outputs = [
        output for role in runtime["runtime_roles"]
        for output in role.get("required_outputs") or []
    ]
    required_outputs = _unique_strings(params.get("required_outputs") or list(_unique_strings(record.get("card_required_outputs"))) + runtime_required_outputs)
    image_markers = [item["marker"] for item in source_managed_images]
    source_markers = _unique_strings(list(_unique_strings(params.get("source_markers"))) + list(replacements.keys()) + image_markers)
    card_runtime_required = bool(
        params.get("card_runtime_required")
        if "card_runtime_required" in params
        else record.get("card_runtime_supported")
        or all(token in source_html for token in ("data-qb-card-template", "data-qb-card-manifest", "data-qb-card-runtime"))
    )
    try:
        minimum_target_package_count = int(params.get("minimum_target_package_count", len(active_packages)))
        minimum_target_grant_count = int(params.get("minimum_target_grant_count", len(active_grants)))
    except (TypeError, ValueError):
        return {"code": 1, "message": "fork_prepare 的 minimum_target_package_count/minimum_target_grant_count 必须是非负整数"}
    if minimum_target_package_count < 0 or minimum_target_grant_count < 0:
        return {"code": 1, "message": "fork_prepare 的 minimum_target_package_count/minimum_target_grant_count 必须是非负整数"}
    if (minimum_target_package_count < len(active_packages) or minimum_target_grant_count < len(active_grants)) and not reduction_reason:
        return {"code": 1, "message": "fork_prepare 下调最低凭证数量时必须提供 credential_count_reduction_reason"}

    trace = C.current_trace_context()
    user_query = str(params.get("user_query") or trace.get("user_query") or "").strip()
    target_page_id = str(params.get("target_page_id") or "").strip()

    # new_page 已经为目标页写入了用户意图标题。fork_prepare 不能在调用方没有
    # 再传 title 时回退到来源范式标题，否则异资产 fork 会在正式发布时把目标页
    # metadata 覆盖回来源资产。目标页详情读取失败时仍可用替换后的来源 metadata
    # 安全降级，不能因为一次只读请求阻断整个 fork。
    target_record = {}
    if target_page_id and target_page_id != str(source_template_id) and not params.get("title"):
        target_result = cmd_template({"page_id": target_page_id})
        if isinstance(target_result, dict) and target_result.get("code") == 0:
            target_record = _template_record(target_result)

    resolved_title = _replace_fork_metadata(
        params.get("title") or target_record.get("title") or record.get("title"),
        replacements,
    )
    resolved_description = _replace_fork_metadata(
        params.get("description") or record.get("description"),
        replacements,
    )
    resolved_page_context = (
        _replace_fork_metadata(params.get("page_context"), replacements)
        if isinstance(params.get("page_context"), dict)
        else None
    )
    resolved_metadata = {
        "title": resolved_title,
        "description": resolved_description,
        "page_context": resolved_page_context,
    }
    if not same_asset and source_identity.get("name"):
        metadata_residual = _fork_metadata_residual_tokens(resolved_metadata, source_identity)
        if metadata_residual:
            return {
                "code": 1,
                "error": "FORK_METADATA_SOURCE_ASSET_RESIDUAL",
                "message": (
                    f"异资产 fork 的发布 metadata 仍残留来源资产「{source_identity['name']}」："
                    f"{metadata_residual}。已在正式发布前中止，避免目标页标题或描述回退来源范式。"
                ),
                "residual_tokens": metadata_residual,
            }

    manifest = {
        "version": _FORK_MANIFEST_VERSION,
        "prepared_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_template_id": str(record.get("template_id") or record.get("page_id") or source_template_id),
        "source_url": source_url,
        "source_html_file": source_html_file,
        "working_html_file": working_html_file,
        "review_file": review_file,
        "publish_plan_file": publish_plan_file,
        "prepared_html_file": prepared_html_file,
        "runtime_share_poster_contract_repairs": runtime_share_poster_contract_repairs,
        "source_html_sha256": source_sha,
        "source_package_ids": source_packages,
        "source_grant_ids": source_grants,
        "source_signature_sha256": source_signature_hashes,
        "minimum_target_package_count": minimum_target_package_count,
        "minimum_target_grant_count": minimum_target_grant_count,
        "credential_count_reduction_reason": reduction_reason,
        "required_sections": required_sections,
        "context_sections": _unique_strings(context.get("core_sections") or []),
        "required_outputs": required_outputs,
        "source_headings": _html_headings(source_html),
        "source_markers": source_markers,
        "replacement_audit": replacement_audit,
        # target_asset 保持字符串：_bind_fork_task 会 str() 它，传 dict 会被错误 stringify。
        "target_asset": str(target_identity.get("raw") or params.get("target_asset") or ""),
        "target_asset_identity": target_identity,
        "source_asset_identity": source_identity,
        "intent_profile": params.get("intent_profile") or _read_intent_profile(task_id),
        "card_runtime_required": card_runtime_required,
        "agent_reply_template": record.get("agent_reply_template"),
        "page_context_reference": context or None,
        "source_managed_images": source_managed_images,
        "runtime_roles": runtime["runtime_roles"],
        "augmented_roles": runtime.get("augmented_roles") or [],
        "contract_fingerprint": FRC.contract_fingerprint([
            {"role_id": role["role_id"], "fingerprint": role["contract_fingerprint"]}
            for role in runtime["runtime_roles"] + (runtime.get("augmented_roles") or [])
        ]),
    }
    review = runtime["review"]
    review_bytes = (json.dumps(review, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    review_base_sha256 = hashlib.sha256(review_bytes).hexdigest()
    manifest["review_base_sha256"] = review_base_sha256
    publish_verified = {
        "page_id": target_page_id,
        "source_template_id": manifest["source_template_id"],
        "fork_manifest_file": manifest_file,
        "title": resolved_title,
        "description": resolved_description,
        "page_context": resolved_page_context,
        "agent_reply_template": record.get("agent_reply_template"),
        "require_agent_reply_template": True,
    }
    publish_plan = FRC.build_publish_plan(
        task_id=task_id,
        user_query=user_query,
        manifest_file=manifest_file,
        review_file=review_file,
        working_html_file=working_html_file,
        prepared_html_file=prepared_html_file,
        target_page_id=target_page_id,
        images=source_managed_images,
        publish_verified=publish_verified,
    )
    for path, payload in ((manifest_file, manifest), (publish_plan_file, publish_plan)):
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    _atomic_write_bytes(review_file, review_bytes)
    review_update_params = {
        "task_id": task_id,
        "target_page_id": target_page_id,
        "source_template_id": manifest["source_template_id"],
        "manifest_file": manifest_file,
        "review_file": review_file,
        "working_html_file": working_html_file,
        "publish_plan_file": publish_plan_file,
        "review_update_params_file": review_update_params_file,
        "review_receipt_file": review_receipt_file,
        "review_base_sha256": review_base_sha256,
        "decisions": FRC.build_decisions_skeleton(review),
    }
    _atomic_write_bytes(review_update_params_file, (json.dumps(review_update_params, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    review_state = FRC.review_state(manifest, review, working_html, intent_profile=manifest.get("intent_profile"))
    review_state["review_base_sha256"] = review_base_sha256

    fork_task_binding, binding_error = _bind_fork_task(params, manifest, manifest_file)
    if binding_error:
        binding_error.update({"source_template_id": manifest["source_template_id"], "manifest_file": manifest_file})
        return binding_error

    out = {
        "code": 0,
        "manifest_version": manifest["version"],
        "task_temp_dir": output_dir,
        "source_template_id": manifest["source_template_id"],
        "working_html_file": working_html_file,
        "manifest_file": manifest_file,
        "review_file": review_file,
        "review_state": review_state,
        "review_update_params_file": review_update_params_file,
        "review_update_command": _command_string([sys.executable, os.path.abspath(__file__), "fork_review_update", f"@{review_update_params_file}"]),
        "review_receipt_file": review_receipt_file,
        "publish_plan_file": publish_plan_file,
        "prepared_html_file": prepared_html_file,
        "required_sections": required_sections,
        "required_outputs": required_outputs,
        "runtime_role_count": len(runtime["runtime_roles"]),
        "augmented_role_count": len(runtime.get("augmented_roles") or []),
        "package_role_count": len(active_packages),
        "grant_role_count": len(active_grants),
        "card_runtime_required": card_runtime_required,
        "replacement_audit": replacement_audit,
        "images": source_managed_images,
        "page_context": context or None,
        "agent_reply_template": record.get("agent_reply_template"),
        "fork_task_binding": fork_task_binding,
        "publish_command": _command_string([sys.executable, os.path.join(C.SCRIPT_DIR, "publish_workflow.py"), f"@{publish_plan_file}"]),
        "next_step": "review_update_params_file.decisions 已按角色预生成嵌套占位骨架，只需要在骨架里补全空值；不要新增/改写顶层字段，也不要照抄 required_decisions 里的 decision_id 当 key。填完后运行 review_update_command；收到 complete receipt 后运行 publish_command。不要直接编辑 HTML/review 或创建辅助脚本。",
    }
    return _attach_agent_reply_hint(out, resource_role="source_template")


def _read_json_object(path, label):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except Exception as exc:
        raise ValueError(f"读取 {label} 失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} 必须是 JSON 对象")
    return payload


def cmd_fork_review_update(params):
    task_id = _fork_task_id(params)
    if not task_id:
        return {"code": 1, "error": "QBV_TRACE_CONTEXT_REQUIRED", "message": "fork_review_update 需要 task_id"}
    required_paths = {
        "manifest_file": params.get("manifest_file"),
        "review_file": params.get("review_file"),
        "working_html_file": params.get("working_html_file"),
        "publish_plan_file": params.get("publish_plan_file"),
        "review_receipt_file": params.get("review_receipt_file"),
    }
    if any(not str(value or "").strip() for value in required_paths.values()):
        return {
            "code": 1,
            "error": "FORK_REVIEW_FILES_REQUIRED",
            "message": "fork_review_update 缺少生成的 manifest/review/html/plan/receipt 路径",
        }
    paths = {key: os.path.abspath(str(value)) for key, value in required_paths.items()}
    try:
        manifest = _read_json_object(paths["manifest_file"], "manifest_file")
        review = _read_json_object(paths["review_file"], "review_file")
        plan = _read_json_object(paths["publish_plan_file"], "publish_plan_file")
        if plan.get("version") != FRC.PLAN_VERSION:
            raise ValueError(f"publish plan.version 必须是 {FRC.PLAN_VERSION}")
        expected_plan_paths = {
            "fork_manifest_file": paths["manifest_file"],
            "fork_review_file": paths["review_file"],
            "html_template_file": paths["working_html_file"],
        }
        for key, expected in expected_plan_paths.items():
            if os.path.abspath(str(plan.get(key) or "")) != expected:
                raise ValueError(f"publish plan.{key} 与 fork_prepare 产物不一致")
        with open(paths["working_html_file"], "r", encoding="utf-8") as handle:
            working_html = handle.read()
        with open(paths["review_file"], "rb") as handle:
            current_review_sha256 = hashlib.sha256(handle.read()).hexdigest()
        expected_review_sha256 = str(params.get("review_base_sha256") or "").strip()
        if not expected_review_sha256 or current_review_sha256 != expected_review_sha256:
            return {
                "code": 1,
                "error": "FORK_REVIEW_STALE",
                "message": "review 文件已脱离 fork_prepare/review_update 基线，请重新运行 fork_prepare",
            }
        updated = FRC.apply_review_decisions(review, params.get("decisions") or {})
        updated_bytes = (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        updated_sha256 = hashlib.sha256(updated_bytes).hexdigest()
        state = FRC.review_state(manifest, updated, working_html, intent_profile=manifest.get("intent_profile"))
        _atomic_write_bytes(paths["review_file"], updated_bytes)
        params["review_base_sha256"] = updated_sha256
        params["decisions"] = FRC.build_decisions_skeleton(updated)
        update_params_file = str(params.get("review_update_params_file") or "")
        if update_params_file:
            _atomic_write_bytes(
                update_params_file,
                (json.dumps(params, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            )
        if state["status"] != "complete":
            plan["review_receipt_file"] = ""
            plan["review_receipt_sha256"] = ""
            _atomic_write_bytes(
                paths["publish_plan_file"],
                (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            )
            try:
                os.unlink(paths["review_receipt_file"])
            except OSError:
                pass
            return {
                "code": 0,
                "review_state": {**state, "review_base_sha256": updated_sha256},
                "receipt_created": False,
                "review_update_params_file": update_params_file,
            }
        with open(paths["manifest_file"], "rb") as handle:
            manifest_sha256 = hashlib.sha256(handle.read()).hexdigest()
        with open(paths["working_html_file"], "rb") as handle:
            html_sha256 = hashlib.sha256(handle.read()).hexdigest()
        page_id = str(params.get("target_page_id") or (plan.get("publish_verified") or {}).get("page_id") or "")
        receipt = FRC.build_review_receipt(
            task_id=task_id,
            page_id=page_id,
            source_template_id=params.get("source_template_id") or manifest.get("source_template_id"),
            manifest_sha256=manifest_sha256,
            review_sha256=updated_sha256,
            working_html_sha256=html_sha256,
            review_base_sha256=str(manifest.get("review_base_sha256") or ""),
            resolved_contract_sha256=state["resolved_contract_sha256"],
        )
        receipt_bytes = (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
        _atomic_write_bytes(paths["review_receipt_file"], receipt_bytes)
        plan["review_receipt_file"] = paths["review_receipt_file"]
        plan["review_receipt_sha256"] = receipt_sha256
        _atomic_write_bytes(
            paths["publish_plan_file"],
            (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        return {
            "code": 0,
            "review_state": {**state, "review_base_sha256": updated_sha256},
            "review_receipt_file": paths["review_receipt_file"],
            "review_receipt_sha256": receipt_sha256,
            "publish_plan_file": paths["publish_plan_file"],
            "publish_command": _command_string([
                sys.executable, os.path.join(C.SCRIPT_DIR, "publish_workflow.py"),
                f"@{paths['publish_plan_file']}",
            ]),
        }
    except (OSError, ValueError, json.JSONDecodeError, FRC.ForkRuntimeError) as exc:
        if isinstance(exc, FRC.ForkRuntimeError):
            return exc.as_dict()
        return {"code": 1, "error": "FORK_REVIEW_UPDATE_FAILED", "message": str(exc)}


def _fetch_public_html(url):
    if not url:
        raise ValueError("缺少可下载的 public/download URL")
    req = urllib.request.Request(url, headers={"Accept": "text/html,application/xhtml+xml"}, method="GET")
    with C._NO_PROXY_OPENER.open(req, timeout=_DEFAULT_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _default_retrofit_out_file(page_id):
    base = os.path.join(C.SKILL_ROOT, "output", "card-runtime-retrofit")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "%s.html" % (page_id or "page"))


def _run_card_runtime_verify(
    html_file,
    *,
    artifact_only=False,
    require_browser=True,
    require_visual_contract=False,
    timeout_sec=180
):
    target = html_file
    cmd = ["node", os.path.join(C.SKILL_ROOT, "scripts", "verify_page.mjs"), target, "--card-runtime"]
    if require_browser:
        cmd.append("--require-browser")
    if artifact_only:
        cmd.append("--card-runtime-only")
    if require_visual_contract:
        cmd.append("--require-card-visual-contract")
    try:
        proc = subprocess.run(
            cmd,
            cwd=C.SKILL_ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raw = ((exc.stdout or "") + "\n" + (exc.stderr or "")).strip()
        return {
            "code": 124,
            "message": "card runtime 验收超时",
            "target": target,
            "timeout_sec": timeout_sec,
            "raw": raw[-1000:],
        }
    raw = (proc.stdout or proc.stderr or "").strip()
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {"code": proc.returncode, "raw": raw[-1000:]}
    data.setdefault("code", proc.returncode)
    return data


def _run_page_verifier(target, profile, *, card_runtime=False, timeout_sec=180):
    cmd = [
        "node",
        os.path.join(C.SKILL_ROOT, "scripts", "verify_page.mjs"),
        str(target),
        "--profile",
        str(profile),
        "--require-browser",
    ]
    if card_runtime:
        cmd.append("--card-runtime")
    try:
        proc = subprocess.run(
            cmd,
            cwd=C.SKILL_ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raw = ((exc.stdout or "") + "\n" + (exc.stderr or "")).strip()
        return {
            "code": 124,
            "error": "BROWSER_VERIFICATION_TIMEOUT",
            "verification_profile": profile,
            "target": str(target),
            "raw": raw[-1000:],
        }
    raw = (proc.stdout or proc.stderr or "").strip()
    try:
        result = json.loads(raw) if raw else {}
    except Exception:
        result = {"code": proc.returncode, "raw": raw[-1000:]}
    result.setdefault("code", proc.returncode)
    result.setdefault("verification_profile", profile)
    return result


def _verify_card_runtime_html(html, *, require_browser=True, timeout_sec=180):
    with tempfile.TemporaryDirectory(prefix="qb_card_runtime_verify_") as td:
        path = os.path.join(td, "page.html")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(html)
        return _run_card_runtime_verify(
            path,
            artifact_only=True,
            require_browser=require_browser,
            timeout_sec=timeout_sec,
        )


def _maybe_verify_card_runtime(html, params):
    if not params.get("verify_card_runtime"):
        return None
    result = _verify_card_runtime_html(
        html,
        require_browser=params.get("verify_card_runtime_browser", True),
        timeout_sec=int(params.get("verify_card_runtime_timeout_sec", 180)),
    )
    return {
        "ok": isinstance(result, dict) and result.get("code") == 0,
        "mode": "card-runtime-only",
        "result": result,
        "message": "card runtime artifact 验收未通过" if not (isinstance(result, dict) and result.get("code") == 0) else "",
    }


def _as_list(value):
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def _safe_stem(value):
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", str(value or "").strip())
    return stem.strip("._-") or "target"


def _card_runtime_verify_targets(params):
    targets = []
    for item in _as_list(params.get("targets")):
        if isinstance(item, dict):
            targets.append(dict(item))
        elif isinstance(item, str) and re.match(r"https?://", item, re.I):
            targets.append({"url": item})
        elif item:
            targets.append({"page_id": str(item)})
    for page_id in _as_list(params.get("page_ids")) + _as_list(params.get("page_id")):
        if page_id:
            targets.append({"page_id": str(page_id)})
    for template_id in _as_list(params.get("template_ids")) + _as_list(params.get("template_id")):
        if template_id:
            targets.append({"template_id": str(template_id)})
    for url in _as_list(params.get("urls")) + _as_list(params.get("url")):
        if url:
            targets.append({"url": str(url)})
    return targets


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _resolve_card_runtime_target(spec):
    spec = dict(spec or {})
    tid = spec.get("template_id") or spec.get("page_id")
    record = {}
    template = None
    url = spec.get("url") or spec.get("download_url")
    if tid:
        template = cmd_template({"template_id": tid} if spec.get("template_id") else {"page_id": tid})
        if not (isinstance(template, dict) and template.get("code") == 0):
            if not url:
                downloaded = cmd_download({"page_id": tid})
                if isinstance(downloaded, dict) and downloaded.get("code") == 0:
                    record = dict(downloaded)
                    record.pop("html", None)
                    url = record.get("download_url") or record.get("public_url") or record.get("url")
                    tid = record.get("template_id") or record.get("page_id") or tid
                else:
                    raise ValueError("读取模板失败: %s" % json.dumps(template, ensure_ascii=False)[:500])
        else:
            record = _template_record(template)
            url = url or record.get("download_url") or record.get("public_url") or record.get("url")
            tid = record.get("template_id") or record.get("page_id") or tid
    if not url:
        raise ValueError("缺少可验收的 url/download_url")
    return tid or "", url, record, template


def cmd_verify_card_runtime(params):
    """Fast batch verification for standalone card runtime artifacts."""
    targets = _card_runtime_verify_targets(params)
    if not targets:
        return {"code": 1, "message": "verify_card_runtime 需要 page_id/template_id/url 或对应列表"}

    out_dir = params.get("out_dir") or os.path.join(
        C.SKILL_ROOT,
        "output",
        "card-runtime-verify",
        datetime.now().strftime("%Y%m%d-%H%M%S"),
    )
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(C.SKILL_ROOT, out_dir)
    os.makedirs(out_dir, exist_ok=True)
    summary_file = os.path.join(out_dir, "summary.json")
    require_browser = params.get("require_browser", True)
    timeout_sec = int(params.get("timeout_sec", 180))
    results = []

    def flush():
        _write_json(summary_file, {
            "code": 0 if all(item.get("code") == 0 for item in results) else 1,
            "checked": len(results),
            "passed": len([item for item in results if item.get("code") == 0]),
            "failed": len([item for item in results if item.get("code") != 0]),
            "out_dir": out_dir,
            "results": results,
        })

    for index, spec in enumerate(targets, start=1):
        entry = {"index": index, "input": spec}
        try:
            tid, url, record, template = _resolve_card_runtime_target(spec)
            label = tid or ("url_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:10])
            html_file = os.path.join(out_dir, _safe_stem(label) + ".html")
            html = _fetch_public_html(url)
            with open(html_file, "w", encoding="utf-8", newline="\n") as f:
                f.write(html)
            verification = _run_card_runtime_verify(
                html_file,
                artifact_only=True,
                require_browser=require_browser,
                timeout_sec=timeout_sec,
            )
            card_check = verification.get("card_runtime_check") if isinstance(verification, dict) else {}
            manifest = card_check.get("manifest") if isinstance(card_check, dict) else {}
            artifact = card_check.get("artifact_hydrate") if isinstance(card_check, dict) else {}
            entry.update({
                "code": verification.get("code") if isinstance(verification, dict) else 1,
                "page_id": tid,
                "url": url,
                "html_file": html_file,
                "json_file": os.path.join(out_dir, _safe_stem(label) + ".json"),
                "title": record.get("title") if isinstance(record, dict) else "",
                "required_outputs": (manifest or {}).get("required_outputs") or [],
                "artifact_text": (artifact or {}).get("text") or "",
                "problems": verification.get("problems") if isinstance(verification, dict) else ["verify_page 无法解析输出"],
                "verification": verification,
            })
            if template is not None:
                entry["template"] = {
                    "template_id": record.get("template_id") or record.get("page_id") or tid,
                    "download_url": record.get("download_url"),
                    "updated_at": record.get("updated_at"),
                    "sha256": record.get("sha256"),
                }
        except Exception as exc:
            fallback = spec.get("page_id") or spec.get("template_id") or spec.get("url") or "target_%s" % index
            entry.update({
                "code": 1,
                "page_id": spec.get("page_id") or spec.get("template_id") or "",
                "url": spec.get("url") or "",
                "json_file": os.path.join(out_dir, _safe_stem(fallback) + ".json"),
                "message": str(exc),
                "problems": [str(exc)],
            })
        _write_json(entry["json_file"], entry)
        results.append(entry)
        flush()

    failed = [item for item in results if item.get("code") != 0]
    return {
        "code": 1 if failed else 0,
        "checked": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "out_dir": out_dir,
        "summary_file": summary_file,
        "results": results,
    }


def _load_card_runtime_retrofit():
    # Keep the optional retrofit stack isolated from every other static_page
    # command. A broken renderer/import must not prevent new_page/update/etc.
    import importlib
    return importlib.import_module("card_runtime_retrofit")


def _retrofit_error_code(error):
    message = str(error or "")
    prefix = message.split(":", 1)[0].strip()
    if prefix.startswith("CARD_") or prefix == "TEMPLATE_WRITE_UNSUPPORTED":
        return prefix
    return "CARD_RUNTIME_RETROFIT_FAILED"


def cmd_retrofit_card_runtime(params):
    """Rebuild standalone card-runtime artifacts without affecting other commands."""
    try:
        retrofit_module = _load_card_runtime_retrofit()
    except Exception as error:
        return {
            "code": 1,
            "error": "CARD_RUNTIME_RETROFIT_UNAVAILABLE",
            "message": "card runtime retrofit 模块加载失败: %s" % error,
        }
    try:
        return _cmd_retrofit_card_runtime_impl(params, retrofit_module)
    except Exception as error:
        return {
            "code": 1,
            "error": _retrofit_error_code(error),
            "message": str(error),
        }


def _cmd_retrofit_card_runtime_impl(params, retrofit_module):
    """Rebuild standalone card-runtime artifacts for a published template/page."""
    tid = params.get("template_id") or params.get("page_id")
    url = params.get("url") or params.get("download_url")
    if not tid and not url:
        return {"code": 1, "message": "retrofit_card_runtime 需要 page_id/template_id 或 url"}

    before = None
    record = {}
    if tid:
        before = cmd_template({"template_id": tid} if params.get("template_id") else {"page_id": tid})
        if not (isinstance(before, dict) and before.get("code") == 0):
            if not url:
                return {"code": 1, "message": "读取模板失败", "template": before}
        else:
            record = _template_record(before)
            url = url or record.get("download_url") or record.get("public_url") or record.get("url")
            tid = record.get("template_id") or record.get("page_id") or tid

    source_html_file = params.get("source_html_file")
    if source_html_file:
        source_path = source_html_file if os.path.isabs(source_html_file) else os.path.join(C.SKILL_ROOT, source_html_file)
        with open(source_path, "r", encoding="utf-8") as f:
            html = f.read()
    else:
        html = _fetch_public_html(url)
    if params.get("preserve_visual"):
        next_html, info = retrofit_module.upgrade_artifact_protocol(html)
    else:
        next_html, info = retrofit_module.retrofit_html(
            html,
            page_id=tid or params.get("page_id") or "",
            title=params.get("title") or record.get("title") or "",
            visual_contract=params.get("visual_contract"),
        )

    out_file = params.get("out_file") or _default_retrofit_out_file(tid or params.get("page_id") or "page")
    if not os.path.isabs(out_file):
        out_file = os.path.join(C.SKILL_ROOT, out_file)
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(next_html)

    verify_default = (
        _run_card_runtime_verify(
            out_file,
            artifact_only=True,
            require_visual_contract=not bool(params.get("preserve_visual")),
        )
        if params.get("verify", True)
        else None
    )
    if verify_default and verify_default.get("code") != 0:
        return {"code": 1, "message": "card runtime 独立验收未通过", "html_file": out_file, "retrofit": info, "verification": verify_default}

    update_result = None
    if params.get("update"):
        if not tid:
            return {"code": 1, "message": "url 模式不能 update；请传 page_id/template_id", "html_file": out_file, "retrofit": info}
        if record.get("template_status") == "published" or record.get("is_template") is True:
            return {
                "code": 1,
                "error": "TEMPLATE_WRITE_UNSUPPORTED",
                "message": "该页面已转为公共模板（template_status=published），本 skill 不支持写回；如需保留原模板链接更新，请走后台/admin 管理入口。",
                "html_file": out_file,
                "retrofit": info,
                "preflight_template": before,
            }
        update_result = cmd_update({
            "page_id": tid,
            "html_file": out_file,
        })
        if not (isinstance(update_result, dict) and update_result.get("code") == 0):
            return {"code": 1, "message": "写回失败", "html_file": out_file, "retrofit": info, "update": update_result}

    return {
        "code": 0,
        "page_id": tid or params.get("page_id") or "",
        "url": url,
        "html_file": out_file,
        "retrofit": info,
        "verification": verify_default,
        "update": update_result,
        "preflight_template": before,
    }


_COMMANDS = {
    "new_asset_page": cmd_new_asset_page,
    "new_page": cmd_new_page,
    "update_progress": cmd_update_progress,
    "publish_final": cmd_publish_final,
    "publish_verified": cmd_publish_verified,
    "upload": cmd_upload,
    "update": cmd_update,
    "interpret": cmd_interpret,
    "interpret_csv": cmd_interpret_csv,
    "download": cmd_download,
    "list": cmd_list,
    "init_reply_metadata": cmd_init_reply_metadata,
    "revoke": cmd_revoke,
    "image_upload": cmd_image_upload,
    "image_list": cmd_image_list,
    "tags": cmd_tags,
    "autotag": cmd_autotag,
    "publish_community": cmd_publish_community,
    "unpublish_community": cmd_unpublish_community,
    "templates": cmd_templates,
    "intent_profile": cmd_intent_profile,
    "research_templates": cmd_research_templates,
    "template": cmd_template,
    "direct_deliver": cmd_direct_deliver,
    "direct_finalize": cmd_direct_finalize,
    "fork_prepare": cmd_fork_prepare,
    "fork_compose": cmd_fork_compose,
    "fork_review_update": cmd_fork_review_update,
    "fork_validate": cmd_fork_validate,
    "retrofit_card_runtime": cmd_retrofit_card_runtime,
    "verify_card_runtime": cmd_verify_card_runtime,
}

_TRACE_REQUIRED_COMMANDS = {
    "new_asset_page", "new_page", "update_progress", "publish_final", "publish_verified", "upload", "update", "direct_deliver", "direct_finalize", "fork_validate", "image_upload",
    "templates", "intent_profile", "research_templates", "fork_prepare", "fork_compose", "fork_review_update",
}


def main():
    if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help"):
        C.emit({"code": 0, "message": f"用法: static_page.py <{'|'.join(_COMMANDS)}> [params]"}, out_name="sp_out.txt")
        sys.exit(0)
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        C.emit({"code": 1, "message": f"用法: static_page.py <{'|'.join(_COMMANDS)}> [params]",
                "doc": (__doc__ or "").strip()[:400]}, out_name="sp_out.txt")
        sys.exit(1)
    cmd = sys.argv[1]
    if any(arg in ("-h", "--help") for arg in sys.argv[2:]):
        C.emit({
            "code": 0,
            "command": cmd,
            "message": f"查看 {cmd} 用法请阅读 tools/static_page.md；帮助请求不会访问网络。",
        }, out_name="sp_out.txt")
        sys.exit(0)
    params = C.read_params(sys.argv[2:], env_var="SP_PARAMS")

    try:
        trace_err = C.require_trace_context() if cmd in _TRACE_REQUIRED_COMMANDS else None
        result = trace_err or _COMMANDS[cmd](params)
    except (FileNotFoundError, ValueError) as e:
        result = {"code": 1, "message": str(e)}
    emitted = _publish_verified_cli_result(result, params.get("task_id")) if cmd == "publish_verified" else result
    C.emit(emitted, out_name="sp_out.txt")
    sys.exit(0 if (isinstance(result, dict) and result.get("code") == 0) else 1)


if __name__ == "__main__":
    main()
