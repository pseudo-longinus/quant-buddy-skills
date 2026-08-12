(function(){
  const VERSION = "snapshot-tall-v1";
  const EMPTY = new Set(["", "-", "--", "—", "null", "undefined", "nan", "n/a", "取数中"]);
  const SNAPSHOT_POSTER_RATIO = 762 / 732;
  function isNum(v){ return typeof v === "number" && isFinite(v); }
  function clamp(v,a,b){ return Math.max(a, Math.min(b, v)); }
  function text(v){ return String(v == null ? "" : v); }
  function clean(v, max){
    let s = text(v).replace(/\s+/g, " ").trim();
    if(max && Array.from(s).length > max) s = Array.from(s).slice(0, max).join("");
    return s;
  }
  function isUseful(v){
    const s = clean(v).toLowerCase();
    return !EMPTY.has(s) && !/^公式包实时读取$/.test(clean(v));
  }
  function fmtValue(v){
    if(isNum(v)) return Math.abs(v) >= 10000 ? v.toLocaleString("zh-CN", {maximumFractionDigits: 1}) : String(v);
    return clean(v, 18);
  }
  function fit(ctx, s, maxW){
    s = text(s);
    if(ctx.measureText(s).width <= maxW) return s;
    while(s && ctx.measureText(s + "...").width > maxW) s = Array.from(s).slice(0, -1).join("");
    return s ? s + "..." : "";
  }
  function lines(ctx, value, maxW, maxLines){
    const chars = Array.from(clean(value));
    let line = "", out = [];
    chars.forEach(ch => {
      const test = line + ch;
      if(ctx.measureText(test).width > maxW && line){ out.push(line); line = ch; }
      else line = test;
    });
    if(line) out.push(line);
    if(maxLines && out.length > maxLines){
      out = out.slice(0, maxLines);
      out[out.length - 1] = fit(ctx, out[out.length - 1], maxW);
    }
    return out;
  }
  function wrap(ctx, value, x, y, maxW, lineH, maxLines){
    const out = lines(ctx, value, maxW, maxLines);
    out.forEach((ln, i) => ctx.fillText(ln, x, y + i * lineH));
    return y + Math.max(1, out.length) * lineH;
  }
  function roundRect(ctx,x,y,w,h,r){
    const rr=Math.min(r,w/2,h/2);
    ctx.beginPath(); ctx.moveTo(x+rr,y); ctx.lineTo(x+w-rr,y);
    ctx.quadraticCurveTo(x+w,y,x+w,y+rr); ctx.lineTo(x+w,y+h-rr);
    ctx.quadraticCurveTo(x+w,y+h,x+w-rr,y+h); ctx.lineTo(x+rr,y+h);
    ctx.quadraticCurveTo(x,y+h,x,y+h-rr); ctx.lineTo(x,y+rr);
    ctx.quadraticCurveTo(x,y,x+rr,y); ctx.closePath();
  }
  function fillRound(ctx,x,y,w,h,r,fill){ ctx.fillStyle=fill; roundRect(ctx,x,y,w,h,r); ctx.fill(); }
  function strokeRound(ctx,x,y,w,h,r,stroke){ ctx.strokeStyle=stroke; roundRect(ctx,x,y,w,h,r); ctx.stroke(); }
  function logoSrc(){
    const img=document.querySelector(".qb-logo img");
    if(img) return img.currentSrc || img.src || "";
    const svg=document.querySelector(".qb-logo svg");
    if(!svg) return "";
    const clone=svg.cloneNode(true);
    clone.setAttribute("xmlns","http://www.w3.org/2000/svg");
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(new XMLSerializer().serializeToString(clone));
  }
  function loadImage(src){
    return new Promise((resolve,reject)=>{
      const image=new Image();
      image.onload=()=>resolve(image);
      image.onerror=reject;
      image.src=src;
    });
  }
  async function drawLogo(ctx,x,y,size){
    fillRound(ctx,x,y,size,size,12,"#fff7ea");
    strokeRound(ctx,x,y,size,size,12,"rgba(255,194,125,.45)");
    const src=logoSrc();
    if(src){
      try{
        const image=await loadImage(src);
        const pad=6;
        ctx.save(); roundRect(ctx,x+pad,y+pad,size-pad*2,size-pad*2,8); ctx.clip();
        ctx.drawImage(image,x+pad,y+pad,size-pad*2,size-pad*2); ctx.restore();
        return;
      }catch(e){}
    }
    ctx.fillStyle="#20150a"; ctx.font="800 21px Microsoft YaHei, sans-serif"; ctx.fillText("QB",x+14,y+36);
  }
  function posterTarget(){
    return document.querySelector("[data-qb-poster-target]")
      || document.querySelector("main")
      || document.querySelector(".wrap")
      || document.body;
  }
  function copyCanvas(src, clone){
    const srcCanvas = Array.from(src.querySelectorAll("canvas"));
    const cloneCanvas = Array.from(clone.querySelectorAll("canvas"));
    srcCanvas.forEach((canvas, i) => {
      const dst = cloneCanvas[i];
      if(!dst) return;
      try{
        const image = document.createElement("img");
        image.src = canvas.toDataURL("image/png");
        image.style.cssText = dst.getAttribute("style") || "";
        image.style.width = (canvas.getBoundingClientRect().width || canvas.width) + "px";
        image.style.height = (canvas.getBoundingClientRect().height || canvas.height) + "px";
        dst.replaceWith(image);
      }catch(e){}
    });
  }
  function copyStyleTree(src, clone){
    if(src.nodeType !== 1 || clone.nodeType !== 1) return;
    const cs = getComputedStyle(src);
    let css = "";
    for(let i = 0; i < cs.length; i++){
      const prop = cs[i];
      css += prop + ":" + cs.getPropertyValue(prop) + ";";
    }
    clone.setAttribute("style", css + (clone.getAttribute("style") || ""));
    Array.from(src.children).forEach((child, i) => copyStyleTree(child, clone.children[i]));
  }
  function sanitizeClone(clone){
    clone.querySelectorAll([
      "script",
      "style",
      ".qb-head",
      ".qb-footer",
      ".qb-actions",
      ".share-modal",
      ".share-card",
      ".qb-retrofit-qr-placeholder",
      "[data-qb-share-shell]",
      "[data-qb-share-shell-footer]",
      "[data-qb-poster-exclude]",
      "#sharePosterModal",
      "#refresh",
      "#shareBtn"
    ].join(",")).forEach(el => el.remove());
  }
  function makeSnapshotSvg(source, width, height){
    const clone = source.cloneNode(true);
    copyCanvas(source, clone);
    copyStyleTree(source, clone);
    sanitizeClone(clone);
    clone.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");
    clone.style.margin = "0";
    clone.style.width = width + "px";
    clone.style.minWidth = width + "px";
    clone.style.maxWidth = width + "px";
    clone.style.height = "auto";
    clone.style.overflow = "hidden";

    const wrapper = document.createElement("div");
    wrapper.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");
    wrapper.style.width = width + "px";
    wrapper.style.height = height + "px";
    wrapper.style.overflow = "hidden";
    wrapper.style.margin = "0";
    wrapper.style.background = getComputedStyle(source).backgroundColor || getComputedStyle(document.body).backgroundColor || "#0b0e14";
    wrapper.appendChild(clone);

    const html = new XMLSerializer().serializeToString(wrapper);
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><foreignObject width="100%" height="100%">${html}</foreignObject></svg>`;
  }
  function usableCanvas(canvas){
    const ctx = canvas.getContext("2d");
    const w = canvas.width, h = canvas.height;
    if(w < 120 || h < 120) return false;
    const data = ctx.getImageData(0, 0, w, h).data;
    let varied = 0;
    const r0 = data[0], g0 = data[1], b0 = data[2], step = Math.max(4, Math.floor(data.length / 4000));
    for(let i = 0; i < data.length; i += step * 4){
      if(Math.abs(data[i] - r0) + Math.abs(data[i+1] - g0) + Math.abs(data[i+2] - b0) > 24) varied++;
    }
    return varied > 40;
  }
  async function capturePosterTarget(){
    const source = posterTarget();
    if(!source) return null;
    const rect = source.getBoundingClientRect();
    const width = Math.round(clamp(rect.width || source.scrollWidth || document.documentElement.clientWidth, 320, 1180));
    const minPosterHeight = Math.ceil(width * SNAPSHOT_POSTER_RATIO);
    const viewportHeight = Math.round(window.innerHeight * 0.9);
    const captureCap = Math.max(620, Math.min(1320, Math.max(viewportHeight, minPosterHeight)));
    const naturalHeight = Math.round(source.scrollHeight || rect.height || captureCap);
    const height = Math.round(clamp(Math.max(naturalHeight, minPosterHeight), 420, captureCap));
    const svg = makeSnapshotSvg(source, width, height);
    const url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    const image = await loadImage(url);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = getComputedStyle(document.body).backgroundColor || "#0b0e14";
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(image, 0, 0);
    if(!usableCanvas(canvas)) return null;
    canvas.toDataURL("image/png");
    return { canvas, width, height };
  }
  function firstText(selectors){
    for(const sel of selectors){
      const el = document.querySelector(sel);
      const s = el ? clean(el.textContent, 80) : "";
      if(isUseful(s)) return s;
    }
    return "";
  }
  function domMetrics(){
    const nodes = Array.from(document.querySelectorAll("#metrics .metric,.metric,.card-number")).slice(0, 12);
    return nodes.map(el => ({
      label: firstIn(el, [".label", ".card-head h3", "h3"]),
      value: firstIn(el, [".value", ".big", ".body"]),
      sub: firstIn(el, [".sub", ".desc", ".card-head p"])
    }));
  }
  function firstIn(root, selectors){
    for(const sel of selectors){
      const el = root.querySelector(sel);
      const s = el ? clean(el.textContent, 36) : "";
      if(isUseful(s)) return s;
    }
    return "";
  }
  function normalizeMetric(m){
    if(!m || typeof m !== "object") return null;
    const label = clean(m.label || m.name || m.title, 16);
    const value = fmtValue(m.value != null ? m.value : m.display);
    const sub = clean(m.sub || m.note || m.description, 18);
    if(!isUseful(label) || !isUseful(value)) return null;
    if(/^(数据日期|刷新方式|页面口径)$/i.test(label)) return null;
    return { label, value, sub };
  }
  function normalizeMetrics(raw, fallback){
    const seen = new Set();
    return (Array.isArray(raw) && raw.length ? raw : fallback)
      .map(normalizeMetric)
      .filter(Boolean)
      .filter(m => {
        const key = m.label.toLowerCase();
        if(seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, 6);
  }
  function normalizeItem(item, type){
    if(!item || typeof item !== "object") return null;
    const label = clean(item.label || item.name || item.title || item.asset, 18);
    const display = fmtValue(item.display != null ? item.display : item.value);
    if(!isUseful(label) || !isUseful(display)) return null;
    let value = isNum(item.value) ? item.value : null;
    if(value == null && typeof item.value === "string"){
      const parsed = parseFloat(item.value.replace("%", ""));
      if(isFinite(parsed)) value = parsed;
    }
    if((type === "bars" || type === "water") && value == null) return null;
    return {
      label,
      value,
      display,
      color: clean(item.color, 24) || null,
      sub: clean(item.sub, 18)
    };
  }
  function sectionScore(section){
    const title = clean(section && section.title);
    if(/口径|提示|说明|免责声明|页面/.test(title)) return -1;
    if(section.type === "water") return 4;
    if(section.type === "bars") return 3;
    return 2;
  }
  function normalizeSections(raw){
    if(!Array.isArray(raw)) return [];
    return raw.map(section => {
      if(!section || typeof section !== "object") return null;
      const type = ["bars", "water", "list"].includes(section.type) ? section.type : "list";
      const items = (Array.isArray(section.items) ? section.items : [])
        .map(item => normalizeItem(item, type))
        .filter(Boolean)
        .slice(0, type === "list" ? 4 : 3);
      const title = clean(section.title || "精选观察", 18);
      if(!isUseful(title) || items.length < 2) return null;
      return {
        title,
        type,
        items,
        summary: clean(section.summary, 56),
        score: sectionScore(section)
      };
    }).filter(Boolean).filter(s => s.score >= 0).sort((a,b)=>b.score-a.score).slice(0,1);
  }
  function normalizeData(raw, options){
    raw = raw && typeof raw === "object" ? raw : {};
    const headline = clean(raw.headline || raw.title || options.title || firstText(["h1", ".title", "#title"]) || document.title, 34);
    const summary = clean(raw.summary || options.subtitle || firstText([".question", ".subtitle", ".text-panel", ".balance-caption"]), 92);
    const metrics = normalizeMetrics(raw.metrics, domMetrics());
    const sections = normalizeSections(raw.sections);
    const asof = clean(raw.asof || options.asof || firstText(["#asof", ".asof b", ".asof"]), 20);
    return { headline, summary, metrics, sections, asof, templateName: clean(raw.templateName || options.templateName, 24) };
  }
  function metricColor(value){
    const s = clean(value);
    if(/^\+/.test(s)) return "#ff9a8f";
    if(/^[-−]/.test(s)) return "#43e091";
    return "#e8edf4";
  }
  async function drawHeader(ctx,W,data,options){
    await drawLogo(ctx,64,60,56);
    ctx.fillStyle="#eef2f7"; ctx.font="800 24px Microsoft YaHei, sans-serif"; ctx.fillText("QuantBuddy · 宽宝",136,89);
    ctx.fillStyle="#bba995"; ctx.font="500 15px Microsoft YaHei, sans-serif"; ctx.fillText(data.templateName || options.templateName || "实时数据页面",136,113);
    fillRound(ctx,W-246,70,182,34,17,"rgba(255,255,255,.06)");
    ctx.fillStyle="#43e091"; ctx.beginPath(); ctx.arc(W-224,87,5,0,Math.PI*2); ctx.fill();
    ctx.fillStyle="#d9c3ae"; ctx.font="700 12px Consolas, monospace"; ctx.fillText("REAL-TIME",W-209,92);
  }
  function drawMetrics(ctx,metrics,x,y,w){
    if(!metrics.length) return 0;
    ctx.fillStyle="#f3f4f6"; ctx.font="800 23px Microsoft YaHei, sans-serif"; ctx.fillText("核心指标",x,y);
    const cols = 2, gap = 16, cardW = (w - gap) / cols, cardH = 118;
    metrics.forEach((m,i)=>{
      const cx = x + (i % cols) * (cardW + gap), cy = y + 22 + Math.floor(i / cols) * (cardH + gap);
      fillRound(ctx,cx,cy,cardW,cardH,10,"rgba(255,255,255,.055)");
      strokeRound(ctx,cx,cy,cardW,cardH,10,"rgba(255,255,255,.12)");
      ctx.fillStyle="#cbb8a3"; ctx.font="700 14px Microsoft YaHei, sans-serif"; wrap(ctx,m.label,cx+18,cy+28,cardW-36,17,1);
      ctx.fillStyle=metricColor(m.value); ctx.font="800 31px Consolas, Microsoft YaHei, monospace"; wrap(ctx,m.value,cx+18,cy+68,cardW-36,34,1);
      if(m.sub){ ctx.fillStyle="#958777"; ctx.font="500 13px Microsoft YaHei, sans-serif"; wrap(ctx,m.sub,cx+18,cy+94,cardW-36,16,1); }
    });
    return 22 + Math.ceil(metrics.length / cols) * cardH + Math.max(0, Math.ceil(metrics.length / cols) - 1) * gap;
  }
  function drawRows(ctx,items,x,y,w){
    items.forEach((r,i)=>{
      const cy = y + i * 42;
      ctx.fillStyle="#cab8a4"; ctx.font="700 16px Microsoft YaHei, sans-serif"; ctx.fillText(fit(ctx,r.label,w*0.56),x,cy+22);
      ctx.fillStyle=r.color || "#eef2f7"; ctx.font="800 17px Consolas, Microsoft YaHei, monospace"; ctx.textAlign="right";
      ctx.fillText(fit(ctx,r.display,w*0.34),x+w,cy+22); ctx.textAlign="left";
      if(i < items.length - 1){ ctx.strokeStyle="rgba(255,255,255,.08)"; ctx.beginPath(); ctx.moveTo(x,cy+38); ctx.lineTo(x+w,cy+38); ctx.stroke(); }
    });
  }
  function drawBars(ctx,section,x,y,w){
    const items = section.items;
    const maxAbs = Math.max(1, ...items.map(r => Math.abs(+r.value || 0)));
    items.forEach((r,i)=>{
      const cy = y + i * 50;
      ctx.fillStyle="#cab8a4"; ctx.font="700 15px Microsoft YaHei, sans-serif"; ctx.fillText(fit(ctx,r.label,150),x,cy+24);
      fillRound(ctx,x+168,cy+9,w-290,16,8,"rgba(255,255,255,.10)");
      const color = r.color || (+r.value >= 0 ? "#ff9a8f" : "#43e091");
      const pct = section.type === "water" ? clamp(+r.value,0,100) / 100 : Math.abs(+r.value || 0) / maxAbs;
      fillRound(ctx,x+168,cy+9,Math.max(4,pct*(w-290)),16,8,color);
      ctx.fillStyle="#eef2f7"; ctx.font="800 16px Consolas, Microsoft YaHei, monospace"; ctx.textAlign="right";
      ctx.fillText(fit(ctx,r.display,92),x+w,cy+24); ctx.textAlign="left";
    });
  }
  function drawSection(ctx,section,x,y,w){
    const h = section.type === "list" ? 240 : 226;
    fillRound(ctx,x,y,w,h,12,"rgba(255,255,255,.055)");
    strokeRound(ctx,x,y,w,h,12,"rgba(255,255,255,.13)");
    ctx.fillStyle="#f3f4f6"; ctx.font="800 24px Microsoft YaHei, sans-serif"; ctx.fillText(section.title,x+24,y+42);
    let bodyY = y + 76;
    if(section.summary){
      ctx.fillStyle="#a99989"; ctx.font="500 14px Microsoft YaHei, sans-serif";
      bodyY = wrap(ctx,section.summary,x+24,bodyY,w-48,20,2) + 14;
    }
    if(section.type === "bars" || section.type === "water") drawBars(ctx,section,x+24,bodyY,w-48);
    else drawRows(ctx,section.items,x+24,bodyY,w-48);
    return h;
  }
  function drawFallbackNote(ctx,x,y,w){
    fillRound(ctx,x,y,w,146,12,"rgba(255,194,125,.07)");
    strokeRound(ctx,x,y,w,146,12,"rgba(255,194,125,.18)");
    ctx.fillStyle="#ffc27d"; ctx.font="800 22px Microsoft YaHei, sans-serif"; ctx.fillText("打开完整实时页查看更多",x+24,y+44);
    ctx.fillStyle="#bba995"; ctx.font="500 15px Microsoft YaHei, sans-serif";
    wrap(ctx,"海报只展示高置信摘要；完整图表、明细表和数据口径以页面实时结果为准。",x+24,y+78,w-48,24,2);
    return 146;
  }
  function drawSnapshotFrame(ctx,snap,x,y,w,h){
    fillRound(ctx,x,y,w,h,16,"rgba(255,255,255,.055)");
    strokeRound(ctx,x,y,w,h,16,"rgba(255,255,255,.16)");
    const pad = 20;
    const ix = x + pad, iy = y + pad, iw = w - pad * 2, ih = h - pad * 2;
    fillRound(ctx,ix,iy,iw,ih,12,"#0b0e14");
    ctx.save();
    roundRect(ctx,ix,iy,iw,ih,12);
    ctx.clip();
    const scale = iw / snap.width;
    const srcH = Math.min(snap.height, ih / scale);
    const drawH = Math.min(ih, srcH * scale);
    ctx.drawImage(snap.canvas, 0, 0, snap.width, srcH, ix, iy, iw, drawH);
    ctx.restore();
    strokeRound(ctx,ix,iy,iw,ih,12,"rgba(255,255,255,.12)");
  }
  async function generateSnapshotPoster(canvas,img,raw,opts){
    const options = opts || {};
    const data = normalizeData(raw, options);
    const snap = await capturePosterTarget();
    if(!snap) return false;
    const W=900,H=1400,ctx=canvas.getContext("2d");
    canvas.width=W; canvas.height=H;
    ctx.clearRect(0,0,W,H);
    ctx.fillStyle="#0b0e14"; ctx.fillRect(0,0,W,H);
    const bg=ctx.createLinearGradient(0,0,W,H);
    bg.addColorStop(0,"rgba(255,194,125,.12)");
    bg.addColorStop(.5,"rgba(18,23,31,.18)");
    bg.addColorStop(1,"rgba(67,224,145,.07)");
    ctx.fillStyle=bg; ctx.fillRect(0,0,W,H);
    ctx.fillStyle="rgba(255,255,255,.05)";
    for(let yy=44; yy<H-44; yy+=28){ for(let xx=44; xx<W-44; xx+=28){ ctx.fillRect(xx,yy,1,1); } }
    fillRound(ctx,40,40,W-80,H-80,18,"rgba(12,15,21,.74)");
    strokeRound(ctx,40,40,W-80,H-80,18,"rgba(255,255,255,.13)");
    await drawHeader(ctx,W,data,options);
    ctx.fillStyle="#ffc27d"; ctx.font="800 42px Microsoft YaHei, sans-serif";
    let y = wrap(ctx,data.headline || document.title,64,188,W-128,54,2) + 16;
    if(data.summary){
      ctx.fillStyle="#d6c5b3"; ctx.font="600 18px Microsoft YaHei, sans-serif";
      y = wrap(ctx,data.summary,64,y,W-128,28,2) + 26;
    }
    const frameY = Math.max(286, y);
    drawSnapshotFrame(ctx,snap,64,frameY,W-128,802);
    fillRound(ctx,64,1138,W-128,198,14,"rgba(255,255,255,.07)");
    strokeRound(ctx,64,1138,W-128,198,14,"rgba(255,255,255,.13)");
    drawQr(ctx,88,1160,152,options.shareUrl || location.href);
    ctx.fillStyle="#ffc27d"; ctx.font="800 23px Microsoft YaHei, sans-serif"; ctx.fillText("扫码查看完整实时页面",272,1196);
    ctx.fillStyle="#d8c7b4"; ctx.font="500 15px Microsoft YaHei, sans-serif";
    wrap(ctx,"海报为页面实时状态预览；完整图表、明细和数据口径以打开页面后的实时结果为准。",272,1232,W-360,24,2);
    ctx.fillStyle="#928477"; ctx.font="500 13px Microsoft YaHei, sans-serif";
    wrap(ctx,"QuantBuddy · 宽宝 · 页面仅作市场观察与数据展示，不构成投资建议。" + (data.asof ? " 数据截至 " + data.asof : ""),272,1294,W-360,20,2);
    img.src=canvas.toDataURL("image/png");
    return true;
  }
  function drawQr(ctx,x,y,size,url){
    fillRound(ctx,x,y,size,size,12,"#fff");
    const qr=document.createElement("canvas");
    try{
      if(window.QRMini){ QRMini.toCanvas(qr,url,420); ctx.imageSmoothingEnabled=false; ctx.drawImage(qr,x+10,y+10,size-20,size-20); return; }
    }catch(e){}
    ctx.fillStyle="#10131a"; ctx.font="800 20px Microsoft YaHei, sans-serif"; ctx.fillText("QR",x+size/2-14,y+size/2+7);
  }
  async function generate(canvas,img,raw,opts){
    try{
      if(!(raw && raw.posterMode === "structured") && !(opts && opts.posterMode === "structured")){
        const ok = await generateSnapshotPoster(canvas,img,raw,opts);
        if(ok) return;
      }
    }catch(e){}
    const options = opts || {};
    const data = normalizeData(raw, options);
    const W=900,H=1400,ctx=canvas.getContext("2d");
    canvas.width=W; canvas.height=H;
    ctx.clearRect(0,0,W,H);
    ctx.fillStyle="#0b0e14"; ctx.fillRect(0,0,W,H);
    const bg=ctx.createLinearGradient(0,0,W,H);
    bg.addColorStop(0,"rgba(255,194,125,.11)");
    bg.addColorStop(.36,"rgba(22,25,31,.18)");
    bg.addColorStop(1,"rgba(67,224,145,.06)");
    ctx.fillStyle=bg; ctx.fillRect(0,0,W,H);
    ctx.fillStyle="rgba(255,255,255,.055)";
    for(let yy=44;yy<H-44;yy+=28){ for(let xx=44;xx<W-44;xx+=28){ ctx.fillRect(xx,yy,1,1); } }
    fillRound(ctx,40,40,W-80,H-80,18,"rgba(12,15,21,.72)");
    strokeRound(ctx,40,40,W-80,H-80,18,"rgba(255,255,255,.13)");
    await drawHeader(ctx,W,data,options);
    ctx.fillStyle="#ffc27d"; ctx.font="800 44px Microsoft YaHei, sans-serif";
    let y = wrap(ctx,data.headline || document.title,64,196,W-128,56,2) + 18;
    if(data.summary){
      ctx.fillStyle="#d6c5b3"; ctx.font="600 19px Microsoft YaHei, sans-serif";
      y = wrap(ctx,data.summary,64,y,W-128,30,2) + 36;
    }else{
      y += 18;
    }
    const metricsH = drawMetrics(ctx,data.metrics,64,y,W-128);
    y += metricsH ? metricsH + 42 : 0;
    if(data.sections.length && y < 1010){
      y += drawSection(ctx,data.sections[0],64,y,W-128) + 28;
    }else if(y < 1010){
      y += drawFallbackNote(ctx,64,y,W-128) + 28;
    }
    fillRound(ctx,64,1138,W-128,198,14,"rgba(255,255,255,.07)");
    strokeRound(ctx,64,1138,W-128,198,14,"rgba(255,255,255,.13)");
    drawQr(ctx,88,1160,152,options.shareUrl || location.href);
    ctx.fillStyle="#ffc27d"; ctx.font="800 23px Microsoft YaHei, sans-serif"; ctx.fillText("扫码查看完整实时页面",272,1196);
    ctx.fillStyle="#d8c7b4"; ctx.font="500 15px Microsoft YaHei, sans-serif";
    wrap(ctx,"图表、明细、口径说明和最新数据以页面打开时的实时取数结果为准。",272,1232,W-360,24,2);
    ctx.fillStyle="#928477"; ctx.font="500 13px Microsoft YaHei, sans-serif";
    wrap(ctx,"QuantBuddy · 宽宝 · 页面仅作市场观察与数据展示，不构成投资建议。" + (data.asof ? " 数据截至 " + data.asof : ""),272,1294,W-360,20,2);
    img.src=canvas.toDataURL("image/png");
  }
  window.QB_SHARE_POSTER_VERSION = VERSION;
  window.QBSharePoster = { generate, version: VERSION };
})();
