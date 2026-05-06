# Bundled Scripts Audit

This document enumerates every Python script shipped inside this skill, what it does, and its network / subprocess / filesystem behavior. Reviewers can use it to verify the skill's declared behavior without reading every line of code.

Last audited against version: **4.20.7**

---

## Top-level scripts

### `scripts/call.py`
- **Purpose**: Thin CLI dispatcher. Takes a tool name + JSON params, forwards most tool calls to `scripts/executor.py` via a subprocess of the same Python interpreter, and handles local session management / output post-processing.
- **Network**: Sends a best-effort `newSession` trace payload to the configured quant-buddy endpoint when both endpoint and API key are available. Other network calls happen inside `executor.py`.
- **Authentication**: Resolves API key from `config.json`, then `config.local.json`, then `QUANT_BUDDY_API_KEY` as an environment override. The key is sent only in the `Authorization: Bearer <key>` header.
- **Subprocess**: `subprocess.run([sys.executable, "scripts/executor.py", ...])`. No shell, no external binary.
- **Filesystem writes**: Session files under `output/`; command output snapshots under the system temp directory; chart / CSV outputs under `output/` for chart or download tools.
- **Reads secrets**: quant-buddy API key from config files or `QUANT_BUDDY_API_KEY`.

### `scripts/executor.py`
- **Purpose**: Calls the quant-buddy HTTPS API and returns the response.
- **Network**: Only the configured quant-buddy endpoint, defaulting to `https://www.quantbuddy.cn/**`, via `urllib.request` (stdlib). No third-party host is used by this script.
- **Authentication**: Resolves `api_key` in this order: (1) `config.json`, (2) `config.local.json` override, (3) `QUANT_BUDDY_API_KEY` environment override. The resolved key is sent only in the `Authorization: Bearer <key>` header. It is never logged, printed to stdout/stderr, or written to files.
- **Subprocess**: None.
- **Filesystem writes**: Optional logs / outputs under the skill root, depending on the invoked tool.

### `scripts/quant_api.py`
- **Purpose**: Python wrapper around `executor.py` for use as a library.
- **Network**: Same as `executor.py` (delegates to it).
- **Authentication**: Uses the same config loading behavior as `executor.py`.
- **Subprocess**: None.
- **Filesystem writes**: Session-aware calls may read the session file; normal API wrapper calls do not write files directly.

### `scripts/event_study_local.py`
- **Purpose**: Optional event-study helper. Combines quant-buddy data with a Bocha web-search step for news context.
- **Network**:
  - `https://www.quantbuddy.cn/**` through the quant-buddy API path.
  - `https://api.bochaai.com/v1/web-search` only when `BOCHA_API_KEY` or `bocha_api_key` is configured. The function returns an error immediately if no Bocha key is configured.
- **Authentication**: Reads `BOCHA_API_KEY` from the environment, or `bocha_api_key` from `config.local.json` / `config.json`.
- **Subprocess**: None.
- **Filesystem writes**: None.
- **Dependency**: Requires the `requests` package when this optional event-news helper is invoked.

### `scripts/self_update.py`
- **Purpose**: Self-update helper used only when the server explicitly requires a newer skill version and provides a verified zip package.
- **Network**: Downloads the provided zip URL with `urllib.request` when `--url` is used. No network call is made when `--zip-path` is used.
- **Integrity checks**: Requires an expected SHA-512 digest and expected version; validates the archive before replacing files.
- **Subprocess**: None.
- **Filesystem writes**: Extracts into a temporary staging directory; backs up the current skill outside `skills/` by default; replaces the target skill root while preserving `config.json`, `config.local.json`, `output`, and `logs`. `--dry-run` validates without replacement.
- **Safety checks**: Rejects absolute paths, Windows drive paths, NUL bytes, and `..` path traversal entries in the zip.

---

## Summary guarantees

| Concern | Status |
|---|---|
| Outbound network hosts | quant-buddy endpoint (required), `api.bochaai.com` (opt-in only), verified update zip URL only during self-update fallback |
| quant-buddy API key ever logged / transmitted to third-party host | No |
| PII (phone / SMS / email / device ID) collected | No |
| Subprocess / shell to external binary | No external binary; only `call.py` re-invokes `sys.executable` for dispatch |
| Writes outside skill root | Normal tools: no. `self_update.py`: yes, only for temporary extraction / backup / target skill replacement during explicit update fallback |
| Reads OS credentials / env vars beyond declared ones | No; declared environment variables are `QUANT_BUDDY_API_KEY` and optional `BOCHA_API_KEY` |

If any of the above statements is inaccurate, it is a bug and should be reported to the skill author.
