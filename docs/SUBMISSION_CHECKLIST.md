# 제출 준비 체크리스트 (마감 2026-11-25 17:00)

> 정원이 직접 해야 하는 일을 순서대로 정리한 문서 — 명령은 복사해서 그대로 쓰면 된다
> 제출물: GitHub 저장소 URL (README · 발표 자료 · 시연 GIF 포함)

---

## 1. GitHub 저장소에 올리기 (약 10분)

### 올리기 전에 정할 것

| 항목 | 현재 상태 | 선택지 |
|---|---|---|
| 공개 여부 | — | 심사위원이 URL 로 열어야 하므로 **공개(Public)** 가 안전. 비공개면 심사위원 계정 초대 필요 (운영진 확인) |
| 커밋 작성자 이메일 | 기존 커밋에 개인 Gmail 이 기록돼 있음 | 공개 저장소면 누구나 볼 수 있음. 가리려면 GitHub 설정 → Emails → "Keep my email addresses private" 후 나오는 `…@users.noreply.github.com` 주소로 바꾸고 **올리기 전에** 기존 커밋 작성자도 바꿔야 함 (원하면 Claude 에게 요청) |
| 발표 자료 개인정보 | 표지에 학번, 마지막 장에 학교 이메일 | 대회 제출용이라 보통 그대로 둠. 빼려면 `scripts/build_presentation.py` 에서 수정 후 재생성 |
| 저장소 이름 | — | 예: `ai-model-eval-platform` (영문·하이픈 권장, URL 이 깔끔) |

### 올리는 방법

1. https://github.com/new 에서 저장소 생성 — **README·.gitignore·라이선스 추가 체크하지 않기** (이미 있음)
2. 아래 명령 실행 (`<아이디>`·`<저장소>` 바꾸기)

```bash
cd ~/Desktop/"2026-2학기 채점사이트경진대회"
```

```bash
git remote add origin https://github.com/<아이디>/<저장소>.git
```

```bash
git push -u origin main
```

> 현재 파일 약 60MB (GIF 40MB · 발표 자료 20MB · PDF 3MB), 이전 버전 GIF 가 커밋 기록에 남아 첫 업로드는 100MB 안팎. 파일 하나당 GitHub 한도(100MB) 미만이라 Git LFS 불필요

### 올린 뒤 확인

- [ ] 저장소 첫 화면에서 README 의 로고·배지·GIF 가 보이는가
- [ ] Actions 탭의 CI 가 초록색(통과)인가 — 테스트 131개 · 린트 · 보안 검사(bandit) · 의존성 취약점(pip-audit) · 마이그레이션 누락
- [ ] 로그인하지 않은 브라우저(시크릿 창)에서 URL 이 열리는가
- [ ] `presentation/` 의 .pptx·PDF 를 내려받아 열리는가

### 발표 자료에 저장소 주소 넣기

저장소 URL 이 생기면 Q&A 슬라이드에 표시되도록 다시 생성한다 (주소를 바꾸고 실행)

```bash
REPO_URL=https://github.com/<아이디>/<저장소> .venv/bin/python scripts/build_presentation.py
```

```bash
.venv/bin/python scripts/pptx_preview.py presentation/AI모델_성능평가_자동화_발표.pptx var/preview --pdf presentation/AI모델_성능평가_자동화_발표_백업.pdf
```

그다음 커밋·푸시 (QR 코드는 넣지 않기로 함 — 주소만 표시)

---

## 2. 운영진 질문 (오픈채팅에 붙여넣기용)

RFP 해석이 갈리는 부분 — 답이 없어도 현재 구현으로 문제없지만, 답이 오면 설정만 바꾸면 된다 ([QUESTIONS.md](QUESTIONS.md) B1~B8)

> 안녕하세요, AI모델 성능평가 자동화 경진대회 참가자입니다. RFP 관련해 몇 가지 여쭙고 싶습니다.
>
> 1. 심사 시 제출한 코드를 직접 실행해 보시나요, 아니면 README·발표 자료·시연 영상(GIF)을 중심으로 보시나요?
> 2. 관리자1(조교) 계정은 참여자와 같은 참여 코드로 가입하나요, 아니면 역할별로 별도 코드를 두어도 될까요?
> 3. 리더보드는 프로젝트 단위로 한 개(전체 마감 구간 통틀어 최고 점수)로 이해했는데 맞을까요?
> 4. 업로드 시작 후 완료까지 허용하는 시간 기준이 있을까요? (현재 프로젝트별 설정, 기본 30분)
> 5. PyTorch·TensorFlow 모델의 재실행 검증까지 필요할까요, 아니면 scikit-learn 기준이면 충분할까요?
> 6. 저장소는 공개(Public)로 제출하면 될까요?
>
> 감사합니다!

---

## 3. 사람이 해야 하는 검증 (평가 점수 보강)

| 작업 | 시간 | 방법 | 결과를 넣을 곳 |
|---|---|---|---|
| 사용성 테스트 (동기 3~5명) | 1인당 20분 | [USABILITY_TEST.md](USABILITY_TEST.md) — `usability_kit` 로 준비물 생성 | README '사용성 검증' 절 |
| 업무 시간 실측 | 30분 | [USABILITY_TEST.md](USABILITY_TEST.md) 5장 | [PERFORMANCE.md](PERFORMANCE.md) 3장 (추정 → 실측) |
| 라이브 배포 (선택) | 30분 + 서버 선택 | [DEPLOY.md](DEPLOY.md) | README 상단에 접속 URL |

> 결과 CSV 를 `docs/usability/` 에 넣고 Claude 에게 "사용성 결과 반영해줘" 라고 하면 표 생성·README·발표 자료 갱신까지 처리

---

## 4. 마감 전 최종 점검 (11/25 오전)

- [ ] PowerPoint 로 발표 자료를 직접 열어 글자 넘침·GIF 재생 확인 (자체 미리보기로만 점검했기 때문)
- [ ] 발표 대본([PRESENTATION_SCRIPT.md](PRESENTATION_SCRIPT.md))으로 소리 내어 1회 연습 — 15분 안에 끝나는지
- [ ] GitHub 의 최신 커밋에서 CI 통과
- [ ] 제출 양식에 저장소 URL 입력 (마감 **17:00**)

## 5. 일정 제안

| 날짜 | 할 일 |
|---|---|
| 11/19 (오늘) | 커밋 · GitHub 업로드 · 운영진 질문 |
| 11/20~22 | 사용성 테스트 · 업무 시간 실측 → 결과 반영 |
| 11/23 | (선택) 라이브 배포 |
| 11/24 | PowerPoint 확인 · 발표 연습 |
| 11/25 오전 | 최종 점검 → 제출 |
