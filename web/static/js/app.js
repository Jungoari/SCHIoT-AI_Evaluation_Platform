// 공통 UI 스크립트 (인라인 스크립트 없이 동작 — CSP script-src 'self' 유지)

// 성공 메시지 자동 숨김
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-autodismiss]").forEach((el) => {
    setTimeout(() => {
      el.style.transition = "opacity .4s";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 400);
    }, 5000);
  });

  // 클릭 시 텍스트 복사 (참여 코드 등)
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(btn.dataset.copy);
        const original = btn.textContent;
        btn.textContent = "복사됨";
        setTimeout(() => (btn.textContent = original), 1500);
      } catch (_) {
        /* 클립보드 권한이 없으면 무시 */
      }
    });
  });
});
