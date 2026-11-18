"""
안전한 노트북 렌더러 (RFP p.7 "Notebook 비신뢰 HTML·스크립트·위젯을 안전하게 처리")

3중 방어
  1) 서버 정제   : 스크립트·위젯·JS 출력은 아예 렌더링하지 않고, HTML·마크다운은 허용 목록 기반 정제(nh3)
  2) 격리 표시   : 결과는 sandbox 속성(스크립트 금지) iframe 안에서만 표시
  3) CSP 헤더   : 노트북 응답은 script-src 'none'
이미지는 base64 PNG/JPEG만 허용 (SVG 는 스크립트를 담을 수 있어 제외)
"""

import base64
import binascii
import html
import re

import markdown as md
import nh3

ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "code", "dd", "del", "div", "dl", "dt", "em", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "i", "img", "li", "ol", "p", "pre", "s", "span", "strong", "sub", "sup",
    "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul", "caption",
}
ALLOWED_ATTRS = {"a": {"href", "title"}, "img": {"src", "alt"}, "td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan"}}
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
BLOCKED_MIME = ("application/javascript", "application/vnd.jupyter.widget-view+json",
                "application/vnd.jupyter.widget-state+json", "text/javascript")
MAX_OUTPUT_CHARS = 20_000


_IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
_DATA_IMG = re.compile(r'src="data:image/(png|jpeg|gif);base64,[A-Za-z0-9+/=]+"', re.I)


def sanitize_html(raw: str) -> str:
    """
    허용 목록 기반 정제. 외부 주소 이미지는 제거한다
    (관리자 브라우저가 외부 서버로 요청을 보내 열람 사실·IP 가 새는 것 방지)
    """
    cleaned = nh3.clean(
        raw, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, url_schemes={"http", "https", "data"},
        link_rel="noopener noreferrer nofollow",
    )
    return _IMG_TAG.sub(lambda m: m.group(0) if _DATA_IMG.search(m.group(0)) else '<span class="blocked">[외부 이미지 제거]</span>', cleaned)


def _text(value) -> str:
    return "".join(value) if isinstance(value, list) else str(value or "")


def _pre(text: str, cls: str = "") -> str:
    text = ANSI.sub("", text)
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + f"\n… (출력 {len(text) - MAX_OUTPUT_CHARS:,}자 생략)"
    return f'<pre class="{cls}">{html.escape(text)}</pre>'


def _image(mime: str, data) -> str:
    raw = _text(data).replace("\n", "")
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return '<p class="blocked">[손상된 이미지]</p>'
    ok = (mime == "image/png" and decoded.startswith(b"\x89PNG")) or (
        mime == "image/jpeg" and decoded.startswith(b"\xff\xd8")
    )
    if not ok:
        return '<p class="blocked">[형식이 맞지 않는 이미지는 표시하지 않음]</p>'
    return f'<img alt="출력 이미지" src="data:{mime};base64,{raw}">'


def _output(out: dict) -> str:
    kind = out.get("output_type")
    if kind == "stream":
        return _pre(_text(out.get("text")), "stream stderr" if out.get("name") == "stderr" else "stream")
    if kind == "error":
        return _pre("\n".join(out.get("traceback", [])) or f"{out.get('ename')}: {out.get('evalue')}", "error")
    if kind in ("execute_result", "display_data"):
        data = out.get("data", {})
        blocked = [m for m in data if m in BLOCKED_MIME]
        for mime in ("image/png", "image/jpeg"):
            if mime in data:
                return _image(mime, data[mime])
        if "text/html" in data:
            return f'<div class="html-out">{sanitize_html(_text(data["text/html"]))}</div>'
        if "text/markdown" in data:
            return sanitize_html(md.markdown(_text(data["text/markdown"]), extensions=["tables", "fenced_code"]))
        if "text/plain" in data:
            return _pre(_text(data["text/plain"]))
        if blocked:
            return '<p class="blocked">[스크립트·위젯 출력은 보안상 표시하지 않음]</p>'
    return ""


def render_notebook(nb: dict) -> tuple[str, dict]:
    """노트북 → 정제된 HTML 조각, 통계"""
    parts = []
    stats = {"cells": 0, "code": 0, "blocked": 0}
    for cell in nb.get("cells", []):
        stats["cells"] += 1
        ctype = cell.get("cell_type")
        src = _text(cell.get("source"))
        if ctype == "markdown":
            parts.append(f'<section class="cell md">{sanitize_html(md.markdown(src, extensions=["tables", "fenced_code"]))}</section>')
        elif ctype == "code":
            stats["code"] += 1
            count = cell.get("execution_count")
            tags = cell.get("metadata", {}).get("tags", [])
            tag_html = "".join(f'<span class="tag">{html.escape(str(t))}</span>' for t in tags)
            outs = []
            for out in cell.get("outputs", []):
                rendered = _output(out)
                if "보안상 표시하지 않음" in rendered:
                    stats["blocked"] += 1
                outs.append(rendered)
            parts.append(
                '<section class="cell code">'
                f'<div class="prompt">[{count if count is not None else " "}]{tag_html}</div>'
                f'<pre class="src">{html.escape(src)}</pre>'
                + (f'<div class="outputs">{"".join(outs)}</div>' if outs else "")
                + "</section>"
            )
        else:  # raw 셀은 텍스트로만
            parts.append(_pre(src, "raw"))
    return "\n".join(parts), stats


NOTEBOOK_CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"

NOTEBOOK_STYLE = """
body{font:14px/1.6 -apple-system,BlinkMacSystemFont,'Pretendard','Apple SD Gothic Neo',sans-serif;color:#111;margin:0;padding:20px;background:#fff}
.cell{margin:0 0 14px}
.md{padding:4px 2px}
.md h1,.md h2,.md h3{margin:.6em 0 .3em}
.code .prompt{font:600 11px ui-monospace,monospace;color:#7a7a7a;margin-bottom:4px}
.tag{display:inline-block;margin-left:6px;padding:0 6px;border-radius:999px;background:#e3ebfd;color:#1e4fd0}
pre{margin:0;white-space:pre-wrap;word-break:break-word;font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace}
pre.src{background:#f3f5f9;border-radius:12px;padding:12px 14px}
.outputs{border-left:3px solid #e7e8ec;margin:6px 0 0 4px;padding:4px 0 4px 12px}
pre.stderr{color:#b45309}
pre.error{color:#be123c}
.blocked{color:#b45309;font-weight:600;font-size:12px}
img{max-width:100%}
table{border-collapse:collapse;font-size:12px}
td,th{border:1px solid #e7e8ec;padding:3px 8px}
"""
