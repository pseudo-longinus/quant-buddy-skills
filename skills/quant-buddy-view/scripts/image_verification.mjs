export function staticImageProblems(html) {
  const text = String(html || '');
  const problems = [];
  if (/__QB_IMAGE_[A-Z0-9_]+__/.test(text)) problems.push('图片 marker 残留');
  if (/(?:<img\b[^>]*\bsrc\s*=\s*["']|url\(\s*["']?)http:\/\//i.test(text)) problems.push('图片 URL 禁止使用 http://');
  const imageTags = text.match(/<img\b[^>]*>/gi) || [];
  const hasRuntimeSrcContract = tag => /(?:^|\s)data-qb-runtime-src(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>"']+))?(?=\s|\/?>)/i.test(tag);
  if (imageTags.some(tag => (
    !/\bsrc\s*=\s*(?:"[^"]+"|'[^']+'|[^\s>"']+)/i.test(tag)
    && !hasRuntimeSrcContract(tag)
  ))) {
    problems.push('img 必须带非空 src；运行时赋值的预览图必须声明 data-qb-runtime-src');
  }
  return problems;
}

export function imageElementProblems(images = []) {
  return images
    .filter(image => !/^data:image\//i.test(String(image.src || '')))
    .filter(image => image.complete !== true || Number(image.naturalWidth || 0) <= 0)
    .map(image => ({ src: String(image.src || ''), complete: !!image.complete, naturalWidth: Number(image.naturalWidth || 0) }));
}
