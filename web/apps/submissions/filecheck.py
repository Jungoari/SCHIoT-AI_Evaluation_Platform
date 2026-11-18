"""
업로드 파일 내용 검증 — 확장자만 믿지 않고 실제 내용을 확인한다 (RFP p.7)

주의: 가중치 파일은 '형식 확인'만 한다. pickle 계열(.pkl/.joblib/.pt)은 불러오는 순간
안에 든 코드가 실행될 수 있으므로 웹·채점 서버에서는 절대 로드하지 않는다.
실제 로드는 샌드박스(네트워크 차단·정답 없음) 안에서만 한다.
"""

import json
import struct
from pathlib import Path

import nbformat

from apps.grading.validation import CsvReadError, read_csv


class FileCheckError(Exception):
    """사용자에게 보여줘도 안전한 메시지"""


WEIGHT_EXTENSIONS = {
    ".pkl": "pickle", ".pickle": "pickle", ".joblib": "joblib",
    ".pt": "pytorch", ".pth": "pytorch",
    ".h5": "keras-h5", ".keras": "keras",
    ".onnx": "onnx", ".safetensors": "safetensors",
}


def suffix_of(name: str) -> str:
    name = (name or "").lower()
    dot = name.rfind(".")
    return name[dot:] if dot != -1 else ""


def check_csv(path: Path) -> None:
    try:
        df = read_csv(path)
    except CsvReadError as exc:
        raise FileCheckError(str(exc)) from None
    if df.shape[1] < 2:
        raise FileCheckError("CSV에 열이 2개 이상 있어야 합니다")


def check_notebook(path: Path) -> dict:
    """노트북 JSON·스키마 검증. 코드 셀 수 등 간단한 정보 반환"""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        json.loads(raw)
        nb = nbformat.reads(raw, as_version=4)
        nbformat.validate(nb)
    except UnicodeDecodeError:
        raise FileCheckError("노트북 파일이 UTF-8 텍스트가 아닙니다") from None
    except json.JSONDecodeError:
        raise FileCheckError(".ipynb 파일이 아닙니다 (JSON 형식 오류)") from None
    except Exception:  # nbformat 검증 오류
        raise FileCheckError("Jupyter 노트북 형식이 올바르지 않습니다") from None
    code_cells = [c for c in nb.cells if c.cell_type == "code"]
    if not code_cells:
        raise FileCheckError("노트북에 코드 셀이 없습니다")
    return {"cells": len(nb.cells), "code_cells": len(code_cells)}


def _looks_pickle(head: bytes) -> bool:
    return len(head) >= 2 and head[0] == 0x80 and 2 <= head[1] <= 5


def _looks_zip(head: bytes) -> bool:
    return head.startswith(b"PK\x03\x04")


def _looks_compressed(head: bytes) -> bool:
    # joblib 압축 저장: zlib / gzip / xz / bz2 / lz4
    return head[:1] == b"\x78" or head.startswith((b"\x1f\x8b", b"\xfd7zXZ", b"BZh", b"\x04\x22\x4d\x18"))


def detect_weights(path: Path, original_name: str) -> str:
    """가중치 파일 형식 판별. 확장자와 실제 내용이 다르면 거부"""
    ext = suffix_of(original_name)
    if ext not in WEIGHT_EXTENSIONS:
        allowed = ", ".join(sorted(WEIGHT_EXTENSIONS))
        raise FileCheckError(f"지원하지 않는 가중치 파일 형식입니다 (허용: {allowed})")
    with open(path, "rb") as fh:
        head = fh.read(16)
    if not head:
        raise FileCheckError("가중치 파일이 비어 있습니다")

    kind = WEIGHT_EXTENSIONS[ext]
    ok = False
    if kind in ("pickle", "joblib"):
        ok = _looks_pickle(head) or (kind == "joblib" and _looks_compressed(head))
    elif kind == "pytorch":
        ok = _looks_zip(head) or _looks_pickle(head)
    elif kind == "keras":
        ok = _looks_zip(head)
    elif kind == "keras-h5":
        ok = head.startswith(b"\x89HDF\r\n\x1a\n")
    elif kind == "safetensors":
        if len(head) >= 9:
            (header_len,) = struct.unpack("<Q", head[:8])
            ok = 0 < header_len < 100_000_000 and head[8:9] == b"{"
    elif kind == "onnx":
        ok = head[:1] == b"\x08"  # protobuf 첫 필드(ir_version)
    if not ok:
        raise FileCheckError(f"파일 내용이 {ext} 형식이 아닙니다 (확장자만 바꾼 파일은 허용되지 않음)")
    return kind
