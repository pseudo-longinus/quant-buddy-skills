// Public-page contract guards for host-only WebAgent Preview context.
const META_RE = /<meta\b(?=[^>]*\bname\s*=\s*(["'])qb-live-page-embed-context\1)(?=[^>]*\bcontent\s*=\s*(["'])webagent-preview\2)[^>]*>/gi;
const STYLE_RE = /<style\b(?=[^>]*\bid\s*=\s*(["'])qb-preview-shell-visibility\1)[^>]*>/gi;

export function publicPreviewContextProblems(html) {
  const text = String(html || '');
  const problems = [];
  if (META_RE.test(text)) problems.push('公开活页禁止携带 qb-live-page-embed-context=webagent-preview meta');
  META_RE.lastIndex = 0;
  if (STYLE_RE.test(text)) problems.push('公开活页禁止携带 qb-preview-shell-visibility 样式');
  STYLE_RE.lastIndex = 0;
  return problems;
}

export function shareShellHeaderProblems(header) {
  if (!header || header.checked !== true) return ['Share Shell 页头运行态检查未执行'];
  if (header.present !== true) return [];
  const fallback = header.fallback || {};
  if (fallback.visible) {
    if (!fallback.hostVisible || Number(fallback.buttonCount || 0) < 2) {
      return ['Share Shell 兜底页头不可见或操作入口不足'];
    }
    return [];
  }
  const frame = header.iframe || {};
  if (!frame.src || /^about:blank$/i.test(frame.src)) return ['Share Shell 官网页头 iframe 未加载'];
  if (!frame.officialUrl) return ['Share Shell 官网页头 iframe 地址无效'];
  if (!frame.paramsValid) return ['Share Shell 官网页头 iframe 参数与当前页面不匹配'];
  if (!frame.visible || Number(frame.height || 0) < 40 || Number(frame.width || 0) <= 0) {
    return ['Share Shell 官网页头 iframe 不可见'];
  }
  if (Number(frame.httpStatus || 0) < 200 || Number(frame.httpStatus || 0) >= 400) {
    return ['Share Shell 官网页头 iframe 响应异常'];
  }
  if (frame.readyStateAvailable === true && frame.ready !== true) {
    return ['Share Shell 官网页头未完成 ready 握手'];
  }
  return [];
}
