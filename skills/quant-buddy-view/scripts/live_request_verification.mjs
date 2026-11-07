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
    result.output_count=outputs.filter(o=>typeof o?.output==='string' && o.data && !rejected(o)).length;
    result.business_ok=!failure && result.output_count>0 && result.output_count===outputs.length;
  } catch { /* Malformed or unreadable evidence stays unsuccessful. */ }
  return result;
}

export function liveRequestProblems(requests, runtime) {
  if (!requests?.length) return ['LIVE_DATA_REQUEST_MISSING: 页面未实际请求实时数据'];
  const problems=[];
  if (requests.some(r=>r.business_ok!==true)) problems.push('LIVE_DATA_REQUEST_FAILED: 实时请求未完成业务成功核验');
  if (!runtime || runtime.status!=='ready' || runtime.pending!==0) problems.push('LIVE_RENDER_NOT_READY: 实时数据未完成页面渲染');
  return problems;
}
