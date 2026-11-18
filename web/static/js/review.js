// 검토 화면 단축키 (J 다음 · K 이전 · A 적합 · R 부적합) 와 사유 템플릿
(function () {
  "use strict";
  document.addEventListener("keydown", (e) => {
    const t = e.target;
    if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.isContentEditable)) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const key = e.key.toLowerCase();
    const link = document.querySelector(`[data-shortcut="${key}"]`);
    if (link) { window.location.href = link.href; return; }
    const radio = document.querySelector(`[data-shortcut-check="${key}"]`);
    if (radio) { radio.checked = true; radio.dispatchEvent(new Event("change", { bubbles: true })); }
  });
  document.querySelectorAll("[data-reason]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const note = document.querySelector("#propose-form textarea[name=note]");
      if (note) { note.value = chip.dataset.reason; note.focus(); }
    });
  });
})();
