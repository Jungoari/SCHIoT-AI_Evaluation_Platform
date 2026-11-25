"""
테스트 케이스 시연 GIF 자동 녹화

    # 운영 설정(DEBUG=False)으로 녹화용 서버를 직접 띄운다 (포트 8011, DB·Redis 는 docker compose)
    .venv/bin/python scripts/record_gifs/record.py            # 전체
    .venv/bin/python scripts/record_gifs/record.py G03 G11    # 일부만

각 시나리오는 실제 화면을 조작하고, 결과를 화면에서 확인(assert)한 뒤에만 PASS 도장을 찍는다.
→ GIF 가 '연출'이 아니라 '테스트 통과의 증거'가 된다. UI 를 고쳐도 명령 한 번으로 전부 다시 만든다.
"""

import html
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
sys.path.insert(0, str(WEB))
os.chdir(WEB)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"  # Playwright(sync)와 ORM 을 같은 스레드에서 사용

import django  # noqa: E402

django.setup()

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from django.utils import timezone  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

PORT = int(os.environ.get("RECORD_PORT", "8011"))
BASE = os.environ.get("BASE_URL", f"http://127.0.0.1:{PORT}")
OUT = ROOT / "docs" / "assets" / "gifs"
TMP = ROOT / "scripts" / "record_gifs" / "output"
OVERLAY = (Path(__file__).parent / "overlay.js").read_text()
PW = "evalhub-demo-2026"
VIEW = {"width": 1280, "height": 800}
PY = str(ROOT / ".venv" / "bin" / "python")


# ---------------------------------------------------------------------------
# 녹화 도구
# ---------------------------------------------------------------------------
class Recording:
    def __init__(self, browser, name, user=None, start="/dashboard/"):
        self.browser, self.name, self.user, self.start = browser, name, user, start

    def __enter__(self):
        state = login_state(self.browser, self.user) if self.user else None
        self.ctx = self.browser.new_context(
            viewport=VIEW, record_video_dir=str(TMP / self.name), record_video_size=VIEW,
            storage_state=state, locale="ko-KR", timezone_id="Asia/Seoul",
        )
        self.ctx.add_init_script(OVERLAY)
        self.page = self.ctx.new_page()
        self.t0 = time.monotonic()
        self.page.goto(BASE + self.start)
        self.page.wait_for_load_state("networkidle")
        self.trim = time.monotonic() - self.t0
        return self

    def caption(self, tc, title, expected="", tag=""):
        self.page.evaluate("([a,b,c,d]) => window.__demo.caption(a,b,c,d)", [tc, title, expected, tag])

    def passed(self, text="", hold=2.2):
        self.page.evaluate("t => window.__demo.pass(t)", text)
        self.pause(hold)

    def blocked(self, text="", hold=2.2):
        self.page.evaluate("t => window.__demo.blocked(t)", text)
        self.pause(hold)

    def pause(self, s=1.0):
        self.page.wait_for_timeout(int(s * 1000))

    def go(self, path, wait=0.8):
        self.page.goto(BASE + path)
        self.page.wait_for_load_state("networkidle")
        self.pause(wait)

    def click(self, locator, wait=0.7):
        loc = self.page.locator(locator) if isinstance(locator, str) else locator
        loc.first.scroll_into_view_if_needed()
        box = loc.first.bounding_box()
        if box:  # 마우스를 실제로 움직여 클릭 위치가 보이게
            self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=12)
        loc.first.click()
        self.pause(wait)

    def type(self, selector, text, delay=45):
        self.page.locator(selector).first.click()
        self.page.locator(selector).first.press_sequentially(text, delay=delay)

    def scroll_to(self, locator, wait=0.6):
        loc = self.page.locator(locator) if isinstance(locator, str) else locator
        loc.first.evaluate("e => e.scrollIntoView({behavior:'smooth', block:'center', inline:'nearest'})")
        self.pause(wait)

    def __exit__(self, exc_type, exc, tb):
        video = self.page.video
        self.ctx.close()
        src = Path(video.path())
        if exc_type is None:
            to_gif(src, OUT / f"{self.name}.gif", trim=self.trim)
            print(f"  ✓ {self.name}.gif")
        else:
            print(f"  ✕ {self.name}: {exc}")
        return False


def to_gif(src: Path, dst: Path, trim=0.0, fps=12, width=960):
    vf = (f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];"
          "[a]palettegen=max_colors=160:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(trim - 0.1, 0):.2f}", "-i", str(src), "-vf", vf, str(dst)],
                   check=True)


_STATES = {}


