"""
로그 필터

- 모든 로그 줄에 요청 추적 ID를 붙인다
- 비밀번호·세션·토큰처럼 보이는 값은 가린다 (로그에 내부 비밀 정보 노출 금지)
"""

import logging
import re
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|secret|token|sessionid|csrftoken|api[_-]?key|join[_-]?code)"
    r"(\s*[=:]\s*|\"\s*:\s*\")([^\s&\"',;]+)"
)


def mask_secrets(text: str) -> str:
    return _SECRET_PATTERN.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class MaskSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # 포맷 실패 시 원본 유지
            return True
        masked = mask_secrets(message)
        if masked != message:
            record.msg = masked
            record.args = ()
        return True
