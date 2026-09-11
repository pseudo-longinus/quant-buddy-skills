"""Immutable, task-bound data snapshots produced by successful data validation."""
import hashlib
import copy
import json
from datetime import datetime,timezone
from pathlib import Path
import common as C
import execution_plan as EP

VERSION='qbv_verified_snapshot_v1'


def capture(task_id,contract,result,resource='grant',hydrate_csv=False):
    if not task_id or not isinstance(result,dict) or result.get('code') not in (0,None) or result.get('success') is False:
        raise EP.PlanError('SNAPSHOT_VALIDATION_REQUIRED','只可保存已成功验证的数据')
    if resource not in ('grant','package'):raise EP.PlanError('SNAPSHOT_RESOURCE_INVALID','未知数据源类型')
    result=copy.deepcopy(result)
    materialized=True
    if resource=='grant' and contract.get('kind')=='fast_query':
        import fast_query_csv as FQCSV
        data=result.get('data')
        if isinstance(data,dict) and bool(data.get("csv_fields")):
            if hydrate_csv:result['data']=FQCSV.download_and_hydrate(data,timeout=20)
            else:materialized=False
    body={'version':VERSION,'task_id':task_id,'resource':resource,'contract':contract,
          'contract_fingerprint':EP.digest(contract),'captured_at':datetime.now(timezone.utc).isoformat(),
          'result':result,'materialized':materialized}
    # Never accept credentials as snapshot payload. Values/CSV references stay local; only normalized data is rendered.
    EP._no_secrets(body)
    data_path=C.task_temp_path(task_id,'verified-snapshots/data-'+EP.digest(body)+'.json',create_parent=True)
    EP.atomic_json(data_path,body)
    data_sha=hashlib.sha256(data_path.read_bytes()).hexdigest()
    receipt={k:body[k] for k in ('version','task_id','resource','contract_fingerprint','captured_at')}
    receipt.update(data_file=str(data_path),data_sha256=data_sha,status='completed' if materialized else 'validated_reference',success=True,materialized=materialized)
    receipt_path=C.task_temp_path(task_id,'verified-snapshots/receipt-'+data_sha+'.json',create_parent=True)
    EP.atomic_json(receipt_path,receipt)
    return {'snapshot_receipt_file':str(receipt_path),'snapshot_receipt_sha256':hashlib.sha256(receipt_path.read_bytes()).hexdigest()}


def load(task_id,receipt_file,expected_sha256=None,allow_deferred=False):
    try:
        path=Path(receipt_file);raw=path.read_bytes();receipt=json.loads(raw)
        if expected_sha256 and hashlib.sha256(raw).hexdigest()!=expected_sha256:
            raise EP.PlanError('SNAPSHOT_RECEIPT_STALE','快照收据hash变化')
        if not isinstance(receipt,dict) or receipt.get('version')!=VERSION or receipt.get('task_id')!=task_id or receipt.get('success') is not True or receipt.get('status') not in ('completed','validated_reference'):
            raise EP.PlanError('SNAPSHOT_IDENTITY_INVALID','快照不属于当前任务的已验证结果')
        root=C.task_temp_path(task_id,'verified-snapshots').resolve()
        data_path=Path(receipt['data_file']).resolve()
        if root not in data_path.parents:raise EP.PlanError('SNAPSHOT_PATH_INVALID','快照数据必须位于当前任务存储')
        data_raw=data_path.read_bytes()
        if hashlib.sha256(data_raw).hexdigest()!=receipt.get('data_sha256'):
            raise EP.PlanError('SNAPSHOT_DATA_STALE','快照数据内容变化，不能沿用旧验证')
        data=json.loads(data_raw)
        if data.get('task_id')!=task_id or data.get('contract_fingerprint')!=receipt['contract_fingerprint'] or EP.digest(data.get('contract'))!=receipt['contract_fingerprint']:
            raise EP.PlanError('SNAPSHOT_CONTRACT_MISMATCH','快照合同与收据不一致')
        if data.get('resource')!=receipt.get('resource') or data.get('resource') not in ('grant','package'):
            raise EP.PlanError('SNAPSHOT_RESOURCE_INVALID','快照类型无效')
        if receipt.get('materialized') is not data.get('materialized'):
            raise EP.PlanError('SNAPSHOT_DATA_STALE','快照物化状态不一致')
        if not data.get('materialized') and not allow_deferred:
            raise EP.PlanError('SNAPSHOT_NEEDS_MATERIALIZATION','CSV引用尚未物化；调用materialize_snapshot下载已有结果，不重复查询')
        return {**data,'receipt_sha256':hashlib.sha256(raw).hexdigest(),'receipt_file':str(path.resolve())}
    except EP.PlanError:raise
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise EP.PlanError('SNAPSHOT_RECEIPT_REQUIRED','需要可读取且未变更的任务数据快照') from exc


