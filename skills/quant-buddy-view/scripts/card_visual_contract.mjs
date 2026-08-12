const GENERIC_COPY = [
  '实时活卡',
  '核心输出实时刷新',
  '打开即取最新',
];


function visibleTemplateText(template) {
  return String(template || '')
    .replace(/<style\b[\s\S]*?<\/style>/gi, ' ')
    .replace(/<script\b[\s\S]*?<\/script>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/\s+/g, ' ')
    .trim();
}

function attributeValue(template, name) {
  const match = String(template || '').match(new RegExp(`\\b${name}\\s*=\\s*["']([^"']+)["']`, 'i'));
  return match ? match[1].trim() : '';
}


export function cardVisualContractProblems(template, manifest, options = {}) {
  if (!options.strict) return [];
  const problems = [];
  const source = String(template || '');
  const visibleText = visibleTemplateText(source);
  const templateKind = attributeValue(source, 'data-qb-card-visual-kind');
  const manifestKind = String(manifest?.visual_kind || '').trim();

  if (!templateKind) problems.push('card template 缺少 data-qb-card-visual-kind 显式视觉类型');
  if (!manifestKind) problems.push('card manifest 缺少 visual_kind');
  if (templateKind && manifestKind && templateKind !== manifestKind) {
    problems.push(`card visual_kind 不一致: template=${templateKind}, manifest=${manifestKind}`);
  }

  const genericCopyHits = GENERIC_COPY.filter(text => visibleText.includes(text));
  if (genericCopyHits.length) problems.push(`card template 含通用文案: ${genericCopyHits.join(', ')}`);

  const rawOutputHits = (Array.isArray(manifest?.required_outputs) ? manifest.required_outputs : [])
    .map(value => String(value || '').trim())
    .filter(value => value && visibleText.toLowerCase().includes(value.toLowerCase()));
  if (rawOutputHits.length) problems.push(`card template 把原始 output key 当作可见文案: ${rawOutputHits.join(', ')}`);

  if (templateKind === 'numeric-focus') {
    if (!/\bdata-qb-card-numeric-focus\b/i.test(source)) {
      problems.push('numeric-focus 缺少 data-qb-card-numeric-focus 主数字标记');
    }
  } else if (templateKind && !/\bdata-qb-card-visual\b/i.test(source)) {
    problems.push('visual-focus 卡片缺少 data-qb-card-visual 主视觉标记');
  }

  const miniMetricCount = (source.match(/\bqb-mini-metric\b/gi) || []).length;
  if (miniMetricCount >= 2) {
    problems.push('card template 仍是重复 qb-mini-metric 矩形，缺少页面专属主视觉');
  }
  return problems;
}
