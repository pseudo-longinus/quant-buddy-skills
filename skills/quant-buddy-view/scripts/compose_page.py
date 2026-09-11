"""Controlled full-page Compose assembly using reviewed layout, never source credentials."""
import copy
import hashlib
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
import common as C
import execution_plan as EP
import runtime_credentials as RC

RECEIPT_FILE = 'receipts/compose-build.json'
SUPPORTED = {'layout', 'layout+style', 'original'}


class _OuterSection(HTMLParser):
    def __init__(self, source):
        super().__init__(); self.classes = []
        self.feed(source)
    def handle_starttag(self, tag, attrs):
        if tag == 'section' and not self.classes:
            self.classes = [x for x in dict(attrs).get('class', '').split() if re.fullmatch(r'[A-Za-z_][\w-]*', x)]


def _scoped_styles(entry, classes, section_id):
    """Only inert presentation declarations for the selected outer layout container."""
    allowed = {'color', 'background', 'background-color', 'border', 'border-color', 'border-radius',
               'padding', 'margin', 'gap', 'font-family', 'font-size', 'font-weight', 'line-height',
               'box-shadow', 'display', 'grid-template-columns', 'max-width', 'width', 'min-width'}
    out = []
    for item in entry.get('style_kit') or []:
        css = str(item.get('css') or '')
        if any(x in css.lower() for x in ('url(', '@import', 'expression', '</', '\\')): continue
        for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
            if not any(re.fullmatch(r'\.' + re.escape(c), selector.strip()) for c in classes): continue
            declarations = []
            for declaration in body.split(';'):
                key, sep, value = declaration.partition(':')
                if sep and key.strip().lower() in allowed and '!important' not in value.lower():
                    declarations.append(key.strip() + ':' + value.strip())
            if declarations: out.append('#' + section_id + '{' + ';'.join(declarations) + '}')
    return '\n'.join(out)


def _read_binding(plan, routing, sp):
    binding, error = sp._compose_binding_publish_state(routing, plan['target_page_id'])
    if error: raise EP.PlanError(error.get('error'), error.get('message', 'Compose绑定无效'))
    if not binding or binding.get('compose_binding_sha256') != plan.get('compose_binding_sha256'):
        raise EP.PlanError('COMPOSE_BINDING_STALE', '计划与Compose绑定不一致')
    path = Path(binding['compose_binding_file'])
    material = json.loads(path.read_text(encoding='utf-8'))
    if material.get('task_id') != plan['task_id'] or material.get('page_id') != plan['target_page_id']:
        raise EP.PlanError('COMPOSE_BINDING_IDENTITY_CONFLICT', 'Compose绑定身份不一致')
    digest = json.loads(Path(material['research_digest_file']).read_text(encoding='utf-8'))
    sha = EP.digest({k: v for k, v in digest.items() if k != 'digest_sha256'})
    if sha != material.get('research_digest_sha256') or sha != digest.get('digest_sha256'):
        raise EP.PlanError('COMPOSE_DIGEST_STALE', '研究摘要内容已改变，重新确认借鉴计划')
    entry = next((x for x in digest.get('templates', []) if x.get('page_id') == plan['source_page_id']), None)
    if not entry: raise EP.PlanError('COMPOSE_SOURCE_NOT_IN_DIGEST', '来源不在研究摘要内')
    return entry


