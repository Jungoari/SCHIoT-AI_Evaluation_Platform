// 처음 로그인 사용 안내: 이전/다음 단계 넘김, 키보드(←/→/Esc), 끝내면 서버에 기록하고 닫기
(function () {
  "use strict";
  const box = document.getElementById("tutorial");
  if (!box) return;

  const steps = [...box.querySelectorAll("[data-tutorial-step]")];
  const dots = [...box.querySelectorAll("[data-tutorial-dot]")];
  const now = box.querySelector("[data-tutorial-now]");
  const prev = box.querySelector("[data-tutorial-prev]");
  const next = box.querySelector("[data-tutorial-next]");
  const finish = box.querySelector("[data-tutorial-finish]");
  const form = box.querySelector("[data-tutorial-form]");
  const before = document.activeElement;
  let i = 0;

  function show(n) {
    i = Math.max(0, Math.min(steps.length - 1, n));
    steps.forEach((s, k) => s.classList.toggle("hidden", k !== i));
    dots.forEach((d, k) => {
      d.classList.toggle("bg-brand-600", k <= i);
      d.classList.toggle("bg-line", k > i);
    });
    now.textContent = String(i + 1);
    prev.classList.toggle("hidden", i === 0);
    const last = i === steps.length - 1;
    next.classList.toggle("hidden", last);
    finish.classList.toggle("hidden", !last);
    // 화면 낭독기가 지금 단계 제목을 읽도록 대화상자 이름을 바꾼다
    const h = steps[i].querySelector("h2");
    h.id = "tutorial-title";
    steps.forEach((s, k) => { if (k !== i) s.querySelector("h2").removeAttribute("id"); });
    (last ? finish : next).focus();
  }

  // 완료·건너뛰기: 페이지를 새로 읽지 않고 기록만 남긴 뒤 닫는다
  function close() {
    fetch(form.action, { method: "POST", body: new FormData(form), headers: { "X-Requested-With": "fetch" } })
      .catch(() => {}); // 기록 실패해도 사용은 막지 않는다 (다음 로그인 때 다시 표시될 뿐)
    box.remove();
    document.body.classList.remove("overflow-hidden");
    if (before && before.focus) before.focus();
  }

  prev.addEventListener("click", () => show(i - 1));
  next.addEventListener("click", () => show(i + 1));
  form.addEventListener("submit", (e) => { e.preventDefault(); close(); });
  // 대화상자가 열려 있는 동안은 포커스가 어디 있든 키 입력을 받는다
  function onKey(e) {
    if (!document.body.contains(box)) { document.removeEventListener("keydown", onKey); return; }
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowRight" && i < steps.length - 1) show(i + 1);
    else if (e.key === "ArrowLeft") show(i - 1);
    else if (e.key === "Tab") {
      // 포커스가 대화상자 밖으로 나가지 않게 가둔다
      const f = [...box.querySelectorAll("button:not(.hidden)")];
      const first = f[0], end = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); end.focus(); }
      else if (!e.shiftKey && document.activeElement === end) { e.preventDefault(); first.focus(); }
      else if (!box.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
    }
  }
  document.addEventListener("keydown", onKey);

  document.body.classList.add("overflow-hidden"); // 뒤 화면 스크롤 막기
  show(0);
})();
