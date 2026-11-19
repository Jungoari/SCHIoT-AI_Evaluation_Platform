// 제출 화면 스크립트
//  1) 파일 선택(클릭·드래그)  2) 브라우저 사전 검사(CSV 헤더·행 수·ID·레이블)
//  3) 파일 지문(SHA-256) 계산  4) 업로드 티켓 발급(시작 시각 서버 기록)
//  5) 진행률 표시 업로드        6) 채점 상태 자동 갱신(HTMX)
// 사전 검사는 편의 기능일 뿐이며, 서버에서 같은 검사를 반드시 다시 한다

(function () {
  "use strict";

  const form = document.getElementById("submit-form");
  if (!form) return;
  const schema = JSON.parse(document.getElementById("submit-schema").textContent);
  const files = { csv: null, notebook: null, weights: null };
  const $ = (id) => document.getElementById(id);
  const precheck = $("precheck");
  const progress = $("progress");
  const result = $("submit-result");
  const button = $("submit-btn");

  function csrfToken() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function fmtSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1024 / 1024).toFixed(1) + " MB";
  }

  // ---------------- 파일 선택 ----------------
  form.querySelectorAll(".dropzone").forEach((zone) => {
    const kind = zone.dataset.kind;
    const input = zone.querySelector("input[type=file]");
    const nameEl = zone.querySelector(".file-name");
    const set = (file) => {
      files[kind] = file || null;
      if (file) {
        nameEl.textContent = `${file.name} · ${fmtSize(file.size)}`;
        nameEl.classList.add("text-ink", "font-semibold");
        zone.classList.add("border-brand-500", "bg-brand-50");
        zone.classList.remove("border-line");
      }
      precheck.classList.add("hidden");
    };
    input.addEventListener("change", () => set(input.files[0]));
    zone.addEventListener("dragover", (e) => {
      e.preventDefault();
      zone.classList.add("border-brand-500");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("border-brand-500"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      if (e.dataTransfer.files.length) {
        const dt = new DataTransfer();
        dt.items.add(e.dataTransfer.files[0]);
        input.files = dt.files;
        set(e.dataTransfer.files[0]);
      }
    });
  });

  // ---------------- CSV 사전 검사 ----------------
  function parseCsvLine(line) {
    const out = [];
    let cur = "", q = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (q) {
        if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; }
        else if (c === '"') q = false;
        else cur += c;
      } else if (c === '"') q = true;
      else if (c === ",") { out.push(cur); cur = ""; }
      else cur += c;
    }
    out.push(cur);
    return out;
  }

  async function checkCsv(file) {
    const errors = [];
    if (file.size > 20 * 1024 * 1024) return errors; // 큰 파일은 서버 검사에 맡김
    let text = await file.text();
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    const lines = text.split(/\r?\n/).filter((l) => l.length > 0);
    if (!lines.length) return ["빈 CSV 파일입니다"];
    const header = parseCsvLine(lines[0]).map((h) => h.trim());
    const idIdx = header.indexOf(schema.id_column);
    const tIdx = header.indexOf(schema.target_column);
    if (idIdx < 0 || tIdx < 0) {
      errors.push(`필요한 열이 없습니다 (필요: ${schema.id_column}, ${schema.target_column} / 현재: ${header.join(", ")})`);
      return errors;
    }
    const extra = header.filter((h) => h !== schema.id_column && h !== schema.target_column);
    if (extra.length) errors.push(`허용되지 않은 열: ${extra.slice(0, 5).join(", ")}`);
    const rows = lines.length - 1;
    if (rows !== schema.row_count) errors.push(`행 수가 맞지 않습니다: ${rows}행 / 필요 ${schema.row_count}행`);
    const seen = new Set(), dup = [], bad = [];
    const allowed = new Set(schema.allowed_labels || []);
    for (let i = 1; i < lines.length && bad.length < 5; i++) {
      const cells = parseCsvLine(lines[i]);
      const id = (cells[idIdx] || "").trim();
      const v = (cells[tIdx] || "").trim();
      if (seen.has(id)) dup.push(id);
      seen.add(id);
      if (v === "") bad.push(`${i + 1}행: 값이 비어 있음`);
      else if (schema.task_type === "classification" && !allowed.has(v)) bad.push(`${i + 1}행: '${v.slice(0, 20)}'은(는) 허용된 레이블이 아님`);
      else if (schema.task_type === "regression" && !isFinite(Number(v))) bad.push(`${i + 1}행: '${v.slice(0, 20)}'은(는) 숫자가 아님`);
    }
    if (dup.length) errors.push(`중복 ID: ${dup.slice(0, 5).join(", ")}`);
    return errors.concat(bad);
  }

  function showPrecheck(ok, items) {
    precheck.classList.remove("hidden");
    precheck.innerHTML = "";
    const title = document.createElement("p");
    title.className = "font-semibold " + (ok ? "text-emerald-700" : "text-rose-600");
    title.textContent = ok ? "✓ 사전 검사 통과" : "✕ 업로드 전에 수정이 필요합니다 (횟수 차감 없음)";
    precheck.appendChild(title);
    if (items.length) {
      const ul = document.createElement("ul");
      ul.className = "mt-2 space-y-1 text-ink-2";
      items.forEach((t) => {
        const li = document.createElement("li");
        li.textContent = "· " + t; // textContent → XSS 방지
        ul.appendChild(li);
      });
      precheck.appendChild(ul);
    }
  }

  // ---------------- 지문 계산 ----------------
  // 큰 파일은 4MB 조각 스트리밍 해시 (static/js/sha256.js)
  async function sha256(file, label) {
    return window.sha256File(file, (r) => setProgress(`파일 확인 중 · ${label}`, 1 + r * 4));
  }

  function setProgress(label, pct) {
    progress.classList.remove("hidden");
    $("progress-label").textContent = label;
    $("progress-pct").textContent = Math.round(pct) + "%";
    $("progress-bar").style.width = pct + "%";
  }

  function showError(msg) {
    result.innerHTML = "";
    const box = document.createElement("div");
    box.className = "rounded-2xl bg-rose-50 p-4 text-sm font-medium text-rose-600";
    box.textContent = msg;
    result.appendChild(box);
  }

  // 채점이 끝나면 위쪽 '남은 제출' 카드도 갱신
  document.body.addEventListener("htmx:afterSwap", (e) => {
    const box = document.getElementById("sub-status");
    if (!box || box.dataset.final !== "1" || box.dataset.remaining === undefined) return;
    const value = document.querySelector('[data-testid="quota"] .stat-value');
    if (value) {
      value.innerHTML = "";
      value.append(box.dataset.remaining);
      const sub = document.createElement("span");
      sub.className = "stat-sub";
      sub.textContent = "/" + box.dataset.limit;
      value.appendChild(sub);
    }
  });

  // ---------------- 제출 ----------------
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    result.innerHTML = "";
    const missing = [["csv", "예측 결과 CSV"], ["notebook", "소스코드 .ipynb"], ["weights", "모델 파라미터"]]
      .filter(([k]) => !files[k]).map(([, l]) => l);
    if (missing.length) {
      showPrecheck(false, ["필수 파일을 선택하세요: " + missing.join(", ")]);
      return;
    }
    for (const [k, label] of [["csv", "CSV"], ["notebook", "노트북"], ["weights", "가중치"]]) {
      if (files[k].size > schema.max_bytes[k]) {
        showPrecheck(false, [`${label} 파일이 너무 큽니다 (최대 ${fmtSize(schema.max_bytes[k])})`]);
        return;
      }
    }
    if (!files.notebook.name.toLowerCase().endsWith(".ipynb")) {
      showPrecheck(false, ["소스코드는 .ipynb 파일이어야 합니다"]);
      return;
    }
    const errors = await checkCsv(files.csv);
    if (errors.length) {
      showPrecheck(false, errors);
      return;
    }
    showPrecheck(true, []);

    button.disabled = true;
    try {
      setProgress("파일 확인 중", 3);
      const hashes = {
        csv: await sha256(files.csv, "CSV"),
        notebook: await sha256(files.notebook, "노트북"),
        weights: await sha256(files.weights, "가중치"),
      };
      setProgress("업로드 준비 중", 6);
      const startRes = await fetch(form.dataset.startUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
        body: JSON.stringify({
          hashes,
          sizes: { csv: files.csv.size, notebook: files.notebook.size, weights: files.weights.size },
        }),
      });
      const start = await startRes.json();
      if (!start.ok) throw new Error(start.error || "업로드를 시작할 수 없습니다");

      const fd = new FormData();
      fd.append("csv", files.csv);
      fd.append("notebook", files.notebook);
      fd.append("weights", files.weights);
      fd.append("comment", form.querySelector("[name=comment]").value || "");

      const done = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", start.upload_url);
        xhr.setRequestHeader("X-CSRFToken", csrfToken());
        xhr.upload.onprogress = (ev) => {
          if (ev.lengthComputable) setProgress("업로드 중", 6 + (ev.loaded / ev.total) * 94);
        };
        xhr.onload = () => {
          try { resolve(JSON.parse(xhr.responseText)); } catch (_) { reject(new Error("서버 응답을 해석할 수 없습니다")); }
        };
        xhr.onerror = () => reject(new Error("네트워크 오류로 업로드에 실패했습니다 (횟수 차감 없음)"));
        xhr.send(fd);
      });
      if (!done.ok) throw new Error(done.error);
      setProgress("업로드 완료", 100);

      // 채점 상태 자동 갱신
      const holder = document.createElement("div");
      holder.setAttribute("hx-get", done.status_url);
      holder.setAttribute("hx-trigger", "load");
      holder.setAttribute("hx-swap", "outerHTML");
      result.innerHTML = "";
      result.appendChild(holder);
      if (window.htmx) window.htmx.process(holder);
    } catch (err) {
      showError(err.message);
    } finally {
      button.disabled = false;
    }
  });
})();
