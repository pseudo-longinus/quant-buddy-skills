"""Publication requirements derived from the route, not optional HTML opt-in."""
import hashlib
from pathlib import Path


def requires_design(plan, html):
    return bool((plan or {}).get('source_route') == 'unmatched'
                or (plan or {}).get('build_mode') == 'compose_page'
                or 'data-qb-page-design=' in html)


def metadata_error(params):
    description = str(params.get('description') or '').strip()
    if not description or '活页生成进度' in description or '最终内容会在同一个链接显示' in description:
        return {'code': 1, 'error': 'FINAL_DESCRIPTION_REQUIRED',
                'message': '自建/Compose正式发布需要描述实际研究内容的description，不能保留进度占位文案'}
    return None


def evidence(params, html_bytes, profile, browser):
    scripts = Path(__file__).resolve().parent
    validator_hash = hashlib.sha256(b''.join((scripts / name).read_bytes() for name in (
        'verify_page.mjs', 'verification_profiles.mjs', 'dashboard_design_checks.mjs'))).hexdigest()
    return {'schema_version': 'page_quality_v1', 'task_id': params.get('task_id'),
            'turn_id': params.get('turn_id'), 'page_id': params.get('page_id'),
            'html_sha256': hashlib.sha256(html_bytes).hexdigest(), 'profile': profile,
            'validator_sha256': validator_hash,
            'browser_verified': browser.get('code') == 0,
            'viewports': [x.get('viewport') for x in (browser.get('browser') or {}).get('viewports', [])]}
