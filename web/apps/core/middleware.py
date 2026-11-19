"""
공통 미들웨어

- TrustedProxyMiddleware: 리버스 프록시(HTTPS 종단) 뒤에서 실제 접속자 IP 복원.
  설정한 프록시 개수만큼만 X-Forwarded-For 를 믿는다 (기본 0 = 헤더 무시, 위조 불가)
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


class TrustedProxyMiddleware:
    """
    프록시 뒤에서는 모든 요청의 REMOTE_ADDR 가 프록시 IP 하나로 보인다.
    그러면 IP 기준 실패 횟수 제한(참여 코드·로그인)이 '모든 방문자 공동 계정'처럼 동작해
    누군가 10번 틀리면 반 전체의 가입이 15분간 막힌다 → 실제 접속자 IP 로 바꿔 준다.

    X-Forwarded-For 는 '클라이언트, 프록시1, 프록시2' 순으로 쌓이고, 맨 앞쪽은 접속자가 위조할 수 있다.
    그래서 우리 쪽 프록시 개수(N)만큼 오른쪽에서 센 값만 믿는다 (N=1 이면 마지막 값).
    """

    def __init__(self, get_response):
        from django.conf import settings

        self.get_response = get_response
        self.count = int(getattr(settings, "TRUSTED_PROXY_COUNT", 0))

    def __call__(self, request):
        if self.count > 0:
            hops = [h.strip() for h in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if h.strip()]
            if len(hops) >= self.count:
                request.META["REMOTE_ADDR"] = hops[-self.count]
        return self.get_response(request)


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
