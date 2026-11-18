"""
공통 미들웨어

- RequestIdMiddleware: 요청마다 추적 ID를 부여한다. 오류 화면에는 이 ID만 보여주고
  상세 내용은 서버 로그에서 ID로 찾는다 (행안부 가이드 '오류 메시지 정보노출' 대응)
- SecurityHeadersMiddleware: CSP 등 보안 헤더 기본값을 붙인다.
  뷰에서 더 엄격한 CSP를 직접 지정하면 그 값을 존중한다 (예: 노트북 뷰어)
"""

import secrets

from .logging import request_id_var

DEFAULT_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "frame-src 'self'",
        "frame-ancestors 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
)


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = secrets.token_hex(4).upper()
        request.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        response["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", DEFAULT_CSP)
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        return response