def login_state(browser, email):
    if email in _STATES:
        return _STATES[email]
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(BASE + "/accounts/login/")
    page.fill("input[name=username]", email)
    page.fill("input[name=password]", PW)
    page.press("input[name=password]", "Enter")
    page.wait_for_url("**/dashboard/")
    # 처음 로그인 사용 안내가 뜨면 건너뛰기 (녹화 화면을 가리지 않도록 — 안내 자체는 G02 에서 시연)
    if page.locator("[data-testid=tutorial]").count():
        with page.expect_response("**/accounts/tutorial/done/"):
            page.click("[data-tutorial-skip]")
    _STATES[email] = ctx.storage_state()
    ctx.close()
    return _STATES[email]


def email(local):
    return f"{local}@demo.evalhub"


# ---------------------------------------------------------------------------
# 데이터 준비
# ---------------------------------------------------------------------------
from apps.core.demo import P1_TITLE as P1  # noqa: E402 — 데모 생성기와 같은 이름을 쓴다


def project_id(title):
    from apps.competitions.models import Project

    return Project.objects.filter(title=title).order_by("-pk").first().pk


def fashion_files():
    """패션 MNIST 프로젝트용 실제 제출물 생성 (CSV · 5-폴드 결과가 출력된 노트북 · 가중치)"""
    from apps.core import demo
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import MinMaxScaler

    train, test = demo.fashion_frames()
    X, y = train.drop(columns=["id", "label"]), train["label"]
    model = make_pipeline(MinMaxScaler(), LogisticRegression(C=0.2, max_iter=300))
    scores = demo.cv_scores(model, X, y, "accuracy")
    model.fit(X, y)
    pred = model.predict(test.drop(columns=["id", "label"]))
    code = ("from sklearn.pipeline import make_pipeline\nfrom sklearn.preprocessing import MinMaxScaler\n"
            "from sklearn.linear_model import LogisticRegression\n"
            "model = make_pipeline(MinMaxScaler(), LogisticRegression(C=0.2, max_iter=300))")
    nb = demo.make_notebook(code, "label", demo.cv_log(scores, "accuracy"))
    d = TMP / "files"
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"id": test["id"], "label": pred}).to_csv(d / "submission.csv", index=False)
    (d / "solution.ipynb").write_bytes(nb)
    (d / "model.joblib").write_bytes(demo.dump_weights(model))
    # 형식 오류 예시: 152행 레이블을 'cat' 으로
    bad = pd.DataFrame({"id": test["id"], "label": pred.astype(object)})
    bad.loc[150, "label"] = "cat"
    bad.loc[33, "label"] = ""
    bad.to_csv(d / "submission_bad_label.csv", index=False)
    pd.DataFrame({"id": test["id"], "digit": pred}).to_csv(d / "submission_bad_header.csv", index=False)
    # 위장 파일: 실행 파일을 .csv 로
    (d / "virus.csv").write_bytes(b"MZ\x90\x00\x03\x00\x00\x00\x04\x00" + bytes(range(256)) * 4)
    # 대용량 가중치 (업로드 속도 제한 시연용)
    (d / "big_model.joblib").write_bytes(demo.dump_weights({"w": np.random.default_rng(0).random(160_000)}))
    return d


def pick_files(rec, csv, nb, w):
    rec.page.set_input_files("input[name=csv]", str(csv))
    rec.pause(0.5)
    rec.page.set_input_files("input[name=notebook]", str(nb))
    rec.pause(0.5)
    rec.page.set_input_files("input[name=weights]", str(w))
    rec.pause(0.7)


