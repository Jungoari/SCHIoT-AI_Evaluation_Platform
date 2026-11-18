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
RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown -R app:app /app /data
USER app

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["web"]
