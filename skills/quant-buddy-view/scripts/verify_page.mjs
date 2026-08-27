#!/usr/bin/env node
/*
 * Verify a generated QuantBuddy page before upload/update.
 *
 * Usage:
 *   node scripts/verify_page.mjs output/pages/demo.html
 *   node scripts/verify_page.mjs https://pages.quantbuddy.cn/...
 *   node scripts/verify_page.mjs output/pages/demo.html --manifest output/pages/demo.manifest.json
 *   node scripts/verify_page.mjs output/pages/demo.html --require-browser
 *   node scripts/verify_page.mjs output/pages/demo.html --card-runtime-only
 *   node scripts/verify_page.mjs output/pages/demo.html --card-runtime-structure-only
 */

import fs from 'node:fs';
import crypto from 'node:crypto';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { parseExtraViewport, resolveVerificationProfile, CORE_ERROR_RE, TRACKER_NOISE_RE, isCoreConsoleError } from './verification_profiles.mjs';
import { staticImageProblems } from './image_verification.mjs';
import { cardVisualContractProblems } from './card_visual_contract.mjs';

const args = process.argv.slice(2);
const requireBrowser = args.includes('--require-browser');
const profileIdx = args.indexOf('--profile');
const profileName = profileIdx >= 0 ? args[profileIdx + 1] : 'full';
const minVisibleFontIdx = args.indexOf('--min-visible-font-px');
const minVisibleFontPx = minVisibleFontIdx >= 0 ? Number(args[minVisibleFontIdx + 1]) : 0;
if (minVisibleFontIdx >= 0 && (!Number.isFinite(minVisibleFontPx) || minVisibleFontPx <= 0)) {
  fs.writeSync(1, JSON.stringify({ code: 1, error: 'INVALID_MIN_VISIBLE_FONT', message: '--min-visible-font-px 必须是正数' }) + '\n');
  process.exit(1);
}
let verificationProfile;
try {
  verificationProfile = resolveVerificationProfile(profileName);
} catch (err) {
  fs.writeSync(1, JSON.stringify({ code: 1, error: err.code || 'UNKNOWN_VERIFICATION_PROFILE', message: err.message }) + '\n');
  process.exit(1);
}
const cardRuntimeStructureOnly = args.includes('--card-runtime-structure-only');
const cardRuntimeOnly = !cardRuntimeStructureOnly && (args.includes('--card-runtime-only') || verificationProfile.cardRuntimeOnly);
const cardRuntime = args.includes('--card-runtime') || cardRuntimeOnly || cardRuntimeStructureOnly;
const requireCardVisualContract = args.includes('--require-card-visual-contract');
const cardScreenshotIdx = args.indexOf('--card-screenshot');
const cardScreenshotPath = cardScreenshotIdx >= 0 ? args[cardScreenshotIdx + 1] : '';
const manifestIdx = args.indexOf('--manifest');
const manifestPath = manifestIdx >= 0 ? args[manifestIdx + 1] : '';
const extraViewports = [];
try {
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === '--extra-viewport') extraViewports.push(parseExtraViewport(args[i + 1], extraViewports.length + 1));
  }
} catch (err) {
  fs.writeSync(1, JSON.stringify({ code: 1, error: err.code || 'INVALID_EXTRA_VIEWPORT', message: err.message }) + '\n');
  process.exit(1);
}
const valueFlags = new Set(['--manifest', '--profile', '--card-screenshot', '--extra-viewport', '--min-visible-font-px']);
const positionals = [];
for (let i = 0; i < args.length; i += 1) {
  const arg = args[i];
  if (valueFlags.has(arg)) {
    i += 1;
    continue;
  }
  if (arg.startsWith('--')) continue;
  positionals.push(arg);
}
const target = positionals[0];

const VIEWPORTS = [...verificationProfile.viewports, ...extraViewports];

