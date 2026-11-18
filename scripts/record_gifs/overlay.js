// GIF 녹화용 오버레이 — 테스트 케이스 캡션 바 · 클릭 하이라이트 · PASS/BLOCKED 도장
// 앱 코드에는 포함되지 않고, 녹화 스크립트가 Playwright init script 로만 주입한다
(() => {
  const KEY = "__demo_overlay";
  const state = () => {
    try { return JSON.parse(sessionStorage.getItem(KEY) || "{}"); } catch (_) { return {}; }
  };
  const save = (s) => { try { sessionStorage.setItem(KEY, JSON.stringify(s)); } catch (_) {} };

  const css = `
  #demo-cap{position:fixed;left:0;right:0;top:0;z-index:2147483646;display:flex;align-items:center;gap:14px;
    padding:12px 22px;background:rgba(17,24,39,.92);color:#fff;font:600 15px/1.35 'Pretendard Variable',system-ui,sans-serif;
    box-shadow:0 6px 24px rgba(0,0,0,.25)}
  #demo-cap .tc{flex:none;padding:4px 10px;border-radius:8px;background:#2f63ea;font:700 13px ui-monospace,monospace;letter-spacing:.02em}
  #demo-cap .tag{flex:none;margin-left:auto;padding:3px 10px;border-radius:999px;background:rgba(255,255,255,.14);font-size:12px}
  #demo-cap .exp{display:block;font-weight:500;font-size:13px;color:#c9d8fb}
  body{padding-top:var(--demo-pad,0)!important}
  aside.sticky{top:var(--demo-pad,0)!important;height:calc(100vh - var(--demo-pad,0px))!important}
  #demo-stamp{position:fixed;right:28px;bottom:28px;z-index:2147483647;display:flex;align-items:center;gap:10px;
    padding:14px 22px;border-radius:16px;color:#fff;font:800 20px/1 'Pretendard Variable',system-ui,sans-serif;
    box-shadow:0 18px 40px -12px rgba(0,0,0,.45);transform:scale(.6);opacity:0;transition:all .35s cubic-bezier(.2,1.4,.4,1)}
  #demo-stamp.show{transform:scale(1);opacity:1}
  #demo-stamp small{display:block;font:600 13px/1.3 'Pretendard Variable',system-ui,sans-serif;opacity:.9;margin-top:4px}
  .demo-ripple{position:fixed;z-index:2147483647;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;
    border:3px solid #2f63ea;background:rgba(47,99,234,.18);pointer-events:none;animation:demo-r .6s ease-out forwards}
  @keyframes demo-r{from{transform:scale(.4);opacity:1}to{transform:scale(1.8);opacity:0}}
  `;

  function render() {
    const s = state();
    let cap = document.getElementById("demo-cap");
    if (!s.tc) { if (cap) cap.remove(); document.documentElement.style.setProperty("--demo-pad", "0"); return; }
    if (!cap) {
      cap = document.createElement("div");
      cap.id = "demo-cap";
      document.body.appendChild(cap);
    }
    cap.innerHTML = "";
    const tc = document.createElement("span"); tc.className = "tc"; tc.textContent = s.tc;
    const text = document.createElement("span"); text.textContent = s.title;
    const exp = document.createElement("span"); exp.className = "exp"; exp.textContent = s.expected ? "기대 결과 · " + s.expected : "";
    text.appendChild(exp);
    cap.append(tc, text);
    if (s.tag) { const t = document.createElement("span"); t.className = "tag"; t.textContent = s.tag; cap.appendChild(t); }
    document.documentElement.style.setProperty("--demo-pad", cap.offsetHeight + "px");
  }

  function stamp(kind, text) {
    let el = document.getElementById("demo-stamp");
    if (!el) { el = document.createElement("div"); el.id = "demo-stamp"; document.body.appendChild(el); }
    el.style.background = kind === "blocked" ? "#0f9f6e" : "#16a34a";
    el.innerHTML = "";
    const big = document.createElement("span");
    big.textContent = kind === "blocked" ? "🛡 BLOCKED" : "✔ PASS";
    const wrap = document.createElement("span");
    wrap.appendChild(big);
    if (text) { const sm = document.createElement("small"); sm.textContent = text; wrap.appendChild(sm); }
    el.appendChild(wrap);
    requestAnimationFrame(() => el.classList.add("show"));
  }

  window.__demo = {
    caption(tc, title, expected, tag) { save({ tc, title, expected, tag }); render(); },
    clear() { save({}); render(); const st = document.getElementById("demo-stamp"); if (st) st.remove(); },
    pass(text) { stamp("pass", text); },
    blocked(text) { stamp("blocked", text); },
  };

  const boot = () => {
    if (!document.getElementById("demo-style")) {
      const st = document.createElement("style"); st.id = "demo-style"; st.textContent = css;
      document.head.appendChild(st);
    }
    render();
    document.addEventListener("mousedown", (e) => {
      const r = document.createElement("div"); r.className = "demo-ripple";
      r.style.left = e.clientX + "px"; r.style.top = e.clientY + "px";
      document.body.appendChild(r); setTimeout(() => r.remove(), 650);
    }, true);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
