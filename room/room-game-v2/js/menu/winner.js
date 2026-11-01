/* Виджет «Лучший игрок за всё время».
   Данные: API.getTopWinner() → { nick, score } или null. Обновляется при каждом возврате в меню. */
async function refreshWinner() {
  let w = null;
  try { w = await API.getTopWinner(); } catch (e) { /* нет связи — покажем прочерк */ }
  $("wWinNick").textContent = w && w.nick ? w.nick : "—";
  $("wWinScore").textContent = w && w.nick ? `${w.score} очков` : "Пока никто не играл";
}
document.addEventListener("screen:show", e => { if (e.detail === "s-menu") refreshWinner(); });
refreshWinner();