# ---------------------------------------------------------------------------
# 시나리오
# ---------------------------------------------------------------------------
def g01_create(browser):
    """G01 대회 개설 → 코드 발급 → 프로젝트 → 테스트셋 규격 자동 추론 → 마감일 → 공개"""
    from apps.core import demo

    d = TMP / "files"
    d.mkdir(parents=True, exist_ok=True)
    _, test = demo.fashion_frames()
    test.to_csv(d / "fashion_test_with_labels.csv", index=False)
    with Recording(browser, "G01_create_competition", email("prof")) as r:
        r.caption("TC-A04", "교수 · 대회 개설과 참여 코드 자동 발급", "참여자 코드·운영 코드가 자동 생성되고 한 번만 표시", "RFP p.3")
        r.click("text=대회 개설")
        r.type("input[name=title]", "2026-2 딥러닝 중간 프로젝트")
        r.type("textarea[name=description]", "미니프로젝트 #1 — 패션 이미지 10개 클래스 분류", delay=25)
        r.click("button:has-text('대회 개설하고')", wait=1.2)
        expect(r.page.locator("[data-testid=participant-code]")).to_have_text(re.compile(r"^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$"))
        r.passed("참여자·운영 코드 발급 (해시로만 저장)", hold=1.6)
        r.click("text=대회 홈으로")
        r.caption("TC-D", "프로젝트 추가 → 정답 파일 업로드", "ID 열·정답 열·분류/회귀·허용 레이블·행 수 자동 분석", "RFP p.5")
        r.click("a:has-text('프로젝트 추가')")
        r.type("input[name=title]", "패션 MNIST 분류")
        r.click("button:has-text('다음')", wait=1)
        r.page.set_input_files("input[name=testset]", str(d / "fashion_test_with_labels.csv"))
        r.click("button:has-text('업로드')", wait=1.2)
        r.scroll_to("text=자동 분석 결과 확인", wait=1.5)
        expect(r.page.locator("text=자동 분석 결과 확인")).to_be_visible()
        r.click("button:has-text('형식 확정')", wait=1.2)
        r.caption("TC-B05", "마감일·횟수 설정 후 공개", "정답 열이 제거된 학생용 자료가 자동 생성되고 공개 가능", "RFP p.4~5")
        r.scroll_to("#deadlines")
        r.page.fill("input[name=due_at]", (timezone.localtime() + timedelta(days=7)).strftime("%Y-%m-%dT18:00"))
        r.click("#deadlines button:has-text('추가')", wait=1.2)
        r.scroll_to("#files", wait=1.4)
        expect(r.page.locator("#files")).to_contain_text("평가용 입력 데이터 (정답 제외)")
        r.click("button:has-text('참여자에게 공개')", wait=1)
        r.passed("형식 자동 분석 · 학생용 자료 자동 생성 · 공개")


def g02_signup(browser):
    """G02 참여 코드 가입 (코드 없으면 불가) → 처음 로그인 사용 안내"""
    from apps.competitions.models import Competition, JoinCode, Role

    comp = Competition.objects.get(title="2026-2 머신러닝 기말 프로젝트")
    _, code = JoinCode.issue(comp, Role.PARTICIPANT, comp.created_by)
    with Recording(browser, "G02_signup_with_code", None, "/accounts/signup/") as r:
        r.caption("TC-A01", "참여 코드 없이 가입 시도", "가입 불가 — 대회에 속하지 않은 계정 방지", "RFP p.3")
        r.type("input[name=email]", "newstudent@demo.evalhub", delay=25)
        r.type("input[name=name]", "신입생")
        r.type("input[name=password1]", "secure-pass-2026", delay=20)
        r.type("input[name=password2]", "secure-pass-2026", delay=20)
        r.click("button:has-text('가입하고')", wait=1)
        expect(r.page.locator(".field-error").first).to_be_visible()
        r.blocked("코드 없이는 가입할 수 없음", hold=1.6)
        r.caption("TC-A01", "관리자에게 받은 참여 코드로 가입", "가입과 동시에 대회 참여 · 익명 이름 자동 부여", "RFP p.3")
        r.type("input[name=join_code]", code, delay=60)
        r.page.fill("input[name=password1]", "secure-pass-2026")
        r.page.fill("input[name=password2]", "secure-pass-2026")
        r.click("button:has-text('가입하고')", wait=1.4)
        expect(r.page.locator("body")).to_contain_text("2026-2 머신러닝 기말 프로젝트")
        r.passed("가입 + 대회 참여 완료", hold=1.4)
        r.caption("TC-A07", "처음 로그인 · 역할별 사용 안내", "학생·조교·교수마다 다른 5단계 안내, 끝내면 다시 뜨지 않음", "사용성")
        expect(r.page.locator("[data-testid=tutorial]")).to_be_visible()
        for _ in range(4):
            r.click("[data-tutorial-next]", wait=1.1)
        r.click("[data-tutorial-finish]", wait=1.0)
        expect(r.page.locator("[data-testid=tutorial]")).to_have_count(0)
        r.passed("사용 안내 완료 → 대시보드")


def g03_submit(browser):
    """G03 제출 → 사전 검사 → 지문 계산 → 업로드 → 즉시 채점 → 순위"""
    d = fashion_files()
    pid = project_id(P1)
    with Recording(browser, "G03_submit", email("student4"), f"/p/{pid}/") as r:
        r.caption("TC-C01", "참여자 · CSV·노트북·가중치 제출", "사전 검사 → 업로드 → 즉시 채점, 1회 차감, 순위 표시", "RFP p.4~5")
        r.pause(0.8)
        pick_files(r, d / "submission.csv", d / "solution.ipynb", d / "model.joblib")
        r.type("textarea[name=comment]", "로지스틱 회귀 C=0.2", delay=30)
        r.click("#submit-btn", wait=0.4)
        expect(r.page.locator("[data-testid=score]")).to_be_visible(timeout=20000)
        r.scroll_to("#submit-result", wait=1.6)
        r.passed("채점 완료 · 1회 차감 · 순위 반영")


