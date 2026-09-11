"""Task-scoped registration lineage for Grants and Formula Packages.

Local locking and sealed receipts are recovery aids, not server idempotency/CAS.
Uncertain writes never trigger another registration automatically.
"""
import copy
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import common as C
import execution_plan as EP

ID_FIELDS = {'grant': 'grant_id', 'package': 'package_id'}

class CredentialError(EP.PlanError):
    pass


def task_of(params=None):
    return str((params or {}).get('task_id') or C.current_trace_context().get('task_id') or '').strip()


def validate_id(resource, identifier):
    prefix = r'(?:dg|grant)' if resource == 'grant' else 'pkg'
    if not isinstance(identifier,str) or (not re.fullmatch(prefix+r'_[A-Za-z0-9._-]+',identifier) or '..' in identifier):
        raise CredentialError('CREDENTIAL_ID_INVALID','凭证ID格式无效，禁止路径片段')
    return identifier


def _read(path):
    try:
        value=json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:return None
    except (OSError,ValueError) as exc:raise CredentialError('REGISTRATION_STATE_INVALID','注册状态不可读') from exc
    if not isinstance(value,dict) or value.get('record_hash')!=EP.digest({k:v for k,v in value.items() if k!='record_hash'}):
        raise CredentialError('REGISTRATION_STATE_INVALID','注册状态hash不一致，不能当成未注册')
    return value


def _write(path,value,private=False):
    record={k:v for k,v in value.items() if k!='record_hash'}
    record['record_hash']=EP.digest(record)
    EP.atomic_json(path,record)
    if private and os.name!='nt':os.chmod(path,0o600)
    return record


def _secret_path(task,resource,identifier):
    validate_id(resource,identifier)
    return C.task_temp_path(task,f'credentials/{resource}/{identifier}.json')


def _index_path(task,resource,fingerprint):
    if not re.fullmatch(r'[a-f0-9]{64}',str(fingerprint)):
        raise CredentialError('REGISTRATION_FINGERPRINT_INVALID','合同fingerprint无效')
    return C.task_temp_path(task,f'receipts/registrations/{resource}/{fingerprint}.json')


def _id_path(task,resource,identifier):
    validate_id(resource,identifier)
    return C.task_temp_path(task,f'receipts/registrations/{resource}/by-id/{identifier}.json')


def _context(endpoint,key):return EP.digest({'endpoint':str(endpoint).rstrip('/'),'principal':hashlib.sha256(str(key).encode()).hexdigest()})


def _proof(task,fingerprint,path,required=False):
    if not path:
        if required:raise CredentialError('REGISTRATION_VALIDATION_REQUIRED','先验证目标合同，再传validation_receipt_file注册')
        return None
    try:
        raw=Path(path).read_bytes();value=json.loads(raw)
    except (OSError,ValueError,TypeError) as exc:raise CredentialError('REGISTRATION_VALIDATION_REQUIRED','验证收据不可读') from exc
    if not isinstance(value,dict) or value.get('task_id')!=task or value.get('success') is not True or value.get('status')!='completed' or value.get('contract_fingerprint')!=fingerprint:
        raise CredentialError('REGISTRATION_VALIDATION_MISMATCH','验证收据不属于当前任务/已完成合同')
    return {'file':str(Path(path).resolve()),'sha256':hashlib.sha256(raw).hexdigest()}


def _active(record):
    status=record.get('status')
    if status=='revoked':raise CredentialError('REGISTRATION_REVOKED','凭证已撤销；不能自动重新注册')
    if status!='confirmed':raise CredentialError('REGISTRATION_OUTCOME_UNKNOWN','前一次注册/轮换结果不确定，先查询恢复状态，不重复注册',next_action='registration_status')
    try:
        expiry=datetime.fromisoformat(str(record['expires_at']).replace('Z','+00:00'))
        if expiry.tzinfo is None:raise ValueError()
    except (KeyError,ValueError,TypeError):raise CredentialError('CREDENTIAL_EXPIRY_REQUIRED','缺少可信有效期；先核验/刷新同一凭证，不新建替代项')
    if expiry<=datetime.now(timezone.utc):raise CredentialError('REGISTRATION_EXPIRED','凭证已到期，显式刷新同一ID，不自动重复注册')


def save_legacy(resource,response,legacy_dir):
    identifier=validate_id(resource,response.get(ID_FIELDS[resource]))
    if not response.get('signature'):return None
    path=Path(legacy_dir)/f'{identifier}.json'
    record={key:copy.deepcopy(response.get(key)) for key in (ID_FIELDS[resource],'signature','kind','outputs','whitelist_fields','whitelist_indicators','expires_at')}
    EP.atomic_json(path,record)
    return str(path)


