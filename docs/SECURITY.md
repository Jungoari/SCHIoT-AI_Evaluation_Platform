# 보안 설계와 검증 결과

> RFP p.7 "행정안전부 소프트웨어 개발보안 가이드 참고" 대응 — 구현 위치와 테스트 결과
> 설계 배경(보호 자산·위협 모델)은 [SECURITY_PLAN.md](SECURITY_PLAN.md) 참고

## 1. 핵심 원칙

| 원칙 | 구현 |
|---|---|
| 최소 권한 | 정답 볼륨은 `web`·`worker`에만 마운트, `sandbox-worker`와 샌드박스 컨테이너에는 없음 (`docker-compose.yml`) |
| 심층 방어 | 노트북 표시: 서버 정제 → 스크립트 금지 iframe → CSP. 권한: 뷰 검사 → 서비스 함수 재검사 |
| 기본 거부 | 권한 정책 단일 모듈(`apps/core/permissions.py`), 권한이 없으면 404 (존재 여부도 숨김) |
| 사람의 최종 판단 | 무결성 리포트는 표시만, 부적합 확정은 관리자2만 (`apps/review/services.py`) |

## 2. RFP 보안 요구사항별 구현

### 2.1 참여자 코드 격리 실행 — `apps/integrity/sandbox.py`, `sandbox/`

| 설정 | 막는 것 | 자가 진단 |
|---|---|---|
| 작업 폴더에 정답 파일을 복사하지 않음 | 정답 탈취 | S01 ✓ |
| 환경 변수는 경로 3개만 전달 | 비밀키 탈취 | S02 ✓ |
| `network_disabled=True` | 외부 전송, DB·Redis·웹 접근 | S03 ✓ |
| `read_only=True`, 비루트(65534), `cap_drop=ALL`, `no-new-privileges` | 시스템 변조·권한 상승 | S03b ✓ |
| `pids_limit=128` | 프로세스 폭탄 | S04 ✓ |
| `mem_limit=2g`, 시간 제한 300초 | 메모리 폭탄·무한 루프 | S04b ✓ |
| 실행마다 새 컨테이너, 종료 후 삭제 | 이전 실행 흔적 엿보기 | — |

```bash
python manage.py sandbox_selftest   # 결과: 6/6 공격 차단
```

**pickle 위험:** `.pkl/.joblib/.pt`는 불러오는 순간 코드가 실행될 수 있으므로 웹·채점 서버에서는 형식(매직 바이트)만 확인하고, 실제 로드는 샌드박스 안에서만 한다 (`apps/submissions/filecheck.py`).

### 2.2 파일 내용 검증·안전한 저장명 — `apps/core/storage.py`, `apps/submissions/filecheck.py`

- CSV: UTF-8 디코딩·파싱·NUL 바이트 검사 / 노트북: JSON + `nbformat.validate` / 가중치: 확장자별 매직 바이트
- 저장명은 `uuid4().hex + 확장자`, 읽을 때도 정규식으로 형식 검증 후 루트 밖 경로 거부
- 파일은 `0640`, 덮어쓰기 금지(`open(..., "xb")`), 크기 상한 초과 시 저장 중단·삭제
- 다운로드는 권한 검사 뷰만, `attachment` + `nosniff`
- 요청 전체 크기가 허용 상한(파일 3종 합 + 1MB)을 넘으면 **본문을 읽기 전에 413 거부** (`UploadSizeLimitMiddleware`) — 거대 요청으로 디스크를 채우는 공격 차단

### 2.3 노트북 비신뢰 콘텐츠 — `apps/review/notebook.py`

1. 스크립트·위젯 출력은 렌더링하지 않음, HTML·마크다운은 nh3 허용 목록 정제, 이미지는 PNG/JPEG 매직 바이트 확인 (SVG 제외), **외부 주소 이미지는 제거** (관리자 열람 사실·IP 유출 방지)
2. `<iframe sandbox="">`(스크립트·같은 출처 권한 없음)에서만 표시
3. 응답 CSP `default-src 'none'; img-src data:` — 정제를 우회해도 실행 불가

### 2.4 비밀번호·세션·비밀 정보

| 항목 | 구현 |
|---|---|
| 비밀번호 | Argon2, 10자 이상, 흔한 비밀번호·숫자만 금지 |
| 무차별 대입 | 로그인: django-axes 10회 실패 시 15분 / 참여 코드: 10회 실패 시 15분 (`apps/core/ratelimit.py`) |
| 세션 | HttpOnly·SameSite=Lax·(HTTPS 시) Secure, 8시간 만료, 로그인 시 세션 ID 재발급, 로그아웃은 POST만 |
| 참여 코드 | `secrets` 12자리(60비트), SHA-256 해시만 저장, 원문은 발급 화면에 한 번만 |
| 비밀 설정 | `.env`(gitignore), 저장소에는 `.env.example`만 |
| 의존성 취약점 | `pip-audit` — 웹 서버 라이브러리·샌드박스 이미지 52개 모두 알려진 취약점 0건 (2026-11-19). CI 에서 취약점 발견 시 빌드 실패 |
| 샌드박스 재현성 | 샌드박스 라이브러리 버전 고정 (웹 서버와 동일한 scikit-learn·pandas·numpy) → 재빌드해도 재실행 결과 동일, 탐지 실험 재측정 결과 변화 없음 |
| 오류 응답 | `DEBUG=False`, 오류 화면에는 추적 ID만 (`X-Request-ID`), CSV 오류 메시지에 정답 값 미포함 |
| 로그 | 요청 ID 부여, password·token·session·join_code 값 자동 마스킹 (`apps/core/logging.py`) |
| 프록시 뒤 접속자 IP | `TRUSTED_PROXY_COUNT` 개수만큼만 `X-Forwarded-For` 를 오른쪽부터 신뢰 (기본 0 = 무시). 프록시 IP 하나로 모든 방문자가 묶여 한 사람의 실패가 반 전체를 차단하는 문제 방지 (`TrustedProxyMiddleware`) |
| 보안 헤더 | CSP(`script-src 'self'`, 인라인 스크립트 없음), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP |

