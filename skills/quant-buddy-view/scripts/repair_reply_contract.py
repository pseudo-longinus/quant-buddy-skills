"""Narrow, auditable repair of an automatically misclassified screening reply.

Never publishes, updates a page, or completes a reply. Old contracts stay
immutable; the validator pointer and its task binding switch under the task lock.
"""
import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import common as C
import delivery_state as DS
import execution_plan as EP


def _fail(code, message):
    raise EP.PlanError(code, message)


def _restore(path, payload):
    fd, scratch = tempfile.mkstemp(prefix='.repair-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(scratch, path)
    finally:
        if os.path.exists(scratch): os.unlink(scratch)


def repair(params):
    import static_page as SP
    allowed = {'task_id', 'turn_id', 'page_id', 'expected_contract_sha256', 'execute'}
    try:
        if set(params) - allowed or type(params.get('execute', False)) is not bool:
            _fail('REPLY_REPAIR_PARAMS_INVALID', '只接受任务身份、预期旧合同哈希及execute布尔值')
        task, turn, page = [str(params.get(k) or '').strip() for k in ('task_id','turn_id','page_id')]
        expected = str(params.get('expected_contract_sha256') or '')
        if not all((task,turn,page)) or not re.fullmatch('[0-9a-f]{64}', expected):
            _fail('REPLY_REPAIR_IDENTITY_REQUIRED', '需要task_id、turn_id、page_id及预期旧合同SHA256')
        context = C.current_trace_context()
        if context.get('task_id') != task or context.get('turn_id') != turn:
            _fail('REPLY_REPAIR_IDENTITY_CONFLICT', '仅能修复当前Trace绑定的同任务同轮合同')
        with EP.locked(task):
            plan = EP.require(task, page_id=page)
            state = DS.load(task,page)
            write, good = state.get('last_write') or {}, state.get('last_good_version') or {}
            if (state.get('turn_id') != turn or write.get('status') != 'confirmed'
                    or write.get('turn_id') != turn or state.get('delivery_state') != 'published'
                    or not all(DS.flags(state).get(k) for k in ('written','public_reachable','verified'))
                    or write.get('plan_hash') != plan['plan_hash'] or state.get('reply_plan_hash') != plan['plan_hash']):
                _fail('REPLY_REPAIR_PUBLICATION_REQUIRED', '需要当前任务、轮次与计划的已确认写入和公开验收')
            identity = {k:good.get(k) for k in ('page_id','version_no','sha256')}
            if (identity['page_id'] != page or type(identity['version_no']) is not int
                    or not re.fullmatch('[0-9a-f]{64}',str(identity['sha256'] or ''))
                    or any((write.get('remote') or {}).get(k) != v for k,v in identity.items())):
                _fail('REPLY_REPAIR_VERSION_CONFLICT', '成功版本与写入回执不一致')
            result = SP.cmd_template({'page_id':page})
            remote = SP._template_record(result)
            if result.get('code') != 0 or any(DS._remote(remote).get(k) != v for k,v in identity.items()):
                _fail('REPLY_REPAIR_VERSION_CONFLICT', '当前页面版本或HTML哈希已变化，不能修复旧合同')
            root = Path(C.task_temp_path(task,'agent-contract.json')).parent.resolve()
            pointer = C.task_temp_path(task,'reply-validate.json')
            pointer_bytes = pointer.read_bytes()
            inputs = json.loads(pointer_bytes)
            contract_path = Path(inputs.get('contract_file','')).resolve()
            if root not in contract_path.parents:
                _fail('REPLY_REPAIR_CONTRACT_INVALID', '合同文件必须位于当前任务目录')
            raw = contract_path.read_bytes()
            current_hash = hashlib.sha256(raw).hexdigest()
            if inputs.get('contract_sha256') != current_hash or state.get('reply_contract_hash') != current_hash:
                _fail('REPLY_CONTRACT_STALE', '合同文件、校验参数与任务绑定不一致')
            contract = json.loads(raw)
            if (inputs.get('task_id') != task or contract.get('terminal') is not True
                    or contract.get('page_id') != page or not contract.get('public_url')
                    or contract['public_url'] != good.get('url')):
                _fail('REPLY_REPAIR_CONTRACT_INVALID', '需要当前页面的封存终态合同')
            audit_path = root / 'receipts/reply-contract-repairs' / expected / 'audit.json'
            audit = json.loads(audit_path.read_text(encoding='utf-8')) if audit_path.is_file() else {}
            if audit.get('status') == 'prepared':
                _fail('REPLY_REPAIR_INTERRUPTED', '上次纠错未完成；保留原合同及备份，需先核对事务记录')
            if audit.get('status') == 'committed' and audit.get('new_sha256') == current_hash:
                return {'code':0,'reused':True,'dry_run':not params.get('execute',False),
                        'page_id':page,'contract_sha256':current_hash,'audit_file':str(audit_path)}
            if expected != current_hash:
                _fail('REPLY_CONTRACT_STALE', '预期旧合同哈希已过期')
            receipt = write.get('confirmed_result') or {}
            provenance = receipt.get('agent_reply_template_resolution') or {}
            query = str(remote.get('user_query') or receipt.get('user_query') or '').strip()
            original = str(context.get('user_query') or '').strip()
            if not query or query != original:
                _fail('REPLY_REPAIR_QUERY_UNVERIFIED', '页面原问题与当前Trace原问题无法相互核验')
            template = contract.get('template_ref')
            if (template != 'single_stock_deep_dive_v1' or provenance.get('mode') != 'publish_metadata'
                    or provenance.get('source_template_id') or plan.get('source_page_id')
                    or (receipt.get('agent_reply_template') or {}).get('template_ref') != template
                    or (remote.get('agent_reply_template') or {}).get('template_ref') != template
                    or contract.get('reply_data_evidence_file') or contract.get('reply_data_evidence_sha256')):
                _fail('REPLY_REPAIR_NOT_ELIGIBLE', '仅纠正无单股证据且由发布元数据自动误配的单股深度合同')
            metadata = {k:remote.get(k) for k in ('title','description')}
            metadata['user_query'] = query
            if not SP._is_screening_publish({'user_query': query}):
                _fail('REPLY_REPAIR_NOT_SCREENING', '没有明确的筛选研究依据，不自动降低合同要求')
            metadata['agent_reply_template'] = dict(SP._GENERIC_LIVE_PAGE_REPLY_TEMPLATE)
            metadata['page_context'] = SP._infer_page_context_from_publish_params(metadata,template_ref='generic_live_page_delivery_v1')
            fixed_record = {**remote,**metadata,'url':contract['public_url']}
            replacement = SP._agent_reply_template_contract(fixed_record,operation=contract.get('operation'))
            # Retain publication, research, ranking and presentation constraints;
            # replace only template-specific shape and its derived page semantics.
            repaired = copy.deepcopy(contract)
            for key in ('template_ref','template_file','template_exists','reply_scope','output_format',
                        'hybrid_composition','reply_render_policy','final_response_required','final_response_steps','page_context'):
                if key in replacement: repaired[key] = replacement[key]
                else: repaired.pop(key,None)
            repaired['page_context'] = metadata['page_context']
            new_raw = json.dumps(repaired,ensure_ascii=False,indent=2).encode('utf-8')
            new_hash = hashlib.sha256(new_raw).hexdigest()
            report = {'code':0,'dry_run':not params.get('execute',False),'page_id':page,
                      'old_sha256':current_hash,'new_sha256':new_hash,
                      'old_template_ref':template,'new_template_ref':repaired['template_ref'],
                      'reason':'automatic_single_stock_contract_for_screening','publication':identity}
            if not params.get('execute'): return report
            if state.get('execution_status') == 'succeeded':
                _fail('REPLY_REPAIR_ALREADY_FINISHED', '已完成的历史回复不在维护纠错范围')
            directory = audit_path.parent
            directory.mkdir(parents=True,exist_ok=True)
            new_path = directory / 'agent-contract.json'
            state_path = C.task_temp_path(task,DS.FILE)
            state_bytes = state_path.read_bytes()
            _restore(directory/'old-contract.json',raw)
            _restore(directory/'old-reply-validate.json',pointer_bytes)
            _restore(directory/'old-delivery-state.json',state_bytes)
            _restore(new_path,new_raw)
            audit = {**report,'status':'prepared','task_id':task,'turn_id':turn,
                     'plan_hash':plan['plan_hash'],'new_sha256':new_hash}
            EP.atomic_json(audit_path,audit)
            try:
                DS.bind_reply_contract(plan,new_hash)
                EP.atomic_json(pointer,{**inputs,'contract_file':str(new_path),'contract_sha256':new_hash})
                EP.atomic_json(audit_path,{**audit,'status':'committed'})
            except Exception:
                _restore(state_path,state_bytes)
                _restore(pointer,pointer_bytes)
                EP.atomic_json(audit_path,{**audit,'status':'rolled_back'})
                raise
            return {**report,'audit_file':str(audit_path),'contract_file':str(new_path),
                    'next_action':{'command':'validate_agent_reply','params_file':str(pointer)}}
    except EP.PlanError as exc:
        return exc.as_dict()
    except (OSError,ValueError,TypeError) as exc:
        return {'code':1,'error':'REPLY_REPAIR_FAILED','message':str(exc)}
