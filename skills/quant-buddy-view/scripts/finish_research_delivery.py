"""Protected host-only last step after bounded SDK recovery. No new research.

Uses normal page creation, plan revisions, browser gates and reply validation.
Never overwrites a published good version or repeats an uncertain write.
"""
import json,re,sys,os
from pathlib import Path
import common as C
import execution_plan as EP
import delivery_state as DS
import delivery_recovery as recovery
import research_contract as RC
import static_page as SP
import export_delivery as export


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
    if plan:
        state=DS.load(task,plan['target_page_id'])
        if (state.get('last_write') or {}).get('status') in ('pending','unknown'):
            return recovery.backup_html({'task_id':task,'turn_id':turn,'user_query':query},plan)
        if state.get('last_good_version'):
            return {'code':1,'error':'PRESERVED_LAST_GOOD_PAGE'}
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
                                'require_live_data':params.get('require_live_data',True)})
        if created.get('code')!=0:
            if created.get('error')=='PUBLISH_OUTCOME_UNKNOWN': return recovery.backup_html({'task_id':task,'turn_id':turn,'user_query':query})
            return created
        plan=EP.load(task)
        contract=RC.load_for_delivery(task,'unavailable','methodology')
        route,_,error=SP._read_routing_credential(task)
        if error:return error
        plan=EP.bind(route,expected_revision=plan['revision'],revision_reason='host_budget_methodology',
                     research_contract=contract,research_status='unavailable',delivery_kind='methodology',
                     require_live_data=params.get('require_live_data',True))
    prepared=recovery.recover({'task_id':task,'turn_id':turn,'plan_hash':plan['plan_hash'],
                               'force_fallback':True,'user_query':query})
    if prepared.get('code')!=0:return prepared
    draft=json.loads(Path(prepared['next_action']['params_file']).read_text(encoding='utf-8'))
    built=SP.cmd_compose_page(draft)
    if built.get('code')!=0:return built
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
    plan=EP.load(task);kind=plan['delivery_kind'];live=published.get('live_data_mode')
    modules=(contract.get('page_context') or {}).get('core_sections') or ['研究范围与核验方法']
    intro='研究尚未完成，已交付策略、缺口与核验方法。' if kind=='methodology' else '已交付部分研究成果，完整条件仍待核验。'
    mode='页面为已验证快照，不会自动刷新。' if live=='verified_snapshot' else '本页为方法研究页，不宣称实时选股研究完成。'
    url=contract['public_url']
    label={'verified_snapshot':'可分享静态研究页','static_content_only':'策略与核验方法研究页','mixed':'可分享活页（部分实时、部分静态）'}.get(contract.get('delivery_data_mode'),'可分享实时活页')
    reply='**'+str(plan.get('title') or '策略研究与核验方法')+'**\n\n【一句话结论】'+intro+'\n\n'
    reply+='## 这份活页做了什么\n\n保留原始研究条件，呈现已核验内容及尚未完成的部分。\n\n'
    reply+='## 核心模块\n\n'+'\n'.join('- '+str(module) for module in modules)+'\n\n'
    reply+='## 重点怎么看\n\n逐项核对范围、价格基准、单位、实际观察日与排序。未验证条件保留缺口。\n\n'
    reply+='## 能力边界\n\n'+intro+' '+mode+' 未取得完整证据不能证明符合条件为零；不构成投资建议。\n\n'
    reply+='## 公开链接\n\n活页链接见回复末尾。\n\n'+label+'：['+url+']('+url+')\n若效果不满意，页面可进一步升级'
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
