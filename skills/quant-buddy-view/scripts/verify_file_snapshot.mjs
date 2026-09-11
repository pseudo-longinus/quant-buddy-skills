// Existing-file acceptance: no template, finance, title or H1 requirements.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { launchFileBrowser } from './file_browser.mjs';
const target = process.argv[2];
let browser, server;
async function localTarget(file) {
  const target = fs.realpathSync(path.resolve(file));
  const root = path.dirname(target);
  const types = {'.html':'text/html; charset=utf-8','.htm':'text/html; charset=utf-8',
    '.js':'text/javascript','.mjs':'text/javascript','.css':'text/css','.png':'image/png',
    '.jpg':'image/jpeg','.jpeg':'image/jpeg','.svg':'image/svg+xml','.webp':'image/webp',
    '.woff':'font/woff','.woff2':'font/woff2'};
  server = http.createServer((req, res) => {
    try {
      if (!['GET','HEAD'].includes(req.method)) { res.writeHead(405); return res.end(); }
      const requestPath = decodeURIComponent(new URL(req.url,'http://localhost').pathname);
      const candidate = requestPath === '/__qb_candidate__.html' ? target :
        fs.realpathSync(path.resolve(root,'.'+requestPath));
      if (candidate !== target && !candidate.startsWith(root+path.sep)) throw new Error('outside root');
      const mime = types[path.extname(candidate).toLowerCase()];
      if (!mime) throw new Error('unsupported resource');
      const data = fs.readFileSync(candidate);
      res.writeHead(200,{'Content-Type':mime,'Cache-Control':'no-store'});
      res.end(req.method === 'HEAD' ? undefined : data);
    } catch { res.writeHead(404); res.end(); }
  });
  await new Promise((resolve,reject) => { server.once('error',reject); server.listen(0,'127.0.0.1',resolve); });
  return `http://127.0.0.1:${server.address().port}/__qb_candidate__.html`;
}
try {
  if (!target) throw new Error('FILE_TARGET_REQUIRED');
  const url = /^https?:\/\//i.test(target) ? target : await localTarget(target);
  browser = await launchFileBrowser();
  const results = [], problems = [];
  for (const width of [1440,390]) {
    const page = await browser.newPage({ viewport:{width,height:900}, serviceWorkers:'block' });
    if (process.env.QBV_TEST_SUPPRESS_TRACKING === '1') {
      await page.route('https://www.quantbuddy.cn/webapi/skill/track*',route=>route.fulfill({status:204,body:''}));
    }
    const errors = [], resources = [];
    page.on('pageerror', () => errors.push('SCRIPT_ERROR'));
    page.on('requestfailed', r => { if (['image','stylesheet','script','font'].includes(r.resourceType())) resources.push(r.resourceType()); });
    const response = await page.goto(url,{waitUntil:'load',timeout:30000});
    if (response && !response.ok()) problems.push('DOCUMENT_HTTP_ERROR');
    try { await page.waitForLoadState('networkidle',{timeout:5000}); } catch {}
    await page.evaluate(async () => {
      for (const image of document.images) {
        image.loading='eager';
        try { await image.decode(); } catch {}
      }
      await document.fonts.ready;
    });
    const metrics = await page.evaluate(() => {
      const visible = e => {const r=e.getBoundingClientRect();const s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'};
      const imageList=[...document.images];
      const text=(document.body?.innerText||'').trim();
      const media=[...document.querySelectorAll('img,canvas,svg,video')].filter(visible);
      const idlePoster = i => i.id === 'sharePosterImage' && i.hasAttribute('data-qb-runtime-src') &&
        !i.getAttribute('src') && !i.currentSrc && !visible(i) &&
        i.closest('#sharePosterModal')?.getAttribute('aria-hidden') === 'true';
      const ignoredPosters=imageList.filter(idlePoster).length;
      const broken=imageList.filter(i=>!idlePoster(i)&&(!i.complete||i.naturalWidth<=0)).length;
      const localReferences=[...document.querySelectorAll('[src],[href]')].filter(e=>
        !['SCRIPT'].includes(e.tagName) && /^file:|^[A-Za-z]:[\\/]/i.test(e.getAttribute('src')||e.getAttribute('href')||'')).length;
      return {hasContent:!!text||media.length>0, textLength:text.length, mediaCount:media.length,
        imageCount:imageList.length, ignoredIdlePosters:ignoredPosters, brokenImages:broken, localReferences,
        horizontalOverflow:document.documentElement.scrollWidth>innerWidth+1};
    });
    if (!metrics.hasContent) problems.push('EMPTY_SOURCE_SNAPSHOT');
    if (metrics.brokenImages) problems.push('BROKEN_IMAGES');
    if (metrics.localReferences) problems.push('LOCAL_RESOURCE_REFERENCE');
    if (metrics.horizontalOverflow) problems.push('HORIZONTAL_OVERFLOW');
    if (errors.length) problems.push('SCRIPT_ERROR');
    if (resources.length) problems.push('RESOURCE_LOAD_FAILED');
    results.push({width,...metrics,scriptErrors:errors.length,resourceErrors:resources.length});
    await page.close();
  }
  const code=problems.length?1:0;
  process.stdout.write(JSON.stringify({code,verification_profile:'file-snapshot',browser:{checked:true,viewports:results},problems:[...new Set(problems)]}));
  process.exitCode=code;
} catch {
  process.stdout.write(JSON.stringify({code:1,error:'FILE_SNAPSHOT_BROWSER_CHECK_FAILED'}));
  process.exitCode=1;
} finally {
  if(browser)await browser.close();
  if(server) { server.closeAllConnections?.(); await new Promise(resolve=>server.close(resolve)); }
}
