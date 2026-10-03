"""Request IDs and HTTP security headers for every API response (pure ASGI, no buffering)."""

from __future__ import annotations

import re
import uuid

from starlette.datastructures import MutableHeaders

_RID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_DOCS = ("/docs", "/redoc", "/openapi.json")

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
# The API only returns JSON, so nothing may load or frame it. The interactive docs page (Swagger UI
# from a CDN) is left without a CSP so it keeps working.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


class SecurityHeadersMiddleware:
    def __init__(self, app, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _RID.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid
        path = scope.get("path", "")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                h["X-Request-ID"] = rid
                for k, v in BASE_HEADERS.items():
                    h.setdefault(k, v)
                if not path.startswith(_DOCS):
                    h.setdefault("Content-Security-Policy", API_CSP)
                if path.startswith("/v1/"):
                    h.setdefault("Cache-Control", "no-store")
                if self.hsts:
                    h.setdefault("Strict-Transport-Security", "max-age=31536000")
            await send(message)

        await self.app(scope, receive, send_with_headers)
