# 배포 가이드 (서버 1대 + HTTPS)

> 대상: Ubuntu 22.04/24.04 VM 1대 (권장 2 vCPU · 4GB RAM · 40GB 디스크, 50명 규모 — [PERFORMANCE.md](PERFORMANCE.md))
> 샌드박스가 Docker 컨테이너를 직접 띄우므로 **Docker 를 쓸 수 있는 VM** 이 필요하다 (Heroku·Render 같은 PaaS 불가)
> 소요: 약 30분

```
인터넷 ──HTTPS──▶ Caddy (호스트, 인증서 자동) ──http──▶ 127.0.0.1:8000 web 컨테이너
                                                         worker · sandbox-worker · db · redis (외부 비노출)
```

---

## 1. 서버 준비

```bash
# Docker 설치 (공식 스크립트)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker

# Caddy 설치 (HTTPS 인증서 자동 발급·갱신)
sudo apt install -y caddy

# 방화벽: SSH · HTTP · HTTPS 만 연다
sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable
```

> 클라우드 콘솔의 보안 그룹(방화벽)에서도 22·80·443 만 연다. **8000·5432·6379 는 열지 않는다**

도메인: `eval.example.com` 의 A 레코드를 VM 공인 IP 로 연결 (학교 도메인이 없으면 `duckdns.org` 같은 무료 도메인)

---

## 2. 코드와 환경 변수

```bash
git clone <저장소 URL> evalhub && cd evalhub
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # → DJANGO_SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # → POSTGRES_PASSWORD
```

`.env` 에서 **반드시 바꿀 값**

| 변수 | 값 | 이유 |
|---|---|---|
| `DJANGO_SECRET_KEY` | 위에서 만든 긴 무작위 값 | 세션·토큰 서명 키. 예시 값 그대로면 세션 위조 가능 |
| `POSTGRES_PASSWORD` | 위에서 만든 값 | |
| `DJANGO_ALLOWED_HOSTS` | `eval.example.com` | 다른 도메인으로 들어온 요청 거부 |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://eval.example.com` | |
| `SECURE_COOKIES` | `true` | 쿠키를 HTTPS 로만 전송 |
| `SECURE_HSTS` | `true` | 브라우저가 항상 HTTPS 로 접속 |
| `TRUSTED_PROXY_COUNT` | `1` | Caddy 뒤에서 실제 접속자 IP 복원 (아래 설명) |
| `WEB_PORT` | `127.0.0.1:8000` | web 을 **서버 내부에만** 열고 외부는 Caddy 로만 |
| `DEMO_MODE` | 시연 서버 `true` / 실제 수업 `false` | `false` 면 공개된 데모 비밀번호 계정이 생성되지 않음 |

> **`TRUSTED_PROXY_COUNT` 가 왜 필요한가?** 프록시 뒤에서는 모든 방문자가 프록시 IP 하나로 보인다.
> 그러면 누군가 참여 코드를 10번 틀렸을 때 **반 전체의 가입이 15분간 막힌다.** 1 로 두면 Caddy 가 붙여 준 실제 IP 를 쓴다.
> 반대로 프록시 없이 직접 노출할 때 1 로 두면 IP 를 위조할 수 있으므로 **0 (기본값)** 으로 둔다

---

## 3. 실행

```bash
docker compose up -d --build
docker compose ps                     # 모두 running / healthy 확인
docker compose exec sandbox-worker python manage.py sandbox_selftest   # 6/6 차단 확인
```

`DEMO_MODE=false` 일 때 첫 관리자2(교수) 계정 만들기

```bash
docker compose exec web python manage.py createsuperuser   # 이메일·이름·비밀번호 입력 → 관리자2 권한 자동 부여
```

---

## 4. HTTPS (Caddy)

`/etc/caddy/Caddyfile`

```
eval.example.com {
    encode gzip
    request_body {
        max_size 600MB          # 가중치 500MB + CSV·노트북 (앱이 정확한 한도를 다시 검사)
    }
    reverse_proxy 127.0.0.1:8000 {
        transport http {
            read_timeout 10m    # 대용량 업로드
        }
    }
}
```

```bash
sudo systemctl reload caddy
curl -I https://eval.example.com/healthz     # 200 이면 완료
```

Caddy 가 Let's Encrypt 인증서를 자동으로 받고 갱신한다. 별도 설정 없음

---

## 5. 백업과 복구