### 2.5 권한 분리·중요 변경 기록

- 대회 단위 역할(`Membership`) — 관리자1은 담당 대회만
- 승인 상태 전환은 서비스 함수 안에서 권한 재검사 (`PermissionDenied` → 404)
- 관리자1은 다른 관리자1 계정을 변경할 수 없음, 자기 자신 변경 불가
- 관리자2가 자기가 제안한 건을 승인하면 화면 경고 + 감사 로그 `self_approval: true`
- **감사 로그 해시 체인** (`apps/audit/`): `hash = SHA256(이전 hash + 내용)`, PostgreSQL advisory lock 으로 동시 기록 직렬화, 앱에 수정·삭제 기능 없음, 관리자2 화면에서 위변조 검증

## 3. 행정안전부 가이드 구현단계 보안약점 대응표

| 분류 | 보안약점 | 구현 위치 | 테스트 |
|---|---|---|---|
| 입력데이터 검증 및 표현 | SQL 삽입 | Django ORM 전용 (원시 SQL은 advisory lock 상수 1곳) | — |
| | 경로 조작 및 자원 삽입 | `core/storage.py` | `test_S07_path_traversal_filename_is_ignored` |
| | 크로스사이트 스크립트 | 템플릿 이스케이프, `review/notebook.py`, `static/js/submit.js`(textContent) | `test_S05_notebook_scripts_are_removed` |
| | 운영체제 명령어 삽입 | Docker SDK 인자 배열 (셸 미사용) | — |
| | 위험한 형식 파일 업로드 | `submissions/filecheck.py` | `test_S06_exe_renamed_as_csv_rejected`, `test_weights_extension_mismatch_rejected` |
| | 크로스사이트 요청 위조 | CSRF 미들웨어, 상태 변경 POST 전용 | `test_logout_requires_post` |
| | 보안기능 결정에 사용되는 부적절한 입력값 | 역할·소유자는 세션 기준 | `test_A05_A06_*` |
| 보안기능 | 적절한 인증 없는 중요 기능 허용 / 부적절한 인가 | `core/permissions.py` | `test_permission_matrix` (7개 권한 × 5개 역할) |
| | 하드코드된 중요정보 | `.env` 분리, bandit | CI |
| | 적절하지 않은 난수 | `secrets` 모듈 (코드·별칭) | — |
| | 취약한 비밀번호 허용 / 솔트 없는 해시 | 비밀번호 검증기, Argon2 | `test_weak_password_rejected` |
| | 반복된 인증시도 제한 기능 부재 | axes, `FailureLimiter` | `test_A02_*` |
| 시간 및 상태 | 경쟁조건(TOCTOU) | 슬롯 예약 + `SELECT … FOR UPDATE` | `test_C04_concurrent_submissions_respect_limit` |
| | 종료되지 않는 반복문 | 샌드박스 시간·자원 제한 | `sandbox_selftest` S04 |
| 에러처리 | 오류 메시지 정보노출 | 추적 ID 오류 화면, 로그 마스킹 | `test_mask_secrets_in_logs` |
| | 오류상황 대응 부재 | 재시도 3회 → 시스템 오류·미차감 | `test_C03_system_error_not_deducted` |
| 코드오류 | **신뢰할 수 없는 데이터의 역직렬화** | pickle 은 샌드박스에서만 로드 | `sandbox_selftest` |
| 캡슐화 | 잘못된 세션에 의한 데이터 정보노출 | 리더보드 실명 서버 제외 | `test_E01_E05_participant_sees_aliases_only` |
| | 제거되지 않고 남은 디버그 코드 | Django 관리 화면은 `DEBUG` 일 때만 | — |
| API 오용 | 취약한 API 사용 | `eval`·`shell=True`·웹 서버 pickle 로드 없음, bandit | CI |

추가로 발견해 막은 문제

| 문제 | 대응 | 테스트 |
|---|---|---|
| 업로드 시작 후 파일 바꿔치기 | 시작 시 해시 선언·완료 시 대조 | `test_B03_*` |
| CSV 수식 주입 (성적 엑셀 내보내기) | `= + - @` 시작 값 앞에 `'` | `test_csv_export_escapes_formula` |
| 정답이 섞인 파일 배포 | 정답 열을 제거한 배포본 자동 생성, 정답은 별도 저장소 | `test_admin2_full_setup_flow` |
| 감사 로그 사후 조작 | 해시 체인 | `test_chain_valid_and_detects_tampering` |
| 프록시 뒤에서 한 사람의 코드 오입력이 반 전체 가입 차단 | 신뢰 프록시 개수 기반 실제 IP 복원, 헤더 위조 무시 | `test_behind_proxy_*`, `test_forwarded_for_ignored_without_trusted_proxy` |

## 4. 알려진 제약

- `sandbox-worker`는 Docker 소켓을 쓰므로 root로 실행된다. 대신 정답 볼륨·웹 포트가 없고, 참여자 코드는 별도 격리 컨테이너에서만 실행된다. 운영 환경에서는 rootless Docker 또는 gVisor(`runsc`) 런타임을 권장한다.
- HTTPS 종단은 배포 환경의 리버스 프록시에서 처리한다 (`SECURE_COOKIES=true`, `SECURE_HSTS=true`, `TRUSTED_PROXY_COUNT=1`) — [DEPLOY.md](DEPLOY.md)
