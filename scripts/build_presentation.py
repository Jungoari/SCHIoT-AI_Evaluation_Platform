"""
발표 자료 생성 — 템플릿(~/Desktop/Ubicomp LAB/template.pptx) 기반

    .venv/bin/python scripts/build_presentation.py [템플릿 경로]

템플릿 규칙: 4:3, Arial, 마침표 없이 개조식
요구사항 슬라이드 구도: 좌측 패널(① RFP 요구사항 ② 왜 중요한가 ③ 어떻게 해결했나) + 우측 테스트 시연 GIF
"""

import os
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Desktop" / "Ubicomp LAB" / "template.pptx"
GIFS = ROOT / "docs" / "assets" / "gifs"
OUT = ROOT / "presentation" / "AI모델_성능평가_자동화_발표.pptx"
REPO_URL = os.environ.get("REPO_URL", "https://github.com/Jungoari/SCHIoT-AI_Evaluation_Platform").strip()

NAVY = RGBColor(0x20, 0x37, 0x64)
SCH = RGBColor(0x24, 0x53, 0x9C)
INK = RGBColor(0x1F, 0x29, 0x37)
MUTED = RGBColor(0x5B, 0x67, 0x7A)
CARD = RGBColor(0xEE, 0xF2, 0xFA)
CARD2 = RGBColor(0xF5, 0xF6, 0xF8)
GREEN = RGBColor(0x0F, 0x9F, 0x6E)
RED = RGBColor(0xE1, 0x3B, 0x2E)
AMBER = RGBColor(0xD9, 0x77, 0x06)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT = "Arial"


# ---------------------------------------------------------------------------
# 도구
# ---------------------------------------------------------------------------
def text(slide, x, y, w, h, paras, anchor=MSO_ANCHOR.TOP, align=PP_ALIGN.LEFT, margin=0.08):
    """paras: [(문자열 또는 [(run, {opts})], {size, bold, color, space_after})]"""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for side in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, side, Inches(margin))
    first = True
    for content, opts in paras:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = align
        if opts.get("space_after") is not None:
            p.space_after = Pt(opts["space_after"])
        runs = content if isinstance(content, list) else [(content, {})]
        for run_text, ropts in runs:
            r = p.add_run()
            r.text = run_text
            f = r.font
            f.name = FONT
            f.size = Pt(ropts.get("size", opts.get("size", 14)))
            f.bold = ropts.get("bold", opts.get("bold", False))
            f.color.rgb = ropts.get("color", opts.get("color", INK))
    return box


def rect(slide, x, y, w, h, fill, rounded=True, line=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
                                   Inches(x), Inches(y), Inches(w), Inches(h))
    if rounded:
        shape.adjustments[0] = 0.08
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line:
        shape.line.color.rgb = line
        shape.line.width = Pt(1)
    else:
        shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def bullets(lines, size=13, color=INK, gap=3):
    """문자열은 일반, (문자열, True) 는 강조 색 굵게"""
    out = []
    for t in lines:
        body = (t[0], {"bold": True, "color": SCH}) if isinstance(t, tuple) else (t, {})
        out.append(([("· ", {"color": SCH, "bold": True}), body], {"size": size, "color": color, "space_after": gap}))
    return out


def content_slide(prs, title, number):
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title
    for ph in list(slide.placeholders):
        if ph.placeholder_format.idx == 1:  # 본문 개체 틀은 직접 구성하므로 제거
            ph._element.getparent().remove(ph._element)
    text(slide, 9.45, 7.18, 0.5, 0.3, [(str(number), {"size": 12, "color": NAVY, "bold": True})], align=PP_ALIGN.RIGHT, margin=0)
    return slide


STATIC_LAST_FRAME = {"G12", "G17", "G18"}  # 터미널형 GIF 는 첫 화면이 비어 있어 결과가 보이는 마지막 장면을 사용


def last_frame(path: Path) -> Path:
    import subprocess

    out = ROOT / "presentation" / "frames" / (path.stem + "_last.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.3", "-i", str(path), "-frames:v", "1", str(out)], check=True)
    return out


def gif(slide, name, x, y, w, caption=None):
    path = next(GIFS.glob(f"{name}*.gif"))
    if name in STATIC_LAST_FRAME:
        path = last_frame(path)
    from PIL import Image

    with Image.open(path) as im:
        ratio = im.height / im.width
    h = w * ratio
    rect(slide, x - 0.06, y - 0.06, w + 0.12, h + 0.12, CARD2)
    slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))
    if caption:
        text(slide, x, y + h + 0.12, w, 0.4, [(caption, {"size": 12, "bold": True, "color": GREEN})], align=PP_ALIGN.CENTER)
    return h


def gif_ratio(name):
    from PIL import Image

    with Image.open(next(GIFS.glob(f"{name}*.gif"))) as im:
        return im.height / im.width


