"""Hash-bound research intent and formula-condition audit. No data/network access.

This validates encoded conditions, not the natural-language interpretation itself.
Keep user_messages so the Agent and end-to-end review can check that boundary.
"""
import copy
import hashlib
import json
import re

STATUSES = ('complete', 'partial', 'unavailable', 'unknown')
KINDS = ('result', 'partial_research', 'methodology')

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def freeze(value):
    if not isinstance(value, dict):
        raise ValueError('RESEARCH_CONTRACT_INVALID: object required')
    out = copy.deepcopy(value)
    out.pop('contract_hash', None)
    out.setdefault('schema_version', 'research_contract_v1')
    if out['schema_version'] != 'research_contract_v1' or not out.get('task_id'):
        raise ValueError('RESEARCH_CONTRACT_INVALID: schema/task required')
    if not isinstance(out.get('user_messages'), list) or not out['user_messages'] or not all(isinstance(v, str) and v.strip() for v in out['user_messages']):
        raise ValueError('RESEARCH_USER_MESSAGES_REQUIRED')
    conditions = out.get('conditions')
    if not isinstance(conditions, list) or not conditions:
        raise ValueError('RESEARCH_CONDITIONS_REQUIRED')
    ids = set()
    confirmations = out.get('confirmation_messages', [])
    if not isinstance(confirmations, list) or not all(isinstance(v,str) for v in confirmations):
        raise ValueError('RESEARCH_CONFIRMATION_INVALID')
    evidence_text = '\n'.join(out['user_messages'] + confirmations)
    for condition in conditions:
        if not isinstance(condition, dict) or not condition.get('id') or not condition.get('description') or not isinstance(condition.get('spec'), dict):
            raise ValueError('RESEARCH_CONDITION_INVALID')
        if condition['id'] in ids:
            raise ValueError('RESEARCH_CONDITION_DUPLICATE')
        ids.add(condition['id'])
        if condition.get('proxy') and condition.get('proxy_confirmed') is not True:
            raise ValueError('RESEARCH_PROXY_NOT_CONFIRMED')
        quote = condition.get('source_quote')
        if quote is not None and (not isinstance(quote,str) or not quote.strip() or quote not in evidence_text):
            raise ValueError('RESEARCH_SOURCE_QUOTE_INVALID')
        spec = condition['spec']
        if out.get('require_confirmation_evidence') and spec.get('field') and type(spec.get('value')) in (int,float) and spec.get('operator') in ('gt','gte','lt','lte'):
            if not quote: raise ValueError('RESEARCH_THRESHOLD_SOURCE_REQUIRED')
            matches = re.findall(r'(>=|<=|>|<|≥|≤)\s*(-?\d+(?:\.\d+)?)\s*([%％]?)', quote)
            if not matches:
                words={'小于等于':'<=','大于等于':'>=','不超过':'<=','不高于':'<=','至多':'<=',
                       '不低于':'>=','不小于':'>=','至少':'>=','低于':'<','小于':'<','不足':'<','少于':'<',
                       '高于':'>','大于':'>','超过':'>','多于':'>'}
                matches=[(words[word],number,percent) for word,number,percent in
                         re.findall('('+'|'.join(words)+r')\s*(-?\d+(?:\.\d+)?)\s*([%％]?)',quote)]
            if not matches and quote.strip() == '主力资金净流入' and spec['value'] == 0:
                matches=[('>','0','')]
            if not matches and spec.get('unit') == '倍':
                matches=re.findall(r'(>=|<=|>|<|≥|≤)\s*[^\d。、;:<>≥≤\n]{1,30}[×*]\s*(-?\d+(?:\.\d+)?)\s*([%％]?)',quote)
            if len(matches) == 1:
                token,number,percent = matches[0]
                operator = {'>':'gt','>=':'gte','≥':'gte','<':'lt','<=':'lte','≤':'lte'}[token]
                transform=spec.get('source_transform',condition.get('source_transform'))
                transforms=[] if transform is None else (transform if isinstance(transform,list) else [transform])
                if len(set(transforms)) != len(transforms) or any(t not in ('exclude_complement','unit_conversion') for t in transforms):
                    raise ValueError('RESEARCH_THRESHOLD_TRANSFORM_INVALID')
                if 'exclude_complement' in transforms:
                    operator={'gt':'lte','gte':'lt','lt':'gte','lte':'gt'}[operator]
                if spec['operator'] != operator: raise ValueError('RESEARCH_THRESHOLD_OPERATOR_CHANGED')
                values = [float(number)]
                if percent: values.append(float(number)/100)
                if 'unit_conversion' in transforms:
                    scale=spec.get('source_scale',condition.get('source_scale'))
                    if type(scale) not in (int,float) or scale <= 0: raise ValueError('RESEARCH_THRESHOLD_SCALE_REQUIRED')
                    values=[v*scale for v in values]
                if type(spec.get('value')) not in (int,float) or not any(abs(spec['value']-v)<1e-10 for v in values):
                    raise ValueError('RESEARCH_THRESHOLD_VALUE_CHANGED')
            else:
                raise ValueError('RESEARCH_THRESHOLD_SOURCE_AMBIGUOUS')
    rank = out.get('ranking')
    if rank is not None and (not isinstance(rank, dict) or not rank.get('rank_by') or rank.get('rank_order') not in ('asc', 'desc') or type(rank.get('rank_limit')) is not int or rank['rank_limit'] < 1):
        raise ValueError('RESEARCH_RANKING_INVALID')
    out['contract_hash'] = digest(out)
    return out