정답 파일(`labels`)·제출물(`uploads`)·DB 세 가지를 함께 백업해야 한다

```bash
# 백업 (매일 새벽 cron 권장: 0 4 * * * cd ~/evalhub && ./backup.sh)
mkdir -p ~/backup && TS=$(date +%Y%m%d)
docker compose exec -T db pg_dump -U evalplatform evalplatform | gzip > ~/backup/db-$TS.sql.gz
docker run --rm -v evalhub_uploads:/u -v evalhub_labels:/l -v ~/backup:/b alpine \
    tar czf /b/files-$TS.tar.gz -C / u l
find ~/backup -mtime +14 -delete       # 14일 보관
```

```bash
# 복구
gunzip -c ~/backup/db-YYYYMMDD.sql.gz | docker compose exec -T db psql -U evalplatform evalplatform
docker run --rm -v evalhub_uploads:/u -v evalhub_labels:/l -v ~/backup:/b alpine \
    tar xzf /b/files-YYYYMMDD.tar.gz -C /
```

> 백업 파일에는 **정답이 들어 있다.** 서버 밖으로 옮길 때는 암호화하고 접근 권한을 관리자2로 제한

---

## 6. 업데이트

```bash
git pull
docker compose up -d --build          # 마이그레이션은 web 시작 시 자동 실행
docker compose exec web python manage.py check --deploy
```

채점 중이던 작업은 워커가 다시 시작될 때 `recover_stuck` 이 자동으로 다시 줄 세운다 (README "장애 대책")

---

## 7. 배포 후 점검표

- [ ] `https://` 로만 접속되고 `http://` 는 자동으로 넘어가는가
- [ ] `curl http://<공인IP>:8000` 이 **연결 실패**하는가 (web 이 외부에 직접 노출되지 않음)
- [ ] `docker compose exec web python manage.py check --deploy` 경고 없음
- [ ] `sandbox_selftest` 6/6 차단
- [ ] 다른 PC 에서 틀린 참여 코드 10회 → 그 PC 만 차단, 내 PC 는 가입 가능 (`TRUSTED_PROXY_COUNT` 확인)
- [ ] 백업 1회 실행 후 파일 생성 확인
- [ ] `DEMO_MODE=false` 라면 데모 계정(`*@demo.evalhub`)으로 로그인 불가

## 8. 검증 기록 (2026-11-19, 새 폴더·새 Docker 스택)

저장소 파일만 새 폴더에 복사해 README 빠른 시작대로 `cp .env.example .env` → `docker compose up --build` 실행

| 확인 항목 | 결과 |
|---|---|
| 서비스 5개 기동 · `/healthz` | 모두 실행, 200 |
| 데모 데이터 자동 생성 | 실제 모델 학습 후 제출·검토 데이터 생성 |
| 오류 CSV 제출 → 채점 워커 컨테이너 | `invalid`, "필수 열이 없습니다: label" 안내 (0.5초) |
| 정상 CSV 제출 → 채점 워커 컨테이너 | `graded`, 정확도 0.9764 (0.5초) |
| 참여자·관리자2 주요 화면 12개 | 모두 200 |
| 샌드박스 공격 자가 진단 (`sandbox-worker`) | 6/6 차단 |
| 웹·샌드박스 라이브러리 버전 | scikit-learn 1.9.1 동일 |
| 배포 설정 `check --deploy` | 경고 0건 (의도된 3건 제외) |
| 보안 헤더 | CSP · X-Frame-Options · nosniff · Referrer-Policy · COOP · 추적 ID |
| 프록시 뒤 참여 코드 제한 (`TRUSTED_PROXY_COUNT=1`, 실제 HTTP) | 방문자 A 10회 실패 → 차단 / 다른 IP 방문자 B → 허용 / A 의 헤더 위조 → 여전히 차단 |

## 9. 비용 참고 (2026년 기준 대략)

| 선택지 | 사양 | 월 비용 | 비고 |
|---|---|---|---|
| Oracle Cloud Always Free (Ampere) | 4 vCPU · 24GB | 무료 | ARM — 샌드박스 이미지도 ARM 으로 빌드됨, 가입 시 카드 인증 필요 |
| AWS Lightsail | 2 vCPU · 4GB | 약 $24 | 설정 간단, 고정 IP 포함 |
| 학교 서버 | — | 무료 | 학과 문의, Docker 허용 여부 확인 필요 |
