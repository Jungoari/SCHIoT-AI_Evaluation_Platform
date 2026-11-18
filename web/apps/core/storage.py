"""
안전한 파일 저장소

- 저장 파일명은 항상 UUID (사용자가 준 이름은 DB에 표시용으로만 저장)
  → 경로 조작(../../) 공격과 덮어쓰기가 원천적으로 불가능
- 저장 위치는 웹 루트 밖 (UPLOAD_ROOT / LABEL_ROOT)
- 저장하면서 SHA-256 과 크기를 함께 계산 (스트리밍, 메모리 절약)
- 크기 상한을 넘으면 저장 도중 중단하고 파일을 지운다
"""

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

CHUNK = 1024 * 1024
_SAFE_NAME = re.compile(r"^[0-9a-f]{32}(\.[a-z0-9]{1,12})?$")


class FileTooLarge(Exception):
    pass


@dataclass
class StoredFile:
    name: str  # 저장된 UUID 파일명
    sha256: str
    size: int


def upload_root() -> Path:
    return Path(settings.UPLOAD_ROOT)


def label_root() -> Path:
    return Path(settings.LABEL_ROOT)


def safe_path(root: Path, stored_name: str) -> Path:
    """
    저장 파일명 → 실제 경로. UUID 형식이 아니면 거부한다 (경로 조작 2차 방어)
    """
    if not stored_name or not _SAFE_NAME.match(stored_name):
        raise ValueError("잘못된 저장 파일명")
    path = (root / stored_name).resolve()
    if path.parent != root.resolve():
        raise ValueError("허용되지 않은 경로")
    return path


def _new_name(suffix: str) -> str:
    suffix = suffix.lower()
    if suffix and not re.fullmatch(r"\.[a-z0-9]{1,12}", suffix):
        suffix = ""
    return uuid.uuid4().hex + suffix


def save_stream(chunks, root: Path, suffix: str = "", max_bytes: int | None = None) -> StoredFile:
    root.mkdir(parents=True, exist_ok=True)
    name = _new_name(suffix)
    path = root / name
    digest = hashlib.sha256()
    size = 0
    try:
        with open(path, "xb") as fh:  # x: 이미 있으면 실패 (덮어쓰기 금지)
            for chunk in chunks:
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    raise FileTooLarge
                digest.update(chunk)
                fh.write(chunk)
        path.chmod(0o640)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return StoredFile(name=name, sha256=digest.hexdigest(), size=size)


def save_upload(uploaded_file, root: Path, suffix: str = "", max_bytes: int | None = None) -> StoredFile:
    """Django UploadedFile 저장"""
    return save_stream(uploaded_file.chunks(CHUNK), root, suffix, max_bytes)


def save_bytes(data: bytes, root: Path, suffix: str = "") -> StoredFile:
    return save_stream([data], root, suffix)


def read_head(path: Path, n: int = 64) -> bytes:
    with open(path, "rb") as fh:
        return fh.read(n)


def delete(root: Path, stored_name: str) -> None:
    if stored_name:
        try:
            safe_path(root, stored_name).unlink(missing_ok=True)
        except ValueError:
            pass
