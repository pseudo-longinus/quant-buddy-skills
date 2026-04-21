"""
认证向导（终端交互版）
适用于非 VS Code 环境（Cursor、JetBrains、Neovim 等）。
用法：在 skill 根目录下执行
    python scripts/_auth_wizard.py
"""
import json, pathlib, urllib.request as r, urllib.error, sys

SKILL_ROOT = pathlib.Path(__file__).parent.parent.parent
CONFIG_PATH = SKILL_ROOT / 'config.json'

def load_cfg():
    return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))


def post(url, payload):
    body = json.dumps(payload).encode()
    req = r.Request(url, data=body, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        return json.loads(r.urlopen(req, timeout=15).read().decode())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


def send_code(auth_endpoint, phone):
    print(f'正在向 {phone} 发送验证码...')
    resp = post(auth_endpoint + '/skill/sendCode', {'phone': phone})
    if resp.get('code') != 0:
        print(f'发送失败：{resp}')
        sys.exit(1)
    token = resp['data']['session_token']
    is_registered = resp['data'].get('is_registered', False)
    print('验证码已发送 ✓')
    return token, is_registered


def main():
    cfg = load_cfg()
    auth_endpoint = cfg['auth_endpoint']

    print('=' * 50)
    print('  观照量化投研  认证向导')
    print('  新用户自动注册，老用户重新生成密钥')
    print('=' * 50)

    # 第1步：手机号
    phone = input('\n请输入手机号：').strip()
    if not phone:
        print('手机号不能为空')
        sys.exit(1)

    # 第2步：发送验证码
    session_token, is_registered = send_code(auth_endpoint, phone)

    # 第3步：验证码
    sms_code = input('请输入收到的短信验证码：').strip()
    if not sms_code:
        print('验证码不能为空')
        sys.exit(1)

    # 第4步：根据 is_registered 直接走对应接口
    print('正在认证...')
    if is_registered:
        print('该手机号已注册，正在登录...')
        resp = post(auth_endpoint + '/skill/login', {
            'session_token': session_token,
            'sms_code': sms_code,
        })
    else:
        resp = post(auth_endpoint + '/skill/register', {
            'session_token': session_token,
            'sms_code': sms_code,
        })

    if resp.get('code') != 0:
        print(f'认证失败：{resp}')
        sys.exit(1)

    api_key = resp['data']['api_key']

    # 第5步：写入 config.json
    cfg['api_key'] = api_key
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'\n认证完成 ✓')
    print(f'api_key 已写入 config.json')


if __name__ == '__main__':
    main()
