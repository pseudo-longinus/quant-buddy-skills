#!/usr/bin/env python3
"""
观照量化投研 Skill 一键安装脚本

运行方式：
    python scripts/setup.py

完成后无需任何其他配置，重启 VS Code 即可使用全部工具。
"""

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

SCRIPT_DIR = pathlib.Path(__file__).parent
SKILL_ROOT = SCRIPT_DIR.parent
CONFIG_PATH = SKILL_ROOT / "config.json"

# 兜底默认值——仅在 config.json 尚不存在时使用，勿在其他地方直接引用
_DEFAULT_TOOL_ENDPOINT = "https://test.quantbuddy.cn/skill"
_DEFAULT_AUTH_ENDPOINT = "https://test.quantbuddy.cn/user"


def _read_endpoints():
    """从 config.json 读取端点；文件不存在或字段缺失时回落到兜底值。"""
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return (
                cfg.get("auth_endpoint") or _DEFAULT_AUTH_ENDPOINT,
                cfg.get("endpoint")      or _DEFAULT_TOOL_ENDPOINT,
            )
        except Exception:
            pass
    return _DEFAULT_AUTH_ENDPOINT, _DEFAULT_TOOL_ENDPOINT


# ── 颜色输出（兼容 Windows）────────────────────────────────────────────────────
def _c(text, code):
    if sys.platform == "win32":
        return text
    return f"\033[{code}m{text}\033[0m"

def green(t):  return _c(t, "32")
def yellow(t): return _c(t, "33")
def red(t):    return _c(t, "31")
def bold(t):   return _c(t, "1")


# ── HTTP 工具 ──────────────────────────────────────────────────────────────────
def post(endpoint, path, payload):
    url = f"{endpoint.rstrip('/')}{path}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return json.loads(body)
        except Exception:
            return {"code": e.code, "message": body}
    except urllib.error.URLError as e:
        return {"code": 1, "message": f"无法连接服务器：{e.reason}"}


# ── 步骤 ───────────────────────────────────────────────────────────────────────
def step_check_existing():
    """如果 config.json 已有 api_key，询问是否跳过注册。"""
    if not CONFIG_PATH.exists():
        return None
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        key = cfg.get("api_key", "")
        if key and key != "sk-<你的密钥>":
            print(green(f"\n✓ 检测到已有 API Key（{key[:10]}...）"))
            ans = input("  是否跳过注册，直接进行环境配置？[Y/n] ").strip().lower()
            if ans in ("", "y"):
                # 补全旧配置中缺失的端点字段
                auth_ep, tool_ep = _read_endpoints()
                if not cfg.get("auth_endpoint"):
                    cfg["auth_endpoint"] = auth_ep
                if not cfg.get("endpoint"):
                    cfg["endpoint"] = tool_ep
                return cfg
    except Exception:
        pass
    return None


def step_get_auth_endpoint():
    """确认认证服务地址（用于注册/登录）；优先读 config.json。"""
    default_auth, _ = _read_endpoints()
    print(f"\n{bold('认证服务地址')}（直接回车使用默认值）：")
    print(f"  默认：{default_auth}")
    ep = input("  > ").strip()
    return ep if ep else default_auth


