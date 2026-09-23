"""Trusted host read-only evidence. Never publishes or trusts an Agent report."""
import argparse
import json
import os
import re
import urllib.parse
import common as C
import static_page as SP
import delivery_state as DS
import publication_transport as PT


def inspect(page_id, public_url, *, observe, verify=None):
    before = observe()
    remote = DS._remote(before)
    if (before.get('code') not in (None, 0) or remote['page_id'] != page_id
            or type(remote['version_no']) is not int or remote['version_no'] < 1
            or not re.fullmatch(r'[a-f0-9]{64}', str(remote['sha256'] or ''))
            or remote['url'] != public_url):
        return {'code': 1, 'error': 'MAINTENANCE_PAGE_IDENTITY_INVALID'}
    if verify is not None:
        browser = verify(public_url)
        if browser.get('code') != 0:
            return {'code': 1, 'error': 'MAINTENANCE_BROWSER_FAILED'}
        checked = PT.verify_current({'target_page_id': page_id}, before, observe(), browser_evidence=browser)
        if checked.get('code') != 0:
            return checked
    return {'code': 0, **remote, 'browser_verified': verify is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--page-id', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    try:
        endpoint = os.environ['QBV_HOST_ENDPOINT']
        key = os.environ['QBV_API_KEY']
        def observe():
            url = C.api_url(endpoint, SP._PATH['template']) + '?' + urllib.parse.urlencode({'page_id': args.page_id})
            result = C.http_json('GET', url, C.headers(key), timeout=30)
            return SP._template_record(result) if result.get('code') == 0 else result
        result = inspect(args.page_id, args.url, observe=observe,
                         verify=(lambda url: SP._run_page_verifier(url, 'public-smoke')) if args.verify else None)
    except Exception:
        result = {'code': 1, 'error': 'MAINTENANCE_INSPECTION_UNAVAILABLE'}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