def validate(value, task_id=None):
    if value is None:
        return None
    # Reuse frozen receipts, never silently freeze a draft or substitute a task.
    if isinstance(value,dict) and not value.get('schema_version'):
        if isinstance(value.get('research_contract'),dict): value=value['research_contract']
        elif set(value) <= {'research_contract_file','contract_file'}:
            value=value.get('research_contract_file') or value.get('contract_file')
    if isinstance(value,str):
        from pathlib import Path
        path=Path(value.lstrip('@'))
        try:
            if path.stat().st_size>256*1024: raise ValueError('RESEARCH_CONTRACT_FILE_TOO_LARGE')
            value=json.loads(path.read_text(encoding='utf-8-sig'))
        except OSError as exc: raise ValueError('RESEARCH_CONTRACT_FILE_UNREADABLE') from exc
    frozen = freeze(value)
    if value.get('contract_hash') != frozen['contract_hash']:
        raise ValueError('RESEARCH_CONTRACT_CHANGED: freeze before execution')
    if task_id and frozen['task_id'] != task_id:
        raise ValueError('RESEARCH_TASK_MISMATCH')
    return frozen

def audit(value, *, formulas=None, applied_conditions=None, observation_date=None, asset_rows=None, coverage=None, coverage_rows=None, field_dates=None, require_result_evidence=True):
    contract = validate(value)
    issues = []
    required = {v['id']: v for v in contract['conditions']}
    if applied_conditions is not None:
        if not isinstance(applied_conditions, list) or not all(isinstance(v,dict) and v.get('id') for v in applied_conditions) or len({v['id'] for v in applied_conditions}) != len(applied_conditions):
            raise ValueError('RESEARCH_APPLIED_CONDITIONS_INVALID: expected an array of {id, spec} objects, not an id-to-condition map')
        applied = {v['id']: v for v in applied_conditions}
        for key in sorted(required.keys() - applied.keys()):
            issues.append({'condition_id': key, 'error': 'CONDITION_MISSING'})
        for key in sorted(applied.keys() - required.keys()):
            issues.append({'condition_id': key, 'error': 'CONDITION_ADDED'})
        for key in required.keys() & applied.keys():
            if required[key]['spec'] != applied[key].get('spec'):
                issues.append({'condition_id': key, 'error': 'CONDITION_REPLACED'})
    if formulas is not None:
        mapping = {}
        for formula in formulas:
            match = re.match(r'^\s*([^=]+)=(.*)$', formula, re.S)
            if match:
                mapping[match[1].strip()] = match[2].strip()
        reachable, queue = set(), [contract.get('selection_output')]
        while queue:
            name = queue.pop()
            if not name or name in reachable:
                continue
            reachable.add(name)
            queue.extend(ref for ref in re.findall(r'"([^"]+)"', mapping.get(name, '')) if ref in mapping)
        # Quotes around formula references are syntax, not a different research
        # condition. Keep every identifier, operator, threshold and baseline.
        normalize = lambda s: re.sub(r'\s+', '', s or '').replace('"','')
        boolean_names = {c.get('formula_name') for c in required.values()
                         if re.search(r'[<>=]|板块\(', c.get('predicate',''))}
        def normalize_selection(expression):
            text=normalize(expression)
            # Missing boolean conditions cannot select a row in either form.
            # Do not remove this wrapper from numeric scores or observations.
            for name in boolean_names:
                if name: text=text.replace('缺失填零('+name+')',name)
            return text
        selection_predicate = contract.get('selection_predicate')
        if selection_predicate and normalize_selection(mapping.get(contract.get('selection_output'))) != normalize_selection(selection_predicate):
            issues.append({'error':'SELECTION_PREDICATE_CHANGED'})
        for key, condition in required.items():
            name, predicate = condition.get('formula_name'), condition.get('predicate')
            normalized_predicate=normalize(predicate)
            inline_condition = (predicate and (re.fullmatch(r'板块\([^()]+\)',normalized_predicate) or re.search(r'[<>]=?',normalized_predicate))
                                and any(re.search(r'(?:^|\*)\(*'+re.escape(normalized_predicate)+r'\)*(?=\*|$)',normalize(mapping.get(ref,''))) for ref in reachable))
            if inline_condition:
                continue
            if not name or not predicate or name not in mapping:
                issues.append({'condition_id': key, 'error': 'CONDITION_FORMULA_MISSING'})
            elif normalize(mapping[name]) != normalize(predicate):
                issues.append({'condition_id': key, 'error': 'CONDITION_FORMULA_REPLACED'})
            elif name not in reachable:
                issues.append({'condition_id': key, 'error': 'CONDITION_NOT_APPLIED'})
    requested = contract.get('requested_date')
    if require_result_evidence:
        if contract.get('selection_output'):
            if not isinstance(coverage,dict) or type(coverage.get('universe_count')) is not int or type(coverage.get('rows_evaluated')) is not int:
                issues.append({'error':'RESEARCH_COVERAGE_EVIDENCE_MISSING'})
            elif (coverage['universe_count'] <= 0 or coverage['rows_evaluated'] < 0
                    or coverage['rows_evaluated'] > coverage['universe_count']):
                issues.append({'error':'RESEARCH_COVERAGE_INVALID'})
            elif coverage.get('data_complete') is not True or coverage['rows_evaluated'] != coverage['universe_count']:
                issues.append({'error':'DATA_COVERAGE_PARTIAL','coverage':coverage})
            if coverage_rows is None:
                issues.append({'error':'RESEARCH_COVERAGE_ROWS_REQUIRED'})
            elif not isinstance(coverage_rows,list) or not all(isinstance(row,dict) for row in coverage_rows):
                raise ValueError('RESEARCH_COVERAGE_ROWS_INVALID')
            elif not isinstance(coverage,dict) or len(coverage_rows) != coverage.get('rows_evaluated'):
                issues.append({'error':'RESEARCH_COVERAGE_COUNT_MISMATCH'})
            else:
                assets=[row.get('asset') or row.get('code') for row in coverage_rows]
                if any(not isinstance(asset,str) or not asset.strip() for asset in assets) or len(set(str(asset) for asset in assets)) != len(assets):
                    issues.append({'error':'RESEARCH_COVERAGE_MEMBERS_INVALID'})
                for condition in required.values():
                    spec=condition['spec']
                    fields=list(spec.get('input_fields') or [])
                    fields += [spec[k] for k in ('field','benchmark_field') if spec.get(k)]
                    if not fields:
                        issues.append({'condition_id':condition['id'],'error':'CONDITION_INPUT_FIELDS_REQUIRED'})
                    for field in set(fields):
                        missing=sum(row.get(field) is None or (type(row.get(field)) in (int,float) and not __import__('math').isfinite(row[field])) for row in coverage_rows)
                        if missing: issues.append({'condition_id':condition['id'],'error':'CONDITION_COVERAGE_INCOMPLETE','field':field,'missing_count':missing})
                        if field in ('asset','code','name'): continue
                        # A formula's requested end date is not evidence of a
                        # lagged source field's actual update/evaluation date.
                        actual=(field_dates or {}).get(field) if isinstance(field_dates,dict) else None
                        if isinstance(actual,dict):
                            derived=field==spec.get('benchmark_field') or field in (spec.get('derived_fields') or [])
                            actual=(actual.get('evaluation_date') if derived else None) or actual.get('observation_date') or actual.get('date')
                        expected=spec.get('observation_date') or observation_date or requested
                        if not actual: issues.append({'condition_id':condition['id'],'error':'FIELD_DATE_EVIDENCE_MISSING','field':field})
                        elif expected and str(actual).replace('-','') != str(expected).replace('-',''):
                            issues.append({'condition_id':condition['id'],'error':'FIELD_DATE_NOT_COVERED','field':field,'expected_date':expected,'actual_date':actual})
        if not observation_date and not requested:
            issues.append({'error':'OBSERVATION_DATE_EVIDENCE_MISSING'})
        if asset_rows is None:
            issues.append({'error':'ASSET_MEMBERSHIP_EVIDENCE_MISSING'})
        elif not isinstance(asset_rows,list) or not all(isinstance(row,dict) for row in asset_rows):
            raise ValueError('RESEARCH_ASSET_ROWS_INVALID: expected an array of actual result rows')
        elif not asset_rows and not (isinstance(coverage,dict) and coverage.get('data_complete') is True
                                     and type(coverage.get('rows_evaluated')) is int and coverage['rows_evaluated'] > 0):
            issues.append({'error':'EMPTY_RESULT_EVIDENCE_REQUIRED'})
        rank=contract.get('ranking') or {}
        if rank and asset_rows:
            if len(asset_rows)>rank['rank_limit']: issues.append({'error':'TOPN_LIMIT_EXCEEDED'})
            values=[row.get(rank['rank_by']) for row in asset_rows]
            if not all(type(v) in (int,float) and __import__('math').isfinite(v) for v in values):
                issues.append({'error':'RANKING_EVIDENCE_MISSING','rank_by':rank['rank_by']})
            elif values != sorted(values,reverse=rank['rank_order']=='desc'):
                issues.append({'error':'RANKING_ORDER_VIOLATED'})
    if asset_rows is not None:
        for row in asset_rows:
            for key, condition in required.items():
                spec = condition['spec']
                field, op, expected = spec.get('field'), spec.get('operator'), spec.get('value')
                if not field or op not in ('gte','gt','lte','lt','eq','not_prefix'):
                    continue
                actual = row.get(field)
                if expected is None and op in ('gte','gt','lte','lt','eq'):
                    benchmark_field=spec.get('benchmark_field')
                    expected=row.get(benchmark_field) if benchmark_field else None
                    if expected is None:
                        # A measured predicate output can prove a dynamic
                        # benchmark comparison; a prose benchmark cannot.
                        flag=row.get(condition.get('formula_name'))
                        if type(flag) in (bool,int,float) and flag in (0,1):
                            if flag != 1: issues.append({'condition_id':key,'asset':row.get('asset'),'error':'ASSET_CONDITION_VIOLATED'})
                            continue
                        issues.append({'condition_id':key,'asset':row.get('asset'),'error':'CONDITION_EVIDENCE_MISSING'})
                        continue
                if actual is None:
                    issues.append({'condition_id':key, 'asset':row.get('asset'), 'error':'CONDITION_EVIDENCE_MISSING'})
                    continue
                operators = {'gte':lambda a,b:a>=b,'gt':lambda a,b:a>b,'lte':lambda a,b:a<=b,'lt':lambda a,b:a<b,
                             'eq':lambda a,b:a==b,'not_prefix':lambda a,b:not str(a).startswith(tuple(b))}
                try:
                    passed = operators[op](actual,expected)
                except (TypeError, ValueError):
                    issues.append({'condition_id':key, 'asset':row.get('asset'), 'error':'CONDITION_EVIDENCE_INVALID'})
                    continue
                if not passed:
                    issues.append({'condition_id':key, 'asset':row.get('asset'), 'error':'ASSET_CONDITION_VIOLATED'})
    if requested and not observation_date:
        issues.append({'error':'REQUESTED_DATE_EVIDENCE_MISSING','requested_date':requested})
    if requested and observation_date and str(requested).replace('-', '') != str(observation_date).replace('-', ''):
        issues.append({'error': 'REQUESTED_DATE_NOT_COVERED', 'requested_date': requested, 'observation_date': observation_date})
    if formulas is None and applied_conditions is None and asset_rows is None:
        issues.append({'error':'RESEARCH_CONDITIONS_UNVERIFIED'})
    return {'contract_hash': contract['contract_hash'], 'research_status': 'partial' if issues else 'complete', 'issues': issues,
            **({'field_dates':copy.deepcopy(field_dates),'field_date_evidence_hash':digest(field_dates)} if isinstance(field_dates,dict) else {}),
            **({'coverage_rows_count':len(coverage_rows),'coverage_evidence_hash':digest(coverage_rows)} if isinstance(coverage_rows,list) else {}),
            **({'coverage':copy.deepcopy(coverage)} if coverage is not None else {})}

