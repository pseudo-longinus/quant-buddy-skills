// Finite declarative bindings; never evaluate generated JavaScript or HTML.
function resolveBoundProse(binding, outputs) {
  const read = (value, path) => (path || []).reduce((node, key) =>
    node != null && !['__proto__', 'constructor', 'prototype'].includes(String(key)) && Object.hasOwn(node, key) ? node[key] : undefined, value);
  const values = Object.create(null), tokens = Object.create(null);
  for (const [name, ref] of Object.entries(binding.values || {})) {
    const output = outputs[ref.output];
    if (!output || output.error) throw new Error(`缺少有效产出：${name}`);
    const value = read(output.data, ref.path);
    const date = read(output.data, ref.as_of_path);
    if (value == null || !['string', 'number'].includes(typeof value) || value === '' ||
        (typeof value === 'number' && !Number.isFinite(value)) || date == null || date === '') throw new Error(`字段或观察日缺失：${name}`);
    values[name] = value;
    tokens[name] = typeof value === 'number' && Number.isInteger(ref.decimals) ? value.toFixed(ref.decimals) : String(value);
    tokens[`${name}.as_of`] = String(date);
    tokens[`${name}.unit`] = ref.unit || '';
  }
  let text = String(binding.template || '');
  const operators = { gt: (a,b)=>a>b, gte: (a,b)=>a>=b, lt: (a,b)=>a<b, lte: (a,b)=>a<=b, eq: (a,b)=>a===b };
  for (const rule of binding.conditions || []) {
    const left = values[rule.left], right = typeof rule.right === 'number' ? rule.right : values[rule.right];
    if (typeof left !== 'number' || typeof right !== 'number' || !Number.isFinite(right) || !operators[rule.op]) throw new Error('条件比较需要有效数值');
    text += '\n' + (operators[rule.op](left, right) ? rule.then : rule.else);
  }
  return text.replace(/\{\{([^{}]+)\}\}/g, (_, key) => {
    if (!Object.hasOwn(tokens, key.trim())) throw new Error(`未知绑定：${key}`);
    return tokens[key.trim()];
  });
}
