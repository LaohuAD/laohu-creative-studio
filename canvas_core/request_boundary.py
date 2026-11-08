"""本地服务浏览器边界：校验 Host/Origin，拒绝其他网站跨源操控 HTTP 与 WebSocket。"""
import ipaddress
import json
import logging
import socket
from urllib.parse import urlsplit

log = logging.getLogger(__name__)


def _origin(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            return None
        if parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
            return None
        return parsed.scheme, parsed.hostname.lower().rstrip('.'), parsed.port or (443 if parsed.scheme == 'https' else 80)
    except ValueError:
        return None


def _loopback(host):
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_laohu_oauth_referrer(value):
    try:
        parsed = urlsplit(value)
        return (parsed.scheme.lower() == 'https'
                and parsed.hostname
                and parsed.hostname.lower().rstrip('.') == 'api.lao-hu.com'
                and parsed.username is None
                and parsed.password is None
                and parsed.port in (None, 443))
    except ValueError:
        return False


def _is_laohu_oauth_callback_navigation(scope, headers, expected):
    """Permit only the provider's top-level redirect to the exact local callback."""
    client = scope.get('client') or ('', 0)
    host = headers.get(b'host', b'').decode('latin-1').lower()
    if not (
        scope.get('type') == 'http'
        and scope.get('method') == 'GET'
        and scope.get('scheme') == 'http'
        and scope.get('path') == '/api/laohu/account/callback'
        and host == '127.0.0.1:3000'
        and expected == ('http', '127.0.0.1', 3000)
        and _loopback(str(client[0]).split('%', 1)[0])
        and headers.get(b'sec-fetch-site', b'').lower() in {b'cross-site', b'none'}
        and headers.get(b'sec-fetch-mode', b'').lower() == b'navigate'
        and headers.get(b'sec-fetch-dest', b'').lower() == b'document'
    ):
        return False
    referrer = headers.get(b'referer', b'').decode('latin-1')
    if referrer and not _is_laohu_oauth_referrer(referrer):
        return False
    origin = headers.get(b'origin', b'').decode('latin-1')
    if origin and _origin(origin) != ('https', 'api.lao-hu.com', 443):
        return False
    return True


class LocalRequestBoundary:
    def __init__(self, app):
        self.app = app
        self.local_names = {'localhost', socket.gethostname().lower().rstrip('.')}
        self.local_names.update(name + '.local' for name in tuple(self.local_names) if '.' not in name)

    def _trusted_host(self, host, scope):
        if host in self.local_names:
            return True
        # 测试传输不依赖机器的真实主机名。
        if (scope.get('client') or ('',))[0] == 'testclient' and host == 'testserver':
            return True
        try:
            address = ipaddress.ip_address(host)
            return address.is_loopback or address.is_private
        except ValueError:
            return False

    async def __call__(self, scope, receive, send):
        if scope['type'] not in {'http', 'websocket'}:
            return await self.app(scope, receive, send)
        headers = {key.lower(): value for key, value in scope.get('headers', [])}
        host = headers.get(b'host', b'').decode('latin-1')
        scheme = {'ws':'http', 'wss':'https'}.get(scope['scheme'], scope['scheme'])
        expected = _origin(scheme + '://' + host)
        origin = headers.get(b'origin', b'').decode('latin-1')
        actual = _origin(origin) if origin else None
        oauth_callback_navigation = _is_laohu_oauth_callback_navigation(scope, headers, expected)
        allowed = oauth_callback_navigation or bool(expected and self._trusted_host(expected[1], scope))
        if origin and not oauth_callback_navigation:
            equivalent_loopback = bool(actual and expected and actual[0] == expected[0] and actual[2] == expected[2]
                                       and _loopback(actual[1]) and _loopback(expected[1]))
            allowed = allowed and bool(actual and (actual == expected or equivalent_loopback))
        elif not oauth_callback_navigation and headers.get(b'sec-fetch-site') == b'cross-site' and scope.get('path', '').startswith(('/api/', '/ws/')):
            allowed = False
        if not allowed:
            log.warning('已拒绝非当前页面来源的本地请求：%s %s', scope['type'], scope.get('path', ''))
            if scope['type'] == 'websocket':
                await send({'type':'websocket.close', 'code':1008})
            else:
                body = json.dumps({'ok':False, 'detail':'仅允许从当前画布页面或本地工具访问。',
                                   'message':'Access is restricted to the current canvas page or local tools.'}, ensure_ascii=False).encode('utf-8')
                await send({'type':'http.response.start', 'status':403, 'headers':[(b'content-type', b'application/json; charset=utf-8')]})
                await send({'type':'http.response.body', 'body':body})
            return
        if scope['type'] == 'http' and scope['method'] == 'OPTIONS' and origin:
            await send({'type':'http.response.start', 'status':204, 'headers':[
                (b'access-control-allow-origin', origin.encode('latin-1')),
                (b'access-control-allow-methods', b'GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS'),
                (b'access-control-allow-headers', headers.get(b'access-control-request-headers', b'content-type')),
                (b'vary', b'Origin')]})
            await send({'type':'http.response.body', 'body':b''})
            return
        async def send_response(message):
            if message['type'] == 'http.response.start' and origin and not oauth_callback_navigation:
                message = dict(message)
                message['headers'] = list(message.get('headers', [])) + [(b'access-control-allow-origin', origin.encode('latin-1')), (b'vary', b'Origin')]
            await send(message)
        await self.app(scope, receive, send_response)
