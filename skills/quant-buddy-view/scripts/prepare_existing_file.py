"""Faithful file preparation; capture reads and authorized existing-page asset uploads only."""
import base64
import hashlib
import html
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

from file_publication import atomic, digest, locked


def _data_uri(data, mime):
    return 'data:' + mime + ';base64,' + base64.b64encode(data).decode('ascii')


def decode_html(raw):
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        value = raw.decode('utf-16')
    else:
        charset = re.search(br'<meta\b[^>]*charset\s*=\s*[\'\"]?([a-zA-Z0-9_-]+)', raw[:8192], re.I)
        encoding = charset[1].decode('ascii') if charset else 'utf-8-sig'
        try:
            value = raw.decode(encoding)
        except LookupError:
            raise ValueError('FILE_PREPARE_SOURCE_ENCODING_UNSUPPORTED')
    # Output is UTF-8; preserve originals separately and change only encoding declarations.
    return re.sub(r'(<meta\b[^>]*charset\s*=\s*[\'\"]?)[a-zA-Z0-9_-]+',
                  lambda m: m[1] + 'utf-8', value, flags=re.I)


class LocalResources:
    def __init__(self, source):
        self.root = source.parent.resolve()
        self.assets = []
        self.remote = set()

    def resolve(self, value, base, stack=()):
        value = html.unescape(value.strip())
        if not value or value.startswith(('#', 'data:', 'javascript:', 'mailto:')):
            return value
        parts = urlsplit(value)
        if parts.scheme in ('http', 'https') or value.startswith('//'):
            self.remote.add(value)
            return value
        if parts.scheme and parts.scheme != 'file':
            raise ValueError('FILE_PREPARE_RESOURCE_SCHEME_UNSUPPORTED')
        path = Path(unquote(parts.path))
        path = (path if path.is_absolute() else base / path).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError('FILE_PREPARE_RESOURCE_OUTSIDE_SOURCE_DIRECTORY')
        if path in stack:
            raise ValueError('FILE_PREPARE_RESOURCE_CYCLE')
        raw = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        if path.suffix.lower() == '.css':
            text = self.css(raw.decode('utf-8-sig'), path.parent, stack + (path,))
            raw, mime = text.encode('utf-8'), 'text/css'
        self.assets.append({'name': path.relative_to(self.root).as_posix(), 'sha256': digest(path.read_bytes())})
        return _data_uri(raw, mime) + (('#' + parts.fragment) if parts.fragment else '')

    def css(self, text, base, stack=()):
        return re.sub(r'url\(\s*([\'\"]?)(.*?)\1\s*\)',
                      lambda m: 'url("' + self.resolve(m[2], base, stack) + '")', text, flags=re.I)

    def prepare(self, text):
        # Replace only loading attributes, without reserializing DOM or touching inline JS/data.
        tag_pattern = re.compile(r'<(?:script|img|link|source|video|audio|iframe|object)\b[^>]*>', re.I)
        def tag(m):
            value = m[0]
            if re.search(r'\bsrcset\s*=', value, re.I):
                raise ValueError('FILE_PREPARE_SRCSET_REQUIRES_EXPLICIT_ADAPTATION')
            if value.lower().startswith('<iframe') and re.search(r'\bsrc\s*=', value, re.I):
                raise ValueError('FILE_PREPARE_IFRAME_REQUIRES_EXPLICIT_SNAPSHOT')
            return re.sub(r'\b(src|href|poster|data)\s*=\s*([\'\"])(.*?)\2',
                          lambda a: a[1] + '=' + a[2] + self.resolve(a[3], self.root) + a[2],
                          value, flags=re.I | re.S)
        # Protect script bodies from accidental regex replacement of HTML strings.
        chunks = re.split(r'(<script\b[^>]*>.*?</script\s*>)', text, flags=re.I | re.S)
        for i, chunk in enumerate(chunks):
            if chunk.lower().startswith('<script'):
                end = chunk.find('>') + 1
                chunks[i] = tag_pattern.sub(tag, chunk[:end]) + chunk[end:]
            else:
                chunk = tag_pattern.sub(tag, chunk)
                chunk = re.sub(r'(<style\b[^>]*>)(.*?)(</style\s*>)',
                               lambda m: m[1] + self.css(m[2], self.root) + m[3], chunk, flags=re.I | re.S)
                chunk = re.sub(r'\bstyle\s*=\s*([\'\"])(.*?)\1',
                               lambda m: 'style=' + m[1] + html.escape(self.css(html.unescape(m[2]), self.root), quote=True) + m[1],
                               chunk, flags=re.I | re.S)
                chunks[i] = chunk
        return ''.join(chunks)