function sanitizeBrowserText(value) {
  return String(value || '')
    .replace(/https?:\/\/[^\s)'"<>]+/gi, '[URL]')
    .replace(/([?&](?:x-amz-[^=]+|signature)\s*=)[^&\s]+/gi, '$1[REDACTED]');
}

function emit(obj) {
  fs.writeSync(1, JSON.stringify(obj, null, 2) + '\n');
}

function fail(message) {
  emit({ code: 1, message });
  process.exit(1);
}

if (!target) {
  fail('用法: node scripts/verify_page.mjs <html_file_or_url> [--profile full|fork-local|public-smoke|ui-refinement|live-only] [--extra-viewport [name:]WIDTHxHEIGHT] [--min-visible-font-px N] [--manifest manifest.json] [--require-browser] [--card-runtime] [--card-runtime-only] [--card-runtime-structure-only] [--require-card-visual-contract] [--card-screenshot output.png]');
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function isUrl(v) {
  return /^https?:\/\//i.test(v);
}

function splitLocalTarget(v) {
  const hashIndex = v.indexOf('#');
  const beforeHash = hashIndex >= 0 ? v.slice(0, hashIndex) : v;
  const hash = hashIndex >= 0 ? v.slice(hashIndex) : '';
  const queryIndex = beforeHash.indexOf('?');
  if (queryIndex < 0) return { file: beforeHash, search: '', hash };
  return {
    file: beforeHash.slice(0, queryIndex),
    search: beforeHash.slice(queryIndex),
    hash,
  };
}

function targetUrl(v) {
  if (isUrl(v)) return v;
  const parts = splitLocalTarget(v);
  const abs = path.isAbsolute(parts.file) ? parts.file : path.resolve(process.cwd(), parts.file);
  const url = new URL(pathToFileURL(abs).href);
  url.search = parts.search;
  url.hash = parts.hash;
  return url.href;
}

async function readHtml(v) {
  if (isUrl(v)) {
    const resp = await fetch(v);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.text();
  }
  const parts = splitLocalTarget(v);
  const abs = path.isAbsolute(parts.file) ? parts.file : path.resolve(process.cwd(), parts.file);
  return fs.readFileSync(abs, 'utf8');
}

function staticChecks(html) {
  const problems = [];
  const placeholders = ['QB_SHARED_', 'replace_with_signature', 'pkg_replace', '__PLACEHOLDER__'];
  for (const token of placeholders) {
    if (html.includes(token)) problems.push(`占位符残留: ${token}`);
  }
  if (!/<h1\b[^>]*>[\s\S]*?<\/h1>/i.test(html)) problems.push('缺少 <h1>');
  if (/<script\s+src=["'][^"']*(assets\/data-kernel|assets\/qr-mini|templates\/_shared)/i.test(html)) {
    problems.push('仍引用本地运行时脚本，未内联公共资源');
  }
  const stockConfigText = firstTaggedBlock(html, 'script', 'data-qbv-stock-instance');
  if (stockConfigText) {
    try {
      const stockConfig = JSON.parse(stockConfigText);
      if (stockConfig?.version === 'stock_analysis_instance_v1') {
        for (const match of html.matchAll(/\bconst\s+BOOT\s*=\s*(\{[\s\S]*?\});/g)) {
          try {
            const boot = JSON.parse(match[1]);
            if ((boot?.panels || []).some(panel => String(panel?.target_selector || '').trim() === '#priceChart')) {
              problems.push('STOCK_CHART_OWNER_CONFLICT: stock 原生 runtime 与 panel_block 同时接管 #priceChart');
              break;
            }
          } catch {}
        }
      }
    } catch {}
  }
  problems.push(...staticImageProblems(html));
  const hasPackage = /(?:["']?(?:package_id|packageId)["']?)\s*:\s*["'][^"']+["']/.test(html);
  return { ok: problems.length === 0, problems, hasPackage };
}

function firstTaggedBlock(html, tag, marker) {
  const re = new RegExp(`<${tag}\\b(?=[^>]*\\b${marker}\\b)[^>]*>([\\s\\S]*?)<\\/${tag}>`, 'i');
  const match = re.exec(html || '');
  return match ? match[1].trim() : '';
}

function sseUrl(endpoint) {
  return new URL('/skill/queryFormulaPackage', endpoint).toString();
}

function manifestPackages(manifest) {
  const list = [];
  if (Array.isArray(manifest?.packages)) {
    manifest.packages.forEach((item, index) => {
      if (!item || typeof item !== 'object') return;
      const endpoint = item.endpoint || manifest.endpoint;
      const packageId = item.package_id || item.packageId;
      const signature = item.signature;
      if (!endpoint || !packageId || !signature) return;
      list.push({
        role: item.role || `package_${index + 1}`,
        endpoint,
        package_id: packageId,
        signature,
        outputs: Array.isArray(item.outputs) ? item.outputs : [],
      });
    });
  }
  if (list.length) return list;
  if (manifest?.endpoint && manifest?.package_id && manifest?.signature) {
    return [{
      role: 'default',
      endpoint: manifest.endpoint,
      package_id: manifest.package_id,
      signature: manifest.signature,
      outputs: Array.isArray(manifest.required_outputs) ? manifest.required_outputs : [],
    }];
  }
  return [];
}

async function parseSseOutputs(resp, expectedOutputs = []) {
  const outputs = {};
  if (!resp.body) return outputs;
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const expected = new Set(expectedOutputs || []);
  function hasExpectedOutputs() {
    if (!expected.size) return false;
    for (const key of expected) {
      if (outputs[key] == null) return false;
    }
    return true;
  }
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r/g, '');
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() || '';
    for (const block of blocks) {
      let event = '';
      const lines = [];
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) lines.push(line.slice(5).replace(/^ /, ''));
      }
      if (event !== 'result' || !lines.length) continue;
      try {
        const payload = JSON.parse(lines.join('\n'));
        if (payload.output) outputs[payload.output] = payload;
      } catch {}
      if (hasExpectedOutputs()) {
        try {
          await reader.cancel();
        } catch {}
        return outputs;
      }
    }
  }
  return outputs;
}

function countLongDash(text) {
  return ((text || '').match(/—/g) || []).length;
}

async function artifactHydrateChecks(template, style, runtimeScript, outputs, options = {}) {
  const result = { checked: false, skipped: false, reason: '', text: '', sizes: [], problems: [] };
  const pw = await loadPlaywright();
  if (!pw) {
    result.skipped = true;
    result.reason = 'playwright package is not available';
    if (options.requireBrowser) result.problems.push(`card artifact 独立 hydrate 未执行: ${result.reason}`);
    return result;
  }

  let browser;
  try {
    browser = await launchPlaywrightBrowser(pw);
    const page = await browser.newPage({ viewport: { width: 720, height: 540 } });
    const sizes = [
      { label: '720x540', width: 720, height: 540 },
      { label: '410x308', width: 410, height: 308 },
      { label: '320x240', width: 320, height: 240 },
    ];
    const hydratedSizes = [];
    for (const size of sizes) {
      await page.setViewportSize({ width: size.width, height: size.height });
      await page.setContent(`<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>html,body{margin:0;width:${size.width}px;height:${size.height}px;overflow:hidden}#root{width:${size.width}px;height:${size.height}px}</style>
  <style data-qb-card-style>${style}</style>
</head>
<body>
  <div id="root"></div>
  <template data-qb-card-template>${template}</template>
  <script>${runtimeScript.replace(/<\/script/gi, '<\\/script')}<\/script>
</body>
</html>`, { waitUntil: 'load' });
      const hydrated = await page.evaluate((cardOutputs) => {
      const root = document.getElementById('root');
      const runtime = window.QBCardRuntimeV1;
      if (runtime && typeof runtime.mount === 'function') {
        const mounted = runtime.mount(root, { outputs: cardOutputs || {} });
        if (mounted && typeof mounted.hydrate === 'function') mounted.hydrate(cardOutputs || {});
      } else {
        const templateEl = document.querySelector('template[data-qb-card-template]');
        if (templateEl) root.replaceChildren(templateEl.content.cloneNode(true));
        if (runtime && typeof runtime.hydrate === 'function') runtime.hydrate(root, cardOutputs || {});
      }
      function visibleText(scope) {
        const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT, {
          acceptNode(node) {
            const parent = node.parentElement;
            if (!parent) return NodeFilter.FILTER_REJECT;
            const tag = parent.tagName.toLowerCase();
            if (tag === 'style' || tag === 'script' || tag === 'template') return NodeFilter.FILTER_REJECT;
            const text = (node.nodeValue || '').trim();
            return text ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
          },
        });
        const parts = [];
        while (walker.nextNode()) parts.push(walker.currentNode.nodeValue.trim());
        return parts.join(' ').replace(/\s+/g, ' ').trim();
      }
      const card = root.querySelector('[data-qb-live-card]');
      const rect = card ? card.getBoundingClientRect() : null;
      return {
        runtimePresent: !!(runtime && typeof runtime.hydrate === 'function'),
        rootHasCard: !!card,
        ready: card?.getAttribute('data-qb-card-ready') === 'true',
        text: visibleText(root),
        rect: rect ? { width: rect.width, height: rect.height } : null,
        overflow: card ? {
          scrollWidth: card.scrollWidth,
          clientWidth: card.clientWidth,
          scrollHeight: card.scrollHeight,
          clientHeight: card.clientHeight,
        } : null,
      };
      }, outputs || {});
      hydrated.label = size.label;
      hydratedSizes.push(hydrated);
      if (options.screenshotPath && size.label === '720x540' && hydrated.rootHasCard) {
        const screenshotAbs = path.isAbsolute(options.screenshotPath)
          ? options.screenshotPath
          : path.resolve(process.cwd(), options.screenshotPath);
        fs.mkdirSync(path.dirname(screenshotAbs), { recursive: true });
        await page.locator('#root [data-qb-live-card]').screenshot({ path: screenshotAbs, type: 'png' });
        result.screenshot = screenshotAbs;
      }
    }
    const hydrated = hydratedSizes[0] || {};
    result.checked = true;
    result.sizes = hydratedSizes.map(item => ({
      label: item.label,
      rect: item.rect || null,
      overflow: item.overflow || null,
      text_length: (item.text || '').length,
    }));
    result.text = hydrated.text || '';
    for (const item of hydratedSizes) {
      if (!item.runtimePresent) result.problems.push(`card runtime 独立 hydrate 未暴露 hydrate(root, outputs) (${item.label})`);
      if (!item.rootHasCard) result.problems.push(`card artifact 独立 hydrate 后缺少 data-qb-live-card 根节点 (${item.label})`);
      if (!item.ready) result.problems.push(`card artifact 独立 hydrate 后未进入 ready 状态 (${item.label})`);
      if (!item.text || item.text.length < 6) result.problems.push(`card artifact 独立 hydrate 后内容疑似空白 (${item.label})`);
      // A real strategy position can legitimately be 0.0%. Only explicit
      // loading copy or repeated em-dash placeholders indicate stale hydrate.
      if (/待更新|取数中|判断生成中/.test(item.text) || countLongDash(item.text) >= 3) {
        result.problems.push(`card artifact 独立 hydrate 后仍含长期占位态 (${item.label})`);
      }
      if (item.overflow) {
        const xOverflow = item.overflow.scrollWidth > item.overflow.clientWidth + 2;
        const yOverflow = item.overflow.scrollHeight > item.overflow.clientHeight + 2;
        if (xOverflow || yOverflow) {
          result.problems.push(
            `card artifact 独立 hydrate 后内容溢出 (${item.label}): ${item.overflow.scrollWidth}x${item.overflow.scrollHeight} > ${item.overflow.clientWidth}x${item.overflow.clientHeight}`,
          );
        }
      }
    }
    return result;
  } catch (err) {
    result.skipped = true;
    result.reason = err && err.message ? err.message : String(err);
    if (options.requireBrowser) result.problems.push(`card artifact 独立 hydrate 失败: ${result.reason}`);
    return result;
  } finally {
    if (browser) {
      try {
        await browser.close();
      } catch {}
    }
  }
}

