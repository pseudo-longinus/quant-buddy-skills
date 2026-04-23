# Bundled Scripts Audit

This document enumerates every Python script shipped inside this skill, what it does, and its network / subprocess / filesystem behavior. Reviewers can use it to verify the skill's declared behavior without reading every line of code.

Last audited against version: **4.14.7**

---

## Top-level scripts

### `scripts/call.py`
- **Purpose**: Thin CLI dispatcher. Takes a tool name + JSON params, forwards to `scripts/executor.py` via a subprocess of the same Python interpreter.
- **Network**: None directly. Network calls happen inside `executor.py`.
- **Subprocess**: `subprocess.run([sys.executable, "scripts/executor.py", ...])`. No shell, no external binary.
- **Filesystem writes**: None.
- **Reads secrets**: Only `config.json` / `config.local.json` pass-through; secrets are handled by `executor.py`.

### `scripts/executor.py`
- **Purpose**: Calls the quant-buddy HTTPS API and returns the response.
- **Network**: Only `https://test.quantbuddy.cn/**` via `urllib.request` (stdlib). Host is taken from `config.json#endpoint` with a hardcoded default; no redirects to third-party hosts are followed without verification.
- **Authentication**: Resolves `api_key` in this order: (1) `QUANT_BUDDY_API_KEY` env var, (2) `config.local.json` `api_key` field, (3) `config.json` `api_key` field. The resolved key is sent **only** in the `Authorization: Bearer <key>` header. It is never logged, printed to stdout/stderr, or written to files.
- **Subprocess**: None.
- **Filesystem writes**: Optional response cache under `.cache/` within the skill root; chart / CSV outputs under `output/` when invoked by chart or download tools.

### `scripts/quant_api.py`
- **Purpose**: Python wrapper around `executor.py` for use as a library (not invoked during normal agent flow).
- **Network**: Same as `executor.py` (delegates to it).
- **Subprocess**: None.
- **Filesystem writes**: None.

### `scripts/event_study_local.py`
- **Purpose**: Optional event-study helper. Combines quant-buddy data with a Bocha web-search step for news context.
- **Network**:
  - `https://test.quantbuddy.cn/**` (via `executor.py`) — required.
  - `https://api.bochaai.com/v1/web-search` — **opt-in only**. The function returns `{"ok": false, "error": "BOCHA_API_KEY 未配置"}` immediately if the user has not set `BOCHA_API_KEY` (env var / `bocha_api_key` in `config.local.json` / `config.json`). No request is made without the key.
- **Subprocess**: None.
- **Filesystem writes**: None.
- **Dependency**: Requires the `requests` package **only when Bocha is enabled**. Without BOCHA_API_KEY the import path is bypassed.

### `scripts/repro_scan_null.py`, `scripts/update_cases_index.py`
- **Purpose**: Developer utilities for curating the skill's own preset/case files. Not invoked by the agent at runtime; intended for the skill author to regenerate local indices.
- **Network**: None.
- **Subprocess**: None.
- **Filesystem writes**: Only under `scripts/` and `presets/` within the skill root.

---

## `scripts/eval/`
Offline evaluation harness for the skill author to measure quality regressions. Not invoked at runtime. No network access, no subprocess, writes only to `scripts/eval/` outputs.

---

## Summary guarantees

| Concern | Status |
|---|---|
| Outbound network hosts | `test.quantbuddy.cn` (required), `api.bochaai.com` (opt-in only) |
| api_key ever logged / transmitted to other host | No |
| PII (phone / SMS / email / device ID) collected | No |
| Subprocess / shell to external binary | No (only re-invokes `sys.executable` for dispatch) |
| Writes outside skill root | No |
| Reads OS credentials / env vars beyond the declared ones | No (only reads `BOCHA_API_KEY` when the optional Bocha feature is used) |

If any of the above statements is inaccurate, it is a bug and should be reported to the skill author.
