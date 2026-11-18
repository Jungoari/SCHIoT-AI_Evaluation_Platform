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


class UploadSizeLimitMiddleware:
    """
    업로드 요청의 전체 크기가 허용 상한(CSV + 노트북 + 가중치 + 여유 1MB)을 넘으면
    본문을 읽기 전에 413 으로 거부한다 → 거대한 요청으로 디스크·메모리를 고갈시키는 공격 차단
    """

    def __init__(self, get_response):
        from django.conf import settings

        self.get_response = get_response
        self.limit = settings.MAX_CSV_BYTES + settings.MAX_NOTEBOOK_BYTES + settings.MAX_WEIGHTS_BYTES + 1024 * 1024
        self.default_limit = self.limit  # 관리자 배포 파일도 같은 상한 (가중치 최대 크기 기준)

    def __call__(self, request):
        from django.http import JsonResponse

        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        limit = self.limit if request.path.startswith("/s/") else self.default_limit
        if length > limit:
            return JsonResponse({"ok": False, "error": f"요청이 너무 큽니다 (최대 {limit // (1024 * 1024)}MB)"}, status=413)
        return self.get_response(request)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", DEFAULT_CSP)
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        return response
