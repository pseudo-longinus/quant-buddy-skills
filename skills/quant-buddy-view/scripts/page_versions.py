"""Same-link history/restore. Never regenerates research or retries unknown writes."""
import hashlib
import json
import re
from urllib.parse import urlencode
import common as C
import execution_plan as EP
import delivery_requirements as DR
import share_shell_contract as SSC


def _error(code, **fields):
    return {'code':1,'error':code, **fields}


def _request(action, params, body=None):
    cfg=C.load_config_require_key()
    url=C.api_url(C.endpoint_of(cfg), '/skill/'+action)
    if body is None:
        url+='?'+urlencode(params)
    return C.http_json('GET' if body is None else 'POST',url,C.headers(cfg['api_key']),
                       **({'body':body} if body is not None else {}),timeout=120)


def versions(params):
    if not params.get('page_id'): return _error('PAGE_ID_REQUIRED')
    return _request('listStaticPageVersions', {k:params[k] for k in ('page_id','page','page_size') if k in params})


def _resolve(params):
    if params.get('version_id'): return params['version_id'],None
    match=re.fullmatch(r'[vV]?([1-9][0-9]*)',str(params.get('version_no') or params.get('version') or ''))
    if not match: return None,_error('VERSION_ID_REQUIRED')
    number=int(match[1])
    for page in range(1,101):
        listing=versions({'page_id':params.get('page_id'),'page':page,'page_size':100})
        if listing.get('code')!=0: return None,listing
        for item in listing.get('items') or []:
            if item.get('version_no')==number: return item['version_id'],None
        if page*100>=listing.get('total',0): break
    return None,_error('VERSION_NOT_FOUND')


def version(params):
    if not params.get('page_id'): return _error('PAGE_ID_REQUIRED')
    target,error=_resolve(params)
    if error: return error
    result=_request('getStaticPageVersion',{'page_id':params['page_id'],'version_id':target})
    if result.get('code')!=0: return result
    detail=dict(result.get('version') or {})
    preview=detail.pop('preview_url',None)
    detail.pop('preview_expires_in',None)
    result={**result,'version':detail,'preview_available':bool(preview)}
    if params.get('download') is True:
        task=params.get('task_id') or C.current_trace_context().get('task_id')
        if not task: return _error('VERSION_DOWNLOAD_TASK_REQUIRED')
        if not preview: return _error('VERSION_PREVIEW_UNAVAILABLE')
        import static_page as SP
        html,error=SP._fetch_oss(preview)
        if error: return _error('VERSION_PREVIEW_DOWNLOAD_FAILED')
        content=html.encode('utf-8')
        if hashlib.sha256(content).hexdigest()!=detail.get('sha256'):
            return _error('VERSION_PREVIEW_HASH_MISMATCH')
        path=C.task_temp_path(task,'history/'+EP.digest([params['page_id'],target])+'.html',create_parent=True)
        SP._atomic_write_bytes(str(path),content)
        result['html_file']=str(path)
    return result


def _rollback_preview_context_error(page, version_id, expected_sha256):
    """Download a rollback target once and reject host-only preview context before writing."""
    result = _request('getStaticPageVersion', {'page_id': page, 'version_id': version_id})
    if result.get('code') != 0:
        return result
    detail = dict(result.get('version') or {})
    preview = detail.get('preview_url')
    if not preview:
        return _error('VERSION_PREVIEW_UNAVAILABLE')
    import static_page as SP
    html, fetch_error = SP._fetch_oss(preview)
    if fetch_error:
        return _error('VERSION_PREVIEW_DOWNLOAD_FAILED')
    import hashlib as _hashlib
    if _hashlib.sha256(html.encode('utf-8')).hexdigest() != str(expected_sha256 or ''):
        return _error('VERSION_PREVIEW_HASH_MISMATCH')
    context_error = SSC.public_preview_context_error(html)
    if context_error:
        return _error(
            'ROLLBACK_TARGET_PUBLIC_PREVIEW_CONTEXT_FORBIDDEN',
            message=context_error['message'],
        )
    return None


def _journal_path(task,page):
    return C.task_temp_path(task,'receipts/rollback-'+hashlib.sha256(page.encode()).hexdigest()[:20]+'.json',create_parent=True)


def _list_all(page):
    items=[]
    for index in range(1,101):
        listing=versions({'page_id':page,'page':index,'page_size':100})
        if listing.get('code')!=0: return listing
        items.extend(listing.get('items') or [])
        if index*100>=listing.get('total',0): return {**listing,'items':items}
    return _error('VERSION_HISTORY_LIMIT')


_CONTENT_FIELDS=('sha256','is_live','package_ids','grant_ids','managed_asset_ids','title','description',
                 'page_context','agent_reply_template','reply_contract_binding')


