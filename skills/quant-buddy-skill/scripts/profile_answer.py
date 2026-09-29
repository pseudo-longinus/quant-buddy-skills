"""Project profile financial facts into a complete table without another query."""

import copy
import math


VARIANTS = (
    ('quarter_level', '单季'), ('quarter_yoy', '单季同比'),
    ('quarter_qoq', '单季环比'), ('period_yoy', '同比'),
    ('period_qoq', '环比'), ('ttm_level', 'TTM'), ('ttm_yoy', 'TTM同比'),
    ('annual_level', '年度'), ('annual_yoy', '年度同比'),
)


def _cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def _number(value):
    # Descriptions, missing values and boolean flags are not financial amounts.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return str(value)


def _date(value):
    text = str(value or '')
    return f'{text[:4]}-{text[4:6]}-{text[6:]}' if len(text) == 8 and text.isdigit() else text or '未返回'


def attach_financial_table(result):
    """Keep raw evidence intact; add a factual table to successful JSON profiles."""
    if not isinstance(result, dict) or result.get('code', 0) != 0 or result.get('success') is False:
        return result
    data = result.get('data', result)
    if not isinstance(data, dict) or data.get('success') is False:
        return result
    dimensions = data.get('dimensions')
    if not isinstance(dimensions, dict):
        return result
    finance = dimensions.get('财务分析')
    if not isinstance(finance, dict) or not isinstance(finance.get('indicators'), dict):
        return result
    rows, refs = [], []
    for key, item in finance['indicators'].items():
        if not isinstance(item, dict):
            continue
        unit = item.get('unit', finance.get('unit', '')) or ''
        date = item.get('latest_date', finance.get('latest_date'))
        values, dates = [], {}

        def add(label, value, field_unit, field_date, ref):
            number = _number(value)
            if number is None:
                return
            values.append(f'{label}：{number}{_cell(field_unit)}')
            dates.setdefault(_cell(_date(field_date)), []).append(label)
            refs.append(f'dimensions.财务分析.indicators.{key}.{ref}')

        add('最新值', item.get('latest_value'), unit, date, 'latest_value')
        add('上一有效值', item.get('previous_value'), unit, item.get('previous_date'), 'previous_value')
        variants = item.get('variants')
        if isinstance(variants, dict):
            for variant_key, label in VARIANTS:
                variant = variants.get(variant_key)
                if not isinstance(variant, dict):
                    continue
                # Level variants inherit the amount/ratio unit. Change-rate
                # variants must never inherit 元 from a cash-flow parent.
                fallback_unit = unit if variant_key.endswith('_level') else ''
                variant_unit = variant.get('unit', fallback_unit) or ''
                add(label, variant.get('value'), variant_unit,
                    variant.get('date', date), f'variants.{variant_key}.value')
        if values:
            grouped_dates = [f"{'、'.join(labels)} {date}" for date, labels in dates.items()]
            rows.append(f"| {_cell(item.get('name') or key)} | {'；'.join(values)} | {'；'.join(grouped_dates)} |")
    if not rows:
        return result
    result = copy.deepcopy(result)
    target = result.get('data', result)
    target['answer_financial_table'] = {
        'schema_version': 'profile_financial_table_v1',
        'markdown': '\n'.join(['| 指标 | 可核验数据 | 数据日期 |', '|---|---|---|', *rows]),
        'field_refs': refs,
        'notes': '同比/环比变体未标注单位时按原值显示，不继承金额单位；增速指标自身的变动不等于营收或利润同比。',
    }
    return result
