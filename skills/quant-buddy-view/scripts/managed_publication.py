"""Prove the candidate's actual signed bindings on the current Host transport.

Only opaque resource IDs reach the browser verifier. Do not register, repair, or
substitute credentials here. Public endpoints are server-selected, never the proxy.
"""
import common as C
import runtime_credentials as RC
import fork_runtime_contract as FRC



def resolve(params, proofs, *, page_id=None):
    task = RC._host_task(params)
    cfg = C.load_config()
    if not cfg.get('api_key'): raise RC.CredentialError('AUTH_CONTEXT_UNAVAILABLE', '缺少宿主取数连接；保留原页')
    endpoint = RC._host_endpoint(C.endpoint_of(cfg))
    identity = RC._read(C.task_temp_path(task, RC._CONTEXT_PATH))
    expected = identity.get('registration_context') if identity and identity.get('version') == RC.V2 else None
    result = RC._resolve_host_context(task, endpoint, cfg['api_key'], expected=expected, proofs=proofs,
                                      publication={'publication_page_id': page_id})
    public = result.get('public_skill_endpoint')
    if result.get('publication_verified') is not True or public not in RC.PUBLIC_ENDPOINTS:
        raise RC.CredentialError('AUTH_CONTEXT_UNAVAILABLE', '当前后台未提供受核验的公开取数地址；保留原页')
    return {'endpoint': public, 'bindings': [{k:p[k] for k in ('resource','credential_id')} for p in proofs]}


def public_endpoint(params, endpoint):
    return resolve(params, [])['endpoint'] if C.host_managed_lifecycle() else endpoint


def candidate(params, html, *, required, plan=None):
    if not C.host_managed_lifecycle(): return None, []
    # Never publish a run-scoped capability accidentally embedded by a compiler.
    import os
    for name in ('QB_HOST_RUNTIME_REGISTRATION_ENDPOINT','QB_HOST_SKILL_ENDPOINT'):
        private = os.environ.get(name, '').strip().rstrip('/')
        if private and private in html:
            raise RC.CredentialError('PRIVATE_ENDPOINT_IN_PAGE', '候选包含后台临时代理；使用公开取数地址，未提交页面')
    pairs = FRC.discover_credential_pairs(html)
    if not pairs:
        if required: raise RC.CredentialError('REGISTRATION_REMOTE_PROOF_REQUIRED', '实时页面没有可核验的 Grant 或 Formula Package，保留原页')
        return None, []
    bound = {(p['kind'],p['credential_id']) for p in pairs}
    mandatory = set()
    for role in (plan or {}).get('runtime_roles', []):
        kind = role.get('kind')
        identifier = role.get(RC.ID_FIELDS.get(kind))
        if not identifier: continue
        RC.verify_binding(RC._host_task(params),kind,identifier,role.get('contract_fingerprint'))
        mandatory.add((kind,identifier))
    if not mandatory.issubset(bound):
        raise RC.CredentialError('REGISTRATION_CONTRACT_MISMATCH', '候选页面缺少计划中已登记的授权；保留原页，不新建替代授权')
    proofs = [RC._remote_proof(p['kind'], p, signature=p['signature']) for p in pairs]
    task = RC._host_task(params)
    for proof in proofs:
        kind,identifier=proof['resource'],proof['credential_id']
        record = RC._read(RC._id_path(task,kind,identifier))
        if record:
            RC.verify_binding(task,kind,identifier,record.get('contract_fingerprint'))
        else:
            # A resource absent from the task journal is not a new registration by this task.
            # Only the specific target's existing, remotely verified binding can supply lineage.
            proof['require_previous_binding'] = True
    policy = resolve(params, proofs, page_id=params.get('page_id'))
    policy['required_ids'] = sorted(id for _,id in mandatory)
    return policy, proofs