def _healthy(detail):
    check=detail.get('precheck') or {}
    return check.get('ok') is True and check.get('health')=='healthy' and not check.get('issues')


def _current_metadata_matches(page, target, url):
    current=SP_current(page)
    return (current.get('code')==0 and current.get('page_id')==page
            and (current.get('url') or current.get('public_url'))==url
            and all(current.get(k)==target.get(k) for k in _CONTENT_FIELDS if k!='sha256'))


def _target_identity_matches(actual, target):
    if actual.get('version_id')==target.get('version_id'):
        return actual.get('version_no')==target.get('version_no')
    return (bool(actual.get('version_id'))
            and actual.get('source_version_id')==target.get('version_id')
            and type(actual.get('version_no')) is int
            and actual['version_no']>target['version_no'])


def _verify(journal, path):
    import static_page as SP
    page=journal['page_id']
    already_current=journal.get('status')=='already_current'
    written=not already_current
    context=C.current_trace_context()
    if already_current and (journal.get('task_id')!=context.get('task_id') or journal.get('turn_id')!=context.get('turn_id')):
        return _error('ROLLBACK_IDENTITY_CONFLICT',written=False,verified=False)
    journal['verified']=False
    EP.atomic_json(path,journal)
    listing=versions({'page_id':page,'page_size':1})
    if listing.get('code')!=0: return listing
    if listing.get('current_version_id')!=journal['result']['version_id']:
        return _error('VERSION_CHANGED',written=written,verified=False)
    observed=version({'page_id':page,'version_id':journal['result']['version_id']})
    if observed.get('code')!=0: return observed
    actual=observed.get('version') or {}
    target=journal['target']
    if already_current:
        if not _healthy(observed):
            return _error('ROLLBACK_PRECHECK_FAILED',precheck=observed.get('precheck'),written=False,verified=False)
        identity_ok=(_target_identity_matches(actual,target)
                     and actual.get('version_id')==journal['result']['version_id']
                     and actual.get('version_no')==journal['result']['version_no'])
    else:
        identity_ok=actual.get('source_version_id')==target['version_id']
    if not identity_ok or any(actual.get(k)!=target.get(k) for k in _CONTENT_FIELDS):
        return _error('ROLLBACK_CONTENT_MISMATCH',written=written,verified=False)
    if already_current and not _current_metadata_matches(page,target,journal['result']['url']):
        return _error('ROLLBACK_CONTENT_MISMATCH',written=False,verified=False)
    report=SP._run_page_verifier(journal['result']['url'],'full',
                                **({'require_live_data':True} if target.get('is_live') is True else {}))
    EP.atomic_json(path.with_suffix('.browser.json'),report)
    views=(report.get('browser') or {}).get('viewports') or []
    names={v.get('viewport') for v in views}
    if (report.get('code')!=0 or (report.get('browser') or {}).get('checked') is not True
            or not {'desktop','mobile390','mobile320'}.issubset(names)
            or any(v.get('document_sha256')!=target['sha256'] for v in views)):
        return _error('ROLLBACK_PUBLIC_VERIFICATION_FAILED',written=written,verified=False,
                      operation_id=journal['operation_id'],verification_file=str(path.with_suffix('.browser.json')))
    # Browser verification and version readback must describe the same version.
    final=versions({'page_id':page,'page_size':1})
    if final.get('code')!=0 or final.get('current_version_id')!=journal['result']['version_id']:
        return _error('VERSION_CHANGED',written=written,verified=False)
    if already_current:
        final_detail=version({'page_id':page,'version_id':journal['result']['version_id']})
        final_actual=final_detail.get('version') or {}
        if (final_detail.get('code')!=0 or not _healthy(final_detail)
                or not _target_identity_matches(final_actual,target)
                or final_actual.get('version_no')!=journal['result']['version_no']
                or any(final_actual.get(k)!=target.get(k) for k in _CONTENT_FIELDS)
                or not _current_metadata_matches(page,target,journal['result']['url'])):
            return _error('ROLLBACK_CONTENT_MISMATCH',written=False,verified=False)
    journal['verified']=True
    journal['verified_turn_id']=C.current_trace_context().get('turn_id')
    journal['verification_sha256']=hashlib.sha256(path.with_suffix('.browser.json').read_bytes()).hexdigest()
    EP.atomic_json(path,journal)
    return {'code':0,**journal['result'],'operation_id':journal['operation_id'],
            'written':written,'verified':True,'restored_version_id':target['version_id'],
            'restored_version_no':target['version_no'],
            **({'rollback_outcome':'already_current',
                'message':f"当前已是V{target['version_no']}，已核验，无需恢复"} if already_current else {}),
            'verification_file':str(path.with_suffix('.browser.json'))}