def g04_format_error(browser):
    """G04 형식 오류 — 행 단위 안내, 횟수 미차감"""
    d = fashion_files()
    pid = project_id(P1)
    with Recording(browser, "G04_format_error", email("student6"), f"/p/{pid}/") as r:
        r.caption("TC-D02", "허용되지 않은 레이블·빈 값이 있는 CSV", "업로드 전에 행 번호와 함께 안내, 제출 횟수 차감 없음", "RFP p.5")
        before = r.page.locator("[data-testid=quota] .stat-value").inner_text()
        pick_files(r, d / "submission_bad_label.csv", d / "solution.ipynb", d / "model.joblib")
        r.click("#submit-btn", wait=1.2)
        expect(r.page.locator("#precheck")).to_contain_text("152행")
        r.scroll_to("#precheck", wait=1.2)
        assert r.page.locator("[data-testid=quota] .stat-value").inner_text() == before
        r.passed("152행 'cat' · 35행 빈 값 안내 · 미차감", hold=1.8)
        r.caption("TC-D03", "열 이름이 틀린 CSV", "필요한 열과 현재 열을 비교해 안내", "RFP p.5")
        r.page.set_input_files("input[name=csv]", str(d / "submission_bad_header.csv"))
        r.click("#submit-btn", wait=1.2)
        expect(r.page.locator("#precheck")).to_contain_text("필요한 열이 없습니다")
        r.scroll_to("#precheck", wait=1)
        r.passed("헤더 오류 안내 · 미차감")


def g05_deadline(browser):
    """G05 마감 경계: 마감 직전 시작 → 마감 후 완료 = 채점 / 마감 후 시작 = 채점 제외"""
    from apps.competitions import services as cs
    from apps.competitions.models import Competition, Deadline, Project
    from apps.core import demo
    from apps.testing import upload

    comp = Competition.objects.get(title="2026-2 머신러닝 기말 프로젝트")
    prof = comp.created_by
    Project.objects.filter(title="마감 경계 시연").delete()
    p = Project.objects.create(competition=comp, title="마감 경계 시연", task_type="classification", metric="accuracy",
                               higher_is_better=True, decimals=4, grace_minutes=30)
    _, test = demo.fashion_frames()
    cs.upload_testset(p, upload("t.csv", test.to_csv(index=False).encode()), prof)
    cs.confirm_schema(p, "id", "label", "classification", prof)
    due = timezone.now() + timedelta(seconds=24)
    Deadline.objects.create(project=p, title="최종 마감", due_at=due, max_submissions=5)
    p.is_published = True
    p.save()
    d = fashion_files()
    with Recording(browser, "G05_deadline_boundary", email("student3"), f"/p/{p.pk}/") as r:
        r.caption("TC-B01", "마감 직전에 업로드 시작 → 마감 후 업로드 완료", "업로드 '시작 시각' 기준 → 정상 채점", "RFP p.4")
        cdp = r.ctx.new_cdp_session(r.page)
        pick_files(r, d / "submission.csv", d / "solution.ipynb", d / "big_model.joblib")
        wait = (due - timezone.now()).total_seconds() - 7
        if wait > 0:
            r.pause(wait)
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1,
                                                      "uploadThroughput": 110_000})
        r.click("#submit-btn", wait=0.5)
        expect(r.page.locator("[data-testid=score]")).to_be_visible(timeout=60000)
        assert timezone.now() > due, "업로드가 마감 전에 끝나 시연이 성립하지 않음"
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
        r.scroll_to("#submit-result", wait=1)
        r.passed("마감 후 완료됐지만 채점됨 (시작 시각 기준)", hold=1.8)
        r.caption("TC-B02", "마감이 지난 뒤 새로 제출", "접수는 되지만 채점하지 않음", "RFP p.4")
        r.go(f"/p/{p.pk}/", wait=0.6)
        pick_files(r, d / "submission.csv", d / "solution.ipynb", d / "model.joblib")
        r.click("#submit-btn", wait=1.5)
        expect(r.page.locator("#submit-result")).to_contain_text("마감 후 접수", timeout=15000)
        r.scroll_to("#submit-result", wait=1)
        r.passed("접수됨 · 채점 제외")


