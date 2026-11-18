"""
부하 테스트 — "마감 5분 전, N명이 동시에 제출" 시나리오

    python scripts/loadtest.py http://localhost:8000 50

측정: 업로드 티켓 발급 지연, 파일 업로드 지연, 업로드 완료 → 채점 완료까지 시간, 오류 수
(사전 준비: python manage.py loadtest_users --count 50)
"""

import hashlib
import http.cookiejar
import json
import re
import statistics
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid

BASE, N = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 50
PW = "evalhub-demo-2026"


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def csrf(self):
        return next(c.value for c in self.jar if c.name == "csrftoken")

    def get(self, path):
        return self.op.open(BASE + path, timeout=60).read()

    def post(self, path, data=None, body=None, ctype=None):
        req = urllib.request.Request(BASE + path, data=body if body is not None else urllib.parse.urlencode(data).encode(),
                                     headers={"X-CSRFToken": self.csrf(), "Referer": BASE + path,
                                              "Content-Type": ctype or "application/x-www-form-urlencoded"})
        return self.op.open(req, timeout=120).read()

    def login(self, email):
        self.get("/accounts/login/")
        self.post("/accounts/login/", {"username": email, "password": PW, "csrfmiddlewaretoken": self.csrf()})


def multipart(fields, files):
    b = uuid.uuid4().hex
    out = b""
    for k, v in fields.items():
        out += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, (name, data) in files.items():
        out += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n").encode() + data + b"\r\n"
    return out + f"--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def main():
    clients = []
    print(f"{N}명 로그인 중 …")
    for i in range(N):
        c = Client()
        c.login(f"load{i:03d}@demo.evalhub")
        clients.append(c)
    page = clients[0].get("/dashboard/").decode()
    pid = re.search(r'href="/p/(\d+)/"', page).group(1)
    detail = clients[0].get(f"/p/{pid}/").decode()
    files = dict((v, k) for k, v in re.findall(r'href="(/p/\d+/files/\d+/)"[^>]*>.*?<span class="font-medium">([^<]+)</span>', detail, re.S))
    csv, nb = clients[0].get(files["샘플 제출 파일"]), clients[0].get(files["템플릿 노트북"])
    weights = b"\x80\x04" + b"N." + bytes(2 * 1024 * 1024)  # 약 2MB 가중치
    hashes = {k: hashlib.sha256(v).hexdigest() for k, v in {"csv": csv, "notebook": nb, "weights": weights}.items()}

    results, lock, barrier = [], threading.Lock(), threading.Barrier(N)

    def worker(c):
        r = {"ok": False}
        try:
            barrier.wait()
            t0 = time.perf_counter()
            start = json.loads(c.post(f"/p/{pid}/submit/start/", body=json.dumps({"hashes": hashes, "sizes": {}}).encode(),
                                      ctype="application/json"))
            t1 = time.perf_counter()
            body, ctype = multipart({}, {"csv": ("s.csv", csv), "notebook": ("n.ipynb", nb), "weights": ("m.pkl", weights)})
            done = json.loads(c.post(start["upload_url"], body=body, ctype=ctype))
            t2 = time.perf_counter()
            status = done["status"]
            while status in ("queued", "grading"):
                time.sleep(0.25)
                status = re.search(r'data-status="(\w+)"', c.get(done["status_url"]).decode()).group(1)
            t3 = time.perf_counter()
            r = {"ok": status == "graded", "start": t1 - t0, "upload": t2 - t1, "grade": t3 - t2, "total": t3 - t0}
        except Exception as exc:  # 오류도 결과로 기록
            r["error"] = f"{type(exc).__name__}: {exc}"
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker, args=(c,)) for c in clients]
    wall = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - wall

    ok = [r for r in results if r["ok"]]
    print(f"\n동시 제출 {N}건 · 성공 {len(ok)} · 실패 {N - len(ok)} · 전체 {wall:.1f}초")
    for key, label in (("start", "업로드 티켓 발급"), ("upload", "파일 업로드(약 2MB)"), ("grade", "업로드 후 채점 완료까지"),
                       ("total", "시작~채점 완료")):
        vals = [r[key] for r in ok]
        if vals:
            print(f"  {label:<20} 중앙값 {statistics.median(vals):6.2f}초 · p95 {pct(vals, 95):6.2f}초 · 최대 {max(vals):6.2f}초")
    for r in results:
        if not r["ok"]:
            print("  오류:", r.get("error"))


if __name__ == "__main__":
    main()
