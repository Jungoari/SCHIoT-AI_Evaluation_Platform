"""
PPTX 미리보기 렌더러 (시각 점검용) — 슬라이드의 도형·텍스트·그림을 HTML 로 다시 그려 PNG 로 저장

    .venv/bin/python scripts/pptx_preview.py presentation/발표.pptx 출력폴더
    .venv/bin/python scripts/pptx_preview.py presentation/발표.pptx 출력폴더 --pdf presentation/발표_백업.pdf

--pdf: 슬라이드 번호 표시 없이 2배 해상도로 그려 PDF 1개로 묶는다
       (발표장 PC 에 PowerPoint 가 없거나 파일이 안 열릴 때를 대비한 백업. GIF 는 결과가 보이는 마지막 장면)

LibreOffice 없이 글자 넘침·겹침·여백을 확인하기 위한 근사 렌더러다.
(우리 생성기가 쓰는 도형: 텍스트 상자, 사각형/둥근 사각형, 그림, 레이아웃 장식)
"""

import base64
import html
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.util import Emu

DPI = 96
# PDF 백업에서는 GIF 의 첫 장면(동작 전 화면) 대신 마지막 장면(결과 화면)을 쓴다
GIF_LAST_FRAME = False


def gif_last_frame(blob: bytes) -> bytes:
    import io

    from PIL import Image

    im = Image.open(io.BytesIO(blob))
    im.seek(im.n_frames - 1)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def px(emu):
    return Emu(emu).inches * DPI if emu is not None else 0


def color_of(font_or_fill, default="#111"):
    try:
        if font_or_fill.color and font_or_fill.color.type is not None and font_or_fill.color.rgb is not None:
            return "#" + str(font_or_fill.color.rgb)
    except (AttributeError, TypeError):
        pass
    return default


def fill_of(shape):
    try:
        if shape.fill.type == 1:  # solid
            return "#" + str(shape.fill.fore_color.rgb)
    except Exception:  # 테마 색 등
        return "#cfd8ea"
    return "transparent"


def text_html(tf, default_size=18, default_color="#111", default_bold=False):
    out = []
    for p in tf.paragraphs:
        align = {1: "left", 2: "center", 3: "right"}.get(p.alignment, "left") if p.alignment else "left"
        after = p.space_after.pt if p.space_after is not None else 0
        runs = []
        for r in p.runs:
            size = r.font.size.pt if r.font.size else default_size
            bold = r.font.bold if r.font.bold is not None else default_bold
            col = color_of(r.font, default_color)
            t = html.escape(r.text).replace("\n", "<br>").replace("\v", "<br>")
            runs.append(f'<span style="font-size:{size * DPI / 72:.1f}px;font-weight:{700 if bold else 400};color:{col}">{t}</span>')
        content = "".join(runs) or "&nbsp;"
        out.append(f'<p style="margin:0 0 {after * DPI / 72:.1f}px;text-align:{align};line-height:1.2">{content}</p>')
    return "".join(out)


def shape_html(shape, z):
    x, y, w, h = px(shape.left), px(shape.top), px(shape.width), px(shape.height)
    style = f"left:{x:.1f}px;top:{y:.1f}px;width:{w:.1f}px;height:{h:.1f}px;z-index:{z}"
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        blob = shape.image.blob
        mime = shape.image.content_type
        if GIF_LAST_FRAME and mime == "image/gif":
            blob, mime = gif_last_frame(blob), "image/png"
        return f'<img class="s" style="{style};object-fit:fill" src="data:{mime};base64,{base64.b64encode(blob).decode()}">'
    parts = []
    if shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE:
        radius = 0
        try:
            if "ROUND" in str(shape.auto_shape_type):
                radius = min(w, h) * (shape.adjustments[0] if len(shape.adjustments) else 0.16)
        except Exception:
            pass
        border = ""
        try:
            if shape.line.fill.type == 1:
                border = f"border:1.3px solid #{shape.line.color.rgb};"
        except Exception:
            pass
        parts.append(f'<div class="s" style="{style};background:{fill_of(shape)};border-radius:{radius:.1f}px;{border}"></div>')
    if shape.has_text_frame and shape.text_frame.text.strip():
        tf = shape.text_frame
        ml, mr = px(tf.margin_left), px(tf.margin_right)
        mt, mb = px(tf.margin_top), px(tf.margin_bottom)
        anchor = {1: "flex-start", 3: "center", 4: "flex-end"}.get(tf.vertical_anchor, "flex-start") if tf.vertical_anchor else "flex-start"
        is_title = shape.is_placeholder and shape.placeholder_format.type in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE)
        size, col, bold = (25, "#203764", True) if is_title else (18, "#111", False)
        if is_title:
            anchor = "center"
        inner = text_html(tf, size, col, bold)
        if is_title:
            inner = inner.replace("text-align:left", "text-align:left;padding-left:14px")
        parts.append(f'<div class="s t" style="{style};padding:{mt:.1f}px {mr:.1f}px {mb:.1f}px {ml:.1f}px;justify-content:{anchor};z-index:{z + 1}">{inner}</div>')
    return "".join(parts)