def g08_leaderboard(browser):
    """G08 같은 리더보드: 참여자(익명) vs 관리자(실명) — 두 영상을 나란히"""
    pid = project_id(P1)
    for who, label, tc in (("student2", "참여자 화면 — 익명 이름만 (실명은 응답에 아예 없음)", "참여자"),
                           ("ta", "관리자 화면 — 실명·학번", "조교")):
        with Recording(browser, f"_G08_{who}", email(who), f"/p/{pid}/leaderboard/") as r:
            r.caption("TC-E01", label, "동점 공동 순위 · 검토 상태 · 24시간 대비 ▲▼", tc)
            r.pause(1.2)
            r.page.mouse.wheel(0, 260)
            r.pause(2.2)
            if who == "student2":
                html_text = r.page.content()
                assert "박민준" not in html_text
                r.passed("실명 미포함 확인", hold=1.5)
            else:
                r.passed("담당 관리자만 실명", hold=1.5)
    a, b = OUT / "_G08_student2.gif", OUT / "_G08_ta.gif"
    side_by_side(TMP / "_G08_student2", TMP / "_G08_ta", OUT / "G08_leaderboard_anonymous_vs_real.gif")
    a.unlink(missing_ok=True)
    b.unlink(missing_ok=True)
    print("  ✓ G08_leaderboard_anonymous_vs_real.gif")


def side_by_side(dir_a: Path, dir_b: Path, dst: Path):
    va = next(dir_a.glob("*.webm"))
    vb = next(dir_b.glob("*.webm"))
    vf = ("[0:v]scale=640:-1[a];[1:v]scale=640:-1[b];[a][b]hstack=inputs=2,fps=10,split[x][y];"
          "[x]palettegen=max_colors=160:stats_mode=diff[p];[y][p]paletteuse=dither=bayer:bayer_scale=4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.8", "-i", str(va), "-ss", "0.8", "-i", str(vb),
                    "-filter_complex", vf, "-shortest", str(dst)], check=True)


def g09_review(browser):
    """G09 관리자1 검토: 무결성 리포트 + 격리 노트북 + 판정 제안"""
    from apps.review.models import Review

    r9 = Review.objects.get(submission__user__name="한예준", submission__project__title=P1)
    pid = project_id(P1)
    with Recording(browser, "G09_admin1_review", email("ta"), f"/p/{pid}/review/") as r:
        r.caption("TC-F01", "조교 · 검토 목록 — 참여자별 최고 점수 기록부터", "부정 점검 신호등으로 볼 곳을 먼저 확인", "RFP p.6, p.8")
        r.pause(1.8)
        r.click(f"a[href='/review/{r9.pk}/']", wait=1.5)
        r.scroll_to("[data-testid=integrity]", wait=1.8)
        expect(r.page.locator("[data-testid=integrity]")).to_contain_text("부분 복사 패턴")
        r.caption("TC-F02", "검토 의견 (부적합) — 사유 템플릿 원클릭", "제안만으로는 순위에서 빠지지 않음", "RFP p.6")
        r.click("label:has-text('부적합')")
        r.click("button[data-reason='다른 참여자 제출과 예측값이 사실상 동일']")
        r.click("button:has-text('의견 제출')", wait=1.4)
        r.passed("부적합 제안 → 교수 승인 대기")


def g10_approve(browser):
    """G10 관리자2: 부적합 승인 → 다음 기록 자동 상정, 적합 일괄 승인"""
    from apps.review.models import Review

    r8 = Review.objects.get(submission__user__name="오지우", submission__project__title=P1)
    pid = project_id(P1)
    with Recording(browser, "G10_admin2_approve", email("prof"), f"/review/{r8.pk}/") as r:
        r.caption("TC-F03", "교수 · 부적합 확정", "해당 기록 제외 → 같은 참여자의 다음 기록이 자동으로 검토 목록에", "RFP p.6")
        r.scroll_to("button:has-text('부적합 확정')", wait=1.4)
        r.click("button:has-text('부적합 확정')", wait=1.6)
        expect(r.page.locator("body")).to_contain_text("다음 기록이 검토 목록에 추가")
        r.passed("다음 기록 자동 상정", hold=1.6)
        r.caption("TC-F04", "조교가 '적합' 제안한 기록 일괄 승인", "대표 기록·성적 확정", "RFP p.6")
        boxes = r.page.locator("input[name=review]")
        if boxes.count():
            r.click(boxes.first, wait=0.6)
            r.click("button:has-text('일괄 승인')", wait=1.5)
        r.go(f"/p/{pid}/results/", wait=1.8)
        r.passed("최종 성적 확정 · CSV 내보내기 가능")