async function cardRuntimeChecks(html, options = {}) {
  const problems = [];
  const template = firstTaggedBlock(html, 'template', 'data-qb-card-template');
  const style = firstTaggedBlock(html, 'style', 'data-qb-card-style');
  const manifestText = firstTaggedBlock(html, 'script', 'data-qb-card-manifest');
  const runtimeScript = firstTaggedBlock(html, 'script', 'data-qb-card-runtime');
  let manifest = null;
  let sampledOutputs = null;
  let artifactHydrate = {
    checked: false,
    skipped: true,
    reason: options.structureOnly ? 'structure-only 预检不取数、不执行 hydrate' : 'card artifact 不完整，跳过独立 hydrate',
    text: '',
    problems: [],
  };

  if (!template) problems.push('缺少 template[data-qb-card-template]');
  else if (!/\bdata-qb-live-card\b/i.test(template)) problems.push('card template 缺少 data-qb-live-card 根标记');
  if (!style) problems.push('缺少 style[data-qb-card-style]');
  if (!manifestText) {
    problems.push('缺少 script[type="application/json"][data-qb-card-manifest]');
  } else {
    try {
      manifest = JSON.parse(manifestText);
    } catch (err) {
      problems.push(`card manifest JSON 解析失败: ${err && err.message ? err.message : err}`);
    }
  }
  if (!runtimeScript) {
    problems.push('缺少 script[data-qb-card-runtime]');
  } else {
    if (!/window\.QBCardRuntimeV1\b/.test(runtimeScript)) problems.push('card runtime 未暴露 window.QBCardRuntimeV1');
    if (!/data-qb-card-ready/.test(runtimeScript)) problems.push('card runtime 未声明 hydrate ready 标记');
    if (/\b(fetch|XMLHttpRequest|EventSource)\b|queryFormulaPackage/i.test(runtimeScript)) {
      problems.push('card runtime 不应自动发起取数请求');
    }
    if (/sourceCard\s*\(/.test(runtimeScript) || /document\.querySelectorAll\(\s*["']\[data-qb-live-card\]/.test(runtimeScript)) {
      problems.push('card runtime 依赖完整页面 DOM/源 card，不能作为官网独立 artifact 运行');
    }
  }

  if (manifest) {
    const required = ['version', 'kind', 'required_outputs', 'aspect_ratio'];
    for (const key of required) {
      if (manifest[key] === undefined || manifest[key] === null || manifest[key] === '') problems.push(`card manifest 缺少 ${key}`);
    }
    const packages = manifestPackages(manifest);
    if (!packages.length) problems.push('card manifest 缺少 package_id/signature/endpoint 或 packages[]');
    if (manifest.kind !== 'embedded-card-v1') problems.push(`card manifest kind 不支持: ${manifest.kind}`);
    if (manifest.version !== '1.1.0') problems.push(`card manifest version 不支持: ${manifest.version}`);
    if (manifest.aspect_ratio !== '4/3') problems.push(`card manifest aspect_ratio 不支持: ${manifest.aspect_ratio}`);
    // thumbnail_url 的整页缩略图能力已下线，但历史脏 manifest 仍可能带它，继续拒绝
    for (const imageField of ['card_snapshot_url', 'thumbnail_url']) {
      if (Object.prototype.hasOwnProperty.call(manifest, imageField)) {
        problems.push(`card manifest 不得包含服务端图片字段: ${imageField}`);
      }
    }
    if (!Array.isArray(manifest.required_outputs) || manifest.required_outputs.length === 0) {
      problems.push('card manifest required_outputs 必须是非空数组');
    } else {
      const normalizedOutputs = manifest.required_outputs.map(value => String(value || '').trim());
      if (normalizedOutputs.some(value => !value) || new Set(normalizedOutputs).size !== normalizedOutputs.length) {
        problems.push('card manifest required_outputs 必须是非空且不重复的字符串');
      }
    }
    if (!options.structureOnly && Array.isArray(manifest.required_outputs) && manifest.required_outputs.length > 0 && packages.length) {
      sampledOutputs = {};
      for (const pkg of packages) {
        const expected = (pkg.outputs && pkg.outputs.length ? pkg.outputs : manifest.required_outputs)
          .filter(key => manifest.required_outputs.includes(key));
        if (!expected.length) continue;
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 60000);
        try {
          const resp = await fetch(sseUrl(pkg.endpoint), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
            signal: controller.signal,
            body: JSON.stringify({
              package_id: pkg.package_id,
              signature: pkg.signature,
              outputs: expected,
            }),
          });
          if (!resp.ok) {
            problems.push(`card required_outputs 取数失败(${pkg.role}): HTTP ${resp.status}`);
          } else {
            const outputs = await parseSseOutputs(resp, expected);
            Object.assign(sampledOutputs, outputs);
          }
        } catch (err) {
          problems.push(`card required_outputs 取数异常(${pkg.role}): ${err && err.message ? err.message : err}`);
        } finally {
          clearTimeout(timeout);
        }
      }
      const missing = manifest.required_outputs.filter(key => sampledOutputs[key] == null);
      if (missing.length) {
        problems.push(`card manifest required_outputs 不存在或未返回: ${missing.slice(0, 12).join(', ')}`);
      }
    }
    problems.push(...cardVisualContractProblems(template, manifest, { strict: options.requireVisualContract }));
  }

  if (!options.structureOnly && template && style && runtimeScript && sampledOutputs) {
    artifactHydrate = await artifactHydrateChecks(template, style, runtimeScript, sampledOutputs, options);
    if (artifactHydrate.problems.length) problems.push(...artifactHydrate.problems);
  }

  return {
    ok: problems.length === 0,
    problems,
    artifact_hydrate: artifactHydrate,
    manifest: manifest ? {
      version: manifest.version || '',
      kind: manifest.kind || '',
      required_outputs: Array.isArray(manifest.required_outputs) ? manifest.required_outputs : [],
      package_count: manifestPackages(manifest).length,
      aspect_ratio: manifest.aspect_ratio || '',
    } : null,
  };
}

async function loadPlaywright() {
  try {
    return await import('playwright');
  } catch {}
  const roots = [
    ...(process.env.NODE_PATH || '').split(path.delimiter),
    path.join(process.cwd(), 'node_modules'),
    path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules'),
  ]
    .map(item => (item || '').trim())
    .filter(Boolean);
  for (const root of [...new Set(roots)]) {
    const candidates = [path.join(root, 'playwright', 'package.json')];
    const pnpmRoot = path.join(root, '.pnpm');
    if (fs.existsSync(pnpmRoot)) {
      try {
        for (const name of fs.readdirSync(pnpmRoot)) {
          if (name.startsWith('playwright@')) {
            candidates.push(path.join(pnpmRoot, name, 'node_modules', 'playwright', 'package.json'));
          }
        }
      } catch {}
    }
    for (const pkg of candidates) {
      if (!fs.existsSync(pkg)) continue;
      try {
        const requireFromPlaywright = createRequire(pkg);
        return requireFromPlaywright('playwright');
      } catch {}
    }
  }
  return null;
}

async function launchPlaywrightBrowser(pw, relaxSecurity = false) {
  // fork-local 本地 file://(origin=null) 专用：放开同源策略让真实 package/grant 取数能跑完渲染。
  // 仅在 relaxSecurity(fork-local) 时启用，public-smoke 仍用浏览器默认安全策略。
  const relaxArgs = relaxSecurity
    ? ['--disable-web-security', '--disable-features=IsolateOrigins,site-per-process']
    : [];
  const attempts = [
    { channel: 'chrome', headless: true, args: relaxArgs },
    { channel: 'msedge', headless: true, args: relaxArgs },
    { headless: true, args: relaxArgs },
  ];
  const errors = [];
  for (const options of attempts) {
    try {
      return await pw.chromium.launch(options);
    } catch (err) {
      errors.push(err && err.message ? err.message : String(err));
    }
  }
  throw new Error(errors.join(' | '));
}

async function prepareImagesExpression() {
  const images = Array.from(document.images || []);
  const isPendingRuntimeImage = img => (
    img.hasAttribute('data-qb-runtime-src')
    && !String(img.getAttribute('src') || '').trim()
  );
  const verifiableImages = images.filter(img => !isPendingRuntimeImage(img));
  for (const img of verifiableImages) {
    if (/^data:image\//i.test(img.currentSrc || img.src || '')) continue;
    img.loading = 'eager';
    try { img.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch {}
  }
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  await Promise.all(verifiableImages.map(async img => {
    if (/^data:image\//i.test(img.currentSrc || img.src || '')) return;
    try { if (typeof img.decode === 'function') await img.decode(); } catch {}
  }));
  const managed = verifiableImages.filter(img => /^https:\/\/pages\.quantbuddy\.cn\/pages\/assets\/[^/]+\/asset_[0-9a-f]{24}\.webp(?:[?#].*)?$/i.test(img.currentSrc || img.src || ''));
  const posterTarget = document.querySelector('[data-qb-poster-target]');
  let posterCanvasExportable = managed.length === 0;
  if (managed.length && document.getElementById('shareBtn')) {
    try {
      document.getElementById('shareBtn').click();
      const deadline = Date.now() + 10000;
      while (Date.now() < deadline) {
        const preview = document.getElementById('sharePosterImage');
        if (preview && /^data:image\/png/i.test(preview.src || '')) break;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      const canvas = document.getElementById('sharePosterCanvas');
      posterCanvasExportable = !!(canvas && canvas.width > 0 && canvas.height > 0 && /^data:image\/png/i.test(canvas.toDataURL('image/png')));
      const close = document.getElementById('closePoster');
      if (close) close.click();
    } catch {
      posterCanvasExportable = false;
    }
  }
  return {
    total: images.length,
    runtimePending: images.length - verifiableImages.length,
    checked: verifiableImages.filter(img => !/^data:image\//i.test(img.currentSrc || img.src || '')).length,
    broken: verifiableImages
      .filter(img => !/^data:image\//i.test(img.currentSrc || img.src || '') && (!img.complete || Number(img.naturalWidth || 0) <= 0))
      .map(img => ({ src: img.currentSrc || img.src || '', complete: !!img.complete, naturalWidth: Number(img.naturalWidth || 0) })),
    managedTotal: managed.length,
    managedInPosterTarget: managed.filter(img => !!posterTarget && posterTarget.contains(img)).length,
    posterCanvasExportable,
  };
}

async function shareModalChecksExpression() {
  const ids = ['shareBtn', 'sharePosterModal', 'copyLink', 'copyPoster', 'downloadPoster', 'closePoster'];
  const missing = ids.filter(id => !document.getElementById(id));
  if (missing.length) return { checked: true, present: false, missing };

  const byId = id => document.getElementById(id);
  const statusText = () => String(byId('sharePosterStatus')?.textContent || '').trim();
  const waitUntil = async (predicate, timeoutMs = 10000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (predicate()) return true;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    return false;
  };
  const visible = el => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity || 1) !== 0
      && rect.width > 1 && rect.height > 1;
  };
  const controlInfo = el => {
    const rect = el.getBoundingClientRect();
    const x = Math.min(window.innerWidth - 1, Math.max(0, rect.left + rect.width / 2));
    const y = Math.min(window.innerHeight - 1, Math.max(0, rect.top + rect.height / 2));
    const hit = document.elementFromPoint(x, y);
    return {
      id: el.id,
      width: Number(rect.width.toFixed(2)),
      height: Number(rect.height.toFixed(2)),
      left: Number(rect.left.toFixed(2)),
      top: Number(rect.top.toFixed(2)),
      visible: visible(el),
      withinViewport: rect.left >= -1 && rect.top >= -1 && rect.right <= window.innerWidth + 1 && rect.bottom <= window.innerHeight + 1,
      reachable: !!hit && (hit === el || el.contains(hit)),
    };
  };

  const initialScrollY = window.scrollY;
  byId('shareBtn').click();
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  await waitUntil(() => !byId('copyPoster').disabled && !byId('downloadPoster').disabled, 10000);

  const modal = byId('sharePosterModal');
  const posterImage = byId('sharePosterImage');
  const posterCanvas = byId('sharePosterCanvas');
  const posterReady = /^data:image\/png/i.test(String(posterImage?.src || ''))
    && Number(posterCanvas?.width || 0) > 0
    && Number(posterCanvas?.height || 0) > 0;
  const dialog = modal.querySelector('.share-dialog');
  const dialogRect = dialog?.getBoundingClientRect();
  const opened = modal.getAttribute('aria-hidden') === 'false' && modal.classList.contains('open');
  const buttons = ['copyLink', 'copyPoster', 'downloadPoster', 'closePoster'].map(id => controlInfo(byId(id)));
  const columnCount = new Set(buttons.map(item => Math.round(item.left))).size;
  const outcomes = {};

  byId('copyLink').click();
  await waitUntil(() => /复制|地址栏/.test(statusText()), 1000);
  outcomes.copyLink = /复制|地址栏/.test(statusText());

  byId('copyPoster').click();
  await waitUntil(() => /复制图片|右键预览图|下载 PNG/.test(statusText()), 2000);
  outcomes.copyPoster = /复制图片|右键预览图|下载 PNG/.test(statusText());

  let downloadTriggered = false;
  const captureDownload = event => {
    const anchor = event.target?.closest?.('a[download]');
    if (anchor) downloadTriggered = true;
  };
  document.addEventListener('click', captureDownload, true);
  byId('downloadPoster').click();
  await waitUntil(() => /下载 PNG/.test(statusText()), 1000);
  document.removeEventListener('click', captureDownload, true);
  outcomes.downloadPoster = downloadTriggered && /下载 PNG/.test(statusText());

  byId('closePoster').click();
  await new Promise(resolve => requestAnimationFrame(resolve));
  outcomes.closePoster = modal.getAttribute('aria-hidden') === 'true' && !modal.classList.contains('open');

  return {
    checked: true,
    present: true,
    opened,
    posterReady,
    dialogWithinViewport: !!dialogRect && dialogRect.left >= -1 && dialogRect.top >= -1
      && dialogRect.right <= window.innerWidth + 1 && dialogRect.bottom <= window.innerHeight + 1,
    pageScrollStable: Math.abs(window.scrollY - initialScrollY) <= 1,
    buttons,
    columnCount,
    outcomes,
  };
}

async function playwrightBrowserChecks(pw, url, options = {}) {
  const browser = await launchPlaywrightBrowser(pw, options.relaxSecurity);
  const results = [];
  const consoleErrors = [];
  const nonCoreWarnings = [];
  const imageNetworkErrors = [];
  const viewports = VIEWPORTS;
  const settleMs = 1200;
  try {
    for (const viewport of viewports) {
      const page = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } });
      page.on('console', msg => {
        if (!['error', 'warning'].includes(msg.type())) return;
        const text = msg.text();
        if (!CORE_ERROR_RE.test(text)) return;
        const entry = { viewport: viewport.name, type: msg.type(), text: sanitizeBrowserText(text) };
        if (TRACKER_NOISE_RE.test(text)) nonCoreWarnings.push(entry);
        else consoleErrors.push(entry);
      });
      page.on('requestfailed', request => {
        if (request.resourceType() === 'image') {
          imageNetworkErrors.push({ viewport: viewport.name, type: 'requestfailed', url: sanitizeBrowserText(request.url()), message: sanitizeBrowserText(request.failure()?.errorText || '') });
        }
      });
      page.on('response', response => {
        if (response.request().resourceType() === 'image' && !response.ok()) {
          imageNetworkErrors.push({ viewport: viewport.name, type: `http_${response.status()}`, url: sanitizeBrowserText(response.url()) });
        }
      });
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      try {
        await page.waitForFunction(
          () => !window.QB_DATA_RUNTIME || Number(window.QB_DATA_RUNTIME.pending || 0) === 0,
          null,
          { timeout: 30000 },
        );
      } catch (error) {
        consoleErrors.push({ viewport: viewport.name, type: 'error', text: 'QB_DATA_RUNTIME pending 等待超时（30s）' });
      }
      const hasRuntime = await page.evaluate(() => !!window.QB_DATA_RUNTIME);
      // pending=0 只表示取数内核当前没有请求，不代表其它宿主 runtime 已完成最后一次 DOM/ECharts 接管。
      // 始终保留一个稳定窗口，防止“图先出现，宿主 Grant 后完成又清空图表”被瞬时采样放过。
      await page.waitForTimeout(hasRuntime ? settleMs : Math.max(settleMs, 3000));
      const imageMetrics = await page.evaluate(prepareImagesExpression);
      const shareModalMetrics = options.checkShareModal ? await page.evaluate(shareModalChecksExpression) : null;
      const metrics = await page.evaluate(pageMetricsExpression);
      metrics.images = imageMetrics;
      metrics.shareModal = shareModalMetrics;
      results.push(viewportResult(viewport, metrics, options));
      await page.close();
    }
  } finally {
    await browser.close();
  }
  return { checked: true, engine: 'playwright', viewports: results, consoleErrors, nonCoreWarnings, imageNetworkErrors };
}

function pageMetricsExpression() {
  const doc = document.documentElement;
  const bodyText = document.body ? document.body.innerText : '';
  const h1 = document.querySelector('h1');
  const visibleText = bodyText.replace(/\s+/g, '');
  const placeholderHits = ['QB_SHARED_', 'replace_with_signature', 'pkg_replace', '__PLACEHOLDER__']
    .filter(token => document.documentElement.innerHTML.includes(token));
  const placeholderOnly = visibleText.length > 0 && /^[—\-\s.0暂无数据等待取数加载中]+$/.test(visibleText);
  const runtime = window.QB_DATA_RUNTIME && typeof window.QB_DATA_RUNTIME === 'object'
    ? {
        pending: Number(window.QB_DATA_RUNTIME.pending || 0),
        status: String(window.QB_DATA_RUNTIME.status || ''),
        transport: String(window.QB_DATA_RUNTIME.transport || ''),
        error: window.QB_DATA_RUNTIME.error ? String(window.QB_DATA_RUNTIME.error) : null,
      }
    : null;
  const failureTextHits = ['未返回可绘制数据', '取数失败', 'CSV 下载失败', 'CSV 解析失败']
    .filter(token => bodyText.includes(token));
  const loadingTextHits = ['取数中', '数据加载中', '加载中…', '加载中...']
    .filter(token => bodyText.includes(token));
  const viewport = { width: window.innerWidth, height: window.innerHeight };
  const coverSelectors = [
    '[data-qb-live-card]',
    '#essenceCard',
    '[data-qb-cover-card]',
    '[data-cover-card]',
    '[data-qb-essence-card]',
    'article[class*="essence"]',
    'article[class*="cover"]',
    'article[class*="card"]',
  ];

  function elementLabel(el, source) {
    if (!el) return '';
    const id = el.id ? `#${el.id}` : '';
    const className = typeof el.className === 'string'
      ? el.className.trim().split(/\s+/).filter(Boolean).slice(0, 3).map(name => `.${name}`).join('')
      : '';
    return source || `${el.tagName.toLowerCase()}${id}${className}`;
  }

  function rectInfo(el) {
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    return {
      x: Number(rect.x.toFixed(2)),
      y: Number(rect.y.toFixed(2)),
      width: Number(rect.width.toFixed(2)),
      height: Number(rect.height.toFixed(2)),
      right: Number(rect.right.toFixed(2)),
      bottom: Number(rect.bottom.toFixed(2)),
    };
  }

  function isVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none'
      && style.visibility !== 'hidden'
      && Number(style.opacity || 1) !== 0
      && rect.width > 1
      && rect.height > 1;
  }

  const visibleFontSamples = Array.from(document.body?.querySelectorAll('*') || [])
    .filter(el => !['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'PATH'].includes(el.tagName))
    .filter(isVisible)
    .filter(el => Array.from(el.childNodes || []).some(node => node.nodeType === Node.TEXT_NODE && String(node.textContent || '').trim()))
    .map(el => ({
      size: Number.parseFloat(getComputedStyle(el).fontSize || '0') || 0,
      label: elementLabel(el, ''),
      text: String(el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80),
    }))
    .filter(item => item.size > 0)
    .sort((a, b) => a.size - b.size);

  function parseCssColor(value) {
    const text = String(value || '').trim();
    const match = text.match(/rgba?\(([^)]+)\)/i);
    if (!match) return null;
    const parts = match[1].split(',').map(part => Number.parseFloat(part.trim()));
    if (parts.length < 3 || parts.slice(0, 3).some(part => Number.isNaN(part))) return null;
    return {
      r: Math.max(0, Math.min(255, parts[0])),
      g: Math.max(0, Math.min(255, parts[1])),
      b: Math.max(0, Math.min(255, parts[2])),
      a: parts.length >= 4 && !Number.isNaN(parts[3]) ? parts[3] : 1,
      raw: text,
    };
  }

  function colorLuma(color) {
    if (!color) return null;
    return Number((0.2126 * color.r + 0.7152 * color.g + 0.0722 * color.b).toFixed(2));
  }

  function effectiveBackgroundInfo(el) {
    let node = el;
    while (node && node.nodeType === 1) {
      const color = parseCssColor(window.getComputedStyle(node).backgroundColor);
      if (color && color.a >= 0.5) {
        return { color: color.raw, luma: colorLuma(color), selector: elementLabel(node, '') };
      }
      node = node.parentElement;
    }
    return { color: 'rgb(255, 255, 255)', luma: 255, selector: 'default-white' };
  }

  function fontInfo(el) {
    if (!el) return null;
    const style = window.getComputedStyle(el);
    return {
      size: Number.parseFloat(style.fontSize || '0') || 0,
      weight: style.fontWeight || '',
      text: (el.textContent || '').trim(),
    };
  }

  function darkAreaRatio(root, rootRect) {
    if (!root || !rootRect || !rootRect.width || !rootRect.height) return 0;
    const rootArea = rootRect.width * rootRect.height;
    let darkArea = 0;
    const nodes = [root, ...Array.from(root.querySelectorAll('*'))];
    for (const node of nodes) {
      if (!isVisible(node)) continue;
      const rect = node.getBoundingClientRect();
      const area = Math.max(0, rect.width) * Math.max(0, rect.height);
      if (area < 80) continue;
      const color = parseCssColor(window.getComputedStyle(node).backgroundColor);
      const luma = colorLuma(color);
      if (color && color.a >= 0.5 && luma != null && luma < 115) {
        darkArea += Math.min(area, rootArea);
      }
    }
    return Number(Math.min(1, darkArea / rootArea).toFixed(3));
  }

  let coverRoot = null;
  let coverSource = '';
  for (const selector of coverSelectors) {
    const found = document.querySelector(selector);
    if (found) {
      coverRoot = found;
      coverSource = selector;
      break;
    }
  }

  if (!coverRoot) {
    const candidates = Array.from(document.querySelectorAll(
      '[data-qb-cover-card], [data-cover-card], [data-qb-essence-card], article, main > section, main, [class*="essence"], [class*="cover"], [class*="card"]'
    ))
      .filter(isVisible)
      .map(el => {
        const rect = el.getBoundingClientRect();
        const area = rect.width * rect.height;
        const offsetPenalty = Math.abs(rect.left) + Math.abs(rect.top)
          + Math.abs(window.innerWidth - rect.right) + Math.abs(window.innerHeight - rect.bottom);
        return { el, score: area - offsetPenalty * 50 };
      })
      .sort((a, b) => b.score - a.score);
    if (candidates.length) {
      coverRoot = candidates[0].el;
      coverSource = elementLabel(coverRoot, '');
    }
  }

  const coverRect = rectInfo(coverRoot);
  const coverText = coverRoot && coverRoot.innerText ? coverRoot.innerText : '';
  const brandEl = coverRoot ? coverRoot.querySelector('[data-qb-live-card-brand]') : null;
  const dateEl = coverRoot ? coverRoot.querySelector('[data-qb-live-card-date]') : null;
  const titleEl = coverRoot ? coverRoot.querySelector('[data-qb-live-card-title]') : null;
  const descriptionEl = coverRoot ? coverRoot.querySelector('[data-qb-live-card-description]') : null;
  const coreEl = coverRoot ? coverRoot.querySelector('[data-qb-live-card-core]') : null;
  function visibleElements(selector) {
    if (!coverRoot) return [];
    return Array.from(coverRoot.querySelectorAll(selector)).filter(isVisible);
  }
  function textSize(el) {
    return el && el.innerText ? el.innerText.replace(/\s+/g, '').length : 0;
  }
  const infoChipCount = visibleElements([
    '[data-qb-live-card-chip]',
    '.qb-cover-pill',
    '.essence-kpi',
    '.live-card-metric'
  ].join(',')).length;
  const tagCount = visibleElements([
    '[data-qb-live-card-tag]',
    '.live-card-tag',
    '.essence-read > span',
    '.qb-cover-live'
  ].join(',')).length;
  const secondaryBlockCount = visibleElements([
    '.qb-cover-grid',
    '.qb-cover-footer',
    '.essence-summary',
    '.essence-points',
    '.live-card-rank',
    '.live-card-points'
  ].join(',')).length;
  const largeValueCount = visibleElements([
    '.qb-cover-temp .value',
    '.essence-score-value',
    '.live-card-primary-value',
    '[data-qb-live-card-primary-value]'
  ].join(',')).filter(el => {
    const fontSize = Number.parseFloat(getComputedStyle(el).fontSize || '0');
    return fontSize >= 34 && /[\d一二三四五六七八九十优良中差高低冷热]/.test(el.textContent || '');
  }).length;
  const graphicSelector = '[data-qb-live-card-visual], .qb-cover-bars, .live-card-snow, canvas, svg';
  const graphicCount = visibleElements(graphicSelector).filter(el => {
    const ancestor = el.parentElement && el.parentElement.closest(graphicSelector);
    if (ancestor && coverRoot.contains(ancestor)) return false;
    const rect = el.getBoundingClientRect();
    return rect.width >= 40 && rect.height >= 30;
  }).length;
  const coverPlaceholderHits = ['取数中', '判断生成中', '读取中', '加载中', '数据加载中', '等待取数', '暂无数据']
    .filter(token => coverText.includes(token));
  const dashCount = (coverText.match(/—/g) || []).length;
  const rootRatio = coverRect && coverRect.height > 0 ? coverRect.width / coverRect.height : 0;
  const tolerance = 3;
  const sizeTolerance = 6;
  const coverFillsViewport = !!coverRect
    && Math.abs(coverRect.x) <= tolerance
    && Math.abs(coverRect.y) <= tolerance
    && coverRect.width >= viewport.width - sizeTolerance
    && coverRect.height >= viewport.height - sizeTolerance
    && coverRect.right <= viewport.width + sizeTolerance
    && coverRect.bottom <= viewport.height + sizeTolerance;
  const coverRatioOk = !!coverRect && Math.abs(rootRatio - (4 / 3)) <= 0.035;
  const rootBackground = effectiveBackgroundInfo(coverRoot);
  const bodyBackground = effectiveBackgroundInfo(document.body || document.documentElement);
  const darkCoverage = darkAreaRatio(coverRoot, coverRect);

  function stockComparisonMetrics() {
    const cfgNode = document.querySelector('script[data-qbv-stock-instance]');
    if (!cfgNode) return null;
    try {
      const config = JSON.parse(cfgNode.textContent || '{}');
      const benchmarkSource = config?.data_sources?.benchmark_series || config?.comparison?.benchmark_series;
      if (!config || config.version !== 'stock_analysis_instance_v1' || !benchmarkSource) return null;
      const assetName = String(config.asset?.name || '').trim();
      const benchmarkName = String(config.comparison?.name || config.comparison?.benchmark?.name || '沪深300').trim();
      const expectedSeries = [assetName ? `${assetName}收盘价` : '收盘价', benchmarkName].filter(Boolean);
      const expectedSeriesAliases = [
        Array.from(new Set([expectedSeries[0], '收盘价'].filter(Boolean))),
        [benchmarkName],
      ];
      const chartEl = document.getElementById('priceChart');
      const canvasCount = chartEl ? chartEl.querySelectorAll('canvas').length : 0;
      const chart = chartEl && window.echarts && typeof window.echarts.getInstanceByDom === 'function'
        ? window.echarts.getInstanceByDom(chartEl)
        : null;
      const option = chart && typeof chart.getOption === 'function' ? chart.getOption() : null;
      const optionSeries = Array.isArray(option?.series) ? option.series : [];
      const hasDatum = value => {
        if (Array.isArray(value)) return value.length > 1 ? value[1] != null : value.some(item => item != null);
        return value != null;
      };
      const series = optionSeries.map(item => ({
        name: String(item?.name || ''),
        yAxisIndex: Number.isFinite(Number(item?.yAxisIndex)) ? Number(item.yAxisIndex) : 0,
        pointCount: Array.isArray(item?.data) ? item.data.filter(hasDatum).length : 0,
      }));
      const optionSeriesForAliases = aliases => optionSeries.find(item => aliases.includes(String(item?.name || '')));
      const primaryOption = optionSeriesForAliases(expectedSeriesAliases[0] || []);
      const benchmarkOption = optionSeriesForAliases(expectedSeriesAliases[1] || []);
      const primaryData = Array.isArray(primaryOption?.data) ? primaryOption.data : [];
      const benchmarkData = Array.isArray(benchmarkOption?.data) ? benchmarkOption.data : [];
      const alignedLength = Math.max(primaryData.length, benchmarkData.length);
      let overlapPointCount = 0;
      let latestCommonIndex = -1;
      let latestEitherIndex = -1;
      for (let index = 0; index < alignedLength; index += 1) {
        const primaryValid = hasDatum(primaryData[index]);
        const benchmarkValid = hasDatum(benchmarkData[index]);
        if (primaryValid || benchmarkValid) latestEitherIndex = index;
        if (primaryValid && benchmarkValid) {
          overlapPointCount += 1;
          latestCommonIndex = index;
        }
      }
      const latestCommonLag = latestEitherIndex >= 0 && latestCommonIndex >= 0
        ? latestEitherIndex - latestCommonIndex
        : null;
      const yAxes = Array.isArray(option?.yAxis) ? option.yAxis.map(axis => ({
        name: String(axis?.name || ''),
        position: String(axis?.position || ''),
      })) : [];
      const tableHeaders = Array.from(document.querySelectorAll('#priceTable th'))
        .map(item => (item.textContent || '').trim())
        .filter(Boolean);
      return { required: true, expectedSeries, expectedSeriesAliases, tableHeaders, chartPresent: !!chart, canvasCount, series, yAxes, overlapPointCount, latestCommonLag };
    } catch (error) {
      return { required: true, error: String(error && error.message ? error.message : error) };
    }
  }

  const stockComparison = stockComparisonMetrics();
  return {
    scrollWidth: doc.scrollWidth,
    clientWidth: doc.clientWidth,
    scrollHeight: doc.scrollHeight,
    clientHeight: doc.clientHeight,
    hasH1: !!(h1 && h1.textContent.trim()),
    placeholderHits,
    placeholderOnly,
    runtime,
    failureTextHits,
    loadingTextHits,
    stockComparison,
    visibleFonts: {
      minimumPx: visibleFontSamples.length ? visibleFontSamples[0].size : null,
      smallest: visibleFontSamples.slice(0, 8),
    },
    shareModal: null,
    cover: {
      rootFound: !!coverRoot,
      selector: elementLabel(coverRoot, coverSource),
      visible: isVisible(coverRoot),
      rect: coverRect,
      fillsViewport: coverFillsViewport,
      ratio: Number(rootRatio.toFixed(4)),
      ratioOk: coverRatioOk,
      placeholderHits: coverPlaceholderHits,
      dashCount,
      textLength: coverText.replace(/\s+/g, '').length,
      contentBudget: {
        titleLength: textSize(titleEl),
        descriptionLength: textSize(descriptionEl),
        infoChipCount,
        tagCount,
        secondaryBlockCount,
        largeValueCount,
        graphicCount,
      },
      rootHasLiveCardMarker: !!(coverRoot && coverRoot.hasAttribute('data-qb-live-card')),
      containsLegacyVisibleName: coverText.includes('精华卡'),
      background: {
        root: rootBackground,
        body: bodyBackground,
        darkAreaRatio: darkCoverage,
      },
      contract: {
        brand: fontInfo(brandEl),
        date: fontInfo(dateEl),
        title: fontInfo(titleEl),
        description: fontInfo(descriptionEl),
        coreFound: !!coreEl && isVisible(coreEl),
        dateLooksIso: !!(dateEl && /^\d{4}-\d{2}-\d{2}$/.test((dateEl.textContent || '').trim())),
      },
    },
  };
}

function viewportResult(viewport, metrics, options = {}) {
  const result = {
    viewport: viewport.name,
    width: viewport.width,
    horizontalOverflow: metrics.scrollWidth > metrics.clientWidth + 2,
    verticalOverflow: metrics.scrollHeight > metrics.clientHeight + 2,
    hasH1: metrics.hasH1,
    placeholderHits: metrics.placeholderHits,
    placeholderOnly: metrics.placeholderOnly,
    runtime: metrics.runtime,
    failureTextHits: metrics.failureTextHits || [],
    loadingTextHits: metrics.loadingTextHits || [],
    visibleFonts: metrics.visibleFonts || { minimumPx: null, smallest: [] },
    shareModal: metrics.shareModal || null,
    images: {
      ...(metrics.images || {}),
      broken: (metrics.images?.broken || []).map(item => ({ ...item, src: sanitizeBrowserText(item.src) })),
    },
    stockComparison: metrics.stockComparison || null,
  };
  return result;
}

function browserCandidates() {
  const env = [process.env.CHROME_PATH, process.env.EDGE_PATH, process.env.BROWSER].filter(Boolean);
  const win = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  ];
  const unix = ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/microsoft-edge'];
  return [...env, ...(process.platform === 'win32' ? win : unix)];
}

function findBrowser() {
  for (const candidate of browserCandidates()) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  const names = process.platform === 'win32'
    ? ['msedge.exe', 'chrome.exe', 'chromium.exe', 'brave.exe']
    : ['google-chrome', 'chromium', 'chromium-browser', 'microsoft-edge', 'brave'];
  const lookup = process.platform === 'win32' ? 'where.exe' : 'which';
  for (const name of names) {
    const found = spawnSync(lookup, [name], { encoding: 'utf8' });
    if (found.status === 0 && found.stdout.trim()) {
      const first = found.stdout.trim().split(/\r?\n/)[0];
      if (first) return first;
    }
  }
  return '';
}

function waitForDebugEndpoint(proc) {
  return new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => {
      reject(new Error(`browser did not expose DevTools endpoint: ${output.slice(-500)}`));
    }, 10000);
    const onData = chunk => {
      output += chunk.toString();
      const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    };
    proc.stderr.on('data', onData);
    proc.stdout.on('data', onData);
    proc.once('exit', code => {
      clearTimeout(timer);
      reject(new Error(`browser exited before DevTools endpoint was ready: ${code}; ${output.slice(-500)}`));
    });
  });
}

async function fetchJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${url}`);
  return await resp.json();
}

async function pageWebSocketUrl(debugWs) {
  const port = (debugWs.match(/127\.0\.0\.1:(\d+)/) || debugWs.match(/localhost:(\d+)/) || [])[1];
  if (!port) throw new Error(`cannot parse DevTools port from ${debugWs}`);
  const base = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 20; i += 1) {
    const targets = await fetchJson(`${base}/json/list`).catch(() => []);
    const page = targets.find(t => t.type === 'page' && t.webSocketDebuggerUrl);
    if (page) return page.webSocketDebuggerUrl;
    await delay(250);
  }
  throw new Error('no DevTools page target found');
}

class CdpSession {
  constructor(ws) {
    this.ws = ws;
    this.nextId = 1;
    this.pending = new Map();
    this.eventHandlers = new Set();
    ws.onmessage = event => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message || JSON.stringify(msg.error)));
        else resolve(msg.result || {});
        return;
      }
      for (const handler of this.eventHandlers) handler(msg);
    };
  }

  send(method, params = {}) {
    const id = this.nextId++;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      setTimeout(() => {
        if (this.pending.delete(id)) reject(new Error(`CDP timeout: ${method}`));
      }, 30000);
    });
  }

  onEvent(handler) {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  waitForEvent(method, timeout = 30000) {
    return new Promise((resolve, reject) => {
      const off = this.onEvent(msg => {
        if (msg.method === method) {
          clearTimeout(timer);
          off();
          resolve(msg.params || {});
        }
      });
      const timer = setTimeout(() => {
        off();
        reject(new Error(`CDP event timeout: ${method}`));
      }, timeout);
    });
  }
}

class MinimalWebSocket {
  constructor(socket) {
    this.socket = socket;
    this.buffer = Buffer.alloc(0);
    this.onmessage = null;
    this.onerror = null;
    socket.on('data', chunk => this.handleData(chunk));
    socket.on('error', err => {
      if (this.onerror) this.onerror(err);
    });
  }

  handleData(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (this.buffer.length >= 2) {
      const b0 = this.buffer[0];
      const b1 = this.buffer[1];
      const opcode = b0 & 0x0f;
      const masked = (b1 & 0x80) !== 0;
      let len = b1 & 0x7f;
      let offset = 2;
      if (len === 126) {
        if (this.buffer.length < offset + 2) return;
        len = this.buffer.readUInt16BE(offset);
        offset += 2;
      } else if (len === 127) {
        if (this.buffer.length < offset + 8) return;
        len = Number(this.buffer.readBigUInt64BE(offset));
        offset += 8;
      }
      let mask = null;
      if (masked) {
        if (this.buffer.length < offset + 4) return;
        mask = this.buffer.subarray(offset, offset + 4);
        offset += 4;
      }
      if (this.buffer.length < offset + len) return;
      let payload = this.buffer.subarray(offset, offset + len);
      this.buffer = this.buffer.subarray(offset + len);
      if (mask) {
        payload = Buffer.from(payload.map((byte, i) => byte ^ mask[i % 4]));
      }
      if (opcode === 1 && this.onmessage) {
        this.onmessage({ data: payload.toString('utf8') });
      } else if (opcode === 8) {
        this.close();
      } else if (opcode === 9) {
        this.sendFrame(payload, 0x0a);
      }
    }
  }

  send(data) {
    this.sendFrame(Buffer.from(data), 0x01);
  }

  sendFrame(payload, opcode) {
    const mask = crypto.randomBytes(4);
    let header;
    if (payload.length < 126) {
      header = Buffer.from([0x80 | opcode, 0x80 | payload.length]);
    } else if (payload.length <= 0xffff) {
      header = Buffer.alloc(4);
      header[0] = 0x80 | opcode;
      header[1] = 0x80 | 126;
      header.writeUInt16BE(payload.length, 2);
    } else {
      header = Buffer.alloc(10);
      header[0] = 0x80 | opcode;
      header[1] = 0x80 | 127;
      header.writeBigUInt64BE(BigInt(payload.length), 2);
    }
    const masked = Buffer.alloc(payload.length);
    for (let i = 0; i < payload.length; i += 1) {
      masked[i] = payload[i] ^ mask[i % 4];
    }
    this.socket.write(Buffer.concat([header, mask, masked]));
  }

  close() {
    try {
      this.socket.end();
    } catch {}
  }
}

function openRawWebSocket(wsUrl) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(wsUrl);
    const port = Number(parsed.port || 80);
    const host = parsed.hostname;
    const socket = net.createConnection({ host, port });
    const key = crypto.randomBytes(16).toString('base64');
    let buffer = Buffer.alloc(0);
    const timer = setTimeout(() => {
      socket.destroy();
      reject(new Error(`DevTools websocket handshake timeout: ${wsUrl}`));
    }, 10000);
    socket.once('connect', () => {
      socket.write([
        `GET ${parsed.pathname}${parsed.search} HTTP/1.1`,
        `Host: ${host}:${port}`,
        'Upgrade: websocket',
        'Connection: Upgrade',
        `Sec-WebSocket-Key: ${key}`,
        'Sec-WebSocket-Version: 13',
        '\r\n',
      ].join('\r\n'));
    });
    socket.on('data', chunk => {
      buffer = Buffer.concat([buffer, chunk]);
      const headerEnd = buffer.indexOf('\r\n\r\n');
      if (headerEnd < 0) return;
      const head = buffer.subarray(0, headerEnd).toString('utf8');
      const rest = buffer.subarray(headerEnd + 4);
      if (!/^HTTP\/1\.1 101\b/.test(head)) {
        clearTimeout(timer);
        socket.destroy();
        reject(new Error(`DevTools websocket handshake failed: ${head.split('\r\n')[0]}`));
        return;
      }
      clearTimeout(timer);
      socket.removeAllListeners('data');
      const ws = new MinimalWebSocket(socket);
      if (rest.length) ws.handleData(rest);
      resolve(ws);
    });
    socket.once('error', err => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

async function openWebSocket(url) {
  if (typeof WebSocket !== 'function') return openRawWebSocket(url);
  const ws = new WebSocket(url);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = () => reject(new Error(`cannot connect DevTools websocket: ${url}`));
  });
  return ws;
}

async function cdpBrowserChecks(url, options = {}) {
  const browserPath = findBrowser();
  if (!browserPath) return { checked: false, skipped: true, reason: 'system Chrome/Edge browser not found' };

  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qbv-verify-'));
  const browserArgs = [
    '--headless=new',
    '--remote-debugging-port=0',
    `--user-data-dir=${userDataDir}`,
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
  ];
  if (options.relaxSecurity) {
    // fork-local 本地 file://(origin=null) 专用：放开同源策略让真实 package/grant 取数能跑完渲染。
    // 仅限本地 fork-local，不影响 public-smoke 的正常安全策略。
    browserArgs.push('--disable-web-security', '--disable-features=IsolateOrigins,site-per-process');
  }
  browserArgs.push('about:blank');
  const proc = spawn(browserPath, browserArgs, { stdio: ['ignore', 'pipe', 'pipe'] });

  try {
    const debugWs = await waitForDebugEndpoint(proc);
    const ws = await openWebSocket(await pageWebSocketUrl(debugWs));
    const cdp = new CdpSession(ws);
    const results = [];
    const consoleErrors = [];
    const nonCoreWarnings = [];
    const imageNetworkErrors = [];
    let currentViewport = 'unknown';
    cdp.onEvent(msg => {
      if (msg.method === 'Runtime.exceptionThrown') {
        const text = msg.params?.exceptionDetails?.text || 'Runtime exception';
        if (!CORE_ERROR_RE.test(text)) return;
        const entry = { viewport: 'unknown', type: 'error', text: sanitizeBrowserText(text) };
        if (TRACKER_NOISE_RE.test(text)) nonCoreWarnings.push(entry);
        else consoleErrors.push(entry);
      }
      if (msg.method === 'Runtime.consoleAPICalled') {
        const type = msg.params?.type || '';
        const text = (msg.params?.args || []).map(arg => String(arg.value || arg.description || '')).join(' ');
        if (!['error', 'warning', 'warn'].includes(type) || !CORE_ERROR_RE.test(text)) return;
        const entry = { viewport: 'unknown', type, text: sanitizeBrowserText(text) };
        if (TRACKER_NOISE_RE.test(text)) nonCoreWarnings.push(entry);
        else consoleErrors.push(entry);
      }
      if (msg.method === 'Network.loadingFailed' && msg.params?.type === 'Image') {
        imageNetworkErrors.push({ viewport: currentViewport, type: 'requestfailed', message: sanitizeBrowserText(msg.params?.errorText || '') });
      }
      if (msg.method === 'Network.responseReceived' && msg.params?.type === 'Image' && Number(msg.params?.response?.status || 0) >= 400) {
        imageNetworkErrors.push({ viewport: currentViewport, type: `http_${msg.params.response.status}`, url: sanitizeBrowserText(msg.params.response.url || '') });
      }
    });
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Network.enable');
    const viewports = VIEWPORTS;
    const settleMs = 1200;
    for (const viewport of viewports) {
      currentViewport = viewport.name;
      await cdp.send('Emulation.setDeviceMetricsOverride', {
        width: viewport.width,
        height: viewport.height,
        deviceScaleFactor: 1,
        mobile: viewport.mobile,
      });
      const loaded = cdp.waitForEvent('Page.loadEventFired', 30000).catch(() => null);
      await cdp.send('Page.navigate', { url });
      await loaded;
      const runtimeDeadline = Date.now() + 30000;
      for (;;) {
        const state = await cdp.send('Runtime.evaluate', {
          expression: `!window.QB_DATA_RUNTIME || Number(window.QB_DATA_RUNTIME.pending || 0) === 0`,
          returnByValue: true,
        });
        if (state.result && state.result.value === true) break;
        if (Date.now() >= runtimeDeadline) {
          consoleErrors.push({ viewport: viewport.name, type: 'error', text: 'QB_DATA_RUNTIME pending 等待超时（30s）' });
          break;
        }
        await delay(100);
      }
      const runtimePresent = await cdp.send('Runtime.evaluate', {
        expression: `!!window.QB_DATA_RUNTIME`,
        returnByValue: true,
      });
      // 与 Playwright 路径一致：即使 QB_DATA_RUNTIME 已 ready，也等待宿主异步渲染稳定。
      await delay(runtimePresent.result && runtimePresent.result.value ? settleMs : Math.max(settleMs, 3000));
      const preparedImages = await cdp.send('Runtime.evaluate', {
        expression: `(${prepareImagesExpression.toString()})()`,
        returnByValue: true,
        awaitPromise: true,
      });
      const shareModalMetrics = options.checkShareModal ? await cdp.send('Runtime.evaluate', {
        expression: `(${shareModalChecksExpression.toString()})()`,
        returnByValue: true,
        awaitPromise: true,
      }) : null;
      const evaluated = await cdp.send('Runtime.evaluate', {
        expression: `(${pageMetricsExpression.toString()})()`,
        returnByValue: true,
        awaitPromise: true,
      });
      if (evaluated.exceptionDetails) {
        consoleErrors.push({ viewport: viewport.name, type: 'error', text: sanitizeBrowserText(evaluated.exceptionDetails.text || 'Runtime.evaluate failed') });
        continue;
      }
      evaluated.result.value.images = preparedImages.result?.value || {};
      evaluated.result.value.shareModal = shareModalMetrics?.result?.value || null;
      results.push(viewportResult(viewport, evaluated.result.value, options));
    }
    ws.close();
    return { checked: true, engine: 'system-browser', browser: browserPath, viewports: results, consoleErrors, nonCoreWarnings, imageNetworkErrors };
  } catch (err) {
    return { checked: false, skipped: true, reason: err && err.message ? err.message : String(err), browser: browserPath };
  } finally {
    try {
      proc.kill();
    } catch {}
    try {
      fs.rmSync(userDataDir, { recursive: true, force: true });
    } catch {}
  }
}

async function browserChecks(v, options = {}) {
  const url = targetUrl(v);
  const pw = await loadPlaywright();
  let playwrightError = '';
  if (pw) {
    try {
      return await playwrightBrowserChecks(pw, url, options);
    } catch (err) {
      playwrightError = err && err.message ? err.message : String(err);
    }
  }

  const fallback = await cdpBrowserChecks(url, options);
  if (fallback.checked) {
    if (playwrightError) fallback.playwright_error = playwrightError;
    return fallback;
  }
  const prefix = pw
    ? `playwright failed: ${playwrightError}`
    : 'playwright package is not available';
  return {
    checked: false,
    skipped: true,
    reason: `${prefix}; ${fallback.reason}`,
    browser: fallback.browser || '',
  };
}

function summarize(staticResult, browserResult, options) {
  const problems = [...staticResult.problems];
  const warnings = [];
  if (browserResult.checked) {
    for (const r of browserResult.viewports) {
      if (options.checkLayout !== false && r.horizontalOverflow) problems.push(`${r.viewport}: 存在横向溢出`);
      if (!r.hasH1) problems.push(`${r.viewport}: 缺少可见 h1`);
      if (r.placeholderHits.length) problems.push(`${r.viewport}: 占位符残留 ${r.placeholderHits.join(', ')}`);
      if (r.placeholderOnly) problems.push(`${r.viewport}: 核心内容疑似全是占位符`);
      if (r.runtime && r.runtime.pending > 0) problems.push(`${r.viewport}: 数据运行态仍有 ${r.runtime.pending} 个 pending`);
      if (r.runtime && r.runtime.status === 'error') problems.push(`${r.viewport}: 数据运行时失败: ${r.runtime.error || '未知错误'}`);
      if (r.failureTextHits.length) problems.push(`${r.viewport}: 页面显示失败状态 ${r.failureTextHits.join(', ')}`);
      if (r.loadingTextHits.length && r.runtime && r.runtime.pending === 0) {
        problems.push(`${r.viewport}: 数据完成后仍显示加载态 ${r.loadingTextHits.join(', ')}`);
      }
      if (r.stockComparison?.required) {
        const comparison = r.stockComparison;
        if (comparison.error) {
          problems.push(`${r.viewport}: 股票对比配置无法解析: ${comparison.error}`);
        } else {
          if (!comparison.chartPresent) problems.push(`${r.viewport}: 股票对比图未初始化`);
          if (comparison.canvasCount <= 0) problems.push(`${r.viewport}: 股票对比图没有最终 canvas`);
          for (const [index, name] of (comparison.expectedSeries || []).entries()) {
            const aliases = (comparison.expectedSeriesAliases || [])[index] || [name];
            const series = (comparison.series || []).find(item => aliases.includes(item.name));
            if (!series) {
              problems.push(`${r.viewport}: 股票对比图缺少序列 ${name}`);
            } else if (series.pointCount <= 0) {
              problems.push(`${r.viewport}: 股票对比图序列无有效点 ${name}`);
            }
          }
          const primaryName = (comparison.expectedSeries || [])[0];
          const benchmarkName = (comparison.expectedSeries || [])[1];
          const primaryAliases = (comparison.expectedSeriesAliases || [])[0] || [primaryName];
          const primary = (comparison.series || []).find(item => primaryAliases.includes(item.name));
          const benchmarkAliasesForOverlap = (comparison.expectedSeriesAliases || [])[1] || [benchmarkName];
          const benchmarkForOverlap = (comparison.series || []).find(item => benchmarkAliasesForOverlap.includes(item.name));
          if (primary && benchmarkForOverlap) {
            const minimumExpectedOverlap = Math.max(1, Math.floor(Math.min(primary.pointCount, benchmarkForOverlap.pointCount) * 0.5));
            if (comparison.overlapPointCount <= 0) {
              problems.push(`${r.viewport}: 股票对比序列没有共同有效交易日，日期轴可能未归一化`);
            } else if (comparison.overlapPointCount < minimumExpectedOverlap) {
              problems.push(`${r.viewport}: 股票对比序列共同有效交易日过少 (${comparison.overlapPointCount}/${minimumExpectedOverlap})`);
            } else if (comparison.latestCommonLag != null && comparison.latestCommonLag > 5) {
              problems.push(`${r.viewport}: 股票对比序列最近共同交易日落后 ${comparison.latestCommonLag} 个横轴位置`);
            }
          }
          const benchmarkAliases = (comparison.expectedSeriesAliases || [])[1] || [benchmarkName];
          const benchmark = (comparison.series || []).find(item => benchmarkAliases.includes(item.name));
          if (benchmark && benchmark.yAxisIndex !== 1) {
            problems.push(`${r.viewport}: 股票对比基准未绑定右侧 Y 轴 ${benchmarkName}`);
          }
          if ((comparison.yAxes || []).length < 2) problems.push(`${r.viewport}: 股票对比图缺少双 Y 轴`);
          if (!(comparison.yAxes || []).some(axis => axis.position === 'right')) {
            problems.push(`${r.viewport}: 股票对比图缺少右侧 Y 轴`);
          }
          for (const [index, name] of (comparison.expectedSeries || []).entries()) {
            const aliases = (comparison.expectedSeriesAliases || [])[index] || [name];
            if (!aliases.some(alias => (comparison.tableHeaders || []).includes(alias))) {
              problems.push(`${r.viewport}: 股票对比数据表缺少列 ${name}`);
            }
          }
        }
      }
      if ((r.images?.broken || []).length) problems.push(`${r.viewport}: 存在无法解码或零宽图片`);
      if (Number(r.images?.managedTotal || 0) > Number(r.images?.managedInPosterTarget || 0)) {
        problems.push(`${r.viewport}: 同域 WebP 未全部包含在分享海报目标内`);
      }
      if (Number(r.images?.managedTotal || 0) > 0 && !r.images?.posterCanvasExportable) {
        problems.push(`${r.viewport}: 分享海报 canvas 无法导出`);
      }
      if (options.minVisibleFontPx > 0 && Number(r.visibleFonts?.minimumPx || 0) < options.minVisibleFontPx) {
        const sample = (r.visibleFonts?.smallest || [])[0];
        problems.push(`${r.viewport}: 可见文字最小计算字号 ${r.visibleFonts?.minimumPx || 0}px 小于 ${options.minVisibleFontPx}px${sample ? ` (${sample.label}: ${sample.text})` : ''}`);
      }
      if (options.checkShareModal) {
        const share = r.shareModal || {};
        if (!share.present) {
          problems.push(`${r.viewport}: 公共分享弹层合同缺失 ${Array.isArray(share.missing) ? share.missing.join(', ') : ''}`.trim());
        } else {
          if (!share.opened) problems.push(`${r.viewport}: 分享弹层无法打开`);
          if (!share.posterReady) problems.push(`${r.viewport}: 分享海报未生成可用 PNG 预览`);
          if (!share.dialogWithinViewport) problems.push(`${r.viewport}: 分享弹层超出目标视口`);
          if (!share.pageScrollStable) problems.push(`${r.viewport}: 打开分享弹层改变了页面滚动位置`);
          const badButtons = (share.buttons || []).filter(button => !button.visible || !button.withinViewport || !button.reachable
            || (r.width <= 680 && (button.width < 44 || button.height < 44)));
          if (badButtons.length) problems.push(`${r.viewport}: 分享操作不可达${r.width <= 680 ? '或小屏点击目标小于 44px' : ''} (${badButtons.map(button => button.id).join(', ')})`);
          const failedActions = Object.entries(share.outcomes || {}).filter(([, ok]) => !ok).map(([name]) => name);
          if (failedActions.length) problems.push(`${r.viewport}: 分享操作处理路径未响应 (${failedActions.join(', ')})`);
          if (r.width <= 680 && Number(share.columnCount || 0) !== 2) problems.push(`${r.viewport}: 小屏分享操作区不是 2×2`);
        }
      }
    }
    if (browserResult.consoleErrors.length) problems.push('控制台存在核心接口/运行时错误');
    if ((browserResult.imageNetworkErrors || []).length) problems.push('图片请求存在 requestfailed 或非 2xx 响应');
  } else {
    const warning = `浏览器视口检查未执行: ${browserResult.reason}`;
    warnings.push(warning);
    if (options.requireBrowser) problems.push(warning);
  }
  return {
    ok: problems.length === 0,
    problems,
    warnings,
    non_core_console_warnings: browserResult.nonCoreWarnings || [],
    security_mode: options.relaxSecurity ? 'disabled-web-security' : 'default',
  };
}

function updateManifest(file, verification) {
  if (!file) return;
  const abs = path.isAbsolute(file) ? file : path.resolve(process.cwd(), file);
  if (!fs.existsSync(abs)) return;
  const data = JSON.parse(fs.readFileSync(abs, 'utf8'));
  data.verification = Object.assign({}, data.verification || {}, { page_verify: verification });
  fs.writeFileSync(abs, JSON.stringify(data, null, 2), 'utf8');
}

function fontSizeProblem(label, info, min, max) {
  if (!info || !info.text) return '';
  const size = Number(info.size || 0);
  if (size < min || size > max) return `${label}字号不在统一范围 (${size}px, expected ${min}-${max}px)`;
  return '';
}

try {
  const html = await readHtml(target);
  const staticResult = staticChecks(html);
  const cardRuntimeResult = cardRuntime ? await cardRuntimeChecks(html, {
    requireBrowser: requireBrowser || cardRuntimeOnly,
    structureOnly: cardRuntimeStructureOnly,
    requireVisualContract: requireCardVisualContract,
    screenshotPath: cardScreenshotPath,
  }) : { ok: true, problems: [] };
  if (cardRuntimeStructureOnly) {
    const problems = [...(staticResult.problems || []), ...(cardRuntimeResult.problems || [])];
    const result = {
      code: problems.length ? 1 : 0,
      target,
      verification_profile: verificationProfile.name,
      verification_level: 'card-runtime-structure',
      require_browser: false,
      card_runtime: true,
      card_runtime_only: false,
      card_runtime_structure_only: true,
      static: staticResult,
      card_runtime_check: cardRuntimeResult,
      browser: {
        checked: false,
        skipped: true,
        reason: '--card-runtime-structure-only 在任何取数和浏览器启动前完成',
        viewports: [],
        consoleErrors: [],
      },
      warnings: [],
      problems,
    };
    updateManifest(manifestPath, result);
    emit(result);
    process.exit(problems.length ? 1 : 0);
  }
  if (cardRuntimeOnly) {
    const artifactHydrate = cardRuntimeResult.artifact_hydrate || {};
    const result = {
      code: cardRuntimeResult.ok ? 0 : 1,
      target,
      verification_profile: verificationProfile.name,
      verification_level: artifactHydrate.checked ? 'card-runtime-artifact' : 'card-runtime-static',
      require_browser: requireBrowser,
      card_runtime: true,
      card_runtime_only: true,
      static: staticResult,
      card_runtime_check: cardRuntimeResult,
      browser: {
        checked: false,
        skipped: true,
        reason: '--card-runtime-only skips full-page browser viewport checks',
        viewports: [],
        consoleErrors: [],
      },
      warnings: [],
      problems: cardRuntimeResult.problems,
    };
    updateManifest(manifestPath, result);
    emit(result);
    process.exit(cardRuntimeResult.ok ? 0 : 1);
  }
  const browserOptions = {
    checkShareModal: verificationProfile.checkShareModal,
    minVisibleFontPx,
    // fork-local 在本地 file://(origin=null) 下放开同源策略，让真实取数能跑完渲染；
    // public-smoke 仍用浏览器默认安全策略，核心数据接口 CORS 仍严格拦截。
    relaxSecurity: verificationProfile.name === 'fork-local',
  };
  const browserResult = await browserChecks(target, browserOptions);
  const summary = summarize(staticResult, browserResult, {
    requireBrowser,
    checkLayout: verificationProfile.checkLayout,
    ...browserOptions,
  });
  if (cardRuntimeResult.problems.length) {
    summary.ok = false;
    summary.problems.push(...cardRuntimeResult.problems);
  }
  const result = {
    code: summary.ok ? 0 : 1,
    target,
    verification_profile: verificationProfile.name,
    verification_level: browserResult.checked ? 'browser' : 'static-only',
    require_browser: requireBrowser,
    min_visible_font_px: minVisibleFontPx || null,
    extra_viewports: extraViewports,
    card_runtime: cardRuntime,
    card_runtime_only: false,
    static: staticResult,
    card_runtime_check: cardRuntimeResult,
    browser: browserResult,
    security_mode: summary.security_mode,
    non_core_console_warnings: summary.non_core_console_warnings,
    warnings: summary.warnings,
    problems: summary.problems,
  };
  updateManifest(manifestPath, result);
  emit(result);
  process.exit(summary.ok ? 0 : 1);
} catch (err) {
  emit({ code: 1, target, message: err && err.message ? err.message : String(err) });
  process.exit(1);
}
