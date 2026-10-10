"""Validate the finite text binding language before embedding it in a page."""
import math
import re

def coverage_errors(text):
    """Check explicit same-sentence count/percentage arithmetic, not prose intent."""
    pattern=r'覆盖[^。\n]{0,12}?([\d,]+)\s*[/／]\s*([\d,]+)[^。\n]{0,45}?(?:(缺失|覆盖率)[^。\n\d]{0,8}(\d+(?:\.\d+)?)\s*[%％]|(\d+(?:\.\d+)?)\s*[%％]\s*(缺失))'
    for matched in re.finditer(pattern,str(text)):
        used,total=int(matched[1].replace(',','')),int(matched[2].replace(',',''))
        if total <= 0 or used > total: return {'code':1,'error':'PROSE_COVERAGE_INVALID'}
        metric=matched[3] or matched[6];percent=matched[4] or matched[5]
        expected=100*(1-used/total if metric=='缺失' else used/total)
        if abs(expected-float(percent)) > 1:
            return {'code':1,'error':'PROSE_COVERAGE_CONFLICT','message':'覆盖数量与同句比例不一致','expected_percent':round(expected,2)}
    return None


def research_claim_errors(text, status):
    if status is None or status == 'complete': return None
    pattern=r'完全符合|全部符合|符合全部条件|通过全部(?:硬)?条件|满足(?:全部|所有)(?:硬)?条件|全部条件均(?:满足|符合)|完整(?:研究|筛选)已完成|(?:仅|只)差[^。\n]{0,25}(?:一项|该项|承接|条件)|唯一短板|符合(?:上述|筛选)?条件(?:的股票)?\s*(?:为|有|共)?\s*[:：]?\s*(?:0|零)\s*只'
    body=re.sub(r'[*_`]', '',str(text))
    for match in re.finditer(pattern,body):
        prefix=re.split(r'[。\n；]',body[:match.start()])[-1][-35:]
        if re.search(r'(?:不能|不得|不应|不代表|不表示|无法|禁止)[^。\n；，、,:：]{0,18}$|尚未\s*$',prefix): continue
        return {'code':1,'error':'RESEARCH_COMPLETENESS_CLAIM_CONFLICT','message':'研究未完整核验，不能宣称全部符合或完整零命中；展示已核验证据与缺口。'}
    return None

def validate(panels, research_status=None):
    has_runtime = any(p.get('type') not in ('text','image') and not p.get('snapshot_receipt_file') for p in panels)
    for panel in panels:
        error=research_claim_errors(str(panel.get('title',''))+'\n'+str(panel.get('text','')),research_status)
        if error: return {**error,'panel':panel.get('title')}
        error=coverage_errors(panel.get('text',''))
        if error: return {**error,'panel':panel.get('title')}
        if (has_runtime and panel.get('type') == 'text' and not panel.get('binding') and not panel.get('date_binding')
                and panel.get('as_of_mode') != 'historical'
                and re.search(r'当前最新|今日.*(?:未发布|尚未)|20\d{2}-\d{2}-\d{2}.*尚未发布', panel.get('text',''))):
            return {'code':1,'error':'PROSE_ASOF_BINDING_REQUIRED','message':'实时可评估日期正文须绑定同轮输出，固定历史分析标注as_of_mode=historical','panel':panel.get('title')}

        date_binding = panel.get('date_binding')
        if date_binding is not None:
            if (panel.get('type') != 'text' or not isinstance(date_binding, dict)
                    or not isinstance(date_binding.get('outputs'), list) or not date_binding['outputs']
                    or not all(isinstance(name, str) and name for name in date_binding['outputs'])):
                return {'code': 1, 'error': 'PROSE_DATE_BINDING_INVALID', 'message': '日期正文需绑定真实outputs'}
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