def _check_roles(plan, params, panels):
    used_grants = {p['grant_id'] for p in panels if p.get('grant_id')}
    used_packages = {params['package_id']} if params.get('package_id') else set()
    expected_grants = {r.get('grant_id') for r in plan['runtime_roles'] if r['kind'] == 'grant'}
    expected_packages = {r.get('package_id') for r in plan['runtime_roles'] if r['kind'] == 'package'}
    if None in expected_grants or None in expected_packages or used_grants != expected_grants or used_packages != expected_packages:
        raise EP.PlanError('PLAN_ROLE_CONFLICT', '页面数据源与目标计划不一致，先修订计划中的运行角色')
    import verified_snapshot as VS
    expected_snapshots={str(Path(role['snapshot_receipt_file']).resolve()):role for role in plan.get('snapshot_roles',[])}
    used_snapshots={str(Path(panel['snapshot_receipt_file']).resolve()) for panel in panels if panel.get('snapshot_receipt_file')}
    if used_snapshots!=set(expected_snapshots):raise EP.PlanError('PLAN_SNAPSHOT_CONFLICT','快照面板与目标计划不一致')
    for path,role in expected_snapshots.items():
        snapshot=VS.load(plan['task_id'],path,role['snapshot_receipt_sha256'])
        if snapshot['resource']=='package':
            required=set(role.get('required_outputs') or [read['output'] for read in snapshot['contract'].get('reads',[])])
            consumed=set()
            for panel in panels:
                if panel.get('snapshot_receipt_file') and str(Path(panel['snapshot_receipt_file']).resolve())==path:
                    consumed.update(panel.get('snapshot_outputs') or [panel.get('snapshot_output')])
            if required-consumed:
                raise EP.PlanError('PLAN_OUTPUTS_NOT_CONSUMED','快照中用户要求的产出未被页面消费',missing_outputs=sorted(required-consumed))
    registrations = {}
    for role in plan['runtime_roles']:
        try:
            receipt = json.loads(Path(role['validation_receipt_file']).read_text(encoding='utf-8'))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise EP.PlanError('COMPOSE_ROLE_EVIDENCE_REQUIRED', '目标运行角色需要验证收据', role_id=role['role_id']) from exc
        if receipt.get('task_id') != plan['task_id'] or receipt.get('success') is not True or receipt.get('status') != 'completed':
            raise EP.PlanError('COMPOSE_ROLE_EVIDENCE_INVALID', '运行角色验证收据身份/状态不一致')
        if not role.get('contract_fingerprint') or receipt.get('contract_fingerprint') != role['contract_fingerprint']:
            raise EP.PlanError('COMPOSE_ROLE_EVIDENCE_INVALID', '运行角色合同fingerprint不一致')
        registration = RC.verify_binding(plan['task_id'], role['kind'], role['grant_id'] if role['kind']=='grant' else role['package_id'], role['contract_fingerprint'])
        if role['kind']=='package':
            required=set(role.get('required_outputs') or [read['output'] for read in registration['contract'].get('reads',[])])
            consumed=set()
            for panel in panels:
                if not panel.get('grant_id') and not panel.get('snapshot_receipt_file'):
                    consumed.update(panel.get('outputs') or [panel.get('output')])
            if required-consumed:
                raise EP.PlanError('PLAN_OUTPUTS_NOT_CONSUMED','运行时必需产出未被页面消费',missing_outputs=sorted(required-consumed))
        registrations[role['role_id']] = registration['record_hash']
    return registrations


