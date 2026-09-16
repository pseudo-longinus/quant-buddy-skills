#!/usr/bin/env python3
"""Consume a saved fast_query_minute_range response; no API key and no extra query."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from fetch_fastquery_csv import _download
from minute_range_csv import parse_minute_range_csv


def main(argv=None):
    parser = argparse.ArgumentParser(description='下载历史分钟CSV长表，保留全部列及交易日/UTC时间戳')
    parser.add_argument('manifest', help='保存的完整工具JSON响应文件，可用@file')
    parser.add_argument('--output', required=True, help='完整数据JSON，必须位于本skill/output内')
    parser.add_argument('--timeout', type=int, default=60)
    args = parser.parse_args(argv)
    try:
        root = (Path(__file__).resolve().parents[1] / 'output').resolve()
        target = Path(args.output).resolve()
        target.relative_to(root)
        manifest_path = Path(args.manifest.lstrip('@')).resolve()
        manifest_path.relative_to(root)
        raw = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        if raw.get('code') not in (None, 0) or raw.get('success') is False: raise ValueError('取数响应未成功')
        manifest = raw.get('data') if isinstance(raw.get('data'), dict) else raw
        if manifest.get('csv_url'):
            url = urlsplit(manifest['csv_url'])
            if url.scheme not in ('http', 'https') or not url.netloc or url.username or url.password: raise ValueError('非法CSV URL')
        text = _download(manifest['csv_url'], timeout=args.timeout) if manifest.get('csv_url') else None
        data = parse_minute_range_csv(text, manifest)
        data.pop('csv_url', None)  # 物化文件不传播签名地址。
        content = json.dumps({'schema': 'qb_minute_range_artifact_v1', 'data': data}, ensure_ascii=False, allow_nan=False).encode('utf-8')
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
            tmp = out.name; out.write(content)
        try: os.replace(tmp, target)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        print(json.dumps({'code': 0, 'artifact_file': str(target), 'sha256': hashlib.sha256(content).hexdigest(),
            'shape': data['shape'], 'columns': data['columns'], 'empty': not data['rows'], 'warnings': data.get('warnings', [])}, ensure_ascii=False))
        return 0
    except Exception as exc:
        # 网络错误可能带签名URL，不原样打印。
        print(json.dumps({'code': 1, 'error': type(exc).__name__, 'message': '历史分钟CSV解析/保存失败；检查manifest、链接有效期及skill/output输出路径，不改用单日数据替代。'}, ensure_ascii=False))
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
