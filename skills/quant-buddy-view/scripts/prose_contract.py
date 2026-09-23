"""Validate the finite text binding language before embedding it in a page."""
import math
import re


def validate(panels):
    for panel in panels:
        binding = panel.get('binding')
        if binding is None:
            continue
        try:
            if panel.get('type') != 'text' or not isinstance(binding, dict):
                raise ValueError('binding仅用于text面板')
            values = binding.get('values')
            if not isinstance(values, dict) or not values:
                raise ValueError('values必须是非空对象')
            for name, ref in values.items():
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', name) or not isinstance(ref, dict):
                    raise ValueError('绑定名称或引用无效')
                if not isinstance(ref.get('output'), str) or not ref['output']:
                    raise ValueError('必须引用真实output')
                for key in ('path', 'as_of_path'):
                    path = ref.get(key)
                    if not isinstance(path, list) or not path or any(
                        not isinstance(p, (str, int)) or isinstance(p, bool)
                        or str(p) in ('__proto__', 'constructor', 'prototype') for p in path):
                        raise ValueError('path/as_of_path需要安全的字段路径数组')
                if 'decimals' in ref and (type(ref['decimals']) is not int or not 0 <= ref['decimals'] <= 10):
                    raise ValueError('decimals范围为0到10')
            templates = [binding['template']]
            for rule in binding.get('conditions', []):
                if rule.get('left') not in values or rule.get('op') not in ('gt', 'gte', 'lt', 'lte', 'eq'):
                    raise ValueError('条件左值或操作符无效')
                right = rule.get('right')
                if not (isinstance(right, str) and right in values) and not (type(right) in (int, float) and math.isfinite(right)):
                    raise ValueError('条件右值必须是绑定名称或有限数字')
                templates.extend([rule['then'], rule['else']])
            tokens = {n + suffix for n in values for suffix in ('', '.as_of', '.unit')}
            if any(not isinstance(t, str) or any(k.strip() not in tokens for k in re.findall(r'\{\{([^{}]+)\}\}', t)) for t in templates):
                raise ValueError('模板含未知绑定')
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            return {'code': 1, 'error': 'PROSE_BINDING_INVALID', 'message': str(error), 'panel': panel.get('title')}
    return None