def rollback(params):
    task=params.get('task_id') or C.current_trace_context().get('task_id')
    turn=C.current_trace_context().get('turn_id')
    page=params.get('page_id')
    if not task or not turn or not page: return _error('ROLLBACK_IDENTITY_REQUIRED')
    context=C.current_trace_context()
    if context.get('task_id')!=task or params.get('turn_id') not in (None,turn):
        return _error('ROLLBACK_IDENTITY_CONFLICT')
    if params.get('force') or params.get('reactivate_credentials') or params.get('restore_tags'):
        return _error('ROLLBACK_UNSAFE_OVERRIDE_FORBIDDEN')
    try:
        requested_number=DR.restore_version_number(params)
        with EP.locked(task):
            path=_journal_path(task,page)
            EP.atomic_json(C.task_temp_path(task,'receipts/rollback-current.json',create_parent=True),
                           {'task_id':task,'turn_id':turn,'page_id':page})
            journal=None
            # Use strict parsing: damaged journals must never authorize replay.
            if path.is_file():
                journal=json.loads(path.read_text(encoding='utf-8'))
            if journal and journal.get('status') in ('pending','unknown'):
                history=_list_all(page)
                if history.get('code')!=0: return _error('ROLLBACK_OUTCOME_UNKNOWN')
                candidates=[v for v in history['items'] if v.get('source_version_id')==journal['target']['version_id']
                            and v.get('task_id')==task and v.get('change_kind')=='rollback'
                            and v.get('version_no')==journal['base_version_no']+1
                            and v.get('sha256')==journal['target']['sha256']]
                if len(candidates)!=1: return _error('ROLLBACK_OUTCOME_UNKNOWN',operation_id=journal['operation_id'])
                item=candidates[0]
                # The readback proves target lineage/content, not a POST retry.
                journal.update(status='confirmed',result={**{k:item[k] for k in ('version_id','version_no','source_version_id')},
                               'page_id':page,'url':journal['public_url']})
                EP.atomic_json(path,journal)
            target_id,error=_resolve(params)
            if error: return error
            # Only a later original user message can change an explicit target.
            # A model choice/default or a matching cached write cannot authorize it.
            if requested_number is not None:
                requested_id,error=_resolve({'page_id':page,'version_no':requested_number})
                if error: return error
                if target_id!=requested_id:
                    return _error('ROLLBACK_TARGET_CONFLICT',requested_version_no=requested_number)
            if journal and journal.get('status') in ('confirmed','already_current') and journal.get('turn_id')==turn:
                if journal['target']['version_id']!=target_id: return _error('ROLLBACK_OPERATION_CONFLICT')
                return _verify(journal,path)
            listing=versions({'page_id':page,'page_size':1})
            if listing.get('code')!=0: return listing
            expected=params.get('expected_current_version_id')
            if not expected: return _error('EXPECTED_CURRENT_VERSION_REQUIRED')
            if listing.get('current_version_id')!=expected: return _error('VERSION_CHANGED')
            detail=version({'page_id':page,'version_id':target_id})
            if detail.get('code')!=0: return detail
            check=detail.get('precheck') or {}
            if not _healthy(detail):
                return _error('ROLLBACK_PRECHECK_FAILED',precheck=check)
            target=detail.get('version') or {}
            if (target.get('version_id')!=target_id or type(target.get('version_no')) is not int
                    or target['version_no']<1
                    or (requested_number is not None and target['version_no']!=requested_number)
                    or not re.fullmatch(r'[a-f0-9]{64}',str(target.get('sha256') or ''))):
                return _error('ROLLBACK_TARGET_INVALID')
            # Read current page metadata for its permanent public link. Never
            # derive a public URL from the private signed preview URL.
            current=SP_current(page)
            if current.get('code')!=0: return current
            public_url=current.get('url') or current.get('public_url')
            if not public_url: return _error('PUBLIC_URL_REQUIRED')
            active=target
            if expected!=target_id:
                active_detail=version({'page_id':page,'version_id':expected})
                if active_detail.get('code')!=0: return active_detail
                active=active_detail.get('version') or {}
            if active.get('version_id')!=expected or active.get('version_no')!=listing.get('current_version_no'):
                return _error('ROLLBACK_TARGET_INVALID')
            if _target_identity_matches(active,target):
                journal={'status':'already_current','task_id':task,'turn_id':turn,'page_id':page,
                         'operation_id':'verify_current_'+EP.digest([task,turn,page,target_id,expected])[:48],
                         'public_url':public_url,
                         'target':{k:v for k,v in target.items() if not k.startswith('preview_')},
                         'result':{'page_id':page,'url':public_url,'version_id':expected,'version_no':active['version_no'],
                                   **({'source_version_id':target_id} if expected!=target_id else {})}}
                EP.atomic_json(path,journal)
                return _verify(journal,path)
            preview_context_error = _rollback_preview_context_error(page, target_id, target.get('sha256'))
            if preview_context_error:
                return preview_context_error
            operation=params.get('operation_id') or 'rollback_'+EP.digest([task,turn,page,target_id,expected])[:48]
            if not re.fullmatch(r'[A-Za-z0-9_-]{16,100}',operation): return _error('INVALID_OPERATION')
            body={'task_id':task,'page_id':page,'version_id':target_id,'operation_id':operation,
                  'expected_current_version_id':expected,'restore_metadata':True,'restore_tags':False,
                  'reactivate_credentials':False,'force':False,'change_note':params.get('change_note') or '恢复历史版本 '+str(target.get('version_no'))}
            journal={'status':'pending','task_id':task,'turn_id':turn,'page_id':page,'operation_id':operation,
                     'base_version_no':listing['current_version_no'],'public_url':public_url,
                     'target':{k:v for k,v in target.items() if not k.startswith('preview_')}}
            EP.atomic_json(path,journal)
            try:
                result=_request('rollbackStaticPage',{},body)
            except (OSError,TimeoutError,ValueError):
                result={}
            if (result.get('code')!=0 or result.get('page_id')!=page or result.get('source_version_id')!=target_id
                    or not result.get('version_id') or result.get('version_no')!=listing['current_version_no']+1
                    or result.get('url')!=public_url):
                journal['status']='unknown'
                EP.atomic_json(path,journal)
                return _error('ROLLBACK_OUTCOME_UNKNOWN',operation_id=operation)
            journal.update(status='confirmed',result={k:result[k] for k in ('page_id','url','version_id','version_no','source_version_id')})
            EP.atomic_json(path,journal)
            return _verify(journal,path)
    except C.TraceContextError as exc:
        return _error(exc.code)
    except (EP.PlanError,OSError,ValueError,KeyError,TypeError):
        return _error('ROLLBACK_JOURNAL_INVALID')