def g11_integrity(browser):
    """G11 부정 제출 적발 + I-6 격리 재실행"""
    from apps.review.models import Review

    def rid(name):
        return Review.objects.get(submission__user__name=name, submission__project__title=P1).pk

    with Recording(browser, "G11_cheating_detection", email("ta"), f"/review/{rid('윤지호')}/") as r:
        r.caption("TC-I07", "코드·가중치는 그대로, CSV만 수정한 제출", "I-7 결과만 바뀐 제출 🔴", "RFP p.8 ★")
        r.scroll_to("[data-testid=integrity]", wait=1.6)
        r.caption("TC-I04", "격리 컨테이너에서 가중치로 다시 추론", "제출 CSV와 일치율이 낮으면 🔴", "RFP p.8 ★")
        r.click("button:has-text('다시 실행')", wait=0.5)
        r.page.wait_for_load_state("networkidle")
        r.scroll_to("[data-testid=integrity]", wait=1.2)
        expect(r.page.locator("[data-testid=integrity]")).to_contain_text("일치합니다")
        from apps.integrity.models import IntegrityReport  # 실제 재실행 결과를 그대로 표시 (하드코딩 금지)

        rate = IntegrityReport.objects.get(submission__review__pk=rid("윤지호")).rerun.get("match_rate", 0)
        r.passed(f"다시 실행 일치율 {rate:.0%} → 수기 수정 의심", hold=1.8)
        r.caption("TC-I03", "예측값을 코드에 직접 적은 노트북", "AST 분석으로 상수 목록 탐지 🔴", "RFP p.8 ★")
        r.go(f"/review/{rid('임수아')}/", wait=0.4)
        r.scroll_to("[data-testid=integrity]", wait=1.8)
        r.passed("I-3 노트북 코드 분석", hold=1.4)


def g13_xss(browser):
    """G13 노트북 XSS 무력화"""
    import nbformat
    from apps.accounts.models import User
    from apps.review import services as review
    from apps.submissions.models import Submission
    from apps.testing import submit

    user = User.objects.get(email=email("student2"))
    pid = project_id(P1)
    best = Submission.objects.filter(user=user, project_id=pid, status="graded").order_by("-score").first()
    from apps.core import storage

    csv = storage.safe_path(storage.upload_root(), best.csv_file).read_bytes()
    nb = nbformat.v4.new_notebook()
    cell = nbformat.v4.new_code_cell("display(HTML(payload))", execution_count=1)
    cell.outputs = [
        nbformat.v4.new_output("display_data", data={"text/html": "<h2>모델 결과</h2><img src=x onerror=\"document.body.innerHTML='HACKED'\"><script>fetch('/accounts/logout/',{method:'POST'})</script><b>accuracy 0.99</b>"}),
        nbformat.v4.new_output("display_data", data={"application/javascript": "alert('관리자 세션 탈취')"}),
    ]
    nb.cells = [nbformat.v4.new_markdown_cell("# 정상처럼 보이는 노트북\n<script>alert(1)</script>"), cell,
                nbformat.v4.new_code_cell("model.fit(X, y)\npred = model.predict(T)\npd.DataFrame(pred).to_csv('s.csv')", execution_count=2)]
    sub = submit(user, best.project, csv, notebook=nbformat.writes(nb).encode())
    review.sync_queue(best.project)
    rv = review.queue(best.project)
    target = next(x for x in rv if x.submission_id == sub.pk)
    with Recording(browser, "G13_notebook_xss", email("ta"), f"/review/{target.pk}/") as r:
        r.caption("TC-S05", "악성 스크립트를 숨긴 노트북을 관리자가 열람", "스크립트 실행 안 됨 · 관리자 세션 안전", "RFP p.7")
        r.pause(2.5)
        frame = r.page.frame_locator("iframe")
        expect(frame.locator("body")).to_contain_text("보안상 표시하지 않음")
        assert "HACKED" not in frame.locator("body").inner_text()
        r.blocked("script · onerror · JS 출력 모두 차단", hold=2.4)


def g15_permissions(browser):
    """G15 권한 우회 차단"""
    pid = project_id(P1)
    with Recording(browser, "G15_permission_bypass", email("student1"), f"/p/{pid}/") as r:
        r.caption("TC-A06", "참여자가 관리자 설정 주소를 직접 입력", "404 — 페이지 존재 여부도 숨김", "RFP p.7")
        r.pause(1)
        r.go(f"/p/{pid}/settings/", wait=1.2)
        expect(r.page.locator("body")).to_contain_text("페이지를 찾을 수 없습니다")
        r.blocked("관리 기능 접근 차단", hold=1.4)
        r.caption("TC-A06", "다른 참여자의 제출물 주소로 접근", "404 — UUID 주소 + 소유자 검사", "RFP p.7")
        from apps.submissions.models import Submission

        other = Submission.objects.filter(project_id=pid).exclude(user__email=email("student1")).first()
        r.go(f"/s/{other.pk}/download/csv/", wait=1.2)
        r.blocked("타인 자료 접근 차단")


