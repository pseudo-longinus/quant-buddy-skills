"""Current host request constrains recovery and publishing, including stale plans."""
import re
import common as C


def live_requested(query):
    """Ignore explicitly deferred followups, not the current request's live intent.

    This is a narrow scope rule, not a general natural-language classifier.
    Unknown phrasing keeps the existing conservative keyword behavior.
    """
    clauses = re.split(r'[。；;\n]+', str(query or ''))
    deferred = r'^(?:实时追问后|(?:后续|下一轮|以后|之后)(?:要求|追问|需要)|(?:如果|若|当)(?:用户|我)(?:追问|要求).*?(?:实时|自动更新|持续刷新))'
    active = [part for part in clauses if not (
        re.search(deferred, part.strip()) and not re.search(r'现在|本轮|立即|马上', part))]
    return bool(re.search(r'实时|持续刷新|自动更新|不再是昨天', '\n'.join(active)))



def current_query(params):
    host=C.host_trace_context(params)
    context=C.current_trace_context()
    context_query=(context.get('user_query') if not params.get('task_id')
                   or context.get('task_id') in (None,params['task_id']) else None)
    return str((host or {}).get('user_query') or params.get('user_query')
               or context_query or '')


def live_required(params):
    # A positive current request cannot be weakened by a stale false parameter.
    query=current_query(params)
    # Quoted examples and explicitly negated capabilities are not requests.
    # Remove only those mentions; a separate positive instruction still counts.
    query=re.sub(r'“[^”]*”|「[^」]*」|‘[^’]*’|"[^"\n]*"|\'[^\'\n]*\'', '', query)
    query=re.sub(r'(?<!不)(?<!不是)(?<!并非)(?:不(?:要|要求|需要|用)|无需|无须|勿|别|禁止|不能)'
                 r'\s*(?:再|进行|使用|启用|开启)?\s*(?:实时|持续刷新|自动更新)', '', query)
    return params.get('require_live_data') is True or live_requested(query)


def _is_composition_select_grant_role(role, task_id):
    if not isinstance(role, dict) or role.get('kind') != 'grant':
        return False
    if role.get('grant_kind') == 'composition_select':
        return True
    contract = role.get('contract')
    if isinstance(contract, dict) and contract.get('kind') == 'composition_select':
        return True
    receipt_file = role.get('validation_receipt_file')
    if not receipt_file or not isinstance(receipt_file, str):
        return False
    try:
        import json as _json
        from pathlib import Path as _Path
        p = _Path(receipt_file)
        if not p.is_file() or p.stat().st_size > 256 * 1024:
            return False
        rec = _json.loads(p.read_text(encoding='utf-8'))
        if (
            not isinstance(rec, dict)
            or rec.get('version') != 'grant_validation_receipt_v1'
            or rec.get('kind') != 'composition_select'
            or rec.get('status') != 'completed'
            or rec.get('success') is not True
        ):
            return False
        if task_id and str(rec.get('task_id') or '') != str(task_id):
            return False
        expected_fp = role.get('contract_fingerprint')
        if expected_fp and str(rec.get('contract_fingerprint') or '') != str(expected_fp):
            return False
        return True
    except (OSError, ValueError, TypeError):
        return False


def _has_live_registration_block(task):
    if not task:
        return False
    try:
        import json as _json
        blocked_path = C.task_temp_path(task, 'receipts/live-registration-blocked.json')
        if blocked_path.is_file():
            rec = _json.loads(blocked_path.read_text(encoding='utf-8'))
            if isinstance(rec, dict) and rec.get('task_id') == task and rec.get('error_code'):
                return True
    except Exception:
        pass
    return False


def _has_task_registered_grants(task):
    if not task:
        return False
    try:
        cred_dir = C.task_temp_path(task, 'credentials/grant')
        if cred_dir.is_dir() and any(cred_dir.glob('*.json')):
            return True
    except Exception:
        pass
    return False


def _has_verified_snapshot_evidence(params, plan=None, task=None):
    p = params if isinstance(params, dict) else {}
    if p.get('validation_receipt_files') or p.get('validation_receipt_file') or p.get('snapshot_roles'):
        return True
    if p.get('grant_ids') or p.get('data_grants') or p.get('registered_grants'):
        return True
    if isinstance(plan, dict) and (plan.get('snapshot_roles') or plan.get('runtime_roles')):
        return True
    if task and _has_task_registered_grants(task):
        return True
    return False


