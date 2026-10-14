"""Optional presentation metadata. Never queries, validates or changes delivery state."""
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path


def _calendar_date(value):
    """Normalize an existing date; never use creation/capture time as data time."""
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    try:
        if re.fullmatch(r'\d{8}', text):
            return date(int(text[:4]), int(text[4:6]), int(text[6:])).isoformat()
        if re.match(r'^\d{4}-\d{2}-\d{2}(?:$|[T ])', text):
            return date.fromisoformat(text[:10]).isoformat()
        if re.fullmatch(r'\d{10}|\d{13}', text):
            return datetime.fromtimestamp(int(text) / (1000 if len(text) == 13 else 1), timezone.utc).date().isoformat()
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _data_dates(data, depth=0):
    """Read date fields only, with a bounded walk of already-validated results."""
    if depth > 6:
        return []
    if isinstance(data, list):
        if len(data) > 10000:
            return []
        return [d for item in data for d in _data_dates(item, depth + 1)]
    if not isinstance(data, dict):
        return []
    dates = []
    for key in ('date', 'trade_date', 'data_date', 'report_period', 'period', 'as_of', '日期', '报告期'):
        d = _calendar_date(data.get(key))
        if d:
            dates.append(d)
    axis = data.get('dates')
    if isinstance(axis, list) and len(axis) <= 10000:
        dates.extend(d for v in axis if (d := _calendar_date(v)))
    columns, rows = data.get('columns'), data.get('rows')
    if isinstance(columns, list) and isinstance(rows, list) and len(rows) <= 10000:
        indexes = [i for i, name in enumerate(columns) if name in ('date', 'trade_date', 'data_date', 'report_period', '日期', '报告期')]
        for row in rows:
            if isinstance(row, (list, tuple)):
                dates.extend(d for i in indexes if i < len(row) and (d := _calendar_date(row[i])))
    for key in ('range_data', 'last_value', 'last_day_stats', 'last_column_full', 'last_valid_per_asset', 'results', 'fields', 'series', 'data'):
        child = data.get(key)
        if isinstance(child, dict):
            dates.extend(_data_dates(child, depth + 1))
            if key in ('fields', 'series'):
                dates.extend(d for value in child.values() for d in _data_dates(value, depth + 1))
        elif isinstance(child, list):
            dates.extend(_data_dates(child, depth + 1))
    return dates


def _fixed_date(panel, spec):
    for value in (panel.get('analysis_date'),):
        if d := _calendar_date(value):
            return d, 'analysis'
    for value in (panel.get('data_date'), panel.get('as_of')):
        if d := _calendar_date(value):
            return d, 'as_of'
    # Explicit date captions already present in the module are usable evidence.
    text = '\n'.join(str(panel.get(k) or '') for k in ('title', 'text', 'caption'))
    for pattern, kind in ((r'(?:分析日|研究日期|历史解读)\s*[：:]?\s*(\d{4}-\d{2}-\d{2})', 'analysis'),
                          (r'(?:数据截至|数据日期)\s*[：:]?\s*(\d{4}-\d{2}-\d{2})', 'as_of')):
        dates = {d for match in re.finditer(pattern, text) if (d := _calendar_date(match[1]))}
        if len(dates) == 1:
            return dates.pop(), kind
        if len(dates) > 1:
            return None, None
    if d := _calendar_date(spec.get('analysis_date')):
        return d, 'analysis'
    return None, None


def enabled(spec):
    return (os.environ.get('QBV_DATA_LABELS', '1').strip().lower() not in ('0', 'false', 'off')
            and spec.get('data_labels') is not False)


def prepare(spec, panels, *, output_names, verified_outputs, live_outputs, snapshots):
    """Called only after the existing build-time data checks; work on copies."""
    if not enabled(spec):
        return panels, {'enabled': False, 'modules': [], 'warnings': []}
    result, modules = [], []
    for index, panel in enumerate(panels):
        p = dict(panel)
        p.pop('_qb_data_label', None)
        names = list(output_names(p))
        kind = p.get('type', 'table')
        mode, reason = 'unknown', 'evidence_unavailable'
        # Bound prose mixes fixed interpretation with changing numbers. Do not
        # upgrade the interpretation, or a fixed image, because it has an output.
        if kind == 'text' and (p.get('binding') or p.get('date_binding')):
            reason = 'mixed_prose'
        elif kind in ('text', 'image') and not names:
            mode, reason = 'snapshot', 'fixed_content'
        elif kind not in ('text', 'image') and names:
            valid = all(isinstance(verified_outputs.get(n), dict)
                        and not verified_outputs[n].get('error')
                        and verified_outputs[n].get('data') is not None for n in names)
            if valid and all(n in snapshots for n in names):
                mode, reason = 'snapshot', 'verified_snapshot'
            elif valid and all(n in live_outputs and n not in snapshots for n in names):
                mode, reason = 'live', 'verified_runtime_binding'
        label = {'mode': mode, 'reason': reason, 'outputs': names, 'kind': kind}
        if mode == 'snapshot':
            if reason == 'verified_snapshot':
                dates = [d for name in names for d in _data_dates(verified_outputs[name]['data'])]
                label_date, date_kind = (max(dates), 'as_of') if dates else (None, None)
            else:
                label_date, date_kind = _fixed_date(p, spec)
            if label_date:
                label.update(date=label_date, date_kind=date_kind)
        p['_qb_data_label'] = label
        result.append(p)
        modules.append({'index': index, 'mode': mode, 'reason': reason})
    return result, {'enabled': True, 'modules': modules, 'warnings': []}


def runtime_source():
    return (Path(__file__).resolve().parents[1] / 'assets' / 'data-labels.js').read_text(encoding='utf-8')


def file_caption(params):
    """Only the generated image/PDF carrier; never touch source HTML."""
    if not enabled(params):
        return ''
    label_date, kind = _fixed_date(params, {})
    caption = 'Snapshot'
    if label_date:
        caption += ' · ' + ('分析日 ' if kind == 'analysis' else '截至 ') + label_date
    return ('<figcaption style="font:12px/1.5 sans-serif;color:#475569;padding:4px 8px">'
            '<span data-qb-data-label="snapshot" title="固定文件快照；不会自动更新" '
            'style="display:inline-block;font-weight:500;padding:1px 6px;border-radius:3px;'
            'color:#77596d;background:#ece3e9">' + caption + '</span> · 固定文件快照</figcaption>')