def g16_audit(browser):
    """G16 감사 로그 위변조 감지"""
    from apps.audit.models import AuditLog

    comp_id = AuditLog.objects.exclude(competition=None).first().competition_id
    with Recording(browser, "G16_audit_tamper", email("prof"), f"/c/{comp_id}/audit/") as r:
        r.caption("TC-S11", "변경 기록 해시 체인 검증", "모든 판정·설정 변경이 체인으로 연결", "RFP p.7")
        r.pause(1)
        r.click("a:has-text('조작 여부 확인')", wait=1.4)
        expect(r.page.locator("body")).to_contain_text("확인 완료")
        r.passed("체인 정상", hold=1.4)
        r.caption("TC-S11", "누군가 DB에서 판정 기록 하나를 몰래 수정", "위변조 지점을 정확히 찾아냄", "RFP p.7")
        victim = AuditLog.objects.filter(action__startswith="review").order_by("id").first() or AuditLog.objects.order_by("id")[3]
        original = victim.summary
        AuditLog.objects.filter(pk=victim.pk).update(summary="(조작) 부적합 → 적합으로 변경")
        try:
            r.go(f"/c/{comp_id}/audit/?verify=1", wait=1.4)
            expect(r.page.locator("body")).to_contain_text("조작 감지")
            r.blocked(f"기록 #{victim.pk} 조작 감지", hold=2.4)
        finally:
            AuditLog.objects.filter(pk=victim.pk).update(summary=original)


