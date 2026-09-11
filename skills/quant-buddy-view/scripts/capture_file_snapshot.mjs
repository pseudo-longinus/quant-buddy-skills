import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { launchFileBrowser } from './file_browser.mjs';

const [source, output] = process.argv.slice(2);
if (!source || !output) throw new Error('usage: capture_file_snapshot.mjs source.html snapshot.html');
const browser = await launchFileBrowser();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, serviceWorkers: 'block' });
  await page.addInitScript(() => {
    window.WebSocket = window.EventSource = class { constructor() { throw new Error('Snapshot capture disables streams'); } };
    navigator.sendBeacon = () => false;
  });
  const sourceUrl = pathToFileURL(path.resolve(source)).href;
  await page.route('**/*', route => {
    const request = route.request();
    // Fresh browser context, normal browser security, no arbitrary local-file reads or writes.
    if (!['GET', 'HEAD'].includes(request.method())) return route.abort();
    if (request.url().startsWith('file:') && request.url() !== sourceUrl) return route.abort();
    return route.continue();
  });
  const cache = {}, reads = [];
  page.on('response', response => {
    if (!['fetch', 'xhr'].includes(response.request().resourceType()) || response.request().method() !== 'GET') return;
    reads.push((async () => {
      if (!response.ok()) return;
      const text = await response.text();
      cache[response.url()] = { body: text, status: response.status(), type: response.headers()['content-type'] || 'text/plain' };
    })().catch(() => {}));
  });
  const base = pathToFileURL(path.resolve(source)).href;
  await page.goto(base, { waitUntil: 'load', timeout: 30000 });
  try { await page.waitForLoadState('networkidle', { timeout: 8000 }); } catch {}
  await page.waitForTimeout(1200);
  await Promise.all(reads);
  let result, mode;
  if (Object.keys(cache).length) {
    // Replay source initialization against immutable GET responses, preserving event listeners,
    // tables, exports and chart/window controls. No source endpoint is used after publication.
    const payload = JSON.stringify({ base, cache }).replace(/</g, '\\u003c');
    const bootstrap = `<script data-qb-file-snapshot-runtime="v1">(() => {
      const {base, cache} = ${payload};
      function lookup(url) { const v=cache[new URL(String(url),base).href]; if(!v) throw new Error('Snapshot response unavailable'); return v; }
      window.fetch = async (input, init={}) => {
        if(String(init.method || input?.method || 'GET').toUpperCase()!=='GET') throw new Error('Snapshot is read only');
        const v=lookup(typeof input==='string'||input instanceof URL?input:input.url);
        return new Response(v.body,{status:v.status,headers:{'content-type':v.type}});
      };
      window.XMLHttpRequest = class extends EventTarget {
        readyState=0; status=0; responseType=''; responseText=''; response=null;
        open(method,url,async=true){this.method=method;this.url=url;this.async=async;this.readyState=1;}
        setRequestHeader(){} abort(){} getResponseHeader(n){return n.toLowerCase()==='content-type'?this.type:null;}
        getAllResponseHeaders(){return 'content-type: '+(this.type||'')+'\\r\\n';}
        emit(n){this.dispatchEvent(new Event(n)); if(typeof this['on'+n]==='function')this['on'+n](new Event(n));}
        send(){ const run=()=>{try{
          if(this.method.toUpperCase()!=='GET')throw new Error('Snapshot is read only');
          const v=lookup(this.url);this.status=v.status;this.type=v.type;this.responseText=v.body;
          this.response=this.responseType==='json'?JSON.parse(v.body):this.responseType==='arraybuffer'?new TextEncoder().encode(v.body).buffer:this.responseType==='blob'?new Blob([v.body]):v.body;
          this.readyState=4;this.emit('readystatechange');this.emit('load');this.emit('loadend');
        }catch{this.status=0;this.readyState=4;this.emit('error');this.emit('loadend');}};
        this.async?queueMicrotask(run):run(); }
      };
      window.WebSocket=window.EventSource=class {constructor(){throw new Error('Snapshot streams disabled');}};
      navigator.sendBeacon=()=>false;
    })();</script>`;
    const original = fs.readFileSync(source, 'utf8');
    result = original.replace(/<head\b[^>]*>/i, match => match + bootstrap);
    if (result === original) throw new Error('HTML_HEAD_REQUIRED');
    mode = 'response_replay';
  } else {
    // If there was no capturable response, preserve visible content rather than shipping dead I/O.
    await page.evaluate(() => {
      for (const canvas of document.querySelectorAll('canvas')) {
        const image = new Image(); image.src=canvas.toDataURL(); image.width=canvas.width; image.height=canvas.height;
        canvas.replaceWith(image);
      }
      for (const e of document.querySelectorAll('*')) for (const a of [...e.attributes]) if (/^on/i.test(a.name)) e.removeAttribute(a.name);
      for (const s of document.scripts) s.type='application/x-qbv-rendered-snapshot';
    });
    result = await page.content();
    mode = 'visual_only';
  }
  fs.mkdirSync(path.dirname(path.resolve(output)), { recursive:true });
  fs.writeFileSync(output,result,'utf8');
  process.stdout.write(JSON.stringify({code:0, mode, capturedResponses:Object.keys(cache).length,
    interactionLoss: mode==='visual_only' ? 'No replayable response; script interactions frozen, visible snapshot retained.' : null}));
} finally { await browser.close(); }