def build(params):
    import static_page as SP
    import build_dashboard as BD
    try:
        task = str(params.get('task_id') or '')
        if not params.get('plan_hash'): raise EP.PlanError('PLAN_HASH_REQUIRED', 'Compose构建必须绑定当前plan_hash')
        plan = EP.require(task, page_id=params.get('page_id'), plan_hash=params['plan_hash'])
        if plan['build_mode'] != 'compose_page': raise EP.PlanError('COMPOSE_ROUTING_REQUIRED', '当前计划不是Compose')
        if plan['target_scope'].get('kind') == 'unspecified': raise EP.PlanError('PLAN_SCOPE_REQUIRED', '先用execution_plan明确资产/研究范围')
        routing, _, error = SP._read_routing_credential(task)
        if error: return error
        if (routing or {}).get('page_id') != plan['target_page_id']:
            raise EP.PlanError('PLAN_PAGE_CONFLICT', '路由和计划目标不一致')
        mutation_error = SP._existing_page_mutation_error(params, action='build_dashboard')
        if mutation_error: return mutation_error
        entry = _read_binding(plan, routing, SP)
        modules = plan['borrow_modules']
        if not modules: raise EP.PlanError('COMPOSE_MODULES_REQUIRED', 'Compose必须声明实际借鉴模块')
        if any(x['borrow_level'] not in SUPPORTED for x in modules):
            raise EP.PlanError('COMPOSE_MODULE_ADAPTER_REQUIRED', '此组装器仅接受layout/layout+style/original；脚本或公式借鉴需显式运行角色适配，不能偷偷继承全部来源')
        panels = copy.deepcopy(params.get('panels') or [])
        if not panels or any(not isinstance(p, dict) for p in panels): raise EP.PlanError('COMPOSE_CONTENT_REQUIRED', '填写目标研究panels')
        registrations = _check_roles(plan, params, panels)
        by_module = {m['module']: [] for m in modules}
        for index, panel in enumerate(panels):
            name = panel.get('compose_module') or panel.get('title')
            if name not in by_module: raise EP.PlanError('COMPOSE_PANEL_MODULE_REQUIRED', '每个panel需要匹配计划中的compose_module')
            if panel.get('type') == 'text' and not str(panel.get('text') or '').strip():
                raise EP.PlanError('COMPOSE_CONTENT_REQUIRED', '不能交付空研究占位内容', module=name)
            by_module[name].append((index, panel))
        if any(not group for group in by_module.values()): raise EP.PlanError('COMPOSE_CONTENT_REQUIRED', '每个计划模块都需要目标内容')
        shells, styles, provenance = [], [], []
        for module_index, module in enumerate(modules):
            section_id = 'qb-compose-' + str(module_index)
            source_classes, source_html = [], ''
            if module['borrow_level'] != 'original':
                ref = module['borrowed_from']['ref']
                block = next((b for b in entry.get('section_blocks', []) if ref in ('section:' + str(b.get('sec_id')), 'heading:' + str(b.get('title')))), None)
                if not block: raise EP.PlanError('COMPOSE_LAYOUT_REQUIRED', '需要研究摘要中的具体section，不能仅用标题冒充布局借鉴')
                source_html = block['html']
                source_classes = _OuterSection(source_html).classes
                if module['borrow_level'] == 'layout+style': styles.append(_scoped_styles(entry, source_classes, section_id))
            bodies = []
            for index, panel in by_module[module['module']]:
                target = 'qb-compose-body-' + str(index)
                panel['target_selector'] = '#' + target
                bodies.append('<article class="card card-' + html.escape(str(panel.get('type') or 'text'), quote=True) + '"><h3>' + html.escape(str(panel.get('title') or '')) + '</h3><div id="' + target + '"></div></article>')
            # Copy only the selected outer layout classes/presentation, not old content or executable code.
            shells.append('<section id="' + section_id + '" class="qb-compose-module ' + ' '.join(source_classes) + '"><h2>' + html.escape(module['module']) + '</h2><div class="qb-compose-panels">' + ''.join(bodies) + '</div></section>')
            provenance.append({'module': module['module'], 'borrow_level': module['borrow_level'],
                               'source_section_sha256': hashlib.sha256(source_html.encode()).hexdigest() if source_html else None,
                               'source_classes': source_classes})
        artifact = C.task_temp_path(task, 'compose/candidate.html', create_parent=True)
        spec = dict(params, panels=panels, out_file=str(artifact), upload=False, update_page_id=None)
        spec.pop('emit', None)
        built = BD._build_authorized(spec)
        if built.get('code') != 0: return built
        document = artifact.read_text(encoding='utf-8')
        if '<div id="grid"></div>' not in document:
            raise EP.PlanError('COMPOSE_RENDERER_CONTRACT_CHANGED', '标准renderer的grid接口发生变化')
        document = document.replace('<div id="grid"></div>', '<div id="grid">' + ''.join(shells) + '</div>', 1)
        css = '.qb-compose-module{grid-column:1/-1;min-width:0}.qb-compose-panels{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr))}'
        document = document.replace('</head>', '<style>' + css + '\n' + '\n'.join(styles) + '</style></head>', 1)
        artifact.write_text(document, encoding='utf-8')
        built['size'] = artifact.stat().st_size
        content_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        receipt = {'version': 'qbv_compose_build_v1', 'task_id': task, 'page_id': plan['target_page_id'],
                   'source_page_id': plan['source_page_id'], 'plan_hash': plan['plan_hash'],
                   'html_file': str(artifact), 'html_sha256': content_hash,
                   'runtime_roles': plan['runtime_roles'], 'registration_bindings': registrations, 'borrow_provenance': provenance,
                   'data_mode': built.get('data_mode', built['mode']), 'snapshot_bindings': built.get('snapshot_bindings', {}), 'verification': 'candidate_only'}
        receipt_path = C.task_temp_path(task, RECEIPT_FILE, create_parent=True)
        EP.atomic_json(receipt_path, receipt)
        research = [{k: v for k, v in panel.items() if k not in ('signature', 'target_selector')} for panel in panels]
        EP.atomic_json(C.task_temp_path(task, 'compose/research.json', create_parent=True), {'plan_hash': plan['plan_hash'], 'panels': research})
        manifest = json.loads(Path(built['manifest']).read_text(encoding='utf-8'))
        manifest.update(html_sha256=content_hash, execution_plan_hash=plan['plan_hash'], compose_provenance=provenance)
        EP.atomic_json(built['manifest'], manifest)
        publish = {k: params[k] for k in ('task_id', 'title', 'description', 'page_context', 'agent_reply_template',
                   'live_data_mode', 'route_receipt_file', 'validation_receipt_files', 'grant_validation_receipt_files',
                   'market_data_required', 'agent_intent') if k in params}
        publish.update(page_id=plan['target_page_id'], html_file=str(artifact), plan_hash=plan['plan_hash'], require_live_data=plan.get('require_live_data',False))
        if receipt['data_mode'] in ('snapshot','mixed'):
            publish['live_data_mode']='verified_snapshot' if receipt['data_mode']=='snapshot' else 'mixed'
        publish_path = C.task_temp_path(task, 'compose/publish-params.json', create_parent=True)
        EP.atomic_json(publish_path, publish)
        return {**built, 'out_file': str(artifact), 'page_id': plan['target_page_id'], 'terminal': False,
                'compose_receipt_file': str(receipt_path), 'plan_hash': plan['plan_hash'],
                'message': '完整Compose候选页已生成；尚未完成浏览器验收和发布',
                'next_action': {'command': 'publish_verified', 'params_file': str(publish_path)}}
    except EP.PlanError as exc: return exc.as_dict()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'code': 1, 'error': 'COMPOSE_ARTIFACT_INVALID', 'message': str(exc)}