def is_authorized_recovery_fallback(params, plan=None):
    """True when the target plan/upload is an authorized degraded fallback for
    this turn: either (a) a bounded recover_delivery plan bound via
    degraded_plan_hash, or (b) a verified_snapshot upload/update after live
    formula/grant validation or registration failed with a real platform/quota/auth
    error in this task.
    """
    task = (plan or {}).get('task_id') or (params or {}).get('task_id') or C.current_trace_context().get('task_id')
    if not task:
        return False
    mode = str((params or {}).get('live_data_mode') or (plan or {}).get('live_data_mode') or '').strip()
    inferred_snapshot = (not mode) and _has_verified_snapshot_evidence(params, plan, task=task)
    if mode not in ('verified_snapshot', 'researched_static') and not inferred_snapshot:
        return False
    # Case (b): Bespoke verified_snapshot / partial-live fallback after real registration/quota block.
    if (mode == 'verified_snapshot' or inferred_snapshot) and _has_live_registration_block(task):
        return True
    if inferred_snapshot:
        return False
    if plan is None:
        import execution_plan as EP
        plan = EP.load(task)
    if not isinstance(plan, dict) or not plan.get('plan_hash'):
        return False
    import delivery_recovery as DR
    rstate = DR.load(task)
    if not isinstance(rstate, dict) or rstate.get('degraded_plan_hash') != plan['plan_hash']:
        return False
    if mode == 'verified_snapshot':
        return bool(plan.get('snapshot_roles'))
    if mode == 'researched_static':
        return rstate.get('researched_static_plan_hash') == plan['plan_hash']
    return False


DEGRADED_LIVE_FALLBACK_MODES = ('verified_snapshot', 'researched_static')


def is_degraded_live_fallback(params, plan=None, *, live_data_mode=None):
    """True when a live-required task legitimately fell back to an authorized snapshot/researched static mode."""
    p = dict(params or {})
    if isinstance(plan, dict) and plan.get('require_live_data') is True and p.get('require_live_data') is not True:
        p['require_live_data'] = True
    if not live_required(p):
        return False
    mode = str(live_data_mode or p.get('live_data_mode') or (plan or {}).get('live_data_mode') or '').strip()
    if mode not in DEGRADED_LIVE_FALLBACK_MODES:
        return False
    return is_authorized_recovery_fallback({**p, 'live_data_mode': mode}, plan)


