import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { findBrowser, playwrightLaunchAttempts, playwrightSearchRoots } from './browser_dependencies.mjs';

export async function launchFileBrowser() {
  let pw;
  try { pw = await import('playwright'); } catch {}
  if (!pw) {
    for (const root of playwrightSearchRoots()) {
      if (!root) continue;
      const pkg = path.join(root, 'playwright/package.json');
      if (!fs.existsSync(pkg)) continue;
      try { pw = createRequire(pkg)('playwright'); break; } catch {}
    }
  }
  if (!pw) throw new Error('PLAYWRIGHT_REQUIRED');
  for (const options of playwrightLaunchAttempts(findBrowser())) {
    try { return await pw.chromium.launch(options); } catch {}
  }
  throw new Error('BROWSER_REQUIRED');
}
