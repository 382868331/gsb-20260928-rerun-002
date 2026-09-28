"""Tiny ASGI test helper - calls the app in-process without any socket.

The sandbox blocks network syscalls and httpx's transports hang on this
Python build, so tests drive the ASGI app directly.
"""
import asyncio
import json


class ASGIResponse:
    def __init__(self, status, headers, body):
        self.status_code = status
        self.headers = {k.decode().lower(): v.decode() for k, v in headers}
        self.body = b"".join(body)

    def json(self):
        return json.loads(self.body.decode())


class ASGIClient:
    def __init__(self, app):
        self.app = app

    def request(self, method, path, body=None, headers=None):
        return asyncio.run(self._request(method, path, body, headers or {}))

    async def _request(self, method, path, body, headers):
        if body is None and method in ("POST", "PUT"):
            body = b""
        elif body is not None and not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body).encode()
            headers = {"content-type": "application/json", **(headers or {})}
        else:
            body = b"" if body is None else bytes(body)
            headers = dict(headers or {})

        response_status = None
        response_headers = None
        response_body = []

        async def receive():
            nonlocal body
            if body:
                chunk, body = body, b""
                return {"type": "http.request", "body": chunk, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            nonlocal response_status, response_headers
            if message["type"] == "http.response.start":
                response_status = message["status"]
                response_headers = message["headers"]
            elif message["type"] == "http.response.body":
                response_body.append(message.get("body", b""))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]
            + [(b"content-length", str(len(body)).encode())],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        await self.app(scope, receive, send)
        return ASGIResponse(response_status, response_headers, response_body)
