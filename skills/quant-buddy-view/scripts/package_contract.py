"""Canonical published formula contract, distinct from QBS execution receipts."""
import copy
import re
from datetime import datetime

DEFAULT_BEGIN_DATE = 20150101
READ_MODES = frozenset({'last_day_stats', 'last_column_full', 'range_data', 'last_valid_per_asset'})


def normalize(value):
    formulas = value.get('formulas')
    reads = value.get('reads', [])
    if not isinstance(formulas, list) or not formulas or not all(isinstance(f, str) and f.strip() for f in formulas):
        raise ValueError('formulas must be a nonempty string array')
    if not isinstance(reads, list):
        raise ValueError('reads must be an array')
    from fork_runtime_contract import formula_output
    outputs = {output.strip() for f in formulas for output in re.split('[,，]', formula_output(f))}
    seen = set()
    for read in reads:
        if not isinstance(read, dict) or read.get('output') not in outputs or read.get('read_mode') not in READ_MODES:
            raise ValueError('reads must reference formula outputs using a supported read_mode')
        if read['output'] in seen:
            raise ValueError('duplicate read output')
        seen.add(read['output'])
        params = read.get('mode_params', {})
        if not isinstance(params, dict):
            raise ValueError('mode_params must be an object')
        if 'date' in params and 'offset' in params:
            raise ValueError('mode_params date and offset are mutually exclusive')
        if read['read_mode'] == 'range_data' and (type(params.get('lookback_days')) is not int or params['lookback_days'] < 1):
            raise ValueError('range_data requires positive integer lookback_days')
    date = value.get('begin_date')
    if date is None or date == '':
        date = DEFAULT_BEGIN_DATE
    if isinstance(date, bool):
        raise ValueError('begin_date must be YYYYMMDD')
    date = int(str(date).strip())
    datetime.strptime(str(date), '%Y%m%d')
    if not 20050104 <= date <= 20991231:
        raise ValueError('begin_date outside supported range')
    return {'formulas': list(formulas), 'reads': copy.deepcopy(reads), 'begin_date': date}