def load(resource,identifier,legacy_dir,task=None):
    validate_id(resource,identifier)
    task=task if task is not None else task_of()
    if task:
        path=_secret_path(task,resource,identifier)
        record=_read(path)
        if record:
            if record.get('task_id')!=task or record.get(ID_FIELDS[resource])!=identifier or record.get('resource')!=resource:
                raise CredentialError('REGISTRATION_IDENTITY_CONFLICT','凭据文件身份不一致')
            if record.get('disabled'):return None
            return record
    path=Path(legacy_dir)/f'{identifier}.json'
    try:return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:return None
    except (OSError,ValueError) as exc:raise CredentialError('CREDENTIAL_FILE_INVALID','旧版凭据损坏，不能猜测恢复') from exc


def verify_binding(task,resource,identifier,fingerprint,require_active=True):
    record=_read(_id_path(task,resource,identifier))
    if not record:raise CredentialError('REGISTRATION_RECEIPT_REQUIRED','该ID缺少当前任务的注册收据',credential_id=identifier)
    if record.get('task_id')!=task or record.get('resource')!=resource or record.get('credential_id')!=identifier or record.get('contract_fingerprint')!=fingerprint:
        raise CredentialError('REGISTRATION_CONTRACT_MISMATCH','凭证ID不属于已验证的目标合同')
    indexed=_read(_index_path(task,resource,fingerprint))
    if not indexed or indexed.get('record_hash')!=record.get('record_hash'):
        raise CredentialError('REGISTRATION_STATE_CONFLICT','注册索引不一致，停止并恢复状态')
    if require_active:_active(record)
    elif record.get("status") != "confirmed":raise CredentialError("REGISTRATION_OUTCOME_UNKNOWN","凭据管理状态尚未确认")
    secret=_read(_secret_path(task,resource,identifier))
    if not secret or secret.get('disabled') or secret.get('contract_fingerprint')!=fingerprint or secret.get('registration_context')!=record.get('registration_context'):
        raise CredentialError('REGISTRATION_CREDENTIAL_MISMATCH','凭据与注册合同不一致')
    if record.get('credential_record_hash')!=secret.get('record_hash'):
        raise CredentialError('REGISTRATION_CREDENTIAL_MISMATCH','注册记录与当前签名版本不一致')
    return record


def _write_record(task,resource,record):
    sealed=_write(_index_path(task,resource,record['contract_fingerprint']),record)
    if record.get('credential_id'):_write(_id_path(task,resource,record['credential_id']),sealed)
    return sealed


def _response(resource,record,secret,reused):
    identifier=record['credential_id']
    receipt=_id_path(record['task_id'],resource,identifier)
    out={key:copy.deepcopy(secret.get(key)) for key in (ID_FIELDS[resource],'signature','kind','outputs','whitelist_fields','whitelist_indicators','expires_at') if secret.get(key) is not None}
    out.update(code=0,contract_fingerprint=record['contract_fingerprint'],registration_reused=reused,
               registration_receipt_file=str(receipt),registration_receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
               _saved_credential=str(_secret_path(record['task_id'],resource,identifier)))
    return out