def materialize_registered(params):
    """Freeze an owned registered runtime after querying it, not Agent-authored numeric JSON."""
    import runtime_credentials as RC
    import data_grant as DG
    import formula_package as FP
    import build_dashboard as BD
    task=str(params.get('task_id') or '')
    if params.get('validation_receipt_file'):
        try:
            proof=json.loads(Path(params['validation_receipt_file']).read_text(encoding='utf-8'))
            if proof.get('task_id')!=task or proof.get('success') is not True or proof.get('status')!='completed':
                raise EP.PlanError('SNAPSHOT_VALIDATION_REQUIRED','需要当前任务已完成的验证收据')
            snapshot=load(task,proof.get('snapshot_receipt_file'),proof.get('snapshot_receipt_sha256'),allow_deferred=True)
            if snapshot['contract_fingerprint']!=proof.get('contract_fingerprint'):
                raise EP.PlanError('SNAPSHOT_CONTRACT_MISMATCH','验证与快照合同不一致')
            if not snapshot.get('materialized'):
                return {'code':0,**capture(task,snapshot['contract'],snapshot['result'],snapshot['resource'],hydrate_csv=True),
                        'data_mode':'snapshot','reused_validation_result':True}
            return {'code':0,'snapshot_receipt_file':snapshot['receipt_file'],
                    'snapshot_receipt_sha256':snapshot['receipt_sha256'],'data_mode':'snapshot','reused_validation_result':True}
        except EP.PlanError as exc:return exc.as_dict()
        except (OSError,ValueError,TypeError) as exc:return {'code':1,'error':'SNAPSHOT_VALIDATION_REQUIRED','message':str(exc)}
    resource=params.get('resource')
    identifier=params.get('grant_id') if resource=='grant' else params.get('package_id')
    if resource not in ('grant','package'):return {'code':1,'error':'SNAPSHOT_RESOURCE_REQUIRED'}
    try:
        registration=RC.verify_binding(task,resource,identifier,str(params.get('contract_fingerprint') or ''))
        client=DG if resource=='grant' else FP
        endpoint,key=client._config(require_key=False)
        if str(endpoint).rstrip('/')!=registration['endpoint']:
            raise EP.PlanError('SNAPSHOT_ENDPOINT_MISMATCH','当前endpoint与原注册身份不同')
        credential=client.load_credential(identifier,task_id=task)
        if resource=='grant':
            result=DG.query_grant(endpoint,identifier,credential['signature'],api_key=key)
            contract=registration['contract']
            kind=contract['kind']
            if kind=='fast_query_minute':
                import grant_capabilities as GC
                evaluated=GC.evaluate_minute(contract['payload'],result)
                if not evaluated.get('success'):return {'code':1,'error':evaluated.get('error_code')}
            data=BD._normalize_grant_data(kind,(result or {}).get('data'))
            if BD._inspect_output_data(data) is not None:raise EP.PlanError('SNAPSHOT_DATA_EMPTY','数据为空，不能冻结为成品')
        else:
            result=FP.query_package(endpoint,identifier,credential['signature'],api_key=key)
            contract=registration['contract']
            outputs=result.get('outputs') or {}
            for read in contract.get('reads') or []:
                value=outputs.get(read.get('output')) or {}
                if value.get('error') or BD._inspect_output_data(value.get('data')) is not None:
                    raise EP.PlanError('SNAPSHOT_DATA_EMPTY','公式包缺少必需有效产出')
        return {'code':0,**capture(task,registration['contract'],result,resource,hydrate_csv=True),
                'data_mode':'snapshot','message':'已保存数据快照；不会自动更新，页面必须标明数据时点'}
    except EP.PlanError as exc:return exc.as_dict()