def contract_path(task_id):
    import os
    from pathlib import Path
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,159}', str(task_id or '')):
        raise ValueError('RESEARCH_TASK_INVALID')
    base = Path(os.environ['SESSION_WORKSPACE']) / 'output' if os.environ.get('SESSION_WORKSPACE') else Path(__file__).resolve().parents[1] / 'output'
    return base / 'research-contracts' / (task_id + '.json')

def save(value):
    from pathlib import Path
    import os
    contract = validate(value)
    path = contract_path(contract['task_id'])
    previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    if previous and previous.get('schema_version') != 'research_contract_draft' and previous != contract:
        raise ValueError('RESEARCH_CONTRACT_CHANGED: explicit user revision required')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(contract,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,path)
    return str(path)

def load(task_id):
    path = contract_path(task_id)
    return validate(json.loads(path.read_text(encoding='utf-8')),task_id) if path.exists() else None

def load_for_delivery(task_id, status, kind):
    path=contract_path(task_id)
    if path.exists() and kind == 'methodology' and status == 'unavailable':
        value=json.loads(path.read_text(encoding='utf-8'))
        if value.get('schema_version') == 'research_contract_draft':
            return None  # Keep the draft blocking calculations; render only original intent.
    return load(task_id)

def delivery_metadata(params, task_id, turn_id=None):
    """Bind rendering to the current task/turn audit, even when a spec omits it."""
    import os
    contract=params.get('research_contract')
    status=params.get('research_status')
    kind=params.get('delivery_kind')
    if contract is None:
        contract=load_for_delivery(task_id,status or 'unknown',kind or 'result')
    checks=params.get('research_checks')
    turn=turn_id or params.get('turn_id') or os.environ.get('QB_HOST_TURN_ID')
    path=contract_path(task_id).with_suffix('.audit.json')
    if contract and turn and path.exists() and path.stat().st_size <= 256*1024:
        receipt=json.loads(path.read_text(encoding='utf-8'))
        if receipt.get('task_id')==task_id and receipt.get('turn_id')==turn and receipt.get('contract_hash')==contract['contract_hash']:
            observed=receipt.get('research_status')
            if observed in STATUSES:
                if status=='complete' and observed!='complete': raise ValueError('RESEARCH_AUDIT_CONFLICT')
                if status in (None,'unknown'):status=observed
                if checks is None:checks=receipt
    values={'research_contract':contract,'research_status':status or 'unknown','delivery_kind':kind or 'result','research_checks':checks}
    result=metadata(values,task_id)
    if checks is not None:result['research_checks']=checks
    return result

