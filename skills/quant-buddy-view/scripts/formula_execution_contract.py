"""Actual QBS execution evidence, independent of Formula Package read support.

Vendored identically in QBS/QBV. Never infer reads or runtime eligibility here.
"""
import hashlib
import json

SCHEMA = 'qbs_formula_execution_contract_v1'


def normalize_execution_contract(value):
    if not isinstance(value, dict) or value.get('schema_version') != SCHEMA:
        raise ValueError('invalid_execution_contract_schema')
    formulas = value.get('formulas')
    if not isinstance(formulas, list) or not formulas or any(not isinstance(f, str) or not f.strip() for f in formulas):
        raise ValueError('invalid_execution_formulas')
    result = {'schema_version': SCHEMA, 'formulas': list(formulas)}
    for name in ('use_minute_data', 'include_description'):
        flag = value.get(name, False)
        if type(flag) is not bool:
            raise ValueError('invalid_execution_' + name)
        result[name] = flag
    reusable = value.get('force_reusable_array', [])
    if not isinstance(reusable, list) or any(not isinstance(x, str) or not x.strip() for x in reusable):
        raise ValueError('invalid_execution_reusable')
    result['force_reusable_array'] = list(dict.fromkeys(reusable))
    if value.get('begin_date') is not None:
        date = value['begin_date']
        if type(date) not in (int, str):
            raise ValueError('invalid_execution_begin_date')
        result['begin_date'] = date
    digest = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':')).encode('utf-8')).hexdigest()
    result['contract_fingerprint'] = 'sha256:' + digest
    supplied = value.get('contract_fingerprint')
    if supplied is not None and supplied != result['contract_fingerprint']:
        raise ValueError('execution_contract_fingerprint_mismatch')
    return result


def execution_contracts_from_receipts(receipts, runtime=None):
    contracts = []
    seen = set()
    for receipt in receipts or []:
        if not isinstance(receipt, dict) or receipt.get('execution_contract') is None:
            continue
        contract = normalize_execution_contract(receipt['execution_contract'])
        if contract['contract_fingerprint'] not in seen:
            contracts.append(contract)
            seen.add(contract['contract_fingerprint'])
        if runtime and runtime.get('formulas') == contract['formulas']:
            for field in ('use_minute_data', 'include_description', 'begin_date', 'force_reusable_array'):
                default = False if field in ('use_minute_data', 'include_description') else ([] if field == 'force_reusable_array' else None)
                if runtime.get(field, default) != contract.get(field, default):
                    raise ValueError('execution_runtime_mismatch:' + field)
    return contracts