def placeholder_geom(shape, layout):
    if shape.left is not None:
        return shape
    for lp in layout.placeholders:
        if lp.placeholder_format.idx == shape.placeholder_format.idx:
            shape.left, shape.top, shape.width, shape.height = lp.left, lp.top, lp.width, lp.height
    return shape


def render(pptx_path, out_dir, pdf_path=None):
    global GIF_LAST_FRAME
    GIF_LAST_FRAME = bool(pdf_path)
    prs = Presentation(pptx_path)
    W, H = px(prs.slide_width), px(prs.slide_height)
    pages = []
    for i, slide in enumerate(prs.slides, start=1):
        items, z = [], 1
        for s in slide.slide_layout.shapes:
            if not s.is_placeholder:
                items.append(shape_html(s, z))
                z += 2
        for s in slide.shapes:
            if s.is_placeholder:
                if s.placeholder_format.type == PP_PLACEHOLDER.SLIDE_NUMBER:
                    continue
                placeholder_geom(s, slide.slide_layout)
            items.append(shape_html(s, z))
            z += 2
        pages.append(f'<section style="width:{W}px;height:{H}px">{"".join(items)}<b class="no">{i}</b></section>')
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><style>
    body{{margin:0;background:#888;font-family:Arial,'Apple SD Gothic Neo',sans-serif}}
    section{{position:relative;background:#fff;margin:0 0 20px;overflow:hidden}}
    .s{{position:absolute;box-sizing:border-box}} .t{{display:flex;flex-direction:column;overflow:visible;word-break:keep-all;overflow-wrap:anywhere}}
    .no{{position:absolute;right:6px;bottom:4px;font:10px Arial;color:#c00}}
    </style></head><body>{''.join(pages)}</body></html>"""
    out = Path(out_dir).resolve()  # 상대 경로로 줘도 동작하도록 (브라우저가 file:// 절대 경로를 요구)
    out.mkdir(parents=True, exist_ok=True)
    (out / "preview.html").write_text(doc, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        scale = 2 if pdf_path else 1
        page = b.new_page(viewport={"width": int(W), "height": int(H)}, device_scale_factor=scale)
        page.goto((out / "preview.html").as_uri())
        page.wait_for_timeout(800)
        if pdf_path:
            page.add_style_tag(content=".no{display:none}")
        for i, sec in enumerate(page.locator("section").all(), start=1):
            sec.screenshot(path=str(out / f"slide-{i:02d}.png"))
        b.close()
    print(f"{len(pages)}장 → {out}")
    if pdf_path:
        from PIL import Image

        images = [Image.open(out / f"slide-{i:02d}.png").convert("RGB") for i in range(1, len(pages) + 1)]
        Path(pdf_path).parent.mkdir(parents=True, exist_ok=True)
        # 4:3 슬라이드 10in 기준 해상도 → 인쇄해도 선명하도록 2배 렌더링 결과를 그대로 사용
        images[0].save(pdf_path, save_all=True, append_images=images[1:], resolution=DPI * scale)
        print(f"PDF → {pdf_path} ({Path(pdf_path).stat().st_size / 1024 / 1024:.1f}MB)")


if __name__ == "__main__":
    args = sys.argv[1:]
    pdf = None
    if "--pdf" in args:
        i = args.index("--pdf")
        pdf = args[i + 1]
        del args[i : i + 2]
    render(args[0], args[1], pdf)
