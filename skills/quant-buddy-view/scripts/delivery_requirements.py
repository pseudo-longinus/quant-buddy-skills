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


def live_delivery_error(params, plan=None):
    """Reject an explicit live delivery before it can infer a stale data scope."""
    if not live_required(params):
        return None
    if plan is None:
        import execution_plan as EP
        plan = EP.load(params.get('task_id') or C.current_trace_context().get('task_id'))
    if not isinstance(plan, dict):
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
            'message': '本轮明确要求实时；当前计划仍是部分研究。完成当前要求的动态取数与核验后再发布，保留原页，未写入。',
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
                'instruction': '补齐本轮要求的动态结果、范围和观察时点；证据仍不完整时停止，不以部分研究或静态页完成实时要求。',
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
        for role in plan.get('runtime_roles') or []:
            if not isinstance(role, dict):
                continue
            outputs = role.get('required_outputs') or role.get('outputs')
            if role.get('kind') == 'package' and (
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
        return {'code':1,'error':'LIVE_REQUIREMENT_NOT_SATISFIED','terminal':False,
                'preserved_existing_page':bool(page),'page_id':page,
                'message':'本轮自动更新尚未核验；保留原页，按当前要求完成数据绑定与真实取数验收',
                'next_action':{'command':'interpret' if page else 'templates',
                               'params':{'task_id':task,**({'page_id':page} if page else {'recommend':'all'})}}}
    return None