def prepare(params, *, skill_root, asset_upload=None):
    """No page write or QBS research. Emitted params are consumed by upload/update."""
    if params.get('publish_authorized') is not True:
        return {'code': 1, 'error': 'FILE_PREPARE_PUBLIC_AUTHORIZATION_REQUIRED'}
    source = Path(str(params.get('source_file') or '')).resolve()
    work = Path(str(params.get('work_dir') or ''))
    task = str(params.get('task_id') or '').strip()
    if not task or not work.is_absolute():
        return {'code': 1, 'error': 'FILE_PREPARE_TASK_AND_ABSOLUTE_WORK_DIR_REQUIRED'}
    work = work.resolve()
    skill = Path(skill_root).resolve()
    if work == skill or skill in work.parents:
        return {'code': 1, 'error': 'FILE_PREPARE_WORKSPACE_OUTSIDE_SKILL_REQUIRED'}
    if not source.is_file():
        return {'code': 1, 'error': 'FILE_PREPARE_SOURCE_UNREADABLE'}
    kind = source.suffix.lower()
    if kind not in ('.html', '.htm', '.jpg', '.jpeg', '.png', '.pdf'):
        return {'code': 1, 'error': 'FILE_PREPARE_FORMAT_UNSUPPORTED'}
    raw = source.read_bytes()
    # Page identity is learned after create; adding that page_id on resume must not create a new journal.
    key = digest(task + '\0' + digest(raw))
    root = work / 'file-publications' / key
    with locked(root):
        manifest = root / 'prepared.json'
        if manifest.exists():
            old = json.loads(manifest.read_text(encoding='utf-8'))
            journal_file = root / 'publication.json'
            journal = json.loads(journal_file.read_text(encoding='utf-8')) if journal_file.exists() else {}
            bound_page = journal.get('page_id') or old['publish_params'].get('page_id')
            requested_page = params.get('page_id')
            if requested_page and bound_page and requested_page != bound_page:
                return {'code': 1, 'error': 'FILE_PREPARE_PAGE_BINDING_MISMATCH'}
            if requested_page or bound_page:
                old['publish_params']['page_id'] = requested_page or bound_page
                old['publish_command'] = 'update'
            original = root / ('original' + kind)
            carrier = Path(old['publish_params']['source_html_file'])
            snapshot = old['publish_params'].get('source_snapshot_html_file')
            snapshot_ok = not snapshot or digest(Path(snapshot).read_bytes()) == old['publish_params'].get('source_snapshot_html_sha256')
            if not snapshot_ok or digest(original.read_bytes()) != digest(raw) or digest(carrier.read_bytes()) != old['publish_params']['source_html_sha256']:
                return {'code': 1, 'error': 'FILE_PREPARE_ARTIFACT_CHANGED'}
            atomic(root / 'publish-params.json', json.dumps(old['publish_params'], ensure_ascii=False, indent=2).encode('utf-8'))
            atomic(manifest, json.dumps(old, ensure_ascii=False, indent=2).encode('utf-8'))
            return old
        atomic(root / ('original' + kind), raw)
        warnings, assets = [], []
        if kind in ('.html', '.htm'):
            resources = LocalResources(source)
            text = resources.prepare(decode_html(raw))
            if not re.match(r'\s*(?:<!doctype\s+html|<html\b)', text, re.I):
                text = '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>' + text + '</body></html>'
            warnings.extend(['外部资源仍需公网验收'] if resources.remote else [])
            assets = resources.assets
        else:
            if kind == '.pdf':
                try:
                    import fitz
                except ImportError:
                    return {'code': 1, 'error': 'FILE_PREPARE_PDF_RENDERER_REQUIRED', 'message': '安装 PyMuPDF 后重试；不进入研究或查数。'}
                with fitz.open(stream=raw, filetype='pdf') as doc:
                    if doc.needs_pass or doc.page_count == 0:
                        return {'code': 1, 'error': 'FILE_PREPARE_PDF_UNREADABLE'}
                    images = [page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).tobytes('png') for page in doc]
                warnings.append('PDF按页渲染为原始视觉快照；文字搜索、表单和原PDF交互不保留。')
                mime = 'image/png'
            else:
                images = [raw]
                mime = 'image/png' if kind == '.png' else 'image/jpeg'
            pictures = []
            for i, data in enumerate(images, 1):
                file = root / ('page-%04d.%s' % (i, 'png' if mime == 'image/png' else 'jpg'))
                atomic(file, data)
                assets.append({'file': str(file), 'sha256': digest(data), 'page': i})
                pictures.append('<figure><img alt="第 %d 页" src="%s"></figure>' % (i, _data_uri(data, mime)))
            text = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(source.stem) + '</title><style>body{margin:0;background:#f3f4f6}main{max-width:1200px;margin:auto}figure{margin:0 0 12px}img{display:block;width:100%;height:auto}</style></head><body><main>' + ''.join(pictures) + '</main></body></html>'
        carrier = root / 'source.html'
        atomic(carrier, text.encode('utf-8'))
        publish = {'task_id': task, 'user_query': params.get('user_query', ''),
                   'transformation_mode': 'preserve_html_qbs_live', 'snapshot_only': True,
                   'source_html_file': str(carrier), 'source_html_sha256': digest(text),
                   'source_original_sha256': digest(raw),
                   'file_publish_dir': str(root), 'title': source.stem}
        if params.get('page_id'):
            publish['page_id'] = params['page_id']
        if re.search(r'\b(?:fetch\s*\(|axios\b|XMLHttpRequest\b|EventSource\b|WebSocket\b)', text):
            snapshot = root / 'snapshot.html'
            script = Path(skill_root) / 'scripts' / 'capture_file_snapshot.mjs'
            proc = subprocess.run(['node', str(script), str(carrier), str(snapshot)], capture_output=True,
                                  text=True, encoding='utf-8', errors='replace', timeout=90)
            if proc.returncode or not snapshot.exists():
                return {'code': 1, 'error': 'FILE_PREPARE_RENDER_FAILED', 'file_publish_dir': str(root),
                        'message': '来源动态内容未成功捕获；保留原件，修复展示依赖后重试，不进入QBS。'}
            publish['source_snapshot_html_file'] = str(snapshot)
            publish['source_snapshot_html_sha256'] = digest(snapshot.read_bytes())
            capture = json.loads(proc.stdout.lstrip('\ufeff'))
            warnings.append('网络读请求已替换为本次捕获的静态响应；原有本地展示脚本保留。' if capture['mode'] == 'response_replay' else '仅保留当前可见快照：未取得可回放响应，脚本交互已冻结。')
        actual = Path(publish.get('source_snapshot_html_file', carrier)).read_bytes()
        if len(actual) > 2 * 1024 * 1024 and params.get('page_id') and asset_upload:
            hosted = actual.decode('utf-8')
            # Content-derived logical names make retries address the same named asset.
            for match in list(re.finditer(r'data:(image/(?:png|jpeg));base64,([A-Za-z0-9+/=]+)', hosted)):
                image = base64.b64decode(match[2])
                image_path = root / ('asset-' + digest(image) + ('.png' if match[1] == 'image/png' else '.jpg'))
                atomic(image_path, image)
                out = asset_upload({'task_id': task, 'page_id': params['page_id'],
                                    'logical_name': 'file-' + digest(image), 'image_file': str(image_path)})
                data = out.get('data', out) if isinstance(out, dict) else {}
                url = data.get('url') or data.get('public_url') or data.get('image_url')
                if not isinstance(out, dict) or out.get('code') != 0 or not str(url or '').startswith('https://'):
                    return {'code': 1, 'error': 'FILE_PREPARE_ASSET_UPLOAD_FAILED', 'file_publish_dir': str(root)}
                hosted = hosted.replace(match[0], html.escape(url, quote=True))
            actual = hosted.encode('utf-8')
            target_key = 'source_snapshot_html_file' if publish.get('source_snapshot_html_file') else 'source_html_file'
            atomic(Path(publish[target_key]), actual)
            publish[target_key.replace('_file', '_sha256')] = digest(actual)
        if len(actual) > 2 * 1024 * 1024:
            # Asset API requires a page id. Never invent one or create an empty placeholder page.
            return {'code': 1, 'error': 'FILE_PREPARE_ASSET_HOSTING_REQUIRED', 'file_publish_dir': str(root),
                    'assets': assets, 'message': '承载页超过2MB；有目标page_id时可用image_upload托管图片后替换引用。无page_id的首次资源托管需要平台支持，不能删页或先发空白页。'}
        result = {'code': 0, 'source_sha256': digest(raw), 'publish_params': publish,
                  'publish_command': 'update' if params.get('page_id') else 'upload',
                  'warnings': warnings, 'assets': assets,
                  'next_action': 'publish_original_static_now_before_research'}
        result['params_file'] = (root / 'publish-params.json').as_posix()
        atomic(manifest, json.dumps(result, ensure_ascii=False, indent=2).encode('utf-8'))
        atomic(root / 'publish-params.json', json.dumps(publish, ensure_ascii=False, indent=2).encode('utf-8'))
        result['params_file'] = (root / 'publish-params.json').as_posix()
        return result
