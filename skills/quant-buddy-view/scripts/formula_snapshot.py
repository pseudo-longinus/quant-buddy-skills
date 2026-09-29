"""Materialize only output IDs bound by successful QBS package validation."""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
import common as C
import execution_plan as EP
import runtime_credentials as RC
import reply_data_evidence as RDE


def read_qbs(task, params):
    path = C.task_temp_path(task, 'snapshot-read-params.json', create_parent=True)
    EP.atomic_json(path, params)
    command = [sys.executable, str(Path(__file__).with_name('qbs_bridge.py')), 'readData', '@' + str(path)]
    try:
        result = subprocess.run(command, capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        raise EP.PlanError('SNAPSHOT_READ_FAILED', 'QBS读取超时或不可用，保留原验证合同')
    try: response = json.loads(result.stdout.decode('utf-8-sig'))
    except (ValueError, UnicodeError): raise EP.PlanError('SNAPSHOT_READ_FAILED', 'QBS读取未返回有效结果')
    if result.returncode or not isinstance(response, dict) or response.get('code') != 0:
        raise EP.PlanError('SNAPSHOT_READ_FAILED', 'QBS读取失败，保留原验证合同')
    return response


def materialize(task, proof_file, proof):
    import verified_snapshot as VS
    import build_dashboard as BD
    contract = proof.get('contract')
    if not isinstance(contract, dict) or not contract.get('reads'):
        raise EP.PlanError('SNAPSHOT_VALIDATION_REQUIRED', '公式验证缺少完整读取合同')
    RC._proof(task, EP.digest(contract), proof_file, required=True)
    sources = proof.get('read_sources')
    if not isinstance(sources, dict) or EP.digest(sources) != proof.get('read_sources_sha256'):
        raise EP.PlanError('SNAPSHOT_READ_SOURCES_REQUIRED', '旧验证缺少产出映射，请对原合同运行validate_package_set，不重发注册',
            next_action={'command': 'validate_package_set', 'script': 'qbs_bridge.py', 'params': {
                'task_id': task, 'user_query': C.current_trace_context().get('user_query') or '恢复原研究合同验证',
                'packages': [dict(contract, name=proof.get('package_name') or 'recovered')]}})
    ids = {str(o.get('data_id') or '') for o in proof.get('outputs', [])}
    if any(not sources.get(r['output']) or sources[r['output']] not in ids for r in contract['reads']):
        raise EP.PlanError('SNAPSHOT_READ_SOURCES_INVALID', '读取ID与已验证公式产出不一致')
    cache = C.task_temp_path(task, 'verified-snapshots/formula-' + EP.digest(proof) + '.json')
    if cache.exists():
        saved = json.loads(cache.read_text(encoding='utf-8'))
        VS.load(task, saved['snapshot_receipt_file'], saved['snapshot_receipt_sha256'])
        return {'code': 0, **saved, 'data_mode': 'snapshot', 'reused_validation_result': True}
    outputs = {}
    for read in contract['reads']:
        output = read['output']; data_id = sources[output]
        params = RDE.read_data_params(read['read_mode'], read.get('mode_params'), today=date.today())
        params.update(task_id=task, user_query=C.current_trace_context().get('user_query') or '物化已验证公式研究快照', ids=[data_id])
        response = read_qbs(task, params)
        entries = RDE.extract_read_data_items(response)
        matching = [e for e in entries if str(e.get('id') or e.get('data_id') or e.get('indexinfo_id') or '') == data_id]
        if len(matching) != 1 or matching[0].get('error') or BD._inspect_output_data(matching[0]) is not None:
            raise EP.PlanError('SNAPSHOT_READ_DATA_INVALID', '公式产出为空或ID不匹配', output=output)
        outputs[output] = {'data': matching[0]}
    saved = VS.capture(task, contract, {'code': 0, 'outputs': outputs}, resource='package')
    EP.atomic_json(cache, saved)
    return {'code': 0, **saved, 'data_mode': 'snapshot', 'reused_validation_result': False,
            'message': '从已验证公式产出读取并冻结；未注册新包、未重算公式，不会自动更新'}