def step_register_or_login(endpoint):
    """完整的注册/登录流程，返回 api_key。"""
    print(f"\n{bold('获取 API Key')}")
    print("  输入您的手机号，将收到短信验证码。")
    print("  新用户自动注册，老用户重新生成密钥。\n")

    phone = input("  手机号：").strip()
    if not phone:
        print(red("  手机号不能为空"))
        sys.exit(1)

    # 发送验证码
    print("  正在发送验证码...", end="", flush=True)
    r = post(endpoint, "/skill/sendCode", {"phone": phone})
    if r.get("code") != 0:
        print(red(f"\n  发送失败：{r.get('message', r)}"))
        sys.exit(1)

    session_token = r["data"]["session_token"]
    is_registered = r["data"].get("is_registered", False)
    print(green(" 已发送"))

    sms_code = input("  请输入验证码：").strip()

    # 根据 is_registered 直接走对应接口
    if is_registered:
        print(yellow("  该手机号已注册，正在登录并生成新密钥..."))
        r2 = post(endpoint, "/skill/login", {
            "session_token": session_token,
            "sms_code": sms_code,
        })
    else:
        r2 = post(endpoint, "/skill/register", {
            "session_token": session_token,
            "sms_code": sms_code,
        })

    if r2.get("code") != 0:
        print(red(f"\n  失败：{r2.get('message', r2)}"))
        sys.exit(1)

    api_key = r2["data"]["api_key"]
    print(green(f"\n  ✓ {r2['data'].get('message', '成功')}"))
    print(f"  API Key：{bold(api_key)}")
    print(yellow("  ⚠ 此密钥只显示一次，请妥善保存（setup.py 会帮您写入配置文件）。"))
    return api_key


def step_write_config(auth_endpoint, tool_endpoint, api_key):
    """写入 config.json（区分工具服务和认证服务两个地址）。"""
    cfg = {
        "endpoint": tool_endpoint,
        "auth_endpoint": auth_endpoint,
        "api_key": api_key,
    }
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(green(f"\n  ✓ 已写入 {CONFIG_PATH}"))


def _print_manual_config():
    """提示用户配置文件位置。"""
    print(f"\n  配置文件位于：{CONFIG_PATH}")
    print(f"  手动编辑 config.json 即可修改 endpoint 和 api_key")


# ── 主流程 ──────────────────────────────────────────────────────────────────────
def main():
    print(bold("\n=== 观照量化投研 Skill 安装向导 ==="))
    print("  依赖：Python 3.8+，无需安装其他包\n")

    # 1. 检查是否已配置
    existing_cfg = step_check_existing()

    if existing_cfg:
        auth_ep, tool_ep = _read_endpoints()
        auth_endpoint = existing_cfg.get("auth_endpoint") or auth_ep
        tool_endpoint = existing_cfg.get("endpoint")      or tool_ep
        api_key  = existing_cfg.get("api_key")
    else:
        # 2. 确认认证服务地址
        auth_endpoint = step_get_auth_endpoint()
        _, tool_endpoint = _read_endpoints()
        # 3. 注册/登录拿 api_key（走 auth_endpoint）
        api_key = step_register_or_login(auth_endpoint)
        # 4. 写配置（两个地址都写入）
        step_write_config(auth_endpoint, tool_endpoint, api_key)

    # 5. 验证连通性（走 tool_endpoint）
    print(f"\n{bold('验证连通性')}...")
    import urllib.request as _ur
    try:
        test_data = json.dumps({"query": "收盘价", "top_k": 1}).encode("utf-8")
        test_req = _ur.Request(
            f"{tool_endpoint.rstrip('/')}/skill/searchFunctions",
            data=test_data,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with _ur.urlopen(test_req, timeout=30) as resp:
            test_result = json.loads(resp.read().decode("utf-8"))
        if test_result.get("code") == 0:
            print(green("  ✓ API 连通正常，Key 有效"))
        else:
            print(yellow(f"  ⚠ 返回 code={test_result.get('code')}：{test_result.get('message', '')}"))
    except Exception as e:
        print(yellow(f"  ⚠ 连通性测试失败：{e}"))
        print("    请检查 endpoint 和网络连接")

    print(green(f"\n✓ 安装完成！现在可以使用 guanzhao-quant skill 了。"))
    print(f"  调用方式：python scripts/call.py <工具名> '<JSON参数>'")
    print(f"  示例：python scripts/call.py searchFunctions '{{\"query\":\"收盘价\"}}'")
    print(f"  如需查看账户信息，访问：{tool_endpoint}/skill/me\n")


if __name__ == "__main__":
    main()