def guard_calculation(contract=None, task_id=None):
    """Persist the screening limit across CLI/API calls and SDK restarts.

    The host task/turn owns the budget; creating a calculation session cannot
    reset it. Legacy non-screening calculations remain unchanged.
    """
    import os,tempfile
    forced=os.environ.get('QBS_SCREENING_CALCULATION_LIMIT')
    if not forced and not (isinstance(contract,dict) and contract.get('selection_output')): return None
    try: limit=int(forced or 12)
    except ValueError: return {'code':1,'error':'RESEARCH_CALCULATION_LIMIT_INVALID'}
    if not 1 <= limit <= 100: return {'code':1,'error':'RESEARCH_CALCULATION_LIMIT_INVALID'}
    owner=os.environ.get('QB_HOST_TASK_ID') or (contract or {}).get('task_id') or task_id
    turn=os.environ.get('QB_HOST_TURN_ID') or 'standalone'
    path=contract_path(owner).with_suffix('.calculation-budget.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    lock=path.with_suffix('.lock')
    # OS locks release on process exit. A killed CLI must not leave a permanent
    # busy marker that blocks the next turn after an SDK/worker restart.
    with open(lock,'a+b') as handle:
        handle.seek(0,2)
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:return {'code':1,'error':'RESEARCH_CALCULATION_BUSY','recoverable':True,'terminal':False}
        try:
            state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
            if state.get('turn_id') != turn: state={'task_id':owner,'turn_id':turn,'attempts':0}
            if state['attempts'] >= limit:
                return {'code':1,'error':'RESEARCH_CALCULATION_LIMIT','research_status':'partial','terminal':False,
                        'next_action':{'command':'repair_or_prepare_partial_page','message':'研究重算已到上限。保留原条件和缺口，读取已有输出并立即交付部分研究或方法页；只文字任务给出部分结果。不使用新会话或Unicode空白绕过，不宣称完整零命中。'}}
            state['attempts']+=1
            fd,scratch=tempfile.mkstemp(prefix='.calculation-',dir=path.parent)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(state,stream)
                os.replace(scratch,path)
            finally:
                if os.path.exists(scratch):os.unlink(scratch)
        finally:
            if os.name=='nt':
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

    return None

def preflight(contract, formulas):
    path = contract_path(contract['task_id']).with_suffix('.formulas.json')
    previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if previous.get('contract_hash') != contract['contract_hash']: previous = {}
    mapping = previous.get('formulas', {})
    current = {}
    for formula in formulas:
        if '=' in formula:
            name,expression = formula.split('=',1)
            current[name.strip()] = expression.strip()
    combined = {**mapping,**current}
    checks = audit(contract,formulas=[name+'='+expression for name,expression in combined.items()],require_result_evidence=False)
    # Helper batches may precede the final screen. They prove no final result.
    final = contract.get('selection_output') in current
    if not final:
        checks = {'contract_hash':contract['contract_hash'],'research_status':'partial','issues':[{'error':'SELECTION_NOT_EVALUATED'}]}
    return checks, final

def record_formulas(contract, formulas):
    import os
    path = contract_path(contract['task_id']).with_suffix('.formulas.json')
    previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    mapping = previous.get('formulas', {}) if previous.get('contract_hash') == contract['contract_hash'] else {}
    for formula in formulas:
        if '=' in formula:
            name,expression = formula.split('=',1)
            mapping[name.strip()] = expression.strip()
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps({'contract_hash':contract['contract_hash'],'formulas':mapping},ensure_ascii=False),encoding='utf-8')
    os.replace(temp,path)