def left_panel(slide, page, req, why, how, y0=1.15, w=3.95, heights=(1.65, 1.3, 2.7)):
    x = 0.4
    blocks = [("① RFP 요구사항", req, CARD), ("② 왜 중요한가", why, CARD), ("③ 어떻게 해결했나", how, CARD)]
    y = y0
    for (label, lines, fill), h in zip(blocks, heights, strict=True):
        rect(slide, x, y, w, h, fill)
        head = [(label, {"size": 15, "bold": True, "color": NAVY, "space_after": 5})]
        if label.startswith("①"):
            head = [([(label, {"bold": True, "color": NAVY}), (f"   {page}", {"color": SCH, "bold": True, "size": 12})],
                     {"size": 15, "space_after": 5})]
        items = []
        for line in lines:
            # 문자열 = 일반 / (문자열, True) = 강조 / (문자열, "기술 설명") = 아래에 작은 회색 글씨로 기술 용어
            main, emph, note = (line, False, None) if isinstance(line, str) else (
                line[0], any(x is True for x in line[1:]), next((x for x in line[1:] if isinstance(x, str)), None))
            body = (main, {"bold": True, "color": SCH}) if emph else (main, {})
            items.append(([("· ", {"color": SCH, "bold": True}), body], {"size": 14, "space_after": 1 if note else 3}))
            if note:
                items.append(([("   " + note, {"color": MUTED})], {"size": 10, "space_after": 4}))
        text(slide, x + 0.1, y + 0.08, w - 0.2, h - 0.12, head + items, margin=0.05)
        y += h + 0.1


def extra_paras(extra):
    """GIF 아래 근거 카드: (제목, [(왼쪽, 오른쪽, 색)...])"""
    head, rows = extra
    paras = [(head, {"size": 13, "bold": True, "color": NAVY, "space_after": 4})]
    for left, right, color in rows:
        paras.append(([(left + "  ", {"color": INK}), (right, {"bold": True, "color": color})], {"size": 13, "space_after": 3}))
    return paras


def stat_card(slide, x, y, w, h, value, label, color=NAVY):
    rect(slide, x, y, w, h, CARD)
    text(slide, x, y + 0.15, w, h * 0.55, [(value, {"size": 30, "bold": True, "color": color})], align=PP_ALIGN.CENTER,
         anchor=MSO_ANCHOR.MIDDLE)
    text(slide, x + 0.1, y + h * 0.58, w - 0.2, h * 0.4, [(label, {"size": 13, "color": MUTED})], align=PP_ALIGN.CENTER)


def remove_slide(prs, index):
    sld_ids = prs.slides._sldIdLst
    sld = sld_ids[index]
    prs.part.drop_rel(sld.rId)
    sld_ids.remove(sld)


def move_slide(prs, old, new):
    sld_ids = prs.slides._sldIdLst
    el = sld_ids[old]
    sld_ids.remove(el)
    sld_ids.insert(new, el)


def set_runs(shape, texts):
    """기존 서식을 유지하며 문단 텍스트만 교체"""
    paras = shape.text_frame.paragraphs
    for p, t in zip(paras, texts, strict=False):
        if p.runs:
            p.runs[0].text = t
            for r in p.runs[1:]:
                r.text = ""