def SP_current(page):
    import static_page as SP
    response=SP.cmd_template({'page_id':page})
    return SP._template_record(response) if response.get('code')==0 else response


def export(task,turn):
    """Current-turn restoration is independent of the previous research plan."""
    pointer=C.task_temp_path(task,'receipts/rollback-current.json')
    if not pointer.is_file(): return None
    try:
        current=json.loads(pointer.read_text(encoding='utf-8'))
        if current.get('task_id')!=task or current.get('turn_id')!=turn: return None
        page=current['page_id']
        out={'schema_version':1,'task_id':task,'turn_id':turn,'operation':'rollback',
             'page_delivery_required':True,'page_id':page,'status':'unknown'}
        path=_journal_path(task,page)
        if not path.is_file(): return out
        journal=json.loads(path.read_text(encoding='utf-8'))
        if journal.get('task_id')!=task or journal.get('page_id')!=page: return out
        status=journal.get('status')
        already_current=status=='already_current'
        if already_current and journal.get('turn_id')!=turn: return out
        if status in ('pending','unknown','confirmed'): out['write_outcome']=status
        if status in ('pending','unknown'):
            return {**out,'status':'failed','error_code':'ROLLBACK_OUTCOME_UNKNOWN'}
        report=path.with_suffix('.browser.json')
        if (status not in ('confirmed','already_current') or not journal.get('verified') or journal.get('verified_turn_id')!=turn
                or not report.is_file() or hashlib.sha256(report.read_bytes()).hexdigest()!=journal.get('verification_sha256')):
            return out
        result=journal['result'];target=journal['target']
        if already_current and not _target_identity_matches(result,target): return out
        receipt={'task_id':task,'turn_id':turn,'page_id':page,'version_no':result['version_no'],
                 'restored_version_id':target['version_id'],'restored_version_no':target['version_no'],
                 'sha256':target['sha256'],'plan_hash':EP.digest([journal['operation_id'],target['version_id']]),
                 'live_data_mode':'live' if target.get('is_live') else 'static_content_only',
                 'research_status':'unknown','delivery_kind':'result',
                 'covered_roles':['grant:'+gid for gid in target.get('grant_ids',[])]+['package:'+pid for pid in target.get('package_ids',[])]}
        if already_current:
            receipt.update(rollback_outcome='already_current',written=False,version_id=result['version_id'])
            if result.get('source_version_id'):
                receipt['source_version_id']=result['source_version_id']
        return {**out,'status':'succeeded','result_url':result['url'],'version_no':result['version_no'],
                **({'rollback_outcome':'already_current','written':False,'verified':True} if already_current else {}),
                **{k:receipt[k] for k in ('live_data_mode','research_status','delivery_kind')},
                'publication_receipt':receipt}
    except (OSError,ValueError,KeyError,TypeError):
        return None
