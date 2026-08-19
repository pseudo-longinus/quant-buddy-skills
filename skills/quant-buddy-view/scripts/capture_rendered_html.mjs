#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

function parseArgs(argv) {
  const args = { source: '', output: '', waitMs: 1200, timeoutMs: 30000, readySelector: '' };
  for (let i = 0; i < argv.length; i += 1) {
    const value = argv[i];
    if (!value.startsWith('--') && !args.source) args.source = value;
    else if (value === '--output') args.output = argv[++i] || '';
    else if (value === '--wait-ms') args.waitMs = Number(argv[++i] || 1200);
    else if (value === '--timeout-ms') args.timeoutMs = Number(argv[++i] || 30000);
    else if (value === '--ready-selector') args.readySelector = argv[++i] || '';
    else throw new Error(`unknown argument: ${value}`);
  }
  if (!args.source || !args.output) {
    throw new Error('usage: node capture_rendered_html.mjs <html-file-or-url> --output <snapshot.html> [--wait-ms 1200] [--ready-selector selector]');
  }
  return args;
}

async function loadPlaywright() {
  try {
    return await import('playwright');
  } catch {}
  const roots = [
    ...(process.env.NODE_PATH || '').split(path.delimiter),
    path.join(process.cwd(), 'node_modules'),
    path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules'),
  ].map(item => (item || '').trim()).filter(Boolean);
  for (const root of [...new Set(roots)]) {
    const candidates = [path.join(root, 'playwright', 'package.json')];
    const pnpmRoot = path.join(root, '.pnpm');
    if (fs.existsSync(pnpmRoot)) {
      try {
        for (const name of fs.readdirSync(pnpmRoot)) {
          if (name.startsWith('playwright@')) candidates.push(path.join(pnpmRoot, name, 'node_modules', 'playwright', 'package.json'));
        }
      } catch {}
    }
    for (const pkg of candidates) {
      if (!fs.existsSync(pkg)) continue;
      try {
        return createRequire(pkg)('playwright');
      } catch {}
    }
  }
  return null;
}

async function launchBrowser(pw) {
  const relaxArgs = ['--disable-web-security', '--disable-features=IsolateOrigins,site-per-process'];
  const attempts = [
    { channel: 'chrome', headless: true, args: relaxArgs },
    { channel: 'msedge', headless: true, args: relaxArgs },
    { headless: true, args: relaxArgs },
  ];
  const errors = [];
  for (const options of attempts) {
    try { return await pw.chromium.launch(options); }
    catch (error) { errors.push(error?.message || String(error)); }
  }
  throw new Error(errors.join(' | '));
}

function sourceUrl(raw) {
  if (/^https?:\/\//i.test(raw)) return raw;
  const absolute = path.resolve(raw);
  if (!fs.existsSync(absolute)) throw new Error(`source HTML not found: ${absolute}`);
  return pathToFileURL(absolute).href;
}

const args = parseArgs(process.argv.slice(2));
const pw = await loadPlaywright();
if (!pw) throw new Error('playwright package is not available');
const browser = await launchBrowser(pw);
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.goto(sourceUrl(args.source), { waitUntil: 'load', timeout: args.timeoutMs });
  if (args.readySelector) {
    await page.waitForSelector(args.readySelector, { state: 'attached', timeout: args.timeoutMs });
  }
  try { await page.waitForLoadState('networkidle', { timeout: Math.min(args.timeoutMs, 8000) }); } catch {}
  if (Number.isFinite(args.waitMs) && args.waitMs > 0) await page.waitForTimeout(args.waitMs);

  const frozen = await page.evaluate(() => {
    let canvasCount = 0;
    for (const canvas of Array.from(document.querySelectorAll('canvas'))) {
      try {
        const image = document.createElement('img');
        image.src = canvas.toDataURL('image/png');
        image.alt = canvas.getAttribute('aria-label') || canvas.getAttribute('title') || '';
        image.width = canvas.width;
        image.height = canvas.height;
        image.setAttribute('data-qb-snapshot-canvas', 'true');
        for (const attr of Array.from(canvas.attributes)) {
          if (!['width', 'height'].includes(attr.name)) image.setAttribute(attr.name, attr.value);
        }
        canvas.replaceWith(image);
        canvasCount += 1;
      } catch {}
    }
    for (const input of Array.from(document.querySelectorAll('input, textarea, select'))) {
      if (input instanceof HTMLInputElement) {
        if (input.type === 'checkbox' || input.type === 'radio') {
          if (input.checked) input.setAttribute('checked', ''); else input.removeAttribute('checked');
        } else input.setAttribute('value', input.value);
      } else if (input instanceof HTMLTextAreaElement) {
        input.textContent = input.value;
      } else if (input instanceof HTMLSelectElement) {
        for (const option of Array.from(input.options)) {
          if (option.selected) option.setAttribute('selected', ''); else option.removeAttribute('selected');
        }
      }
    }
    for (const details of Array.from(document.querySelectorAll('details'))) {
      if (details.open) details.setAttribute('open', ''); else details.removeAttribute('open');
    }
    let inlineHandlerCount = 0;
    for (const element of Array.from(document.querySelectorAll('*'))) {
      for (const attr of Array.from(element.attributes)) {
        if (/^on/i.test(attr.name)) {
          element.removeAttribute(attr.name);
          inlineHandlerCount += 1;
        }
      }
    }
    const scripts = Array.from(document.scripts);
    for (const script of scripts) {
      script.setAttribute('type', 'application/x-qbv-rendered-snapshot');
      script.setAttribute('data-qb-snapshot-frozen', 'true');
    }
    return { canvasCount, inlineHandlerCount, scriptCount: scripts.length };
  });

  const html = await page.content();
  const output = path.resolve(args.output);
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, html, 'utf8');
  process.stdout.write(JSON.stringify({
    code: 0,
    source: args.source,
    output,
    bytes: Buffer.byteLength(html, 'utf8'),
    frozen,
  }, null, 2));
} finally {
  await browser.close();
}