def live_delivery_error(params, plan=None):
    """Reject an explicit live delivery before it can infer a stale data scope."""
    if not live_required(params):
        return None
    if plan is None:
        import execution_plan as EP
        plan = EP.load(params.get('task_id') or C.current_trace_context().get('task_id'))
    if not isinstance(plan, dict):
        return None
    if is_authorized_recovery_fallback(params, plan):
        return None
    scope = plan.get('target_scope') if isinstance(plan.get('target_scope'), dict) else {}
    task = plan.get('task_id') or params.get('task_id')
    if plan.get('require_live_data') is not True:
        return {
            'code': 1,
            'error': 'CURRENT_LIVE_PLAN_REQUIRED',
            'message': '本轮要求实时；先把当前计划升级为实时并绑定所需数据角色，不能沿用旧快照计划发布。',
            'published': False,
            'verified': False,
            'written': False,
            'terminal': False,
            'next_action': {
                'command': 'execution_plan',
                'params': {
                    'task_id': task,
                    'expected_revision': plan.get('revision'),
                    'require_live_data': True,
                    'revision_reason': 'current_live_requirement',
                },
            },
        }
    if scope.get('kind') == 'unspecified':
        return {
            'code': 1,
            'error': 'CURRENT_LIVE_SCOPE_REQUIRED',
            'message': '本轮要求实时交付；先在当前计划中声明目标范围，再用同范围的动态取数证据发布。保留原页，未写入。',
            'published': False,
            'verified': False,
            'written': False,
            'terminal': False,
            'next_action': {
                'command': 'execution_plan',
                'params': {
                    'task_id': task,
                    'expected_revision': plan.get('revision'),
                    'revision_reason': 'current_live_scope',
                },
                'instruction': '绑定本轮结果角色、目标范围和观察时点；没有同范围的动态证据时停止发布并保留原页。',
            },
        }
    if plan.get('research_status') != 'complete' or plan.get('delivery_kind') != 'result':
        return {
            'code': 1,
            'error': 'CURRENT_LIVE_DELIVERY_INCOMPLETE',
            'message': '本轮明确要求实时；当前计划未证明本轮研究完整。先核验当前结果，再构建或发布页面。保留原页，未写入。',
            'published': False,
            'verified': False,
            'written': False,
            'terminal': False,
            'next_action': {
                'command': 'execution_plan',
                'params': {
                    'task_id': task,
                    'expected_revision': plan.get('revision'),
                    'revision_reason': 'current_live_research_incomplete',
                },
                'instruction': ('先复用当轮已验证的 QBS 数据及收据，对照用户要求核验标的、字段、行数/时间范围和实际观察日期。'
                                '证据齐备再提交 execution_plan 的 complete/result 及适用的研究审计；授权注册和路由绑定成功不能代替核验。'
                                '证据不齐时说明缺项并交付已验证正文，不写页面、不把部分研究或静态页当作实时结果。'),
            },
        }
    contract = plan.get('research_contract') if isinstance(plan.get('research_contract'), dict) else {}
    explicit_members = scope.get('assets') or scope.get('members') or scope.get('asset_ids')
    needs_result_contract = (
        scope.get('kind') in ('sector', 'market')
        or (scope.get('kind') == 'basket' and not (
            isinstance(explicit_members, list) and explicit_members
        ))
    )
    result_role = str(contract.get('selection_output') or '').strip()
    if needs_result_contract and not result_role:
        return {
            'code': 1,
            'error': 'CURRENT_LIVE_RESEARCH_CONTRACT_REQUIRED',
            'message': '本轮实时集合结果没有绑定结果合同和结果角色；行情请求成功不能证明名单已按当前范围重算。保留原页，未写入。',
            'published': False,
            'verified': False,
            'written': False,
            'terminal': False,
            'next_action': {
                'command': 'execution_plan',
                'params': {
                    'task_id': task,
                    'expected_revision': plan.get('revision'),
                    'revision_reason': 'current_live_result_contract',
                },
                'instruction': '先冻结本轮结果角色、成员范围和观察时点，再绑定同范围的动态运行证据。',
            },
        }
    if result_role:
        covered = False
        is_composition_contract = contract.get('selection_source') == 'composition_select'
        for role in plan.get('runtime_roles') or []:
            if not isinstance(role, dict):
                continue
            outputs = role.get('required_outputs') or role.get('outputs')
            role_kind_ok = (
                role.get('kind') == 'package'
                or (is_composition_contract and _is_composition_select_grant_role(role, task))
            )
            if role_kind_ok and (
                role.get('role_id') == result_role
                or (isinstance(outputs, list) and result_role in outputs)
            ):
                covered = True
                break
        if not covered:
            return {
                'code': 1,
                'error': 'CURRENT_LIVE_RESULT_ROLE_REQUIRED',
                'message': '本轮实时结果角色没有对应的动态运行角色覆盖；不能用其他行情或旧快照代替。保留原页，未写入。',
                'published': False,
                'verified': False,
                'written': False,
                'terminal': False,
                'result_role': result_role,
                'next_action': {
                    'command': 'execution_plan',
                    'params': {
                        'task_id': task,
                        'expected_revision': plan.get('revision'),
                        'revision_reason': 'bind_current_live_result_role',
                    },
                    'instruction': '把本轮结果角色绑定到同范围的动态运行角色，并提供对应真实取数核验后再发布。',
                },
            }
        try:
            from research_contract import metadata
            metadata({
                'research_contract': contract,
                'research_status': plan.get('research_status'),
                'delivery_kind': plan.get('delivery_kind'),
                'research_checks': plan.get('research_checks'),
            }, task)
        except ValueError:
            return {
                'code': 1,
                'error': 'CURRENT_LIVE_COVERAGE_EVIDENCE_REQUIRED',
                'message': '本轮实时结果缺少同范围的完整覆盖、行数或观察时点证据；不能用固定池或旧快照代替。保留原页，未写入。',
                'published': False,
                'verified': False,
                'written': False,
                'terminal': False,
                'result_role': result_role,
                'next_action': {
                    'command': 'execution_plan',
                    'params': {
                        'task_id': task,
                        'expected_revision': plan.get('revision'),
                        'revision_reason': 'current_live_coverage_evidence',
                    },
                    'instruction': '补齐合同哈希、完整股票范围、逐行覆盖和实际观察日期证据；仍不完整时停止发布。',
                },
            }
    return None


def live_build_handoff(params, plan):
    """Expose the publisher's live research boundary before suggesting a build."""
    blocked = live_delivery_error(params, plan)
    if blocked is None:
        return {}
    action = blocked['next_action']
    return {
        'draft_ready': False,
        'publication_readiness': {'ready': False, 'error': blocked['error'],
                                  'message': blocked['message'],
                                  'research_status': plan.get('research_status', 'unknown')},
        'next_action': {**action, 'params': {**action['params'], 'require_live_data': True}},
    }