# ---------------------------------------------------------------------------
# 슬라이드
# ---------------------------------------------------------------------------
def build():
    prs = Presentation(str(TEMPLATE))
    title_slide, qa_slide = prs.slides[0], prs.slides[3]

    # 1. 표지
    for sh in title_slide.shapes:
        if sh.name == "Chevron 6":
            set_runs(sh, ["AI모델 성능평가 자동화 플랫폼"])
            sh.text_frame.paragraphs[0].runs[0].font.size = Pt(30)
        elif sh.name == "TextBox 7":
            set_runs(sh, ["AI모델 성능평가 자동화 경진대회"])
            sh.width = Inches(4)
    text(title_slide, 1, 3.45, 8, 0.4, [("제출하는 순간 채점되고, 공정하게 검토되는 수업용 평가 시스템",
                                         {"size": 16, "color": SCH, "bold": True})], align=PP_ALIGN.CENTER)
    text(title_slide, 1, 3.9, 8, 0.35, [(REPO_URL, {"size": 12, "color": MUTED})], align=PP_ALIGN.CENTER)

    n = 2

    # 2. 문제 정의 (추정 수치 없이 상황만)
    s = content_slide(prs, "문제 정의 — 수작업 채점의 세 가지 어려움", n); n += 1
    for i, (v, l, c) in enumerate([("손 채점", "CSV를 하나씩 채점하고\n순위표를 직접 정리", NAVY),
                                   ("재제출 반복", "형식이 틀린 파일마다\n안내하고 다시 받기", NAVY),
                                   ("부정 확인", "노트북을 일일이 열어\n부정 여부 확인", RED)]):
        stat_card(s, 0.55 + i * 3.05, 1.35, 2.85, 1.9, v, l, c)
    rect(s, 0.55, 3.6, 8.9, 3.25, CARD2)
    text(s, 0.75, 3.75, 8.5, 3.0, [("RFP가 요구하는 것", {"size": 17, "bold": True, "color": NAVY, "space_after": 6})] + bullets([
        "학생이 올린 예측 결과(CSV)를 자동 채점하고 순위표로 공개",
        "조교 검토 → 교수 최종 승인으로 공정하게 성적 확정",
        "CSV가 정말 모델이 예측한 결과인지 판단하는 절차",
        "학생 코드를 실행해도 정답·비밀 정보·다른 학생 자료는 볼 수 없게",
    ], size=16, gap=8))

    # 3. Kaggle
    s = content_slide(prs, "Kaggle에서 배우고, 수업에 맞게 바꾼 것", n); n += 1
    rows = [("즉시 자동 채점", "올리자마자 점수 + 올리기 전 형식 검사"),
            ("실시간 순위표", "학생끼리는 익명, 관리자만 실명"),
            ("제출 횟수 제한", "학생 잘못이 아닌 오류는 차감 안 함"),
            ("제출 예시 파일", "정답을 뺀 학생용 자료 자동 생성"),
            ("상위권 코드 확인", "최고 기록부터 조교 → 교수 2단계 검토"),
            ("코드 재실행 대회", "의심 제출만 다시 실행해 서버 부담 절약")]
    text(s, 0.55, 1.15, 4.3, 0.4, [("Kaggle의 장점", {"size": 14, "bold": True, "color": MUTED})])
    text(s, 5.0, 1.15, 4.45, 0.4, [("수업 환경에 맞춘 설계", {"size": 14, "bold": True, "color": SCH})])
    for i, (a, b) in enumerate(rows):
        y = 1.6 + i * 0.86
        rect(s, 0.55, y, 4.3, 0.74, CARD2)
        rect(s, 5.0, y, 4.45, 0.74, CARD)
        text(s, 0.7, y, 4.0, 0.74, [(a, {"size": 14, "bold": True, "color": INK})], anchor=MSO_ANCHOR.MIDDLE)
        text(s, 5.15, y, 4.2, 0.74, [(b, {"size": 13, "bold": True, "color": NAVY})], anchor=MSO_ANCHOR.MIDDLE)
        text(s, 4.78, y, 0.3, 0.74, [("→", {"size": 14, "bold": True, "color": SCH})], anchor=MSO_ANCHOR.MIDDLE, margin=0)

    # 4. 핵심 설계
    s = content_slide(prs, "핵심 설계 — 정답이 있는 곳과 학생 코드를 실행하는 곳을 분리", n); n += 1
    rect(s, 3.0, 1.2, 4.0, 0.8, NAVY)
    text(s, 3.0, 1.2, 4.0, 0.8, [("웹 서버 (화면 · 업로드)", {"size": 15, "bold": True, "color": WHITE}),
                                 ("Django · 파일 내용 검사 · 무작위 이름 저장", {"size": 10, "color": WHITE})],
         anchor=MSO_ANCHOR.MIDDLE, align=PP_ALIGN.CENTER)
    text(s, 4.0, 2.05, 2.0, 0.35, [("작업 대기열 (Redis)", {"size": 10, "color": MUTED})], align=PP_ALIGN.CENTER)
    for x, title_, sub, tag, tag_color in ((0.7, "채점 담당", "CSV 숫자만 비교 (코드 실행 안 함)", "정답 있음 · 코드 실행 없음", GREEN),
                                          (5.3, "검증 담당", "학생 코드 실행을 지시만 함", "정답 없음 · 컨테이너 명령만 허용", RED)):
        rect(s, x, 2.5, 4.0, 1.2, CARD)
        text(s, x, 2.55, 4.0, 1.1, [(title_, {"size": 15, "bold": True, "color": NAVY}), (sub, {"size": 12, "color": MUTED}),
                                    (tag, {"size": 12, "bold": True, "color": tag_color})], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    rect(s, 5.3, 4.05, 4.0, 2.75, CARD2, line=SCH)
    text(s, 5.45, 4.12, 3.75, 2.65, [("학생 코드 실행 공간", {"size": 15, "bold": True, "color": SCH, "space_after": 2}),
                                    ("Docker 샌드박스 컨테이너", {"size": 10, "color": MUTED, "space_after": 4})] + bullets([
        "실행할 때마다 새로 만들고 끝나면 삭제", "인터넷 끊김 · 파일은 읽기만", "최소 권한으로 실행",
        "시간 · 메모리 · 프로세스 수 제한", ("정답과 비밀 정보가 아예 없음", True)], size=14, gap=4))
    text(s, 0.7, 4.05, 4.3, 2.75, [("왜 이렇게 나눴나", {"size": 15, "bold": True, "color": NAVY, "space_after": 6})] + bullets([
        "막는 규칙이 하나 빠져도 뚫리지 않도록, 훔칠 정답이 없는 곳에서 실행",
        "채점은 코드를 돌리지 않고 CSV 숫자만 비교 → 빠르고 안전",
        "코드 재실행은 의심 제출만 → 서버 부담 절약",
    ], size=14, gap=6))

    # 5~13. RFP 요구사항 슬라이드 (좌: 요구사항·이유·해결 / 우: 시연 GIF + 근거 카드)
    req_slides = [
        ("정답 보호 · 안전한 코드 실행", "p.2·5·7",
         ["학생에게 정답을 보여 주지 않을 것", "학생 코드를 실행할 때 정답·비밀 정보·다른 학생 자료에 접근 못 하게"],
         ["정답이 새면 대회 전체가 무효", "한 번 새면 되돌릴 수 없는 사고"],
         [("정답이 있는 곳과 코드 실행 공간을 완전히 분리", "채점 서버 ↔ 샌드박스 컨테이너"),
          ("학생 코드는 인터넷이 끊긴 일회용 공간에서만 실행", "네트워크 차단 · 읽기 전용 · 비루트"),
          ("공격 6가지를 직접 시도 → 모두 차단", True)],
         "G12", "학생 코드로 공격을 시도해도 모두 차단",
         ("학생 코드가 실행되는 공간", [("인터넷", "끊겨 있음", NAVY), ("파일", "읽기만 가능 · 정답 파일 없음", NAVY),
                                ("권한", "최소 권한", NAVY), ("시간 · 메모리", "제한 · 넘으면 강제 종료", NAVY)])),
        ("계정 · 참여 코드", "p.3",
         ["대회를 만들면 참여 코드 자동 생성", "처음 가입할 때 코드 필수", "이미 가입한 학생은 코드로 다른 대회 추가"],
         ["대회와 관계없는 사람의 가입 방지", "학생 1명이 계정 하나로 여러 과목 참여"],
         ["학생용 · 조교용 코드를 따로 발급",
          ("코드 원문은 저장하지 않고 한 번만 보여 줌", "해시(SHA-256)로만 저장 · 잃어버리면 재발급"),
          ("10번 틀리면 15분 동안 입력 제한", True, "무작위 대입 공격 방지")],
         "G02", "코드 없이는 가입 불가 · 코드로 가입하면 바로 참여",
         ("참여 코드", [("모양", "XXXX-XXXX-XXXX", NAVY), ("종류", "학생용 / 조교용", NAVY),
                     ("재발급", "예전 코드는 바로 사용 불가", GREEN), ("처음 로그인", "역할별 사용 안내 팝업", GREEN)])),
        ("마감 규칙", "p.4",
         ["마감 전에 업로드를 시작했다면 마감 뒤에 끝나도 채점", "마감 뒤 새 제출은 접수만 하고 채점 안 함"],
         ["큰 파일 업로드가 느려 손해 보는 학생 방지", "규칙을 악용하면 공정성이 깨짐"],
         [("업로드를 시작한 시각을 서버가 기록", "업로드 티켓"),
          ("시작할 때 파일 지문을 먼저 등록 → 마감 뒤 파일 바꿔치기 차단", True, "SHA-256 해시 선언 · 완료 시 대조"),
          ("허용 시간이 지나면 그 업로드는 무효", "문제별 설정 · 기본 30분")],
         "G05", "마감 직전 시작 → 마감 뒤 완료돼도 정상 채점",
         ("마감 판정", [("마감 전 시작 · 마감 뒤 완료", "채점", GREEN), ("마감 뒤 시작", "접수만", AMBER),
                     ("시작 뒤 다른 파일로 교체", "거부", RED)])),
        ("제출 횟수", "p.5",
         ["마감일마다 제출 횟수 제한", "채점 성공 시 1회 차감 · 형식·시스템 오류는 차감 안 함", "부적합 판정을 받아도 차감 유지"],
         ["제출을 반복해 정답을 알아내는 꼼수 방지", "학생 잘못이 아닌 오류로 손해 보지 않게"],
         [("좌석 예약처럼 시작할 때 1회를 잡아 두고 결과에 따라 사용·반환", "제출 슬롯: 예약 → 사용 / 반환"),
          ("1회 남았을 때 동시에 여러 번 눌러도 1건만 통과", True, "데이터베이스 행 잠금"),
          "시스템 오류는 3번까지 자동 재시도"],
         "G03", "채점되면 1회 차감 · 남은 횟수 바로 표시",
         ("차감 규칙", [("정상 채점", "1회 차감", NAVY), ("형식 오류 · 시스템 오류", "차감 안 함", GREEN),
                     ("1회 남고 동시에 10번 제출", "1건만 통과", RED)])),
        ("CSV 형식 검사", "p.4·5",
         ["교수가 정한 형식대로 자동 검사", "레이블 · 행 수 · 열 확인", "형식이 틀리면 채점하지 않음"],
         ["잘못된 파일 때문에 생기는 채점 오류 방지", "학생이 왜 틀렸는지 몰라 답답한 상황 해소"],
         [("정답 파일을 올리면 제출 형식을 자동으로 찾아 줌 → 교수는 확인만", True),
          ("올리기 전 브라우저에서 먼저 검사, 서버에서 한 번 더", "이중 검사"),
          "몇 번째 줄이 왜 틀렸는지 한꺼번에 안내 · 횟수 차감 없음"],
         "G04", "열 이름 · 값 오류를 줄 번호와 함께 안내",
         ("실제 안내 예시", [("152행", "'cat'은 허용된 값이 아님", RED), ("35행", "예측값이 비어 있음", RED),
                         ("열 이름", "필요: id, label / 현재: id, digit", RED), ("처리", "업로드 전 차단 · 횟수 차감 없음", GREEN)])),
        ("리더보드 (순위표)", "p.6",
         ["학생마다 가장 높은 점수 1개만 표시", "검토 전 점수도 상태와 함께 표시", "점수가 같으면 공동 순위 · 학생에겐 익명, 관리자에겐 실명"],
         ["경쟁으로 동기 부여", "성적은 개인정보 · 확정 전 점수로 생기는 오해 방지"],
         ["대회마다 무작위 익명 이름 부여",
          ("학생 화면에는 실명이 아예 전달되지 않음", True, "서버가 역할별로 다른 화면을 만듦"),
          ("화면에 보이는 자릿수로 동점 판단 · 하루 전 대비 순위 변화 ▲▼", "자릿수는 문제별 설정 (최대 8자리)")],
         "G08", "같은 순위표 · 학생은 익명, 관리자는 실명",
         ("같은 순위표, 다른 화면", [("학생", "익명 이름 · 내 줄 강조", NAVY), ("조교 · 교수", "실명 · 학번", NAVY),
                                ("0.9933 · 0.9933", "공동 1위", GREEN)])),
        ("2단계 검토", "p.6",
         ["가장 높은 점수부터 검토, 같은 점수면 최근 제출부터", "조교 의견만으로는 순위에서 빼지 않음", "교수 승인으로 성적 확정"],
         ["한 사람의 실수 · 편파 방지", "학생마다 수십 건인 제출을 다 볼 필요 없게"],
         [("정해진 순서로만 다음 단계로 넘어가게 설계", "상태 머신"),
          ("부적합 확정 시 그 학생의 다음 기록을 자동으로 검토 목록에 올림", True),
          ("여러 건 한꺼번에 승인 · 모든 판정 기록 보관", "변경 기록 · 조작 여부 확인")],
         "G10", "부적합 확정 → 다음 기록 자동 상정 → 성적 확정",
         ("검토 흐름", [("검토 전", "조교가 적합 / 부적합 의견", NAVY), ("승인 대기", "교수가 최종 결정", NAVY),
                     ("검토 통과", "대표 기록 · 성적 확정", GREEN), ("부적합", "제외 → 다음 기록 검토", RED)])),
        ("부정 제출 판별 ★", "p.8",
         ["CSV가 정말 모델이 예측한 결과인지, 다른 방법으로 만든 것인지 판단하는 절차"],
         ["조교 업무 중 가장 오래 걸리고 놓치기 쉬움", "공정성과 바로 연결"],
         [("8가지 점검 결과를 신호등(🟢🟡🔴)으로 보여 줌 → 의심 제출부터 확인", True),
          ("의심 제출은 안전한 공간에서 학생 코드를 다시 실행해 결과 비교", "격리 재실행 (I-6)"),
          "시스템은 표시만, 최종 판단은 조교 · 교수"],
         "G11", "부정 사례마다 해당 점검 항목이 🔴로 표시",
         ("주요 점검 항목", [("다른 학생 CSV를 그대로 제출", "완전 중복", RED), ("남의 CSV를 조금 고쳐 제출", "부분 복사", RED),
                         ("예측값을 코드에 직접 입력", "노트북 코드 분석", RED), ("CSV만 손으로 고침", "결과만 바뀐 제출", RED)])),
        ("노트북 · 파일 보안", "p.7",
         ["파일 내용을 검사하고 안전한 이름으로 저장", "노트북 속 위험한 HTML · 스크립트 처리"],
         ["이름만 바꾼 위험 파일 · 경로 조작 공격", "조교가 노트북을 여는 순간 계정을 빼앗길 위험"],
         [("확장자가 아니라 파일 내용으로 형식 확인 · 무작위 이름으로 저장", "매직 바이트 검사 · UUID 이름"),
          ("노트북의 스크립트를 지우고 격리된 칸에만 표시", True, "HTML 정제 + 격리 iframe + CSP"),
          ("모델 파일은 안전한 공간에서만 열어 봄", "pickle 파일은 샌드박스에서만 로드")],
         "G13", "노트북 속 악성 스크립트가 실행되지 않음",
         ("직접 시도해 막은 것", [("노트북 속 스크립트", "제거 후 표시", GREEN), ("실행 파일을 .csv 로 위장", "내용 검사로 거부", GREEN),
                             ("../../etc/passwd.csv 같은 이름", "무작위 이름으로 저장", GREEN), ("외부 주소 이미지", "제거 (열람 사실 유출 방지)", GREEN)])),
    ]
    for title_, page, req, why, how, g, cap, extra in req_slides:
        s = content_slide(prs, title_, n); n += 1
        left_panel(s, page, req, why, how)
        gx, gw = 4.55, 5.0
        gh = gw * gif_ratio(g)
        top = 1.2 if extra else 1.15 + (5.85 - gh - 0.5) / 2
        gif(s, g, gx, top, gw, cap)
        if extra:
            ey = top + gh + 0.62
            rect(s, gx - 0.06, ey, gw + 0.12, 6.95 - ey, CARD2)
            text(s, gx + 0.08, ey + 0.08, gw - 0.16, 6.95 - ey - 0.12, extra_paras(extra), margin=0.04)

    # 14. 수업 규칙 자동 확인 (I-8) — 정확도 수치 없이 동작 방식만
    s = content_slide(prs, "수업 규칙까지 자동 확인 — 교차 검증 결과 출력", n); n += 1
    left_panel(s, "수업 규칙",
               ["교수님 규칙: '5-폴드 교차 검증 결과와 평균이 출력된 노트북만 인정'"],
               ["제출이 많으면 노트북을 일일이 열어 확인하기 어려움", "학생이 적은 평균이 실제 실력과 다를 수 있음"],
               [("노트북 실행 결과에서 폴드별 점수와 평균을 자동으로 찾음", "문제별로 k 설정 · 0 이면 검사 안 함"),
                ("학생이 적은 평균과 숨겨 둔 정답으로 매긴 점수를 비교 → 차이가 크면 🟡", True),
                ("실제 수업 노트북의 출력 모양에 맞춰 만듦", "줄바꿈 배열 · '10-fold' 숫자 · 오차 행렬 오인 방지")])
    rect(s, 4.55, 1.15, 5.0, 2.65, CARD)
    text(s, 4.7, 1.25, 4.75, 2.5, [("예시 ① 교차 검증 결과를 빠뜨림", {"size": 15, "bold": True, "color": NAVY, "space_after": 8}),
                                  ("행동 인식(HAR) 문제 · 학습 정확도만 출력", {"size": 13, "color": INK, "space_after": 8}),
                                  ([("🟡 ", {}), ("5개 폴드 점수 · 평균을 찾지 못함", {"bold": True, "color": AMBER})], {"size": 14, "space_after": 6}),
                                  ("→ 수업 규칙상 결과 처리 제외 대상인지 조교가 확인", {"size": 13, "color": MUTED})])
    rect(s, 4.55, 3.95, 5.0, 2.95, CARD)
    text(s, 4.7, 4.05, 4.75, 2.8, [("예시 ② 평균을 실제보다 좋게 보고", {"size": 15, "bold": True, "color": NAVY, "space_after": 8}),
                                  ("집값 예측 문제 · 학습에 쓴 데이터로 '검증'하는 실수", {"size": 13, "color": INK, "space_after": 8}),
                                  ([("학생이 적은 5-폴드 평균 RMSE  ", {"color": INK}), ("60,643", {"bold": True, "color": NAVY})], {"size": 14, "space_after": 2}),
                                  ([("숨겨 둔 정답으로 매긴 점수  ", {"color": INK}), ("126,547", {"bold": True, "color": NAVY})], {"size": 14, "space_after": 6}),
                                  ([("🟡 ", {}), ("차이가 커서 확인 권장", {"bold": True, "color": AMBER})], {"size": 14, "space_after": 4}),
                                  ("데모 데이터의 예시 화면 내용", {"size": 10, "color": MUTED})])

    # 15. 행안부 가이드
    s = content_slide(prs, "행정안전부 SW 개발보안 가이드 대응", n); n += 1
    rows = [("입력 데이터 검증", "해킹용 입력 · 위험한 파일 업로드 · 남의 이름으로 요청", "입력은 정해진 방식으로만 처리 · 파일 내용 검사",
             "SQL 삽입 · XSS · 경로 조작 · CSRF → ORM · 이스케이프 · UUID · CSRF 토큰"),
            ("보안 기능", "권한 없는 기능 사용 · 약한 비밀번호 · 비밀번호 대입", "권한 확인은 한곳에서 · 10번 실패 시 제한",
             "권한 단일 모듈 · Argon2 · 로그인/코드 실패 제한"),
            ("시간 및 상태", "동시에 눌러 규칙 우회 · 끝나지 않는 코드", "동시 요청은 하나씩 처리 · 실행 시간 제한",
             "슬롯 예약 + 행 잠금 · 샌드박스 시간 제한"),
            ("에러 처리", "오류 화면에 내부 정보 노출 · 오류 시 학생 손해", "오류 번호만 표시 · 자동 재시도 · 횟수 반환",
             "추적 ID · 3회 재시도"),
            ("코드 오류", "모델 파일을 여는 순간 코드 실행", "모델 파일은 안전한 공간에서만 열기",
             "신뢰할 수 없는 역직렬화 → pickle 은 샌드박스에서만"),
            ("캡슐화", "다른 학생 실명 노출", "학생 화면에는 실명 자체를 보내지 않음", "서버에서 역할별 화면 생성"),
            ("추가로 막은 것", "마감 뒤 파일 바꿔치기 · 엑셀 수식 공격 · 기록 조작", "파일 지문 등록 · 수식 무력화 · 기록 연결 확인",
             "해시 선언 · CSV 수식 이스케이프 · 해시 체인")]
    for i, (a, b, c, tech) in enumerate(rows):
        y = 1.15 + i * 0.8
        fill = CARD if i % 2 == 0 else CARD2
        rect(s, 0.45, y, 9.1, 0.72, fill)
        text(s, 0.55, y, 1.75, 0.72, [(a, {"size": 13, "bold": True, "color": NAVY})], anchor=MSO_ANCHOR.MIDDLE)
        text(s, 2.3, y, 3.4, 0.72, [(b, {"size": 12, "color": INK})], anchor=MSO_ANCHOR.MIDDLE)
        text(s, 5.75, y + 0.02, 3.75, 0.7, [(c, {"size": 12, "bold": True, "color": SCH, "space_after": 1}),
                                            (tech, {"size": 9, "color": MUTED})], anchor=MSO_ANCHOR.MIDDLE)
    text(s, 0.45, 6.8, 9.1, 0.3, [("구현 위치와 테스트 이름은 docs/SECURITY.md 대응표", {"size": 10, "color": MUTED})])

    # 16. 업무를 줄이는 기능 · 성능 (추정치 없음)
    s = content_slide(prs, "조교 · 교수의 일을 줄이는 기능", n); n += 1
    rect(s, 0.45, 1.25, 9.1, 5.6, CARD2)
    text(s, 0.7, 1.45, 8.6, 5.3, [("반복 작업을 시스템이 대신", {"size": 18, "bold": True, "color": NAVY, "space_after": 12})] + bullets([
        "채점 · 점수 기록 · 순위표 → 제출 즉시 자동",
        "형식 오류 안내 → 올리기 전에 줄 번호까지 자동 안내",
        "부정 의심 확인 → 신호등에서 🔴🟡만 자세히 보기",
        "검토 단축키 · 사유 버튼 · 일괄 승인 · 성적 CSV 내려받기",
        "정답 파일만 올리면 제출 형식 자동 설정 → 입력 실수로 전원 채점 실패하는 사고 방지",
        "처음 로그인하면 역할별 사용 안내 · 대시보드에 '지금 할 일'",
    ], size=17, gap=14))

    # 17. 설계 품질
    s = content_slide(prs, "설계 품질 — 숫자로 확인", n); n += 1
    for i, (v, l) in enumerate([("46/46", "RFP 요구사항\n모두 구현"), ("145", "자동 테스트\n모두 통과"), ("6/6", "보안 공격 시도\n모두 차단")]):
        stat_card(s, 0.45 + i * 3.08, 1.25, 2.94, 1.9, v, l, GREEN if i in (0, 2) else NAVY)
    rect(s, 0.45, 3.45, 4.45, 3.4, CARD)
    text(s, 0.6, 3.55, 4.2, 3.2, [("고치기 쉬운 구조", {"size": 15, "bold": True, "color": NAVY, "space_after": 6})] + bullets([
        "기능별로 9개 부분으로 나눔", "권한 확인은 한곳에서만", "평가 지표 추가는 한 줄",
        "설정은 파일 하나로 관리 (.env)", "올릴 때마다 자동 검사 (GitHub CI)"], size=14, gap=6))
    rect(s, 5.1, 3.45, 4.45, 3.4, CARD)
    text(s, 5.25, 3.55, 4.2, 3.2, [("운영 · 장애 대비", {"size": 15, "bold": True, "color": NAVY, "space_after": 6})] + bullets([
        "채점 중 장애가 나도 자동 복구", "정답 파일을 바꾸면 전체 다시 채점", "업로드를 중단하면 횟수 자동 반환",
        "변경 기록 조작 여부 확인", "배포 안내서 · 백업 방법 정리"], size=14, gap=6))

    # 18. RFP가 놓친 문제
    s = content_slide(prs, "RFP가 놓친 문제 7가지 — 스스로 발견하고 해결", n); n += 1
    issues = [("업로드를 시작해 두고 마감 뒤 파일 바꿔치기", "시작할 때 파일 지문 등록"),
              ("1회 남았을 때 동시에 여러 번 제출", "1건만 통과하도록 잠금"),
              ("모델 파일은 여는 순간 코드가 실행될 수 있음", "안전한 공간에서만 열기"),
              ("소수점 오차로 같은 점수가 다르게 비교됨", "화면 자릿수 기준으로 비교"),
              ("성적 엑셀 파일에 수식 공격", "내보낼 때 수식 무력화"),
              ("정답이 섞인 파일을 실수로 배포", "정답 열 뺀 파일 자동 생성"),
              ("조교 가입 경로가 학생과 같음", "역할별 참여 코드")]
    for i, (a, b) in enumerate(issues):
        col, row = i % 2, i // 2
        x, y = 0.45 + col * 4.6, 1.15 + row * 1.42
        rect(s, x, y, 4.45, 1.28, CARD if col == 0 else CARD2)
        text(s, x + 0.12, y, 0.55, 1.28, [(str(i + 1), {"size": 24, "bold": True, "color": SCH})], margin=0, anchor=MSO_ANCHOR.MIDDLE)
        text(s, x + 0.65, y + 0.1, 3.7, 1.1, [(a, {"size": 14, "bold": True, "color": INK, "space_after": 6}),
                                              ([("→ ", {"color": GREEN, "bold": True}), (b, {"bold": True, "color": GREEN})], {"size": 14})],
             anchor=MSO_ANCHOR.MIDDLE)

    # 19. 평가 기준 대응
    s = content_slide(prs, "평가 기준별 대응 요약", n); n += 1
    quads = [("필수 기능 및 정책 준수 · 40", ["RFP 요구사항 46개 모두 구현", "요구사항 → 기능 → 테스트 → 시연 영상 연결표", "마감 · 횟수 · 검토 규칙의 경계 상황까지 테스트"]),
             ("사용성과 업무 효율 · 20", ["올리기 전 검사 · 줄 번호 오류 안내", "역할별 첫 화면 '지금 할 일' · 처음 로그인 안내", "쉬운 화면 용어 · 접근성 점검"]),
             ("시스템 설계 및 보안 · 20", ["정답이 있는 곳과 코드 실행 공간 분리", "행안부 가이드 항목별 대응", "채점 장애 자동 복구 · 배포 안내서"]),
             ("문제 발견 및 창의적 개선 · 20", ["부정 제출 8가지 점검 신호등", "수업 규칙(교차 검증 출력) 자동 확인", "실제 수업 과제로 데모 · RFP가 놓친 문제 7가지"])]
    for i, (head, lines) in enumerate(quads):
        col, row = i % 2, i // 2
        x, y = 0.45 + col * 4.6, 1.15 + row * 2.9
        rect(s, x, y, 4.45, 2.7, CARD)
        text(s, x + 0.15, y + 0.12, 4.15, 2.5, [(head, {"size": 16, "bold": True, "color": NAVY, "space_after": 8})] + bullets(lines, size=15, gap=8))

    # Q&A 를 맨 뒤로, 템플릿 예시 슬라이드 삭제
    qa_box = None
    for sh in qa_slide.shapes:
        if sh.name == "TextBox 5":
            set_runs(sh, ["Questions?", "", "Contact: jw6258@sch.ac.kr"])
            qa_box = sh
    # 저장소 주소: GitHub 에 올린 뒤 REPO_URL 환경 변수로 다시 생성하면 Q&A 슬라이드에 표시
    #   REPO_URL=https://github.com/아이디/저장소 .venv/bin/python scripts/build_presentation.py
    repo_url = REPO_URL
    if repo_url and qa_box is not None:
        y = qa_box.top.inches + qa_box.height.inches + 0.15
        # 슬라이드 전체 폭에 가운데 정렬 (위 'Questions?'·'Contact' 와 같은 축), 긴 주소도 한 줄에
        text(qa_slide, 0.5, y, 9.0, 0.5, [(f"GitHub: {repo_url}", {"size": 14, "bold": True, "color": SCH})],
             align=PP_ALIGN.CENTER)
    order = list(prs.slides._sldIdLst)
    # 템플릿 슬라이드: 0 표지, 1 예시, 2 예시, 3 Q&A, 4 작성 규칙
    for idx in (4, 2, 1):
        remove_slide(prs, idx)
    move_slide(prs, 1, len(prs.slides._sldIdLst) - 1)  # Q&A 를 마지막으로
    _ = order

    # 발표자 노트 (대본) — scripts/presentation_notes.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from presentation_notes import NOTES, write_markdown

    for no, slide in enumerate(prs.slides, 1):
        if no in NOTES:
            sec, body = NOTES[no]
            slide.notes_slide.notes_text_frame.text = f"[약 {sec}초]\n{body}"
    write_markdown(ROOT / "docs" / "PRESENTATION_SCRIPT.md")

    # PowerPoint 는 한글을 기본적으로 글자 단위로 줄바꿈("제출 / 해도") → 모든 문단을 단어 단위로
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    para._p.get_or_add_pPr().set("eaLnBrk", "0")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT))
    print(f"저장: {OUT} ({OUT.stat().st_size / 1024 / 1024:.1f}MB, {len(prs.slides)}장)")


if __name__ == "__main__":
    build()
