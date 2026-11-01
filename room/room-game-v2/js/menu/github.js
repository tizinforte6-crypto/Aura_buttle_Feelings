/* Кнопка GitHub. Ссылка берётся из CFG.GITHUB_URL (js/config.js) */
const ghBtn = $("btnGithub");
if (CFG.GITHUB_URL) ghBtn.href = CFG.GITHUB_URL;
else ghBtn.addEventListener("click", e => {
  e.preventDefault();
  $("ghHint").textContent = "Ссылка на GitHub пока не добавлена (js/config.js → GITHUB_URL)";
});
