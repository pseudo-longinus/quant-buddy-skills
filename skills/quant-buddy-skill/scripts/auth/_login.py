"""认证向导辅助脚本：老用户登录重新获取 api_key。通过环境变量 GZQ_TOKEN / GZQ_SMS 传参。"""
import os, json, urllib.request as r, urllib.error, pathlib, tempfile

SKILL_ROOT = pathlib.Path(__file__).parent.parent.parent
cfg = json.loads((SKILL_ROOT / 'config.json').read_text(encoding='utf-8'))

payload = {
    'session_token': os.environ.get('GZQ_TOKEN', ''),
    'sms_code': os.environ.get('GZQ_SMS', ''),
}
body = json.dumps(payload).encode()
req = r.Request(
    cfg['auth_endpoint'] + '/skill/login',
    data=body, headers={'Content-Type': 'application/json'}, method='POST'
)
try:
    resp = json.loads(r.urlopen(req, timeout=15).read().decode())
except urllib.error.HTTPError as e:
    resp = json.loads(e.read().decode())

out = json.dumps(resp, ensure_ascii=False)
print(out)
out_path = os.path.join(os.environ.get('TEMP', tempfile.gettempdir()), 'gzq_auth.txt')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(out)
