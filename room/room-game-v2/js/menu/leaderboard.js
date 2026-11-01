async function refreshLeaderboard() {
  const body = $("leaderboardBody");
  body.innerHTML = '<tr><td colspan="3" class="mut">Загрузка…</td></tr>';
  try {
    const rows = await API.getLeaderboard();
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="3" class="mut">Пока нет результатов</td></tr>';
      return;
    }
    body.innerHTML = rows.map((r, i) => `<tr class="${i === 0 ? "leader-first" : ""}">
      <td>${i + 1}</td><td>${esc(r.nick)}</td><td>${Number(r.score || 0).toLocaleString("ru-RU")}</td>
    </tr>`).join("");
  } catch (e) {
    body.innerHTML = '<tr><td colspan="3" class="mut">Не удалось загрузить рейтинг</td></tr>';
  }
}
$("openLeaderboard").addEventListener("click", () => {
  show("s-leaderboard");
  refreshLeaderboard();
});
document.addEventListener("screen:show", e => {
  if (e.detail === "s-leaderboard") refreshLeaderboard();
});
