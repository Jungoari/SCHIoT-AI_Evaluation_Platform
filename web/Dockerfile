# ---------- 1단계: CSS 빌드 ----------
FROM node:24-alpine AS assets
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --silent
COPY static ./static
COPY assets ./assets
COPY templates ./templates
COPY apps ./apps
RUN npx tailwindcss -i ./assets/app.css -o ./static/css/app.css --minify

# ---------- 2단계: 앱 ----------
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
COPY --from=assets /build/static/css/app.css ./static/css/app.css
RUN chmod +x /app/entrypoint.sh

# 비루트 사용자로 실행
# 볼륨 마운트 지점을 미리 만들어 두어야 named volume 이 app 사용자 소유로 생성된다
RUN useradd --create-home --uid 1000 app && mkdir -p /data/uploads /data/labels /data/sandbox \
 && chown -R app:app /app /data && chmod 700 /data/labels
USER app

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["web"]
