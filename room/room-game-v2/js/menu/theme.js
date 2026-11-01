(() => {
  const KEY = "room-game-theme";
  const apply = theme => {
    document.documentElement.dataset.theme = theme;
    $("btnTheme").textContent = theme === "dark" ? "☀️ Светлая тема" : "🌙 Тёмная тема";
  };
  let saved = "light";
  try { saved = localStorage.getItem(KEY) || "light"; } catch (e) {}
  apply(saved);
  $("btnTheme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    apply(next);
    try { localStorage.setItem(KEY, next); } catch (e) {}
  });
})();
