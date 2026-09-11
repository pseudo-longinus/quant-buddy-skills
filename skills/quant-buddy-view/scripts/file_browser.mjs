import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import os from 'node:os';

export async function launchFileBrowser() {
  let pw;
  try { pw = await import('playwright'); } catch {}
  if (!pw) {
    for (const root of [...(process.env.NODE_PATH || '').split(path.delimiter),
      path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')]) {
      if (!root) continue;
      const pkg = path.join(root, 'playwright/package.json');
      if (!fs.existsSync(pkg)) continue;
      try { pw = createRequire(pkg)('playwright'); break; } catch {}
    }
  }
  if (!pw) throw new Error('PLAYWRIGHT_REQUIRED');
  for (const channel of ['chrome', 'msedge', undefined]) {
    try { return await pw.chromium.launch({ ...(channel ? { channel } : {}), headless: true,
      args: [] }); } catch {}
  }
  throw new Error('BROWSER_REQUIRED');
}
