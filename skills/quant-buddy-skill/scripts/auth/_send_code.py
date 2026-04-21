"""认证向导辅助脚本：发送短信验证码。通过环境变量 GZQ_PHONE 传入手机号。"""
import os, json, urllib.request as r, urllib.error, pathlib, tempfile

SKILL_ROOT = pathlib.Path(__file__).parent.parent.parent
cfg = json.loads((SKILL_ROOT / 'config.json').read_text(encoding='utf-8'))

phone = os.environ.get('GZQ_PHONE', '')
if not phone:
    raise SystemExit('请先设置环境变量 GZQ_PHONE，例如: export GZQ_PHONE="手机号"')

body = json.dumps({'phone': phone}).encode()
req = r.Request(
    cfg['auth_endpoint'] + '/skill/sendCode',
    data=body, headers={'Content-Type': 'application/json'}, method='POST'
)
try:
    resp = r.urlopen(req, timeout=15).read().decode()
except urllib.error.HTTPError as e:
    resp = json.dumps({'code': e.code, 'message': e.read().decode()})

print(resp)
out_path = os.path.join(os.environ.get('TEMP', tempfile.gettempdir()), 'gzq_auth.txt')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(resp)