def validate_candidate(params):
    plan = EP.require(params['task_id'], page_id=params.get('page_id'), plan_hash=params.get('plan_hash'))
    if not params.get('plan_hash'): raise EP.PlanError('PLAN_HASH_REQUIRED', '发布需要候选页绑定的plan_hash')
    try: receipt = json.loads(C.task_temp_path(plan['task_id'], RECEIPT_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc: raise EP.PlanError('COMPOSE_BUILD_REQUIRED', '先运行compose_page生成完整候选页') from exc
    if receipt.get('plan_hash') != plan['plan_hash'] or receipt.get('page_id') != plan['target_page_id']:
        raise EP.PlanError('COMPOSE_BUILD_STALE', '候选页属于旧计划或其他目标')
    if receipt.get('runtime_roles') != plan['runtime_roles']: raise EP.PlanError('PLAN_ROLE_CONFLICT', '候选角色与计划不同')
    for role in plan['runtime_roles']:
        registration = RC.verify_binding(plan['task_id'], role['kind'], role.get('grant_id') or role.get('package_id'), role['contract_fingerprint'])
        if receipt.get('registration_bindings', {}).get(role['role_id']) != registration['record_hash']:
            raise EP.PlanError('COMPOSE_CREDENTIAL_STALE', '凭据注册/轮换版本变化，重新构建候选页')
    import verified_snapshot as VS
    expected_snapshots={str(Path(role['snapshot_receipt_file']).resolve()):role['snapshot_receipt_sha256'] for role in plan.get('snapshot_roles',[])}
    if receipt.get('snapshot_bindings',{})!=expected_snapshots:raise EP.PlanError('PLAN_SNAPSHOT_CONFLICT','候选快照与计划不一致')
    for file,sha in expected_snapshots.items():VS.load(plan['task_id'],file,sha)
    path = Path(str(params.get('html_file') or ''))
    if not path.is_file() or path.resolve() != Path(receipt['html_file']).resolve():
        raise EP.PlanError('COMPOSE_BUILD_STALE', '只能发布当前已绑定的候选文件')
    if hashlib.sha256(path.read_bytes()).hexdigest() != receipt['html_sha256']:
        raise EP.PlanError('COMPOSE_BUILD_STALE', '候选HTML变化，重新构建并验收')
    return receipt
