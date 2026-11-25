// Browser-observed data evidence. Never persist URLs, request bodies or payloads.
export function liveAction(url) {
  try { return new URL(url).pathname.match(/\/(queryFormulaPackage|queryDataGrant)\/?$/)?.[1] || null; }
  catch { return null; }
}

function rejected(value) {
  if (!value || typeof value !== 'object') return true;
  if (value.success === false || value.error || (value.code !== undefined && value.code !== 0)) return true;
  return value.data && !Array.isArray(value.data) && typeof value.data === 'object' ? rejected(value.data) : false;
}

export function truncatedFullColumn(outputEntry) {
  if (!outputEntry || typeof outputEntry !== 'object') return false;
  const mode = String(outputEntry.read_mode || '').trim();
  const raw = outputEntry.data;
  const section = raw && typeof raw === 'object'
    ? (raw.last_column_full && typeof raw.last_column_full === 'object'
        ? raw.last_column_full
        : (mode === 'last_column_full' ? raw : null))
    : null;
  return !!(section && section.is_truncated === true);
}

export function liveResponse(action, http, body) {
  const result={action,http,business_ok:false,output_count:0};
  if (!(http >= 200 && http < 300)) return result;
  try {
    if (action === 'queryDataGrant') {
      const value=JSON.parse(body);
      result.business_ok=value.code === 0 && !!value.data && typeof value.data === 'object' && !rejected(value);
      return result;
    }
    const outputs=[];let failure=false;
    if (/^\s*[\[{]/.test(body)) {
      const value=JSON.parse(body);
      if (rejected(value)) return result;
      outputs.push(...(Array.isArray(value)?value:Array.isArray(value.outputs)?value.outputs:[value]));
    } else {
      for (const block of body.replace(/\r\n/g,'\n').split(/\n\n/)) {
        const event=block.match(/^event:\s*(\S+)/m)?.[1];
        const lines=block.split('\n').filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trimStart());
        if (!event || !lines.length) continue;
        const value=JSON.parse(lines.join('\n'));
        if (event==='error' || rejected(value)) failure=true;
        if (event==='result') outputs.push(value);
      }
    }
    const truncatedCount=outputs.filter(truncatedFullColumn).length;
    if (truncatedCount > 0) result.truncated_count=truncatedCount;
    result.output_count=outputs.filter(o=>typeof o?.output==='string' && o.data && !rejected(o)).length;
    result.business_ok=!failure && truncatedCount===0 && result.output_count>0 && result.output_count===outputs.length;
  } catch { /* Malformed or unreadable evidence stays unsuccessful. */ }
  return result;
}

export function liveRequestProblems(requests, runtime) {
  if (!requests?.length) return ['LIVE_DATA_REQUEST_MISSING: 页面未实际请求实时数据'];
  const problems=[];
  if (requests.some(r=>Number(r.truncated_count)>0)) {
    problems.push('LIVE_DATA_TRUNCATED: 公式包 last_column_full 返回被后端截断（is_truncated=true），请省略或调大 max_rows 并核查 allow_zero_values');
  }
  if (requests.some(r=>r.business_ok!==true && !(Number(r.truncated_count)>0))) {
    problems.push('LIVE_DATA_REQUEST_FAILED: 实时请求未完成业务成功核验');
  }
  if (!runtime || runtime.status!=='ready' || runtime.pending!==0) problems.push('LIVE_RENDER_NOT_READY: 实时数据未完成页面渲染');
  return problems;
}
// Policy is constructed by the Python publisher from signed server proofs, not page JS.
// The loopback exception is exclusively for offline fixture endpoints (never returned by the service).
export function bindingPolicy(value) {
  const endpoint=new URL(value.endpoint);
  if (!(endpoint.protocol==='https:' || endpoint.protocol==='http:' && ['127.0.0.1','localhost','[::1]'].includes(endpoint.hostname)) || endpoint.username || endpoint.password || endpoint.search || endpoint.hash || endpoint.pathname!=='/skill') throw Error('INVALID_MANAGED_ENDPOINT');
  const ids=new Set();
  if (!Array.isArray(value.bindings) || !value.bindings.length || value.bindings.length>100) throw Error('INVALID_MANAGED_BINDINGS');
  for (const {resource,credential_id:id} of value.bindings) {
    if (!(resource==='grant' && /^(?:dg|grant)_[\w.-]+$/.test(id) || resource==='package' && /^pkg_[\w.-]+$/.test(id))) throw Error('INVALID_MANAGED_BINDINGS');
    ids.add(id);
  }
  const required=value.required_ids || [];
  if (!Array.isArray(required) || required.some(id=>!ids.has(id))) throw Error('INVALID_MANAGED_BINDINGS');
  return {base:endpoint.href,ids,required};
}

export function requestBinding(policy,url,method,postData) {
  const action=liveAction(url);
  if(!policy || !action) return null;
  const dest=new URL(url), key=action==='queryDataGrant'?'grant_id':'package_id';
  if (dest.origin+dest.pathname !== policy.base+'/'+action || dest.username || dest.password) return {action,denied:true};
  if (method==='OPTIONS') return {action,preflight:true};
  if (method!=='POST') return {action,denied:true};
  let id;
  try {
    const data=String(postData || '');
    if (data.trimStart().startsWith('{')) id=JSON.parse(data)[key];
    else {const values=new URLSearchParams(data).getAll(key);if(values.length===1) id=values[0];}
  } catch { /* fail closed; never log the body */ }
  return typeof id==='string' && policy.ids.has(id) && (key==='package_id')===id.startsWith('pkg_') ? {action,credential_id:id} : {action,denied:true};
}

export function bindingProblems(policy,requests,requireLive) {
  if (!policy) return [];
  if (requests.some(x=>x.denied)) return ['LIVE_BINDING_MISMATCH: 请求地址或授权不属于当前任务'];
  const observed=new Set(requests.filter(x=>x.business_ok===true).map(x=>x.credential_id));
  if (requireLive && policy.required.some(id=>!observed.has(id))) return ['LIVE_BINDING_NOT_OBSERVED: 计划要求的授权未全部成功取数'];
  if (requireLive && !requests.some(x=>x.business_ok && policy.ids.has(x.credential_id))) return ['LIVE_BINDING_NOT_OBSERVED: 未观察到已核验授权成功取数'];
  return [];
}