def selection_route_error(query, params):
    text=str(query or '')
    raw_condition = re.search(r'主力资金净流入|放量突破|涨停基因|板后.*回落|累计回落',text)
    score_intent = re.search(r'强度.*排名|有效性.*排名|综合分|等权|组合打分|维度评分',text)
    if params.get('mode','score') == 'score' and raw_condition and not score_intent:
        return {'code':1,'error':'RAW_CONDITION_SCORE_PROXY_FORBIDDEN',
                'message':'用户请求原始量价/资金或涨停回落条件，不能用预计算强度或有效性分数替换。按研究合同走公式筛选；分数仅可作为已明确确认的补充观察。'}
    return None

def metadata(params, task_id=None):
    contract = validate(params.get('research_contract'), task_id)
    status = params.get('research_status', 'unknown')
    kind = params.get('delivery_kind', 'result')
    if status not in STATUSES or kind not in KINDS:
        raise ValueError('RESEARCH_DELIVERY_INVALID')
    if status == 'partial' and kind == 'result': kind = 'partial_research'
    if status == 'unavailable' and kind == 'result': kind = 'methodology'
    if kind == 'methodology' and status != 'unavailable':
        raise ValueError('METHODOLOGY_RESEARCH_UNAVAILABLE_REQUIRED')
    if kind == 'partial_research' and status != 'partial':
        raise ValueError('PARTIAL_RESEARCH_STATUS_REQUIRED')
    if status == 'complete' and contract:
        checks = params.get('research_checks')
        if not isinstance(checks, dict) or checks.get('contract_hash') != contract['contract_hash'] or checks.get('research_status') != 'complete' or checks.get('issues') != []:
            raise ValueError('RESEARCH_COMPLETION_EVIDENCE_REQUIRED')
        if contract.get('selection_output'):
            coverage=checks.get('coverage') or {}
            if (coverage.get('data_complete') is not True or type(coverage.get('universe_count')) is not int
                    or type(coverage.get('rows_evaluated')) is not int or coverage['universe_count'] <= 0
                    or coverage['rows_evaluated'] != coverage['universe_count']):
                raise ValueError('RESEARCH_COVERAGE_EVIDENCE_REQUIRED')
            if checks.get('coverage_rows_count') != coverage['universe_count'] or not re.fullmatch(r'[a-f0-9]{64}',str(checks.get('coverage_evidence_hash') or '')):
                raise ValueError('RESEARCH_COVERAGE_ROWS_REQUIRED')
            if not isinstance(checks.get('field_dates'),dict) or checks.get('field_date_evidence_hash') != digest(checks['field_dates']):
                raise ValueError('RESEARCH_FIELD_DATE_EVIDENCE_REQUIRED')
    return {'research_contract': contract, 'research_status': status, 'delivery_kind': kind}

