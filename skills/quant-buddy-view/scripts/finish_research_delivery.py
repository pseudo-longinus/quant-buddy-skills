"""Protected host-only last step after bounded SDK recovery. No new research.

Uses normal page creation, plan revisions, browser gates and reply validation.
Never overwrites a published good version or repeats an uncertain write.
"""
import hashlib,json,re,sys,os
from pathlib import Path
import common as C
import execution_plan as EP
import delivery_state as DS
import delivery_recovery as recovery
import research_contract as RC
import static_page as SP
import export_delivery as export


def _build_contract_reply(plan,contract,live):
    kind=plan['delivery_kind']
    modules=(contract.get('page_context') or {}).get('core_sections') or ['研究范围与核验方法']
    intro={'methodology':'本页为研究方法说明，数据待补；已交付策略、缺口与核验方法。',
           'partial_research':'已交付部分研究成果，部分数据待补。'}.get(kind,'已交付研究成果，具体覆盖范围以核验记录为准。')
    mode={'verified_snapshot':'页面为已验证快照，不会自动刷新。','static_content_only':'页面为静态展示，不会自动刷新。',
          'live':'已核验自动取数能力。','mixed':'页面含实时与静态内容，按各字段日期与状态查看。'}.get(live,'页面自动更新能力待核验。')
    url=contract['public_url']
    label=contract.get('delivery_link_label') or ('策略与核验方法研究页' if kind=='methodology' else {'verified_snapshot':'可分享静态研究页','static_content_only':'可分享静态研究页','live':'可分享实时活页','mixed':'可分享活页（部分实时、部分静态）'}.get(live,'可分享研究页（数据模式待核验）'))
    reply='**'+str(plan.get('title') or '策略研究与核验方法')+'**\n\n**一句话总结**：'+intro+'\n\n'
    reply+='## 这份活页做了什么\n\n保留原始研究条件，呈现已核验内容及尚未完成的部分。\n\n'
    reply+='## 核心模块\n\n'+'\n'.join('- '+str(module) for module in modules)+'\n\n'
    reply+='## 重点怎么看\n\n逐项核对范围、价格基准、单位、实际观察日与排序。未验证条件保留缺口。\n\n'
    reply+='## 能力边界\n\n'+intro+' '+mode+' 未取得完整证据不能证明符合条件为零；不构成投资建议。\n\n'
    reply+='## 公开链接\n\n活页链接见回复末尾。\n\n'+label+'：['+url+']('+url+')\n若效果不满意，页面可进一步升级'
    return reply


def _finish_verified_reply(task,turn,plan,state,reply_text=None):
    """Complete reply bookkeeping for the current turn's already-verified publish.

    Any guard failure returns None so the caller preserves the last good page;
    this path never creates, composes or publishes pages.
    """
    try:
        good=state.get('last_good_version') or {}
        contract_hash=str(state.get('reply_contract_hash') or '')
        flags=DS.flags(state)
        if (str(state.get('turn_id') or '') != str(turn) or state.get('delivery_state') != 'published'
                or not all(flags.get(key) for key in ('written','public_reachable','verified'))
                or good.get('page_id') != plan['target_page_id']
                or not isinstance(good.get('version_no'),int) or not str(good.get('url') or '').strip()
                or state.get('reply_plan_hash') != plan['plan_hash']
                or not re.fullmatch(r'[0-9a-f]{64}',contract_hash)):
            return None
        params=json.loads(C.task_temp_path(task,'reply-validate.json').read_text(encoding='utf-8'))
        if params.get('contract_sha256') != contract_hash: return None
        contract_file=Path(str(params.get('contract_file') or ''))
        if not contract_file.is_file(): return None
        contract_bytes=contract_file.read_bytes()
        if hashlib.sha256(contract_bytes).hexdigest() != contract_hash: return None
        contract=json.loads(contract_bytes.decode('utf-8'))
        contract=contract.get('agent_reply_contract') or contract
        reply=(reply_text if reply_text is not None else
               _build_contract_reply(plan,contract,state.get('live_data_mode') or contract.get('delivery_data_mode')))
        from validate_agent_reply import validate_reply
        checked=validate_reply(contract,reply)
        if checked.get('code')!=0: return None
        DS.finish_reply(plan,contract_hash,checked['validated_markdown_sha256'])
        return {'code':0,'validated_markdown':checked['validated_markdown'],
                'delivery':export.export(task,turn,checked['validated_markdown'],finalize_reply=True)}
    except Exception:
        return None