def register(resource,params,contract,endpoint,key,send,legacy_dir):
    task=task_of(params);fingerprint=EP.digest(contract)
    if not task:
        response=send()
        if not isinstance(response,dict):return {'code':1,'error':'REGISTRATION_RESPONSE_INVALID'}
        if response.get('code')==0 and response.get(ID_FIELDS[resource]):
            response['_saved_credential']=save_legacy(resource,response,legacy_dir)
        return response
    proof=_proof(task,fingerprint,params.get('validation_receipt_file'),required=bool(EP.load(task)))
    context=_context(endpoint,key)
    with EP.locked(task):
        identity_path=C.task_temp_path(task,'receipts/registrations/identity.json')
        identity=_read(identity_path)
        if identity and identity.get('registration_context')!=context:
            raise CredentialError('REGISTRATION_CONTEXT_CONFLICT','同一任务不能混入不同身份或endpoint的运行凭据')
        if not identity:_write(identity_path,{'task_id':task,'registration_context':context})
        record=_read(_index_path(task,resource,fingerprint))
        if record:
            if record.get('registration_context')!=context:raise CredentialError('REGISTRATION_CONTEXT_CONFLICT','任务凭证身份或endpoint变化，不能复用旧授权')
            if record.get('ttl_days')!=params.get('ttl_days'):raise CredentialError('REGISTRATION_OPTIONS_CHANGED','有效期选项变化，请刷新同一凭证')
            _active(record)
            verify_binding(task,resource,record['credential_id'],fingerprint)
            secret=_read(_secret_path(task,resource,record['credential_id']))
            return _response(resource,record,secret,True)
        record={'version':'qbv_runtime_registration_v1','resource':resource,'task_id':task,'contract':copy.deepcopy(contract),
                'contract_fingerprint':fingerprint,'registration_context':context,'endpoint':str(endpoint).rstrip('/'),
                'ttl_days':params.get('ttl_days'),'validation_receipt':proof,'status':'pending','started_at':datetime.now(timezone.utc).isoformat()}
        _write_record(task,resource,record)
        try:response=send()
        except Exception:
            record['status']='unknown';_write_record(task,resource,record)
            raise CredentialError('REGISTRATION_OUTCOME_UNKNOWN','注册请求结果不确定，不重发')
        if not isinstance(response,dict) or response.get('code')!=0 or not response.get(ID_FIELDS[resource]) or not response.get('signature'):
            record['status']='unknown';_write_record(task,resource,record)
            raise CredentialError('REGISTRATION_OUTCOME_UNKNOWN','未取得可持久化注册结果，不再次创建')
        try:
            identifier=validate_id(resource,response[ID_FIELDS[resource]])
            if resource=='grant' and response.get('kind') not in (None,contract['kind']):
                raise CredentialError('REGISTRATION_RESPONSE_MISMATCH','注册返回kind与请求不一致')
            secret={k:copy.deepcopy(response.get(k)) for k in (ID_FIELDS[resource],'signature','kind','outputs','whitelist_fields','whitelist_indicators','expires_at')}
            secret.update(resource=resource,task_id=task,contract_fingerprint=fingerprint,registration_context=context,
                          kind=contract.get('kind') if resource=='grant' else 'formula_package')
            secret=_write(_secret_path(task,resource,identifier),secret,private=True)
            record.update(status='confirmed',credential_id=identifier,expires_at=response.get('expires_at'),credential_record_hash=secret['record_hash'])
            record=_write_record(task,resource,record)
        except (OSError,ValueError):
            record['status']='unknown';_write_record(task,resource,record)
            raise CredentialError('REGISTRATION_OUTCOME_UNKNOWN','注册响应无法安全落盘，不再次创建')
        return {**response,**_response(resource,record,secret,False)}


def mutate(resource,params,endpoint,key,send,legacy_dir,operation):
    identifier=validate_id(resource,params.get(ID_FIELDS[resource]));task=task_of(params)
    if not task or not _read(_id_path(task,resource,identifier)):
        if task and EP.load(task):raise CredentialError('REGISTRATION_RECEIPT_REQUIRED','先恢复当前任务的注册证据再管理凭证')
        result=send()
        if isinstance(result,dict) and result.get('code')==0:
            legacy=load(resource,identifier,legacy_dir,task='')
            if legacy and result.get('signature'):
                legacy.update(signature=result['signature']);legacy.update({k:result[k] for k in ('expires_at',) if k in result})
                result['_credential_updated']=save_legacy(resource,legacy,legacy_dir)
        return result
    with EP.locked(task):
        record=_read(_id_path(task,resource,identifier))
        if record.get('registration_context')!=_context(endpoint,key):raise CredentialError('REGISTRATION_CONTEXT_CONFLICT','管理凭证的身份与注册身份不一致')
        if record['status']!='confirmed':raise CredentialError('REGISTRATION_OUTCOME_UNKNOWN','前一次操作状态未核实')
        verify_binding(task,resource,identifier,record['contract_fingerprint'],require_active=False)
        record.update(status='pending',operation=operation);_write_record(task,resource,record)
        try:result=send()
        except Exception:result=None
        if not isinstance(result,dict) or result.get('code')!=0 or (operation=='refresh' and params.get('rotate_signature') and not result.get('signature')):
            record['status']='unknown';_write_record(task,resource,record)
            raise CredentialError('REGISTRATION_OUTCOME_UNKNOWN','凭证管理结果不确定，不自动再次执行')
        secret=_read(_secret_path(task,resource,identifier))
        if not secret:raise CredentialError('REGISTRATION_CREDENTIAL_MISMATCH','本地凭证丢失，保留不确定状态')
        if operation=='revoke':secret['disabled']=True;record['status']='revoked'
        else:
            if result.get('signature'):secret['signature']=result['signature']
            if result.get('expires_at') is not None:secret['expires_at']=result['expires_at'];record['expires_at']=result['expires_at']
            record['status']='confirmed'
        secret=_write(_secret_path(task,resource,identifier),secret,private=True)
        record['credential_record_hash']=secret['record_hash'];_write_record(task,resource,record)
        return {**result,'_credential_updated':str(_secret_path(task,resource,identifier))}


def status(resource,params):
    task=task_of(params)
    if not task:raise CredentialError('REGISTRATION_TASK_REQUIRED','查询注册状态需要task_id')
    identifier=params.get(ID_FIELDS[resource])
    record=_read(_id_path(task,resource,identifier)) if identifier else _read(_index_path(task,resource,str(params.get('contract_fingerprint') or '')))
    return {'code':0,'registration':record,'remote_checked':False,'message':'仅本地注册证据；未知状态不能据此重发注册'}
