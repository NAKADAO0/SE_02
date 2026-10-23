"""Loopback-only HTTP adapter with explicit same-origin write checks."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from .manager import ApiError, ID, JobManager

MAX_BODY = 64 * 1024

class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(host='127.0.0.1', port=8763, manager=None, *, static_dir=None):
    if host != '127.0.0.1':
        raise ValueError('The workspace server must bind to 127.0.0.1')
    manager = manager or JobManager()
    assets = Path(static_dir) if static_dir is not None else Path(__file__).parent / 'static'
    assets = assets.resolve()
    class Handler(BaseHTTPRequestHandler):
        server_version = 'SE02LocalUI/0.3'
        def log_message(self, *args):
            pass
        def _send(self, status, body, content_type='application/json; charset=utf-8', *, filename=None):
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if filename:
                self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
        def _json(self,status,value):
            self._send(status,json.dumps(manager.safe(value),ensure_ascii=False,allow_nan=False).encode('utf-8'))
        def _host(self):
            values = self.headers.get_all('Host',[])
            allowed = {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            if len(values)!=1 or values[0] not in allowed:
                raise ApiError(403,'Local host required')
            return values[0]
        def _path(self):
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                raise ApiError(404,'Not found')
            return parsed.path
        def _dispatch(self, method):
            try:
                host = self._host()
                path = self._path()
                if method == 'POST':
                    if path != '/api/runs':
                        raise ApiError(404,'Not found')
                    if self.headers.get_all('Origin',[]) != ['http://' + host] or self.headers.get_all('X-SE02-Request',[]) != ['1']:
                        raise ApiError(403,'Same-origin JSON request required')
                    content_types = self.headers.get_all('Content-Type',[])
                    if len(content_types)!=1 or content_types[0].split(';')[0].strip().lower()!='application/json':
                        raise ApiError(415,'application/json required')
                    lengths = self.headers.get_all('Content-Length',[])
                    if self.headers.get('Transfer-Encoding') or len(lengths)!=1 or not re.fullmatch(r'[0-9]+',lengths[0]):
                        raise ApiError(400,'A valid Content-Length is required')
                    length = int(lengths[0])
                    if length>MAX_BODY:
                        raise ApiError(413,'Request body exceeds 64 KiB')
                    self.connection.settimeout(5)
                    raw = self.rfile.read(length)
                    if len(raw)!=length:
                        raise ApiError(400,'Incomplete JSON body')
                    try:
                        def unique(items):
                            data={}
                            for key,value in items:
                                if key in data:
                                    raise ValueError('duplicate field')
                                data[key]=value
                            return data
                        body = json.loads(raw.decode('utf-8'),object_pairs_hook=unique,parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite number')))
                    except (ValueError,UnicodeError):
                        raise ApiError(400,'Invalid JSON body') from None
                    self._json(202,manager.submit(body))
                    return
                if path == '/api/config':
                    self._json(200,manager.config())
                elif path == '/api/runs':
                    self._json(200,manager.runs())
                elif path.startswith('/api/runs/'):
                    tail = path[len('/api/runs/'):]
                    if tail.endswith('/download'):
                        identifier = tail[:-len('/download')]
                        if not ID.fullmatch(identifier):
                            raise ApiError(404,'Run not found')
                        self._send(200,manager.download(identifier),'text/x-python; charset=utf-8',filename=f'se02-{identifier}.py')
                    else:
                        self._json(200,manager.snapshot(tail))
                else:
                    known = {'/':('index.html','text/html; charset=utf-8'),'/index.html':('index.html','text/html; charset=utf-8'),'/styles.css':('styles.css','text/css; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8')}
                    if path not in known:
                        raise ApiError(404,'Not found')
                    name, media = known[path]
                    file = (assets/name).resolve()
                    if not file.is_relative_to(assets) or not file.is_file():
                        raise ApiError(404,'Not found')
                    self._send(200,file.read_bytes(),media)
            except ApiError as exc:
                self.close_connection = True
                self._json(exc.status,{'error':str(exc)})
            except Exception:
                self.close_connection = True
                self._json(500,{'error':'The local workspace request could not complete.'})
        def do_GET(self):
            self._dispatch('GET')
        def do_POST(self):
            self._dispatch('POST')
        def do_OPTIONS(self):
            self._json(405,{'error':'Method not allowed'})
        def do_PUT(self):
            self._json(405,{'error':'Method not allowed'})
        do_DELETE = do_PUT
        do_PATCH = do_PUT
        do_HEAD = do_PUT
    server = LocalServer((host,port),Handler)
    server.manager = manager
    return server
