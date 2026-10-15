(function(){
  const VERSION = "share-shell-v2";
  const REVISION = 5;
  const OFFICIAL_ORIGIN = "https://www.quantbuddy.cn";
  const PAGES_ORIGIN = "https://pages.quantbuddy.cn";
  const WAREHOUSE_CHANNEL = "qb-research-warehouse-v1";
  const AUTH_CHANNEL = "qb-auth-continue-v1";
  const WEB_AGENT_CHANNEL = "qb-web-agent-v1";
  const HEADER_CHANNEL = "qb-live-page-header-v1";
  const HEADER_PROTOCOL_VERSION = 1;
  const HEADER_READY_TIMEOUT_MS = 4000;
  const AUTH_HELLO_MAX_ATTEMPTS = 75;
  const $ = id => document.getElementById(id);
  let state={};
  let pageContext=null;
  let warehouseReady=false;
  let warehouseTimer=0;
  let warehouseHelloTimer=0;
  let warehouseHelloAttempts=0;
  let authReady=false;
  let authHelloTimer=0;
  let authHelloAttempts=0;
  let authRequestId="";
  let pendingAuthenticatedTarget="";
  let pendingAuthenticatedTrigger=null;
  let webAgentReady=false;
  let webAgentHelloTimer=0;
  let webAgentHelloAttempts=0;
  let pendingWebAgentTrigger=null;
  let pendingWebAgentAsk=null;
  let webAgentAskSequence=0;
  let headerReady=false;
  let headerReadyTimer=0;
  let favoriteState=false;
  let refreshBusy=false;
  let headerUpdateCapable=false;
  let updateFlow=null;
  let updateTimer=0;
  let updateHandshakeTimer=0;
  function callMaybe(v){ return typeof v === "function" ? v() : v; }
  function serviceOrigin(){
    try{
      const candidate=new URL(state.embedOrigin || OFFICIAL_ORIGIN);
      if(candidate.origin===OFFICIAL_ORIGIN) return OFFICIAL_ORIGIN;
      if((candidate.protocol==="http:" || candidate.protocol==="https:") && /^(127\.0\.0\.1|localhost)$/.test(candidate.hostname)) return candidate.origin;
    }catch(e){}
    return OFFICIAL_ORIGIN;
  }
  function normalizeOfficialTarget(targetUrl,fallbackPath){
    const fallback=/^\/(?![\\/])/.test(fallbackPath || "") ? fallbackPath : "/dashboard";
    try{
      const target=new URL(targetUrl,OFFICIAL_ORIGIN);
      const candidate=target.pathname+target.search+target.hash;
      if(target.origin===OFFICIAL_ORIGIN && /^\/(?![\\/])/.test(candidate) && !/[\u0000-\u001f\u007f]/.test(candidate)) return OFFICIAL_ORIGIN+candidate;
    }catch(e){}
    return OFFICIAL_ORIGIN+fallback;
  }
  function resolveNavigationTarget(targetUrl){
    const safe=normalizeOfficialTarget(targetUrl,"/dashboard");
    if(!state.navigationOrigin) return safe;
    try{
      const local=new URL(state.navigationOrigin);
      if(local.protocol==="http:" && /^(127\.0\.0\.1|localhost)$/.test(local.hostname)){
        const parsed=new URL(safe);
        return local.origin+parsed.pathname+parsed.search+parsed.hash;
      }
    }catch(e){}
    return safe;
  }
  function setStatus(msg){ const el=$("sharePosterStatus"); if(el) el.textContent=msg; }
  function setBusy(busy){ ["copyPoster","downloadPoster"].forEach(id=>{ const el=$(id); if(el) el.disabled=!!busy; }); }
  function setRefreshBusy(busy,label){
    refreshBusy=!!busy;
    const btn=$("qbHeaderFallbackRefresh");
    if(btn){ btn.disabled=isUpdateBusy() ? false : refreshBusy; btn.textContent=isUpdateBusy() ? "更新中" : (label || (refreshBusy ? "取数中" : "更新活页")); }
    postHeaderState("state");
  }
  async function runRefresh(){
    if(!state.onRefresh) return;
    try{ setRefreshBusy(true,"取数中"); await state.onRefresh(); }
    finally{ setRefreshBusy(false,"刷新数据"); }
  }
  function derivePageContext(url){
    try{
      const parsed=new URL(url || location.href, location.href);
      const parts=parsed.pathname.split("/").filter(Boolean);
      const pagesIndex=parts.indexOf("pages");
      if(pagesIndex<0 || parts.length<pagesIndex+3) return null;
      const routeParts=parts.slice(pagesIndex+1);
      const file=routeParts.pop() || "";
      if(!/\.html$/i.test(file)) return null;
      const pageId=file.replace(/\.html$/i,"");
      if(!pageId || !routeParts.length) return null;
      const encoded=[...routeParts,pageId].map(value=>encodeURIComponent(decodeURIComponent(value)));
      const playgroundUrl=OFFICIAL_ORIGIN+"/playground/"+encoded.join("/");
      const pageUrl=PAGES_ORIGIN+"/pages/"+encoded.join("/")+".html";
      const embedOrigin=serviceOrigin();
      return {
        pageId:pageId,
        pageUrl:pageUrl,
        playgroundUrl:playgroundUrl,
        embedUrl:embedOrigin+"/embed/research-warehouse?page_id="+encodeURIComponent(pageId),
        authEmbedUrl:embedOrigin+"/embed/auth-continue",
        webAgentEmbedUrl:embedOrigin+"/embed/web-agent",
        headerEmbedUrl:embedOrigin+"/embed/live-page-header"
      };
    }catch(e){ return null; }
  }
  function setFavoriteState(favorited){
    favoriteState=!!favorited;
    const btn=$("qbHeaderFallbackFavorite");
    if(btn){
      btn.classList.toggle("is-favorited",favoriteState);
      btn.setAttribute("aria-pressed",favoriteState ? "true" : "false");
      btn.textContent=favoriteState ? "已收藏" : "收藏";
      btn.title=favoriteState ? "管理投研仓收藏" : "收藏到投研仓";
    }
    postHeaderState("state");
  }
  function isWebAgentPreviewContext(){
    const meta=typeof document.querySelector==="function" ? document.querySelector('meta[name="qb-live-page-embed-context"]') : null;
    return !!(meta && meta.getAttribute("content")==="webagent-preview");
  }
  function headerHost(){ return typeof document.querySelector==="function" ? document.querySelector("[data-qb-live-page-header-host]") : null; }
  function headerFrame(){ return $("qbLivePageHeaderFrame"); }
  function headerParentOrigin(){
    try{
      const origin=new URL(location.href).origin;
      if(origin===PAGES_ORIGIN || (/^https?:$/.test(new URL(origin).protocol) && /^(127\.0\.0\.1|localhost)$/.test(new URL(origin).hostname))) return origin;
    }catch(e){}
    return PAGES_ORIGIN;
  }
  function buildHeaderMessage(type,extra){
    if(!pageContext) return null;
    return Object.assign({channel:HEADER_CHANNEL,version:HEADER_PROTOCOL_VERSION,type:type,page_id:pageContext.pageId},extra || {});
  }
  function postHeaderState(type){
    const frame=headerFrame(), message=buildHeaderMessage(type || "state",{favorited:favoriteState,refresh_busy:refreshBusy,public_update:true,update_busy:isUpdateBusy()});
    if(!headerReady || !frame || !frame.contentWindow || !message) return false;
    frame.contentWindow.postMessage(message,serviceOrigin());
    return true;
  }
  function showHeaderFallback(){
    const host=headerHost(), fallback=typeof document.querySelector==="function" ? document.querySelector("[data-qb-live-page-header-fallback]") : null;
    if(host) host.classList.add("qb-header-fallback-visible");
    if(fallback) fallback.setAttribute("aria-hidden","false");
  }
  function scheduleHeaderFallback(){
    if(headerReady || headerReadyTimer) return;
    headerReadyTimer=window.setTimeout(()=>{ headerReadyTimer=0; if(!headerReady) showHeaderFallback(); },HEADER_READY_TIMEOUT_MS);
  }
  function hideHeaderFallback(){
    const host=headerHost(), fallback=typeof document.querySelector==="function" ? document.querySelector("[data-qb-live-page-header-fallback]") : null;
    if(host) host.classList.remove("qb-header-fallback-visible");
    if(fallback) fallback.setAttribute("aria-hidden","true");
  }
  function ensureHeaderFrame(){
    if(isWebAgentPreviewContext()) return null;
    const frame=headerFrame();
    if(!frame || !pageContext) return null;
    if(!frame.dataset.qbHeaderLoadBound){
      frame.addEventListener("load",()=>{
        headerReady=false;
        scheduleHeaderFallback();
      });
      frame.dataset.qbHeaderLoadBound="1";
    }
    if(!frame.src){
      const params="?page_id="+encodeURIComponent(pageContext.pageId)+"&page_url="+encodeURIComponent(pageContext.pageUrl)+"&parent_origin="+encodeURIComponent(headerParentOrigin());
      frame.src=pageContext.headerEmbedUrl+params;
    }
    scheduleHeaderFallback();
    return frame;
  }
  function isTrustedHeaderMessage(event,frame,context){
    const data=event && event.data;
    return !!(frame && context && event.origin===serviceOrigin() && event.source===frame.contentWindow && data && data.channel===HEADER_CHANNEL && data.version===HEADER_PROTOCOL_VERSION && data.page_id===context.pageId);
  }
  function routeHeaderAction(action){
    if(action==="brand") return openAuthenticatedTarget(null,OFFICIAL_ORIGIN+"/dashboard?scope=favorited");
    if(action==="refresh") return runRefresh();
    if(action==="update") return runPageUpdate();
    if(action==="favorite") return openWarehouse();
    if(action==="share") return openSharePoster();
    if(action==="ask") return openAsk(null);
    return false;
  }
  function onHeaderMessage(event){
    const frame=headerFrame();
    if(!isTrustedHeaderMessage(event,frame,pageContext)) return false;
    const data=event.data;
    if(data.type==="ready"){
      headerReady=true;
      headerUpdateCapable=data.public_update===true;
      window.clearTimeout(headerReadyTimer);
      headerReadyTimer=0;
      hideHeaderFallback();
      postHeaderState("init");
      sendUpdateStart();
      return true;
    }
    if(data.type==="resize"){
      const height=Number(data.height);
      if(!Number.isFinite(height) || height<44 || height>120) return false;
      frame.style.height=Math.round(height)+"px";
      return true;
    }
    if(data.type==="update-progress") return acceptUpdateProgress(data);
    if(data.type==="action" && /^(brand|refresh|update|favorite|share|ask)$/.test(String(data.action || ""))){
      routeHeaderAction(data.action);
      return true;
    }
    return false;
  }
  function isUpdateBusy(){ return !!(updateFlow && !updateFlow.finished); }
  function updateStorageKey(){ return "qb-public-update:"+(pageContext ? pageContext.pageId : ""); }
  function saveUpdateFlow(){
    try{ if(updateFlow && pageContext) window.sessionStorage.setItem(updateStorageKey(),JSON.stringify(Object.assign({},updateFlow,{page_id:pageContext.pageId,saved_at:Date.now()}))); }catch(e){}
  }
  function updateElapsed(){
    if(!updateFlow) return "";
    const seconds=Math.max(0,Math.floor(((updateFlow.finished_at || Date.now())-updateFlow.started_at)/1000));
    return String(Math.floor(seconds/60)).padStart(2,"0")+":"+String(seconds%60).padStart(2,"0");
  }
  function showUpdateTimeline(){ const panel=$("qbUpdateTimeline"); if(panel){ panel.hidden=false;panel.setAttribute("aria-hidden","false"); } }
  function closeUpdateTimeline(){ const panel=$("qbUpdateTimeline"); if(panel){ panel.hidden=true;panel.setAttribute("aria-hidden","true"); } }
  function renderUpdateTimeline(){
    if(!updateFlow) return;
    const flow=updateFlow;
    const text=(id,value)=>{ const el=$(id); if(el && el.textContent!==value) el.textContent=value; };
    text("qbUpdateElapsed",updateElapsed());
    text("qbUpdateDataStatus",flow.data_status==="running" ? "正在按原逻辑刷新数据" : flow.data_status==="failed" ? "刷新失败；第二步仍按权限继续" : "页面数据刷新已结束");
    text("qbUpdateReportStatus",flow.message || "等待第一步结束");
    text("qbUpdateHint",flow.finished ? "本次更新已结束。" : "可收起进度继续阅读，任务状态会持续同步。");
    text("qbUpdateDataMark",flow.data_status==="running" ? "◉" : flow.data_status==="failed" ? "!" : "✓");
    text("qbUpdateReportMark",flow.report_status==="skipped" ? "—" : /^(failed|cancelled)$/.test(flow.report_status) ? "!" : flow.finished ? "✓" : flow.report_status==="waiting" ? "○" : "◉");
    const panel=$("qbUpdateTimeline"); if(panel) panel.dataset.busy=isUpdateBusy() ? "true" : "false";
    const dataRow=$("qbUpdateDataRow"),reportRow=$("qbUpdateReportRow");
    if(dataRow) dataRow.dataset.status=flow.data_status;
    if(reportRow) reportRow.dataset.status=flow.report_status;
    const fallback=$("qbHeaderFallbackRefresh"); if(fallback){ fallback.disabled=false;fallback.textContent=isUpdateBusy() ? "更新中" : "更新活页"; }
    postHeaderState("state");
    if(isUpdateBusy() && !updateTimer){ updateTimer=window.setTimeout(()=>{updateTimer=0;renderUpdateTimeline();},1000); }
  }
  function finishUpdate(status,message){
    if(!updateFlow) return;
    updateFlow.report_status=status;updateFlow.message=message;updateFlow.finished=true;updateFlow.finished_at=Date.now();
    window.clearTimeout(updateHandshakeTimer);updateHandshakeTimer=0;
    saveUpdateFlow();renderUpdateTimeline();
  }
  function sendUpdateStart(){
    if(!updateFlow || updateFlow.finished || updateFlow.data_status==="running" || !headerReady) return false;
    if(!headerUpdateCapable){ finishUpdate("skipped","官网页头尚未支持报告更新，本次仅刷新数据");return false; }
    const frame=headerFrame();if(!frame || !frame.contentWindow) return false;
    window.clearTimeout(updateHandshakeTimer);updateHandshakeTimer=0;
    const message=buildHeaderMessage("update-data-settled",{flow_id:updateFlow.flow_id,data_failed:updateFlow.data_status==="failed",resume:!!updateFlow.sent});
    if(updateFlow.job_id) message.job_id=updateFlow.job_id;
    frame.contentWindow.postMessage(message,serviceOrigin());
    updateFlow.sent=true;saveUpdateFlow();return true;
  }
  function waitForUpdateHeader(){
    window.clearTimeout(updateHandshakeTimer);
    updateHandshakeTimer=window.setTimeout(()=>{
      updateHandshakeTimer=0;
      if(isUpdateBusy() && !headerReady) finishUpdate("failed","报告更新连接暂不可用；第一步结果已保留。如任务已启动，请在我的活页中核对。");
    },8000);
  }
  async function runPageUpdate(){
    if(isWebAgentPreviewContext() || !pageContext) return;
    if(isUpdateBusy()){ showUpdateTimeline();return; }
    updateFlow={flow_id:"upd_"+Date.now().toString(36)+"_"+Math.random().toString(36).slice(2,10),started_at:Date.now(),data_status:"running",report_status:"waiting",finished:false,sent:false,message:"等待第一步结束"};
    showUpdateTimeline();saveUpdateFlow();renderUpdateTimeline();
    try{
      await runRefresh();updateFlow.data_status="done";
    }catch(e){ updateFlow.data_status="failed"; }
    updateFlow.report_status="checking";updateFlow.message="正在核对报告更新权限";
    saveUpdateFlow();renderUpdateTimeline();
    if(!sendUpdateStart() && !updateFlow.finished){
      ensureHeaderFrame();
      waitForUpdateHeader();
    }
  }
  function acceptUpdateProgress(data){
    if(!updateFlow || updateFlow.finished || data.flow_id!==updateFlow.flow_id || updateFlow.data_status==="running"
      || !/^(checking|queued|running|reconnecting|skipped|succeeded|no_change|failed|cancelled)$/.test(String(data.status || ""))
      || typeof data.message!=="string" || data.message.length>500 || typeof data.finished!=="boolean"
      || (data.job_id!==undefined && (typeof data.job_id!=="string" || !/^[A-Za-z0-9_-]{1,100}$/.test(data.job_id)))) return false;
    const terminal=/^(skipped|succeeded|no_change|failed|cancelled)$/.test(data.status);
    if(data.finished!==terminal) return false;
    if(data.job_id) updateFlow.job_id=data.job_id;
    updateFlow.report_status=data.status;updateFlow.message=data.message;
    if(data.status==="succeeded" && data.reload===true){
      if(!Number.isInteger(data.version_no) || data.version_no<=0 || !updateFlow.job_id){ finishUpdate("failed","发布信息尚未确认，请核对版本");return false; }
      void reloadPublishedUpdate(data.version_no);return true;
    }
    if(terminal) finishUpdate(data.status,data.message);
    else { saveUpdateFlow();renderUpdateTimeline(); }
    return true;
  }
  function captureReadingPosition(){
    const position={y:Number(window.scrollY || 0),anchor:"",offset:0};
    if(typeof document.querySelectorAll==="function") document.querySelectorAll('main h1[id],main h2[id],main h3[id],main section[id],main article[id]').forEach(el=>{
      const top=el.getBoundingClientRect().top;if(top<=80 && el.id){position.anchor=el.id;position.offset=top;}
    });
    return position;
  }
  async function reloadPublishedUpdate(version){
    if(!updateFlow || updateFlow.reloading) return;
    updateFlow.reloading=true;updateFlow.version_no=version;updateFlow.reading=captureReadingPosition();
    updateFlow.message="已发布新版，正在加载当前页面";
    saveUpdateFlow();renderUpdateTimeline();
    // Unique query bypasses the old document cache; init restores the canonical URL.
    const target=new URL(pageContext.pageUrl);target.searchParams.set("_qb_update",String(version)+"_"+updateFlow.flow_id);
    try{ target.hash=new URL(location.href).hash; }catch(e){}
    if(window.location && typeof window.location.replace==="function") window.location.replace(target.href);
    else if(window.location && typeof window.location.reload==="function") window.location.reload();
  }
  function restoreUpdateFlow(){
    if(!pageContext || isWebAgentPreviewContext()) return;
    try{
      const saved=JSON.parse(window.sessionStorage.getItem(updateStorageKey()) || "null");
      if(!saved || saved.page_id!==pageContext.pageId || !/^upd_[A-Za-z0-9_-]{8,100}$/.test(saved.flow_id || "") || !Number.isFinite(saved.started_at) || !Number.isFinite(saved.saved_at) || Date.now()-saved.saved_at>86400000) return;
      updateFlow=saved;
      if(!saved.finished) updateFlow.sent=true;
      if(saved.reloading){
        updateFlow.reloading=false;
        finishUpdate("succeeded",saved.data_status==="failed" ? "报告已更新；第一步刷新失败" : "报告已更新，已加载新版");
        try{ window.history.replaceState(null,"",pageContext.pageUrl+new URL(location.href).hash); }catch(e){}
        let interrupted=false;
        window.addEventListener("wheel",()=>{interrupted=true;},{once:true,passive:true});
        window.addEventListener("touchstart",()=>{interrupted=true;},{once:true,passive:true});
        [0,250,1000].forEach(delay=>window.setTimeout(()=>{
          if(interrupted || !saved.reading || typeof window.scrollTo!=="function") return;
          const anchor=saved.reading.anchor && $(saved.reading.anchor);
          const y=anchor ? window.scrollY+anchor.getBoundingClientRect().top-saved.reading.offset : saved.reading.y;
          if(Number.isFinite(y)) window.scrollTo({top:Math.max(0,y),behavior:"auto"});
        },delay));
        showUpdateTimeline();
      }else if(!saved.finished && saved.data_status==="running") finishUpdate("failed","页面曾在第一步执行期间关闭，请重新点击更新");
      else if(!saved.finished){showUpdateTimeline();renderUpdateTimeline();}
    }catch(e){}
  }
  function warehouseFrame(){ return $("researchWarehouseFrame"); }
  function buildWarehouseHello(context){
    if(!context || !context.pageId) return null;
    return {channel:WAREHOUSE_CHANNEL,type:"hello",page_id:context.pageId};
  }
  function postWarehouseHello(){
    const frame=warehouseFrame(), message=buildWarehouseHello(pageContext);
    if(!frame || !frame.contentWindow || !message) return false;
    frame.contentWindow.postMessage(message,serviceOrigin());
    return true;
  }
  function stopWarehouseHelloRetries(){
    window.clearTimeout(warehouseHelloTimer);
    warehouseHelloTimer=0;
    warehouseHelloAttempts=0;
  }
  function scheduleWarehouseHelloRetries(){
    stopWarehouseHelloRetries();
    const send=()=>{
      if(warehouseReady || warehouseHelloAttempts>=8){ stopWarehouseHelloRetries(); return; }
      warehouseHelloAttempts+=1;
      postWarehouseHello();
      warehouseHelloTimer=window.setTimeout(send,500);
    };
    send();
  }
  function ensureWarehouseFrame(){
    const frame=warehouseFrame();
    if(!frame || !pageContext) return null;
    if(!frame.dataset.qbWarehouseLoadBound){
      frame.addEventListener("load",()=>{ warehouseReady=false; scheduleWarehouseHelloRetries(); });
      frame.dataset.qbWarehouseLoadBound="1";
    }
    if(!frame.src) frame.src=pageContext.embedUrl;
    if(!warehouseReady) scheduleWarehouseHelloRetries();
    return frame;
  }
  function fallbackWarehouseWindow(){
    if(!pageContext) return;
    window.open(pageContext.embedUrl,"_blank","noopener,noreferrer");
  }
  function openWarehouse(){
    const modal=$("researchWarehouseModal");
    if(!pageContext || !modal){ fallbackWarehouseWindow(); return; }
    ensureWarehouseFrame();
    if(warehouseReady) postWarehouseHello();
    else scheduleWarehouseHelloRetries();
    if(!warehouseReady){
      window.clearTimeout(warehouseTimer);
      warehouseTimer=window.setTimeout(()=>{ if(!warehouseReady){ closeWarehouse(); fallbackWarehouseWindow(); } },5000);
    }
    modal.classList.add("open");
    modal.setAttribute("aria-hidden","false");
    document.documentElement.style.overflow="hidden";
  }
  function closeWarehouse(){
    window.clearTimeout(warehouseTimer);
    warehouseTimer=0;
    const modal=$("researchWarehouseModal");
    if(!modal) return;
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden","true");
    document.documentElement.style.overflow="";
    const btn=$("qbHeaderFallbackFavorite") || headerFrame(); if(btn && typeof btn.focus==="function") btn.focus();
  }
  function isTrustedWarehouseMessage(event,frame,context){
    const data=event && event.data;
    return !!(
      frame
      && context
      && event.origin===serviceOrigin()
      && event.source===frame.contentWindow
      && data
      && data.channel===WAREHOUSE_CHANNEL
      && data.page_id===context.pageId
    );
  }
  function onWarehouseMessage(event){
    const frame=warehouseFrame();
    if(!isTrustedWarehouseMessage(event,frame,pageContext)) return;
    const data=event.data;
    warehouseReady=true;
    stopWarehouseHelloRetries();
    window.clearTimeout(warehouseTimer);
    warehouseTimer=0;
    if(data.type==="state" || data.type==="collected") setFavoriteState(data.favorited===true);
    if(data.type==="close") closeWarehouse();
  }
  function authFrame(){ return $("authContinueFrame"); }
  function nextAuthRequestId(){
    return "auth-"+Date.now().toString(36)+"-"+Math.random().toString(36).slice(2,10);
  }
  function buildAuthHello(requestId){
    if(!requestId || !/^[A-Za-z0-9._:-]{1,160}$/.test(requestId)) return null;
    return {channel:AUTH_CHANNEL,type:"hello",request_id:requestId};
  }
  function postAuthHello(){
    const frame=authFrame(), message=buildAuthHello(authRequestId);
    if(!frame || !frame.contentWindow || !message) return false;
    frame.contentWindow.postMessage(message,serviceOrigin());
    return true;
  }
  function stopAuthHelloRetries(){
    window.clearTimeout(authHelloTimer);
    authHelloTimer=0;
    authHelloAttempts=0;
  }
  function scheduleAuthHelloRetries(){
    stopAuthHelloRetries();
    const send=()=>{
      if(authReady || authHelloAttempts>=AUTH_HELLO_MAX_ATTEMPTS){ stopAuthHelloRetries(); return; }
      authHelloAttempts+=1;
      postAuthHello();
      authHelloTimer=window.setTimeout(send,400);
    };
    send();
  }
  function ensureAuthFrame(){
    const frame=authFrame();
    if(!frame || !pageContext) return null;
    if(!frame.dataset.qbAuthLoadBound){
      frame.addEventListener("load",()=>{ authReady=false; scheduleAuthHelloRetries(); });
      frame.dataset.qbAuthLoadBound="1";
    }
    if(!frame.src) frame.src=pageContext.authEmbedUrl;
    scheduleAuthHelloRetries();
    return frame;
  }
  function openAuthenticatedTarget(event,targetUrl){
    if(event && typeof event.preventDefault==="function") event.preventDefault();
    const modal=$("authContinueModal");
    if(!modal || !pageContext) return false;
    pendingAuthenticatedTarget=normalizeOfficialTarget(targetUrl,"/dashboard");
    pendingAuthenticatedTrigger=event && event.currentTarget ? event.currentTarget : null;
    authRequestId=nextAuthRequestId();
    authReady=false;
    ensureAuthFrame();
    modal.classList.add("open");
    modal.setAttribute("aria-hidden","false");
    document.documentElement.style.overflow="hidden";
    return true;
  }
  function closeAuthContinue(restoreFocus){
    stopAuthHelloRetries();
    const modal=$("authContinueModal");
    if(modal){
      modal.classList.remove("open");
      modal.setAttribute("aria-hidden","true");
    }
    document.documentElement.style.overflow="";
    if(restoreFocus!==false && pendingAuthenticatedTrigger && typeof pendingAuthenticatedTrigger.focus==="function") pendingAuthenticatedTrigger.focus();
    pendingAuthenticatedTarget="";
    pendingAuthenticatedTrigger=null;
    authRequestId="";
    authReady=false;
  }
  function isTrustedAuthSource(event,frame){
    const data=event && event.data;
    return !!(
      frame
      && event.origin===serviceOrigin()
      && event.source===frame.contentWindow
      && data
      && data.channel===AUTH_CHANNEL
    );
  }
  function isTrustedAuthReadyMessage(event,frame){
    return !!(isTrustedAuthSource(event,frame) && event.data.type==="ready");
  }
  function isTrustedAuthMessage(event,frame,requestId){
    const data=event && event.data;
    return !!(
      requestId
      && isTrustedAuthSource(event,frame)
      && data.request_id===requestId
    );
  }
  function onAuthMessage(event){
    const frame=authFrame();
    if(isTrustedAuthReadyMessage(event,frame)){
      postAuthHello();
      return;
    }
    if(!isTrustedAuthMessage(event,frame,authRequestId)) return;
    const data=event.data;
    authReady=true;
    stopAuthHelloRetries();
    if(data.type==="close"){
      closeAuthContinue(true);
      return;
    }
    if(data.type==="state" && data.authenticated===true && pendingAuthenticatedTarget){
      const target=resolveNavigationTarget(pendingAuthenticatedTarget);
      closeAuthContinue(false);
      window.location.assign(target);
    }
  }
  function webAgentFrame(){ return $("webAgentFrame"); }
  function buildWebAgentHello(context){
    if(!context || !context.pageId || !context.pageUrl) return null;
    return {channel:WEB_AGENT_CHANNEL,type:"hello",page_id:context.pageId,page_url:context.pageUrl};
  }
  function buildWebAgentAsk(context,request){
    if(!context || !context.pageId || !context.pageUrl || !request) return null;
    const question=String(request.question || "").trim();
    const requestId=String(request.requestId || "");
    if(!question || question.length>4000 || !/^ask_[A-Za-z0-9_-]{8,120}$/.test(requestId)) return null;
    return {channel:WEB_AGENT_CHANNEL,type:"ask",page_id:context.pageId,page_url:context.pageUrl,request_id:requestId,question:question,auto_send:true};
  }
  function nextWebAgentAskId(){
    webAgentAskSequence+=1;
    return "ask_"+Date.now().toString(36)+"_"+webAgentAskSequence.toString(36)+"_"+Math.random().toString(36).slice(2,10);
  }
  function postPendingWebAgentAsk(){
    const frame=webAgentFrame(), request=pendingWebAgentAsk;
    if(!webAgentReady || !frame || !frame.contentWindow || !request || request.sent) return false;
    const message=buildWebAgentAsk(pageContext,request);
    if(!message) return false;
    frame.contentWindow.postMessage(message,serviceOrigin());
    request.sent=true;
    return true;
  }
  function postWebAgentHello(){
    const frame=webAgentFrame(), message=buildWebAgentHello(pageContext);
    if(!frame || !frame.contentWindow || !message) return false;
    frame.contentWindow.postMessage(message,serviceOrigin());
    return true;
  }
  function stopWebAgentHelloRetries(){
    window.clearTimeout(webAgentHelloTimer);
    webAgentHelloTimer=0;
    webAgentHelloAttempts=0;
  }
  function scheduleWebAgentHelloRetries(){
    stopWebAgentHelloRetries();
    const send=()=>{
      if(webAgentReady || webAgentHelloAttempts>=16){ stopWebAgentHelloRetries(); return; }
      webAgentHelloAttempts+=1;
      postWebAgentHello();
      webAgentHelloTimer=window.setTimeout(send,400);
    };
    send();
  }
  function ensureWebAgentFrame(){
    const frame=webAgentFrame();
    if(!frame || !pageContext) return null;
    if(!frame.dataset.qbWebAgentLoadBound){
      frame.addEventListener("load",()=>{ webAgentReady=false; if(pendingWebAgentAsk) pendingWebAgentAsk.sent=false; scheduleWebAgentHelloRetries(); });
      frame.dataset.qbWebAgentLoadBound="1";
    }
    if(!frame.src) frame.src=pageContext.webAgentEmbedUrl;
    if(!webAgentReady) scheduleWebAgentHelloRetries();
    return frame;
  }
  function isMobileAsk(){
    try{
      if(window.matchMedia) return window.matchMedia("(max-width: 680px)").matches;
      return typeof window.innerWidth==="number" && window.innerWidth<=680;
    }catch(e){ return false; }
  }
  function openWebAgent(event){
    if(event && typeof event.preventDefault==="function") event.preventDefault();
    const modal=$("webAgentModal");
    if(!modal || !pageContext) return false;
    pendingWebAgentTrigger=event && event.currentTarget ? event.currentTarget : null;
    ensureWebAgentFrame();
    if(webAgentReady) postWebAgentHello();
    else scheduleWebAgentHelloRetries();
    modal.classList.add("open");
    modal.setAttribute("aria-hidden","false");
    document.documentElement.style.overflow="hidden";
    return true;
  }
  function askWebAgent(question,event){
    const normalized=String(question || "").trim();
    if(!normalized || normalized.length>4000) return false;
    pendingWebAgentAsk={requestId:nextWebAgentAskId(),question:normalized,sent:false};
    if(!openWebAgent(event)){ pendingWebAgentAsk=null; return false; }
    postPendingWebAgentAsk();
    return {requestId:pendingWebAgentAsk.requestId,queued:true};
  }
  function closeWebAgent(restoreFocus){
    stopWebAgentHelloRetries();
    const modal=$("webAgentModal");
    if(modal){
      modal.classList.remove("open");
      modal.setAttribute("aria-hidden","true");
    }
    document.documentElement.style.overflow="";
    if(restoreFocus!==false && pendingWebAgentTrigger && typeof pendingWebAgentTrigger.focus==="function") pendingWebAgentTrigger.focus();
    pendingWebAgentTrigger=null;
    pendingWebAgentAsk=null;
  }
  function isTrustedWebAgentMessage(event,frame,context){
    const data=event && event.data;
    return !!(
      frame
      && context
      && event.origin===serviceOrigin()
      && event.source===frame.contentWindow
      && data
      && data.channel===WEB_AGENT_CHANNEL
      && data.page_id===context.pageId
    );
  }
  function reloadAfterAgentUpdate(){
    closeWebAgent(false);
    if(typeof state.onAgentPageUpdated==="function"){ state.onAgentPageUpdated(); return; }
    if(window.location && typeof window.location.reload==="function") window.location.reload();
  }
  function onWebAgentMessage(event){
    const frame=webAgentFrame();
    if(!isTrustedWebAgentMessage(event,frame,pageContext)) return;
    const data=event.data;
    if(data.type==="ready"){ webAgentReady=true; stopWebAgentHelloRetries(); postPendingWebAgentAsk(); return; }
    if(data.type==="ask-accepted" && pendingWebAgentAsk && data.request_id===pendingWebAgentAsk.requestId){
      const requestId=pendingWebAgentAsk.requestId;
      pendingWebAgentAsk=null;
      if(typeof window.CustomEvent==="function" && typeof window.dispatchEvent==="function") window.dispatchEvent(new window.CustomEvent("qb:web-agent-ask-accepted",{detail:{requestId:requestId}}));
      return;
    }
    if(data.type==="close"){ closeWebAgent(true); return; }
    if(data.type==="turn-complete"){ void runRefresh(); return; }
    if(data.type==="page-updated") reloadAfterAgentUpdate();
  }
  function openAsk(event){
    if(isMobileAsk()) return openWebAgent(event);
    return openAuthenticatedTarget(event,pageContext ? pageContext.playgroundUrl : OFFICIAL_ORIGIN+"/playground");
  }
  async function generatePoster(){
    const canvas=$("sharePosterCanvas"), img=$("sharePosterImage");
    if(!canvas || !img || !window.QBSharePoster) return;
    setBusy(true); setStatus("生成中");
    try{
      const data = state.getPosterData ? (await state.getPosterData()) : {};
      await window.QBSharePoster.generate(canvas,img,data || {},{
        templateName: callMaybe(state.templateName), title: callMaybe(state.title), subtitle: callMaybe(state.subtitle),
        asof: callMaybe(state.asof), shareUrl: state.shareUrl || location.href,
      });
      setStatus("已生成 PNG 海报");
    }catch(e){ setStatus("生成失败：" + (e && e.message ? e.message : e)); }
    finally{ setBusy(false); }
  }
  function openSharePoster(){
    const modal=$("sharePosterModal"); if(!modal) return;
    modal.classList.add("open"); modal.setAttribute("aria-hidden","false"); generatePoster();
    const btn=$("copyPoster"); if(btn) btn.focus();
  }
  function closeSharePoster(){
    const modal=$("sharePosterModal"); if(!modal) return;
    modal.classList.remove("open"); modal.setAttribute("aria-hidden","true");
  }
  function canvasBlob(canvas){ return new Promise(resolve=>canvas.toBlob(resolve,"image/png",1)); }
  function shareUrl(){ return state.shareUrl || location.href; }
  function ensureCopyLinkButton(){
    if($("copyLink")) return;
    const tools=document.querySelector(".share-tools"); if(!tools) return;
    const btn=document.createElement("button"); btn.className="share-tool"; btn.id="copyLink"; btn.type="button"; btn.textContent="复制链接";
    tools.insertBefore(btn, tools.firstElementChild || null);
  }
  function copyTextFallback(value){
    const input=document.createElement("textarea"); input.value=value; input.setAttribute("readonly",""); input.style.position="fixed"; input.style.left="-9999px";
    document.body.appendChild(input);
    try{ input.select(); if(!document.execCommand("copy")) throw new Error("copy command unavailable"); }
    finally{ input.remove(); }
  }
  async function copyShareLink(){
    const url=shareUrl(), btn=$("copyLink");
    try{
      if(btn) btn.disabled=true;
      if(navigator.clipboard && navigator.clipboard.writeText){ try{ await navigator.clipboard.writeText(url); } catch(e){ copyTextFallback(url); } }
      else copyTextFallback(url);
      setStatus("已复制链接，可直接粘贴分享");
    }catch(e){ setStatus("复制链接受限，请从浏览器地址栏复制"); }
    finally{ if(btn) btn.disabled=false; }
  }
  async function copyPosterImage(){
    const canvas=$("sharePosterCanvas"), btn=$("copyPoster"); if(!canvas) return;
    try{
      if(btn) btn.disabled=true;
      const blob=await canvasBlob(canvas);
      if(!blob || !navigator.clipboard || !window.ClipboardItem) throw new Error("clipboard image unavailable");
      await navigator.clipboard.write([new ClipboardItem({"image/png":blob})]); setStatus("已复制图片，可直接粘贴");
    }catch(e){ setStatus("复制图片受限，可右键预览图复制或下载 PNG"); }
    finally{ if(btn) btn.disabled=false; }
  }
  async function downloadPosterImage(){
    const img=$("sharePosterImage"); if(!img || !img.src) await generatePoster();
    const a=document.createElement("a"); a.href=$("sharePosterImage").src; a.download=(callMaybe(state.title) || document.title || "quantbuddy") + "-分享海报.png";
    document.body.appendChild(a); a.click(); a.remove(); setStatus("已开始下载 PNG");
  }
  function init(opts){
    state=Object.assign({},opts || {}); ensureCopyLinkButton();
    pageContext=derivePageContext(state.pageUrl || location.href);
    restoreUpdateFlow();
    const previewContext=isWebAgentPreviewContext();
    if(pageContext && !previewContext){ ensureHeaderFrame(); ensureWarehouseFrame(); }
    if(isUpdateBusy() && updateFlow.data_status!=="running" && !headerReady) waitForUpdateHeader();
    const fallbackBrand=$("qbHeaderFallbackBrand"), fallbackRefresh=$("qbHeaderFallbackRefresh"), fallbackFavorite=$("qbHeaderFallbackFavorite"), fallbackShare=$("qbHeaderFallbackShare"), fallbackAsk=$("qbHeaderFallbackAsk");
    if(fallbackBrand && !fallbackBrand.dataset.qbBound){ fallbackBrand.addEventListener("click",()=>routeHeaderAction("brand")); fallbackBrand.dataset.qbBound="1"; }
    if(fallbackRefresh && !fallbackRefresh.dataset.qbBound){ fallbackRefresh.addEventListener("click",runPageUpdate); fallbackRefresh.dataset.qbBound="1"; }
    const closeUpdate=$("qbUpdateClose"); if(closeUpdate && !closeUpdate.dataset.qbBound){ closeUpdate.addEventListener("click",closeUpdateTimeline);closeUpdate.dataset.qbBound="1"; }
    if(fallbackFavorite && !fallbackFavorite.dataset.qbBound){ fallbackFavorite.addEventListener("click",openWarehouse); fallbackFavorite.dataset.qbBound="1"; }
    if(fallbackShare && !fallbackShare.dataset.qbBound){ fallbackShare.addEventListener("click",openSharePoster); fallbackShare.dataset.qbBound="1"; }
    if(fallbackAsk && !fallbackAsk.dataset.qbBound){ fallbackAsk.addEventListener("click",openAsk); fallbackAsk.dataset.qbBound="1"; }
    const link=$("copyLink"), copy=$("copyPoster"), down=$("downloadPoster"), close=$("closePoster"), modal=$("sharePosterModal"), warehouseModal=$("researchWarehouseModal"), authModal=$("authContinueModal"), webAgentModal=$("webAgentModal");
    if(link && !link.dataset.qbBound){ link.addEventListener("click",copyShareLink); link.dataset.qbBound="1"; }
    if(copy && !copy.dataset.qbBound){ copy.addEventListener("click",copyPosterImage); copy.dataset.qbBound="1"; }
    if(down && !down.dataset.qbBound){ down.addEventListener("click",downloadPosterImage); down.dataset.qbBound="1"; }
    if(close && !close.dataset.qbBound){ close.addEventListener("click",closeSharePoster); close.dataset.qbBound="1"; }
    if(modal && !modal.dataset.qbBound){ modal.addEventListener("click",e=>{ if(e.target===modal) closeSharePoster(); }); modal.dataset.qbBound="1"; }
    if(warehouseModal && !warehouseModal.dataset.qbBound){ warehouseModal.addEventListener("click",e=>{ if(e.target===warehouseModal) closeWarehouse(); }); warehouseModal.dataset.qbBound="1"; }
    if(authModal && !authModal.dataset.qbBound){ authModal.addEventListener("click",e=>{ if(e.target===authModal) closeAuthContinue(true); }); authModal.dataset.qbBound="1"; }
    if(webAgentModal && !webAgentModal.dataset.qbBound){ webAgentModal.addEventListener("click",e=>{ if(e.target===webAgentModal) closeWebAgent(true); }); webAgentModal.dataset.qbBound="1"; }
    if(!document.documentElement.dataset.qbShareEsc){
      document.addEventListener("keydown",e=>{ if(e.key==="Escape"){ closeSharePoster(); closeWarehouse(); closeAuthContinue(true); closeWebAgent(true); } });
      window.addEventListener("message",e=>{ onHeaderMessage(e); onWarehouseMessage(e); onAuthMessage(e); onWebAgentMessage(e); });
      document.documentElement.dataset.qbShareEsc="1";
    }
  }
  window.QB_SHARE_SHELL_VERSION=VERSION;
  window.QB_SHARE_SHELL_REVISION=REVISION;
  window.QBShareShell={init:init, open:openSharePoster, close:closeSharePoster, refresh:runRefresh, setRefreshBusy:setRefreshBusy, setFavoriteState:setFavoriteState, isWebAgentPreviewContext:isWebAgentPreviewContext, buildHeaderMessage:buildHeaderMessage, isTrustedHeaderMessage:isTrustedHeaderMessage, routeHeaderAction:routeHeaderAction, onHeaderMessage:onHeaderMessage, ensureHeaderFrame:ensureHeaderFrame, normalizeOfficialTarget:normalizeOfficialTarget, derivePageContext:derivePageContext, buildWarehouseHello:buildWarehouseHello, isTrustedWarehouseMessage:isTrustedWarehouseMessage, openWarehouse:openWarehouse, closeWarehouse:closeWarehouse, buildAuthHello:buildAuthHello, isTrustedAuthReadyMessage:isTrustedAuthReadyMessage, isTrustedAuthMessage:isTrustedAuthMessage, openAuthenticatedTarget:openAuthenticatedTarget, closeAuthContinue:closeAuthContinue, buildWebAgentHello:buildWebAgentHello, buildWebAgentAsk:buildWebAgentAsk, isTrustedWebAgentMessage:isTrustedWebAgentMessage, isMobileAsk:isMobileAsk, openWebAgent:openWebAgent, askWebAgent:askWebAgent, closeWebAgent:closeWebAgent};
})();
