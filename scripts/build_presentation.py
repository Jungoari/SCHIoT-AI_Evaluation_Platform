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


def left_panel(slide, page, req, why, how, y0=1.15, w=3.95, heights=(1.95, 1.45, 2.25)):
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
            if isinstance(line, tuple):  # (문자열, 강조)
                items.append(([("· ", {"color": SCH, "bold": True}), (line[0], {"bold": True, "color": SCH})], {"size": 14, "space_after": 3}))
            else:
                items.append(([("· ", {"color": SCH, "bold": True}), (line, {})], {"size": 14, "space_after": 3}))
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
    text(title_slide, 1, 3.45, 8, 0.4, [("제출하는 순간 채점되고, 공정하게 검증되는 수업용 평가 시스템",
                                         {"size": 16, "color": SCH, "bold": True})], align=PP_ALIGN.CENTER)

    n = 2

    # 2. 문제 정의
    s = content_slide(prs, "문제 정의 — 수작업 채점의 세 가지 고통", n); n += 1
    for i, (v, l, c) in enumerate([("150분", "학생 50명 · 제출 150건\n채점·점수 기록", NAVY),
                                   ("60분", "형식 오류 안내와\n재제출 요청", NAVY), ("150분", "노트북 50개를 열어\n부정 여부 확인", RED)]):
        stat_card(s, 0.55 + i * 3.05, 1.35, 2.85, 1.9, v, l, c)
    text(s, 0.55, 3.55, 8.9, 0.4, [("수작업 기준 추정치 · 시스템 도입 후 모두 자동화 또는 1차 선별", {"size": 12, "color": MUTED})])
    rect(s, 0.55, 4.1, 8.9, 2.75, CARD2)
    text(s, 0.75, 4.25, 8.5, 2.5, [("이 대회가 요구하는 것", {"size": 17, "bold": True, "color": NAVY, "space_after": 6})] + bullets([
        "CSV 예측 결과를 자동 채점하고 리더보드로 공개",
        "관리자1 코드 검토 → 관리자2 최종 승인으로 공정한 성적 확정",
        "CSV가 모델의 추론 결과인지, 우회 수행인지 판단하는 프로세스",
        "참여자 코드 실행 시 정답·비밀키·타인 자료 접근 차단",
    ], size=16, gap=8))

    # 3. Kaggle
    s = content_slide(prs, "Kaggle에서 배우고, 수업에 맞게 바꾼 것", n); n += 1
    rows = [("즉시 자동 채점", "업로드 즉시 점수 + 업로드 전 사전 검사"),
            ("실시간 리더보드", "학생끼리는 익명 별칭, 관리자만 실명"),
            ("제출 횟수 제한", "형식·시스템 오류는 차감하지 않음"),
            ("Sample Submission", "정답 열을 뺀 배포 파일 자동 생성"),
            ("상위권 코드 검증", "최고 기록부터 2단계 검토, 부적합 시 다음 기록"),
            ("Code Competition", "검토 대상만 격리 재실행 (자원 절약)")]
    text(s, 0.55, 1.15, 4.3, 0.4, [("Kaggle의 장점", {"size": 14, "bold": True, "color": MUTED})])
    text(s, 5.0, 1.15, 4.45, 0.4, [("수업 환경에 맞춘 설계", {"size": 14, "bold": True, "color": SCH})])
    for i, (a, b) in enumerate(rows):
        y = 1.6 + i * 0.86
        rect(s, 0.55, y, 4.3, 0.74, CARD2)
        rect(s, 5.0, y, 4.45, 0.74, CARD)
        text(s, 0.7, y, 4.0, 0.74, [(a, {"size": 14, "bold": True, "color": INK})], anchor=MSO_ANCHOR.MIDDLE)
        text(s, 5.15, y, 4.2, 0.74, [(b, {"size": 13, "bold": True, "color": NAVY})], anchor=MSO_ANCHOR.MIDDLE)
        text(s, 4.78, y, 0.3, 0.74, [("→", {"size": 14, "bold": True, "color": SCH})], anchor=MSO_ANCHOR.MIDDLE, margin=0)

    # 4. 아키텍처
    s = content_slide(prs, "핵심 설계 — 정답과 참여자 코드를 물리적으로 분리", n); n += 1
    rect(s, 3.0, 1.2, 4.0, 0.8, NAVY)
    text(s, 3.0, 1.2, 4.0, 0.8, [("web (Django)", {"size": 15, "bold": True, "color": WHITE}),
                                 ("업로드 티켓 · 내용 검증 · UUID 저장 · 화면", {"size": 11, "color": WHITE})],
         anchor=MSO_ANCHOR.MIDDLE, align=PP_ALIGN.CENTER)
    text(s, 4.2, 2.05, 1.6, 0.35, [("Redis 큐", {"size": 11, "bold": True, "color": MUTED})], align=PP_ALIGN.CENTER)
    for x, title_, sub, tag, tag_color in ((0.7, "worker (채점)", "CSV를 데이터로만 파싱", "정답 O · 코드 실행 X", GREEN),
                                          (5.3, "sandbox-worker (검증)", "컨테이너 실행 지시만", "정답 X", RED)):
        rect(s, x, 2.5, 4.0, 1.2, CARD)
        text(s, x, 2.55, 4.0, 1.1, [(title_, {"size": 15, "bold": True, "color": NAVY}), (sub, {"size": 12, "color": MUTED}),
                                    (tag, {"size": 12, "bold": True, "color": tag_color})], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    rect(s, 5.3, 4.05, 4.0, 2.75, CARD2, line=SCH)
    text(s, 5.45, 4.12, 3.75, 2.65, [("샌드박스 컨테이너", {"size": 15, "bold": True, "color": SCH, "space_after": 4})] + bullets([
        "실행마다 새로 생성 후 삭제", "네트워크 없음 · 읽기 전용", "비루트 · 커널 권한 전부 제거",
        "CPU·메모리·프로세스·시간 제한", ("정답·비밀키가 아예 없음", True)], size=14, gap=4))
    text(s, 0.7, 4.05, 4.3, 2.75, [("왜 이렇게 나눴나", {"size": 15, "bold": True, "color": NAVY, "space_after": 6})] + bullets([
        "막는 규칙 하나만 빠져도 뚫리는 방식 대신 훔칠 정답이 없는 곳에서 실행",
        "채점은 코드 실행 없이 CSV만 비교 → 빠르고 안전",
        "재실행은 검토 대상만 → 자원 절약",
        "샌드박스 공격 6종 실측 차단 (6/6)",
    ], size=14, gap=6))

    # 5~13. 요구사항 슬라이드 (좌측 패널 + 우측 GIF)
    req_slides = [
        ("정답 보호 · 격리 실행", "p.2·5·7",
         ["참여자에게 정답 비노출", "참여자 코드 실행 시 정답·비밀키·타인 자료·관리 기능 접근 차단"],
         ["정답 유출 시 대회 전체 무효", "되돌릴 수 없는 유일한 사고"],
         ["정답 보유 프로세스와 실행 프로세스 분리", "네트워크 차단·읽기 전용·비루트 샌드박스", ("공격 노트북 6종 실측 모두 차단", True)],
         "G12", "✔ TC-S01~S04 정답·비밀키·네트워크·자원 공격 6/6 차단",
         ("샌드박스 격리 설정", [("네트워크", "없음 (외부·DB·Redis 접속 불가)", NAVY), ("파일시스템", "읽기 전용 · 정답 파일 없음", NAVY),
                           ("권한", "비루트 · 커널 권한 전부 제거", NAVY), ("자원", "메모리 2GB · 프로세스 128 · 300초", NAVY)])),
        ("계정 · 참여 코드", "p.3",
         ["대회 개설 시 참여 코드 자동 생성", "최초 가입 시 코드 필수", "기존 회원은 코드로 대회 추가"],
         ["대회에 속하지 않은 계정 방지", "학생 1명 = 계정 1개로 여러 과목"],
         ["역할별 코드 발급 (참여자·운영)", "해시로만 저장 · 한 번만 표시 · 재발급", ("10회 실패 시 15분 제한 (무차별 대입 방지)", True)],
         "G02", "✔ TC-A01 코드 없이 가입 불가 · 코드로 가입 시 대회 참여",
         ("참여 코드 설계", [("형식", "XXXX-XXXX-XXXX (60비트 난수)", NAVY), ("저장", "SHA-256 해시만 · 원문 1회 표시", NAVY),
                         ("역할", "참여자 코드 / 운영(관리자1) 코드", NAVY), ("재발급", "기존 코드 즉시 무효", GREEN)])),
        ("마감 규칙", "p.4",
         ["마감 전 시작·마감 후 완료 시 채점", "마감 후 새 제출은 접수만"],
         ["대용량 업로드 지연으로 인한 불이익 방지", "규칙 악용 시 공정성 훼손"],
         ["업로드 시작 시 서버 시각 기록 (업로드 티켓)", ("시작 시 파일 해시 선언 → 마감 후 바꿔치기 차단", True), "티켓 유예 시간 초과 시 만료"],
         "G05", "✔ TC-B01 마감 후 완료돼도 채점 · TC-B02 마감 후 시작은 접수만",
         ("마감 판정 규칙", [("마감 전 시작 · 마감 후 완료", "채점", GREEN), ("마감 후 시작", "접수만 · 채점 제외", AMBER),
                         ("티켓 후 다른 파일 업로드", "해시 불일치 거부", RED)])),
        ("제출 횟수", "p.5",
         ["마감일별 횟수 제한", "성공 1회 차감 · 형식·시스템 오류 미차감", "부적합 판정 시 차감 유지"],
         ["반복 제출로 정답을 역추적하는 프로빙 방지", "학생 책임 없는 오류로 인한 손해 방지"],
         ["좌석 예약 방식 슬롯 (예약 → 사용/반환)", ("행 잠금으로 동시 제출 10건 중 1건만 통과", True), "시스템 오류는 3회 자동 재시도"],
         "G03", "✔ TC-C01 채점 성공 시 1회 차감 · 남은 횟수 즉시 갱신",
         ("횟수 처리 규칙 (테스트로 검증)", [("정상 채점", "1회 차감", NAVY), ("형식 오류 · 시스템 오류", "미차감", GREEN),
                                 ("남은 1회에서 동시 10건", "1건만 통과", RED)])),
        ("CSV 형식 검사", "p.4·5",
         ["관리자2 등록 형식 기준 자동 검사", "레이블·행·열 수 확인", "오류 시 채점 불가"],
         ["잘못된 파일로 인한 채점 오류 방지", "학생이 오류 원인을 모르는 답답함 해소"],
         [("정답 CSV로 규격 자동 추론 → 관리자는 확인만", True), "브라우저 사전 검사 + 서버 재검사", "행 번호까지 오류 일괄 안내 · 미차감"],
         "G04", "✔ TC-D02·D03 행 번호·열 이름 오류 안내 · 횟수 미차감",
         ("실제 오류 안내 예시", [("152행", "'cat'은 허용된 레이블이 아님", RED), ("35행", "예측값이 비어 있음", RED),
                            ("헤더", "필요: id, label / 현재: id, digit", RED), ("처리", "업로드 전 차단 · 횟수 미차감", GREEN)])),
        ("리더보드", "p.6",
         ["참여자별 최고 점수 1개", "미검증 포함 + 검증 상태 표시", "동점 공동 순위 · 참여자 익명, 관리자 실명"],
         ["경쟁을 통한 동기 부여", "성적은 개인정보 · 미확정 점수 분쟁 방지"],
         ["대회별 무작위 익명 별칭", ("실명은 서버에서 제외 (HTML에도 없음)", True), "표시 자릿수 기준 동점 · 24시간 대비 ▲▼"],
         "G08", "✔ TC-E01 같은 순위표 · 참여자는 별칭, 관리자는 실명",
         ("같은 순위표, 다른 화면", [("참여자 화면", "익명 별칭 · 내 행 강조", NAVY), ("담당 관리자1 · 관리자2", "실명 · 학번", NAVY),
                              ("동점 0.9933 · 0.9933", "공동 1위", GREEN)])),
        ("2단계 검증", "p.6",
         ["최고 점수부터 검토, 동점은 최신부터", "관리자1 제안만으로 제외 불가", "관리자2 승인으로 성적 확정"],
         ["1인 판단의 실수·편파 방지", "학생당 수십 건 제출의 검토 부담 해소"],
         ["상태 머신으로 전환 순서 강제", ("부적합 확정 시 다음 기록 자동 상정", True), "일괄 승인 · 모든 판정 감사 로그"],
         "G10", "✔ TC-F03 부적합 확정 → 다음 기록 · TC-F04 성적 확정",
         ("검토 상태 흐름", [("검증 대기", "관리자1 판정 제안", NAVY), ("검토 중", "관리자2 최종 결정", NAVY),
                         ("검증 통과", "대표 기록 · 성적 확정", GREEN), ("부적합", "제외 → 다음 기록 자동 상정", RED)])),
        ("부정 제출 판별 ★", "p.8",
         ["CSV가 모델 추론 결과인지 우회 수행인지 판단하는 프로세스"],
         ["조교 업무 중 가장 오래 걸림", "공정성과 직결"],
         ["무결성 리포트 8종 신호등 (I-1~I-8)", ("갈리는 행의 부자연스러운 답 → 부분 복사", True), "검토 대상만 격리 재실행 · 판단은 사람"],
         "G11", "✔ 탐지 실험: 부정 30/30 탐지 · 정직 오탐 1/20",
         ("탐지 실험 결과 (정직 20 · 부정 30)", [("다른 참여자 CSV 그대로 (5건)", "I-1 완전 중복 5/5", RED), ("남의 CSV 일부 변경 (10건)", "I-2 부분 복사 10/10", RED),
                                ("예측값 직접 기입 (10건)", "I-3 코드 분석 10/10", RED), ("CSV만 수정 (5건)", "I-7 결과만 변경 5/5", RED)])),
        ("노트북 · 파일 보안", "p.7",
         ["파일 내용 검증·안전한 저장명", "노트북 비신뢰 HTML·스크립트·위젯 처리"],
         ["위장 파일·경로 조작 공격", "노트북 열람 시 관리자 계정 탈취 위험"],
         ["매직 바이트·파싱 검증 · UUID 저장명", "스크립트 제거 + 격리 iframe + CSP 3중 방어", ("pickle 가중치는 샌드박스에서만 로드", True)],
         "G13", "✔ TC-S05 script · onerror · JS 출력 모두 차단",
         ("실제로 막은 것 (테스트로 검증)", [("노트북 속 <script> · onerror", "제거 후 격리 표시", GREEN), ("JS · 위젯 출력", "렌더링 안 함", GREEN),
                                    (".exe 를 .csv 로 위장", "내용 검증으로 거부", GREEN), ("../../etc/passwd.csv", "UUID 저장명", GREEN)])),
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

    # 실험으로 약점을 찾고 개선
    s = content_slide(prs, "실험으로 약점을 찾고 고치다 — 부정 탐지 개선", n); n += 1
    for i, (v, l, c) in enumerate([("55% → 5%", "정직한 제출 오탐\n(🟡 이상)", GREEN), ("90% → 100%", "부정 제출 탐지율\n(30건)", GREEN),
                                   ("20/20", "정직한 제출\n격리 재실행 재현", NAVY)]):
        stat_card(s, 0.45 + i * 3.08, 1.2, 2.92, 1.75, v, l, c)
    rect(s, 0.45, 3.2, 4.4, 3.35, CARD)
    text(s, 0.6, 3.3, 4.15, 3.15, [("무엇이 문제였나", {"size": 15, "bold": True, "color": NAVY, "space_after": 6})] + bullets([
        "첫 지표: 상대가 틀린 문항에서 같은 오답을 낸 비율",
        "10클래스 숫자 분류에서는 서로 다른 모델도 같은 숫자를 같은 식으로 헷갈림",
        ("정직한 모델 20종 중 11종을 의심으로 표시", True),
    ], size=14, gap=6))
    rect(s, 5.0, 3.2, 4.55, 3.35, CARD)
    text(s, 5.15, 3.3, 4.3, 3.15, [("어떻게 고쳤나", {"size": 15, "bold": True, "color": NAVY, "space_after": 6})] + bullets([
        "후보 지표 3개를 정직 20종 · 복사 40건으로 비교",
        "복사본이 원본과 갈리는 곳 = 손으로 고친 곳 → 아무도 안 내는 부자연스러운 답",
        ("정직 최대 0.66 vs 복사 최소 0.89 로 분리", True),
        "비교 참여자 10명 미만이면 🟡까지만 (과신 방지)",
    ], size=14, gap=6))
    text(s, 0.45, 6.62, 9.1, 0.3, [("python manage.py integrity_experiment --rerun · docs/INTEGRITY_EXPERIMENT.md · docs/adr/0005", {"size": 11, "color": MUTED})])

    # 14. 행안부 가이드
    s = content_slide(prs, "행정안전부 SW 개발보안 가이드 대응", n); n += 1
    rows = [("입력데이터 검증", "SQL 삽입·XSS·경로 조작·위험 파일 업로드·CSRF", "ORM · 이스케이프 · 노트북 3중 방어 · UUID · CSRF"),
            ("보안기능", "부적절한 인가·취약한 비밀번호·반복 인증", "권한 단일 모듈 · Argon2 · 10회 실패 제한"),
            ("시간 및 상태", "경쟁조건 · 종료되지 않는 반복문", "슬롯 예약 + 행 잠금 · 샌드박스 시간 제한"),
            ("에러처리", "오류 메시지 정보노출 · 오류상황 대응 부재", "추적 ID만 표시 · 3회 재시도 · 미차감"),
            ("코드오류", "신뢰할 수 없는 데이터의 역직렬화", "pickle은 샌드박스에서만 로드"),
            ("캡슐화", "잘못된 세션에 의한 정보노출", "리더보드 실명 서버에서 제외"),
            ("추가 발견", "업로드 후 바꿔치기 · CSV 수식 주입 · 감사 로그 조작", "해시 선언 · 수식 이스케이프 · 해시 체인")]
    for i, (a, b, c) in enumerate(rows):
        y = 1.15 + i * 0.8
        fill = CARD if i % 2 == 0 else CARD2
        rect(s, 0.45, y, 9.1, 0.7, fill)
        text(s, 0.55, y, 1.7, 0.7, [(a, {"size": 13, "bold": True, "color": NAVY})], anchor=MSO_ANCHOR.MIDDLE)
        text(s, 2.25, y, 3.6, 0.7, [(b, {"size": 12, "color": INK})], anchor=MSO_ANCHOR.MIDDLE)
        text(s, 5.85, y, 3.65, 0.7, [(c, {"size": 12, "bold": True, "color": SCH})], anchor=MSO_ANCHOR.MIDDLE)
    text(s, 0.45, 6.8, 9.1, 0.3, [("구현 위치와 테스트 이름은 docs/SECURITY.md 대응표 참고", {"size": 11, "color": MUTED})])

    # 15. 업무 효율 · 성능
    s = content_slide(prs, "업무 효율 · 성능 실측", n); n += 1
    for i, (v, l, c) in enumerate([("50/50", "마감 직전 50명\n동시 제출 성공", GREEN), ("2.85초", "업로드 시작 →\n채점 완료 (중앙값)", NAVY),
                                   ("0.10초", "업로드 티켓 응답\n부하와 무관", NAVY), ("600MB", "전체 스택 유휴 메모리\n소형 VM 1대로 운영", NAVY)]):
        stat_card(s, 0.45 + i * 2.3, 1.25, 2.15, 1.9, v, l, c)
    rect(s, 0.45, 3.45, 9.1, 3.4, CARD2)
    text(s, 0.65, 3.55, 8.7, 3.2, [("조교·교수의 반복 작업 제거", {"size": 15, "bold": True, "color": NAVY, "space_after": 6})] + bullets([
        "채점·점수 기록 약 150분 → 0분 (자동)",
        "형식 오류 안내 약 60분 → 0분 (업로드 전 자동 안내)",
        "부정 의심 1차 선별 약 150분 → 신호등에서 🔴🟡만 정밀 검토",
        "검토 단축키 J·K·A·R · 사유 템플릿 · 일괄 승인 · 성적 CSV 1클릭",
        "규격 자동 추론 → 관리자2 입력 실수로 전원 채점 실패하는 사고 방지",
    ], size=15, gap=8))

    # 16. 설계 품질
    s = content_slide(prs, "설계 품질 — 숫자로 증명", n); n += 1
    for i, (v, l) in enumerate([("46/46", "RFP 요구사항\n구현·추적표"), ("140", "자동화 테스트\n전부 통과"), ("6/6", "샌드박스 공격\n실측 차단"),
                                ("15", "테스트 시연 GIF\n명령 1줄로 재녹화")]):
        stat_card(s, 0.45 + i * 2.3, 1.25, 2.15, 1.9, v, l, GREEN if i in (0, 2) else NAVY)
    rect(s, 0.45, 3.45, 4.45, 3.4, CARD)
    text(s, 0.6, 3.55, 4.2, 3.2, [("유지보수", {"size": 15, "bold": True, "color": NAVY, "space_after": 6})] + bullets([
        "기능별 앱 9개로 분리", "권한 판단은 한 모듈에서만", "지표 추가는 한 줄", "환경 변수로 모든 설정 외부화", "CI: 테스트·린트·보안 검사"], size=15, gap=7))
    rect(s, 5.1, 3.45, 4.45, 3.4, CARD)
    text(s, 5.25, 3.55, 4.2, 3.2, [("운영 · 장애 대책", {"size": 15, "bold": True, "color": NAVY, "space_after": 6})] + bullets([
        "docker compose 명령 1줄 실행", "워커 장애 시 멈춘 채점 자동 복구", "정답 교체 시 전체 재채점",
        "만료된 업로드 티켓 슬롯 자동 반환", "감사 로그 위변조 검증"], size=15, gap=7))

    # 17. RFP가 놓친 문제
    s = content_slide(prs, "RFP가 놓친 문제 7가지 — 스스로 발견하고 해결", n); n += 1
    issues = [("업로드 시작 후 파일 바꿔치기", "시작 시 해시 선언"), ("남은 1회에서 동시 제출", "슬롯 예약 + 행 잠금"),
              ("pickle 가중치는 열기만 해도 코드 실행", "샌드박스에서만 로드"), ("부동소수 오차로 동점이 깨짐", "표시 자릿수 기준 비교"),
              ("성적 엑셀에 수식 주입", "내보낼 때 이스케이프"), ("정답이 섞인 파일 배포 위험", "정답 열 제거 배포본 자동 생성"),
              ("관리자1 가입 경로가 참여자와 같음", "역할별 참여 코드")]
    for i, (a, b) in enumerate(issues):
        col, row = i % 2, i // 2
        x, y = 0.45 + col * 4.6, 1.15 + row * 1.42
        rect(s, x, y, 4.45, 1.28, CARD if col == 0 else CARD2)
        text(s, x + 0.12, y, 0.55, 1.28, [(str(i + 1), {"size": 24, "bold": True, "color": SCH})], margin=0, anchor=MSO_ANCHOR.MIDDLE)
        text(s, x + 0.65, y + 0.1, 3.7, 1.1, [(a, {"size": 15, "bold": True, "color": INK, "space_after": 6}),
                                              ([("→ ", {"color": GREEN, "bold": True}), (b, {"bold": True, "color": GREEN})], {"size": 15})],
             anchor=MSO_ANCHOR.MIDDLE)

    # 18. 평가 기준 대응
    s = content_slide(prs, "평가 기준별 대응 요약", n); n += 1
    quads = [("필수 기능 및 정책 준수 · 40", ["RFP 46개 요구사항 전부 구현", "요구사항 → 기능 → 테스트 → GIF 추적표", "마감·횟수·검증 규칙 경계값 테스트"]),
             ("사용성과 업무 효율 · 20", ["업로드 전 사전 검사 · 행 단위 오류", "역할별 첫 화면 = 지금 할 일", "검토 단축키 · 일괄 승인 · 1클릭 성적"]),
             ("시스템 설계 및 보안 · 20", ["정답·실행 프로세스 물리 분리", "행안부 가이드 대응표 + 공격 실측", "50명 동시 제출 2.85초 · 600MB"]),
             ("문제 발견 및 창의적 개선 · 20", ["무결성 리포트 · 탐지 실험 30/30", "실험으로 오탐 55% → 5% 개선", "RFP가 놓친 문제 7가지 해결"])]
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
    repo_url = os.environ.get("REPO_URL", "").strip()
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

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT))
    print(f"저장: {OUT} ({OUT.stat().st_size / 1024 / 1024:.1f}MB, {len(prs.slides)}장)")


if __name__ == "__main__":
    build()