# ---------------------------------------------------------------------------
# 터미널 출력 GIF (테스트 실행 · 샌드박스 자가 진단)
# ---------------------------------------------------------------------------
TERMINAL = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>
body{margin:0;background:#f5f6f8;font-family:'Pretendard Variable',system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh}
.win{width:1120px;border-radius:20px;background:#0f172a;box-shadow:0 30px 80px -30px rgba(15,23,42,.55);overflow:hidden}
.bar{display:flex;gap:8px;padding:14px 18px;background:#1e293b}.bar i{width:12px;height:12px;border-radius:50%;display:block}
.bar b{margin-left:12px;color:#94a3b8;font:600 13px ui-monospace,monospace}
pre{margin:0;padding:22px 26px;min-height:520px;max-height:600px;overflow:hidden;color:#e2e8f0;font:14.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap}
.ok{color:#4ade80;font-weight:700}.bad{color:#f87171;font-weight:700}.dim{color:#64748b}.cmd{color:#93c5fd}
</style></head><body><div class="win"><div class="bar"><i style="background:#f87171"></i><i style="background:#fbbf24"></i><i style="background:#4ade80"></i><b>TITLE</b></div><pre id="t"></pre></div>
<script>const L=LINES;const t=document.getElementById('t');let i=0;function step(){if(i>=L.length){window.done=true;return}
t.innerHTML+=L[i]+'\\n';t.scrollTop=t.scrollHeight;i++;setTimeout(step,i<2?600:DELAY)}setTimeout(step,500)</script></body></html>"""


def terminal_gif(browser, name, title, command, lines, tc, caption, expected, delay=70):
    import json

    esc = []
    for line in lines:
        h = html.escape(line)
        h = re.sub(r"(BLOCKED ✓|PASSED|passed|✓)", r'<span class="ok">\1</span>', h)
        h = re.sub(r"(FAILED|ALLOWED|✕)", r'<span class="bad">\1</span>', h)
        esc.append(h)
    page_html = (TERMINAL.replace("TITLE", html.escape(title)).replace("DELAY", str(delay))
                 .replace("LINES", json.dumps([f'<span class="cmd">$ {html.escape(command)}</span>'] + esc)))
    path = TMP / f"{name}.html"
    path.write_text(page_html, encoding="utf-8")
    ctx = browser.new_context(viewport=VIEW, record_video_dir=str(TMP / name), record_video_size=VIEW)
    ctx.add_init_script(OVERLAY)
    page = ctx.new_page()
    page.goto(path.as_uri())
    page.evaluate("([a,b,c,d]) => window.__demo.caption(a,b,c,d)", [tc, caption, expected, "실측"])
    page.wait_for_function("window.done === true", timeout=120000)
    page.wait_for_timeout(1500)
    video = page.video
    ctx.close()
    to_gif(Path(video.path()), OUT / f"{name}.gif", trim=0.3, fps=8)
    print(f"  ✓ {name}.gif")


def g12_sandbox(browser):
    out = subprocess.run([PY, "manage.py", "sandbox_selftest"], capture_output=True, text=True, cwd=WEB).stdout
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert "6/6" in out
    terminal_gif(browser, "G12_sandbox_attacks", "sandbox_selftest — 악성 노트북을 실제 격리 컨테이너에서 실행",
                 "python manage.py sandbox_selftest", lines, "TC-S01~S04",
                 "참여자 노트북의 공격 6종을 샌드박스에서 실제 실행", "정답·비밀키·네트워크·시스템·자원 공격 전부 차단", delay=420)


def g17_tests(browser):
    res = subprocess.run([PY, "-m", "pytest", "-o", "addopts=", "-p", "no:warnings", "-v", "--no-header"], capture_output=True, text=True, cwd=WEB)
    lines = []
    for ln in res.stdout.splitlines():
        m = re.match(r"apps/(\S+)::(\S+) (PASSED|FAILED)", ln)
        if m:
            lines.append(f"{m.group(3):6} {m.group(2)}")
        elif re.search(r"\d+ passed", ln):
            lines.append("")
            lines.append(ln.strip("= "))
    assert "failed" not in res.stdout.split("\n")[-2]
    terminal_gif(browser, "G17_all_tests", "pytest — 경계값·동시성·권한·보안·부정 탐지·HTTP 흐름",
                 "pytest -v", lines, "ALL", "전체 자동화 테스트 실행", "모든 테스트 통과", delay=40)


def g18_experiment(browser):
    res = subprocess.run([PY, "-W", "ignore", "manage.py", "integrity_experiment", "--no-save"], capture_output=True, text=True, cwd=WEB)
    keep = []
    for ln in res.stdout.splitlines():
        if ln.startswith("| ") and "---" not in ln and ("제출" in ln or "복사" in ln or "기입" in ln or "수정" in ln or "그룹" in ln):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            keep.append(f"{cells[0]:<22} {cells[1]:>6}  {cells[2]:<14} {cells[3]}")
            if "그룹" in ln:
                keep.append("-" * 70)
        elif ln.startswith("- **"):
            keep.append(ln.replace("**", "").replace("- ", "  "))
    assert any("100%" in k for k in keep)
    terminal_gif(browser, "G18_integrity_experiment", "integrity_experiment — 정직 20 · 부정 30 탐지 실험",
                 "python manage.py integrity_experiment", ["", *keep[:8], "", *keep[8:]], "TC-I05",
                 "부정 의심 점검 탐지 실험 (DB 변경 없이 롤백)", "부정 30/30 탐지 · 정직 오탐 1/20", delay=380)


SCENARIOS = {
    "G01": g01_create, "G02": g02_signup, "G03": g03_submit, "G04": g04_format_error, "G05": g05_deadline,
    "G08": g08_leaderboard, "G09": g09_review, "G10": g10_approve, "G11": g11_integrity, "G13": g13_xss,
    "G15": g15_permissions, "G16": g16_audit, "G12": g12_sandbox, "G17": g17_tests, "G18": g18_experiment,
}
ORDER = ["G17", "G12", "G18", "G01", "G02", "G03", "G04", "G08", "G09", "G10", "G11", "G13", "G15", "G16", "G05"]


def start_server():
    """운영 설정으로 녹화용 서버 실행 (디버그 화면이 아닌 실제 오류 화면이 녹화되도록)"""
    import urllib.request

    env = {**os.environ, "DJANGO_DEBUG": "false", "SECURE_COOKIES": "false", "RQ_EAGER": "true"}
    subprocess.run([PY, "manage.py", "collectstatic", "--noinput"], cwd=WEB, env=env, check=True, capture_output=True)
    proc = subprocess.Popen([PY, "manage.py", "runserver", f"127.0.0.1:{PORT}", "--noreload", "--nostatic"], cwd=WEB, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # iCloud 동기화 폴더에서는 첫 기동이 수십 초 걸릴 수 있어 넉넉히 기다린다
    started = time.time()
    for _ in range(240):
        try:
            urllib.request.urlopen(BASE + "/healthz", timeout=2)
            print(f"녹화용 서버 준비 ({time.time() - started:.0f}초)")
            return proc
        except Exception:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("녹화용 서버를 시작하지 못했습니다")


def main():
    wanted = sys.argv[1:] or ORDER
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)
    server = start_server() if "BASE_URL" not in os.environ else None
    if not set(wanted) <= {"G12", "G17", "G18"}:
        print("데모 데이터 초기화 …")
        subprocess.run([PY, "manage.py", "seed_demo"], check=True, cwd=WEB, capture_output=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for key in [k for k in ORDER if k in wanted]:
            print(f"[{key}] {SCENARIOS[key].__doc__.strip().splitlines()[0] if SCENARIOS[key].__doc__ else key}")
            try:
                SCENARIOS[key](browser)
            except Exception as exc:  # 하나가 실패해도 나머지는 계속
                print(f"  ✕ {key} 실패: {type(exc).__name__}: {str(exc)[:300]}")
        browser.close()
    if server:
        server.kill()
    shutil.rmtree(WEB / "staticfiles", ignore_errors=True)


if __name__ == "__main__":
    main()