def preserve_publication(params, plan, state):
    """Shared read-only guard for both direct recovery and host finalization."""
    task = plan['task_id']
    turn = params.get('turn_id') or C.current_trace_context().get('turn_id')
    from delivery_requirements import recovery_boundary
    blocked=recovery_boundary(params,plan,state)
    if blocked is not None: return blocked
    if state.get('last_good_version'):
        completed = _finish_verified_reply(task, turn, plan, state)
        return completed if completed is not None else {'code':1,'error':'PRESERVED_LAST_GOOD_PAGE',
                                                       'preserved_version':state['last_good_version']}
    write = state.get('last_write') or {}
    if write.get('status') == 'confirmed' and write.get('content_kind', 'candidate') != 'progress':
        checked = SP.cmd_verify_published({'task_id':task,'page_id':plan['target_page_id']})
        if checked.get('code') != 0:
            return checked
        state = DS.load(task, plan['target_page_id'])
        completed = _finish_verified_reply(task, turn, plan, state)
        return completed if completed is not None else {
            'code':1,'error':'DIRECT_DELIVERY_REPLY_REQUIRED','terminal':False,
            'page_id':plan['target_page_id'],
            'public_url':(state.get('last_good_version') or {}).get('url'),
            'next_action':{'command':'verify_published','params':{'task_id':task,'page_id':plan['target_page_id']}}}
    return None


