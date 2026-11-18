"""
간단한 실패 횟수 제한기 (캐시 기반)

참여 코드 입력처럼 '맞힐 때까지 계속 시도'할 수 있는 기능에 사용한다.
로그인은 django-axes 가 담당한다.
"""

from django.core.cache import cache


class FailureLimiter:
    def __init__(self, scope: str, limit: int, window_seconds: int):
        self.scope = scope
        self.limit = limit
        self.window = window_seconds

    def _key(self, ident: str) -> str:
        return f"rl:{self.scope}:{ident}"

    def is_blocked(self, ident: str) -> bool:
        return cache.get(self._key(ident), 0) >= self.limit

    def fail(self, ident: str) -> int:
        key = self._key(ident)
        if cache.add(key, 1, self.window):
            return 1
        try:
            return cache.incr(key)
        except ValueError:  # 그 사이 만료된 경우
            cache.set(key, 1, self.window)
            return 1

    def reset(self, ident: str) -> None:
        cache.delete(self._key(ident))


def client_ident(request) -> str:
    """사용자 단위 + IP 단위 (로그인 전에는 IP만)"""
    ip = request.META.get("REMOTE_ADDR", "unknown")
    if request.user.is_authenticated:
        return f"u{request.user.pk}"
    return f"ip{ip}"


# 참여 코드: 10회 이상 실패하면 15분간 차단
join_code_limiter = FailureLimiter("joincode", limit=10, window_seconds=15 * 60)