def manual_plan_handoff(params, plan):
    """Choose one next action for a live manual build, never attest a registration here."""
    if not live_required(params):
        return {}
    scope_ready = (plan.get('target_scope') or {}).get('kind') not in (None, 'unspecified')
    roles = plan.get('runtime_roles') or []
    refs_ready = bool(roles) and all(role.get(f"{role['kind']}_id") and role.get('validation_receipt_file')
                                     and role.get('contract_fingerprint') for role in roles)
    # While collecting roles, say what to collect instead of telling the caller
    # to finish research it cannot yet perform. Scope/research checks are the
    # publisher's own and a completed plan still needs a verified route.
    if scope_ready and not refs_ready:
        return {'draft_ready': False, 'next_action': {'command': 'execution_plan',
                'params': {'task_id': plan['task_id'], 'expected_revision': plan['revision'],
                           'revision_reason': 'bind_live_role_references', 'require_live_data': True},
                'instruction': '按本轮明确范围收集运行角色。已有授权时复用对应注册结果的 plan_role_reference 并补业务 role_id；多份候选按合同匹配，不猜测、不重复登记。'}}
    handoff = live_build_handoff(params, plan)
    if handoff:
        action = handoff['next_action']
        action.setdefault('instruction', handoff['publication_readiness']['message'])
        if not scope_ready:
            action['instruction'] = ('按本轮已明确的标的填写 target_scope；可同时提交对应已登记授权的 '
                                     'plan_role_reference 加业务 role_id。不要重新询问已知标的、重新注册或先写 HTML。')
        return handoff
    return {'next_action': {'command': 'bind_runtime_route',
            'params': {'task_id': plan['task_id'], 'page_id': plan['target_page_id'], 'plan_hash': plan['plan_hash']},
            'instruction': '用当前计划绑定已登记资源。若需复用旧轮原收据，先 interpret 核验原页维护权限，再显式传 reuse_verified_registrations:true；不改收据、不重登记。仅在路由核验通过后构建页面。'}}


def restore_version_number(params):
    query=current_query(params)
    # A quoted version token is still a target; quoted instructions are text.
    query=re.sub(r'“[^”]*”|「[^」]*」|‘[^’]*’|"[^"\n]*"|\'[^\'\n]*\'',
                 lambda m: m.group(0)[1:-1] if re.fullmatch(
                     r'\s*[vV]\s*[1-9][0-9]*\s*',m.group(0)[1:-1]) else '',query)
    query=re.sub(r'(?:不(?:要|要求|需要|用)?|无需|无须|勿|别|禁止|不能)\s*'
                 r'(?:再|执行|进行)?\s*(?:回退|回滚|恢复)\s*(?:到|至|为)?\s*'
                 r'(?:版本\s*)?[vV]\s*[1-9][0-9]*(?![0-9.])','',query)
    match=re.search(r'(?:回退|回滚|恢复)\s*(?:到|至|为)?\s*(?:版本\s*)?[vV]\s*([1-9][0-9]*)(?![0-9.])',query)
    return int(match[1]) if match else None


def restore_requested(params):
    return restore_version_number(params) is not None


def restore_boundary(params, plan=None):
    if not restore_requested(params): return None
    task=params.get('task_id') or C.current_trace_context().get('task_id')
    page=(plan or {}).get('target_page_id') or params.get('page_id')
    return {'code':1,'error':'ROLLBACK_WORKFLOW_REQUIRED','terminal':False,
            'message':'本轮要求恢复历史版本；先查询并核对目标版本，不能继续构建或发布旧研究内容',
            'next_action':{'command':'versions','params':{'task_id':task,**({'page_id':page} if page else {})}}}


def recovery_boundary(params, plan=None, state=None):
    task=params.get('task_id') or C.current_trace_context().get('task_id')
    page=(plan or {}).get('target_page_id') or params.get('page_id')
    blocked=restore_boundary(params,plan)
    if blocked: return blocked
    if live_required(params) and not ((state or {}).get('turn_id')==C.current_trace_context().get('turn_id')
                                   and (state or {}).get('verified') and (state or {}).get('live_data_mode') in ('live','mixed')):
        # Allow recovery when the current plan already honors require_live_data=True
        # and has either hit a layout-only failure (where recover preserves live
        # bindings) or exhausted/failed candidate builds in this turn.
        if isinstance(plan, dict) and plan.get('require_live_data') is True and task:
            import delivery_recovery as DR
            rstate = DR._turn_state(task, params)
            if ((plan.get('runtime_roles') and DR.is_layout_only_failure(rstate))
                    or int(rstate.get('failures', 0) or 0) >= 1
                    or int(rstate.get('compose_builds', 0) or 0) >= DR.BUILD_BUDGET
                    or _has_live_registration_block(task)):
                return None
        return {'code':1,'error':'LIVE_REQUIREMENT_NOT_SATISFIED','terminal':False,
                'preserved_existing_page':bool(page),'page_id':page,
                'message':'本轮自动更新尚未核验；保留原页，按当前要求完成数据绑定与真实取数验收',
                'next_action':{'command':'interpret' if page else 'templates',
                               'params':{'task_id':task,**({'page_id':page} if page else {'recommend':'all'})}}}
    return None