def finish(params):
    if os.environ.get('QB_HOST_FINISH_RESEARCH_DELIVERY') != '1': return {'code':1,'error':'HOST_RECOVERY_ONLY'}
    task,turn=params.get('task_id'),params.get('turn_id')
    context=C.current_trace_context()
    if context.get('task_id') != task or context.get('turn_id') != turn:
        return {'code':1,'error':'HOST_RECOVERY_IDENTITY_MISMATCH'}
    query=str(params.get('user_query') or context.get('user_query') or '').strip()
    query=re.sub(r'(?i)(?:api_key|signature|authorization|access_token)\s*[=:]\s*\S+','[凭证已移除]',query)
    if not query or len(query)>30000: return {'code':1,'error':'METHODOLOGY_INTENT_REQUIRED'}
    plan=EP.load(task)
    if plan and (DS.load(task,plan['target_page_id']).get('last_write') or {}).get('status') in ('pending','unknown'):
        return recovery.backup_html({'task_id':task,'turn_id':turn,'user_query':query},plan)
    from delivery_requirements import recovery_boundary
    blocked=recovery_boundary(params,plan,DS.load(task,plan['target_page_id']) if plan else None)
    if blocked is not None: return blocked
    if plan:
        state=DS.load(task,plan['target_page_id'])
        write = state.get('last_write') or {}
        if write.get('status') in ('pending','unknown'):
            return recovery.backup_html({'task_id':task,'turn_id':turn,'user_query':query},plan)
        preserved = preserve_publication(params, plan, state)
        if preserved is not None:
            return preserved
    else:
        # A normal candidate fetch is still required. The host's fallback scope
        # is explicitly methods-only, so it never borrows a data-result runtime.
        credential,_,_=SP._read_routing_credential(task)
        if (credential or {}).get('page_id'):
            return {'code':1,'error':'EXISTING_PAGE_PLAN_REQUIRED'}
        for _ in range(2):
            templates=SP.cmd_templates({'task_id':task,'recommend':'all'})
            if templates.get('code')==0: break
        if templates.get('code')!=0:
            return recovery.recover({'task_id':task,'turn_id':turn,'user_query':query})
        credential,_,error=SP._read_routing_credential(task)
        if error: return error
        candidates,error=SP._routing_candidates(task,credential)
        if error:return error
        decision={'mode':'unmatched','reason_code':'required_capability_missing',
                  'reason':'研究预算耗尽，尚无完整标的结果证据；本次交付原始策略与缺口的方法页，不继承结果模板的数据运行时。'}
        if candidates['index']: decision['closest_template_id']=next(iter(candidates['index']))
        created=SP.cmd_new_page({'task_id':task,'turn_id':turn,'title':'策略研究与核验方法',
                                'user_query':query,'routing_decision':decision,
                                'live_data_mode':'static_content_only','market_data_required':False,
                                'research_status':'unavailable','delivery_kind':'methodology',
                                'require_live_data':params.get('require_live_data',False)})
        if created.get('code')!=0:
            if created.get('error')=='PUBLISH_OUTCOME_UNKNOWN': return recovery.backup_html({'task_id':task,'turn_id':turn,'user_query':query})
            return created
        plan=EP.load(task)
        contract=RC.load_for_delivery(task,'unavailable','methodology')
        route,_,error=SP._read_routing_credential(task)
        if error:return error
        plan=EP.bind(route,expected_revision=plan['revision'],revision_reason='host_budget_methodology',
                     research_contract=contract,research_status='unavailable',delivery_kind='methodology',
                     require_live_data=params.get('require_live_data',False))
    prepared=recovery.recover({'task_id':task,'turn_id':turn,'plan_hash':plan['plan_hash'],
                               'force_fallback':True,'user_query':query})
    if prepared.get('code')!=0:return prepared
    if not prepared.get('next_action'):
        return {'code':1,'error':'HOST_RECOVERY_CANDIDATE_MISSING','message':'恢复未返回可执行候选参数','recovery':prepared}
    draft=json.loads(Path(prepared['next_action']['params_file']).read_text(encoding='utf-8'))
    built=SP.cmd_compose_page(draft)
    if built.get('code')!=0:return built
    if not built.get('next_action'):
        if built.get('artifact_verified') is True:
            current=EP.load(task) or {}
            kind=current.get('delivery_kind','methodology')
            note='本页为研究方法说明，数据待补。' if kind=='methodology' else '本页为部分研究成果，部分数据待补。'
            return {'code':0,'delivery':{'status':'local_artifact','artifact_file':built.get('out_file'),
                                          'artifact_sha256':built.get('html_sha256'),'research_status':current.get('research_status','unavailable'),
                                          'delivery_kind':kind,'live_data_mode':draft.get('live_data_mode','static_content_only')},
                    'validated_markdown':note+'公开活页尚未发布；可打开的研究HTML作为备用成果交付。',
                    'artifact_file':built.get('out_file'),'artifact_sha256':built.get('html_sha256'),
                    'artifact_verified':True,'task_id':task,'turn_id':turn}
        return {'code':1,'error':'HOST_RECOVERY_COMPOSE_INCOMPLETE','message':'候选页未返回发布动作','build':built}
    publish_params=json.loads(Path(built['next_action']['params_file']).read_text(encoding='utf-8'))
    published=SP.cmd_publish_verified(publish_params)
    if published.get('code')!=0:
        # Only service/write failures permit an HTML backup. Layout/data errors
        # never become a delivered error page or a publication claim.
        stages=published.get('stages') or {}
        if published.get('error')=='PUBLISH_OUTCOME_UNKNOWN' or any((stages.get(s) or {}).get('code') not in (None,0) for s in ('publish_final','public_smoke')):
            return recovery.backup_html({**publish_params,'user_query':query},EP.load(task))
        return published
    reply_params=json.loads(Path(published['reply_validation_params_file']).read_text(encoding='utf-8'))
    contract=json.loads(Path(reply_params['contract_file']).read_text(encoding='utf-8'))
    contract=contract.get('agent_reply_contract') or contract
    plan=EP.load(task)
    reply=_build_contract_reply(plan,contract,published.get('live_data_mode'))
    from validate_agent_reply import validate_reply
    checked=validate_reply(contract,reply)
    if checked.get('code')!=0:return {'code':1,'error':'HOST_RECOVERY_REPLY_FAILED','errors':checked.get('errors')}
    DS.finish_reply(plan,reply_params['contract_sha256'],checked['validated_markdown_sha256'])
    return {'code':0,'validated_markdown':checked['validated_markdown'],
            'delivery':export.export(task,turn,checked['validated_markdown'],finalize_reply=True)}

if __name__=='__main__':
    try:
        params=json.loads(sys.stdin.read(64000))
        C.configure_trace_context(params)
        result=finish(params)
    except (ValueError,OSError,KeyError,TypeError,EP.PlanError) as error:
        result=error.as_dict() if isinstance(error,EP.PlanError) else {'code':1,'error':'HOST_RECOVERY_FAILED'}
    # No detailed API responses or runtime credentials are exported.
    print(json.dumps({key:result[key] for key in ['code','error','delivery','validated_markdown','artifact_file','artifact_sha256','artifact_verified','task_id','turn_id'] if key in result},ensure_ascii=False))
