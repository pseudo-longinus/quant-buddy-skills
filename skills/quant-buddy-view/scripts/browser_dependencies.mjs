import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';


export function playwrightSearchRoots({
  env = process.env,
  cwd = process.cwd(),
  homeDir = os.homedir(),
  delimiter = path.delimiter,
} = {}) {
  const roots = [
    env.QBV_PLAYWRIGHT_MODULE_ROOT,
    ...String(env.NODE_PATH || '').split(delimiter),
    path.join(cwd, 'node_modules'),
    path.join(homeDir, '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules'),
  ]
    .map(item => String(item || '').trim())
    .filter(Boolean);
  return [...new Set(roots)];
}


export function browserCandidates({ env = process.env, platform = process.platform } = {}) {
  const configured = [env.CHROME_PATH, env.EDGE_PATH, env.BROWSER].filter(Boolean);
  const windows = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  ];
  const unix = ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/microsoft-edge'];
  return [...configured, ...(platform === 'win32' ? windows : unix)];
}


export function firstExistingBrowser(candidates, existsSync = fs.existsSync) {
  for (const candidate of candidates || []) {
    if (candidate && existsSync(candidate)) return candidate;
  }
  return '';
}


export function findBrowser(options = {}) {
  const platform = options.platform || process.platform;
  const configured = firstExistingBrowser(
    browserCandidates({ env: options.env || process.env, platform }),
    options.existsSync || fs.existsSync,
  );
  if (configured) return configured;

  const names = platform === 'win32'
    ? ['msedge.exe', 'chrome.exe', 'chromium.exe', 'brave.exe']
    : ['google-chrome', 'chromium', 'chromium-browser', 'microsoft-edge', 'brave'];
  const lookup = platform === 'win32' ? 'where.exe' : 'which';
  const runLookup = options.runLookup || ((command, args) => spawnSync(command, args, { encoding: 'utf8' }));
  for (const name of names) {
    const found = runLookup(lookup, [name]);
    if (found && found.status === 0 && String(found.stdout || '').trim()) {
      const first = String(found.stdout).trim().split(/\r?\n/)[0];
      if (first) return first;
    }
  }
  return '';
}


export function playwrightLaunchAttempts(executablePath, args = []) {
  return [
    ...(executablePath ? [{ executablePath, headless: true, args }] : []),
    { channel: 'chrome', headless: true, args },
    { channel: 'msedge', headless: true, args },
    { headless: true, args },
  ];
}
