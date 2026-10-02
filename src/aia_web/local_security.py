"""Same-origin browser boundary for the loopback, single-user console.

Not authentication against another program/user on this PC. Non-browser CLI
clients without Origin remain compatible; browsers must prove same origin and
possess this server instance's ephemeral capability before changing state.
"""
import secrets
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


class LocalBrowserBoundary:
    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope['type'] not in {'http', 'websocket'}:
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        host = headers.get(b'host', b'').decode('latin1')
        origin = headers.get(b'origin')
        try:
            parsed_host = urlsplit('http://' + host)
            local = parsed_host.hostname in {'127.0.0.1', 'localhost', '::1'}
            allowed_origin = not origin or urlsplit(origin.decode('latin1')).netloc == host and urlsplit(origin.decode('latin1')).scheme in {'http', 'https'}
        except (ValueError, UnicodeDecodeError):
            local = allowed_origin = False
        mutating = scope['type'] == 'websocket' or scope.get('method') not in {'GET', 'HEAD', 'OPTIONS'}
        valid_token = True
        protocol = None
        if origin and mutating:
            if scope['type'] == 'websocket':
                protocol = 'aia-local.' + self.token
                valid_token = protocol in scope.get('subprotocols', [])
            else:
                supplied = headers.get(b'x-aia-local-token', b'').decode('latin1')
                valid_token = secrets.compare_digest(supplied, self.token)
        if not local or not allowed_origin or not valid_token:
            if scope['type'] == 'websocket':
                return await send({'type': 'websocket.close', 'code': 1008})
            return await JSONResponse({'error': '로컬 앱 연결을 확인해주세요. 외부 페이지 요청은 허용되지 않습니다.'}, status_code=403)(scope, receive, send)
        scope['aia_local_protocol'] = protocol
        await self.app(scope, receive, send)