if __name__ == '__main__':
    import sys
    from pathlib import Path
    try:
        raw = sys.argv[2]
        document=Path(raw[1:]).read_text(encoding='utf-8-sig') if raw.startswith('@') else raw
        if sys.argv[1] == 'freeze':
            task_match=re.search(r'"task_id"\s*:\s*"([A-Za-z0-9][A-Za-z0-9_-]{0,159})"',document)
            if task_match:
                draft_path=contract_path(task_match[1])
                if not draft_path.exists():
                    draft_path.parent.mkdir(parents=True,exist_ok=True)
                    draft_path.write_text(json.dumps({'schema_version':'research_contract_draft','task_id':task_match[1]}),encoding='utf-8')
        params = json.loads(document)
        if sys.argv[1] == 'freeze':
            # Preserve a failed freeze so a later calculation cannot silently
            # drop the requested contract. A corrected freeze replaces this draft.
            draft_path = contract_path(params['task_id'])
            if not draft_path.exists():
                draft_path.parent.mkdir(parents=True,exist_ok=True)
                draft_path.write_text(json.dumps({'schema_version':'research_contract_draft','task_id':params['task_id']}),encoding='utf-8')
            contract = freeze(params)
            result = {'research_contract':contract,'research_contract_file':save(contract)}
        else:
            if params.get('coverage_rows_file'):
                params['coverage_rows']=json.loads(Path(params['coverage_rows_file']).read_text(encoding='utf-8-sig'))
            result = audit(params['research_contract'], **{k:params[k] for k in ('formulas','applied_conditions','observation_date','asset_rows','coverage','coverage_rows','field_dates') if k in params})
            # Host observes this even when Bash redirects stdout to a file.
            import os,datetime,tempfile
            contract=validate(params['research_contract'])
            audit_path=contract_path(contract['task_id']).with_suffix('.audit.json')
            audit_path.parent.mkdir(parents=True,exist_ok=True)
            receipt={'task_id':contract['task_id'],'turn_id':os.environ.get('QB_HOST_TURN_ID'),
                     'completed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),**result}
            fd,temp=tempfile.mkstemp(prefix='.audit-',dir=audit_path.parent)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as handle: json.dump(receipt,handle,ensure_ascii=False)
                os.replace(temp,audit_path)
            finally:
                if os.path.exists(temp):os.unlink(temp)
            if result['research_status'] != 'complete':
                result.update(terminal=False,next_action={'command':'repair_or_prepare_partial_page','message':'审计未完整通过：不得宣称全部符合或完整零命中。按issues修正实际证据；不可核实的条件保留缺口，继续交接partial_research/partial页，而不是结束建页或要求用户重试。'})
        print(json.dumps({'code': 0, **result}, ensure_ascii=False))
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        print(json.dumps({'code': 1, 'error': str(exc), 'recoverable': True, 'terminal': False,
                         'next_action': {'command':'write_skill_file','message':'修正输入JSON或条件编码后重试；严格保留已确认原文与比较符。技术错误不要求用户再次确认。禁止python -c或heredoc绕过工具；无法完成计算时交接methodology/unavailable研究页，保留原问题与缺口。'}}, ensure_ascii=False)); sys.exit(1)
