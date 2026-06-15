"""
ASGI middleware to store 'send' callable in request object.

This allows HTTP views to use Server-Sent Events (SSE) streaming
by accessing request._asgi_send.
"""
import re

from django.conf import settings


class SSEStreamingMiddleware:
    """
    ASGI middleware that stores the 'send' callable in the request scope.

    Also injects CORS headers into HTTP responses so that SSE streams
    (which bypass Django's normal response pipeline) include the
    required Access-Control-* headers.
    """

    def __init__(self, app):
        self.app = app

    def _get_request_origin(self, scope) -> str | None:
        """Extract the Origin header from the ASGI scope."""
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"origin":
                return header_value.decode()
        return None

    def _is_origin_allowed(self, origin: str) -> bool:
        """Check if the origin is in CORS_ALLOWED_ORIGINS or matches CORS_ALLOWED_ORIGIN_REGEXES."""
        allowed_origins = getattr(settings, "CORS_ALLOWED_ORIGINS", [])
        if origin in allowed_origins:
            return True
        allowed_regexes = getattr(settings, "CORS_ALLOWED_ORIGIN_REGEXES", [])
        return any(re.match(pattern, origin) for pattern in allowed_regexes)

    def _build_cors_headers(self, origin: str) -> list[list[bytes]]:
        """Build CORS response headers based on Django settings."""
        headers: list[list[bytes]] = []

        headers.append([b"access-control-allow-origin", origin.encode()])

        if getattr(settings, "CORS_ALLOW_CREDENTIALS", False):
            headers.append([b"access-control-allow-credentials", b"true"])

        expose = getattr(settings, "CORS_EXPOSE_HEADERS", [])
        if expose:
            headers.append([b"access-control-expose-headers", ", ".join(expose).encode()])

        allow_headers = getattr(settings, "CORS_ALLOW_HEADERS", [])
        if allow_headers:
            headers.append([b"access-control-allow-headers", ", ".join(allow_headers).encode()])

        return headers

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            origin = self._get_request_origin(scope)

            if origin and self._is_origin_allowed(origin):
                cors_headers = self._build_cors_headers(origin)

                async def cors_send(message):
                    if message["type"] == "http.response.start":
                        existing = list(message.get("headers", []))
                        # Only add CORS headers if not already present
                        existing_names = {h[0] for h in existing}
                        for h in cors_headers:
                            if h[0] not in existing_names:
                                existing.append(h)
                        message = {**message, "headers": existing}
                    await send(message)

                # Store CORS-wrapped send so SSE views also get CORS headers
                scope["_asgi_send"] = cors_send
                return await self.app(scope, receive, cors_send)

            # No CORS needed — store raw send for SSE views
            scope["_asgi_send"] = send

        return await self.app(scope, receive, send)
