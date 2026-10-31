/* Раунд: таймер, очки, субтитры, «Чувство», шкала, победитель */
$("btnStart").onclick = async () => {
  await API.startRound(S.code);
  clearTimers();
  S = { ...S, playing: true, scores: {}, feel: {}, sub: {}, left: CFG.ROUND_SEC };
  S.players.forEach(p => S.scores[p.id] = 0);
  $("btnStart").classList.add("hidden");
  $("btnAddBot").classList.add("hidden");
  $("hint").textContent = "";
  $("gamePanel").classList.remove("hidden");
  $("result").classList.add("hidden");
  renderPlayers();
  tick(); pullScores(); pullFeel(); pullSub();
  S.timers.push(
    setInterval(tick, 1000),
    setInterval(pullScores, CFG.SCORE_MS),
    setInterval(pullFeel, CFG.FEEL_MS),
    setInterval(pullSub, CFG.SUB_MS)
  );
};

function tick() {
  if (S.left < 0) return;
  $("timer").textContent = Math.floor(S.left / 60) + ":" + String(S.left % 60).padStart(2, "0");
  if (S.left-- === 0) endRound();
}

async function pullSub() {
  S.sub = await API.getSubtitles(S.code);
  S.players.forEach(p => { const e = $("sub-" + p.id); if (e) e.textContent = S.sub[p.id] || ""; });
}
async function pullFeel() {
  S.feel = await API.getFeelings(S.code);
  S.players.forEach(p => { const e = $("fl-" + p.id); if (e) e.textContent = S.feel[p.id] || "—"; });
}
async function pullScores() {
  S.scores = await API.getScores(S.code);
  S.players.forEach(p => { const e = $("sc-" + p.id); if (e) e.textContent = S.scores[p.id] || 0; });
  drawBar();
}

function drawBar() {
  const tot = S.players.reduce((a, p) => a + (S.scores[p.id] || 0), 0);
  $("bar").innerHTML = S.players.map((p, i) =>
    `<div style="width:${tot ? (S.scores[p.id] || 0) / tot * 100 : 100 / S.players.length}%;background:${COLORS[i % 8]}"></div>`).join("");
  $("legend").innerHTML = S.players.map((p, i) =>
    `<span style="color:${COLORS[i % 8]}">●</span> ${esc(p.nick)}: ${S.scores[p.id] || 0}`).join(" &nbsp; ");
  const top = [...S.players].sort((a, b) => (S.scores[b.id] || 0) - (S.scores[a.id] || 0))[0];
  $("leader").textContent = top && tot ? top.nick : "—";
}

async function endRound() {
  clearTimers();
  await pullScores();
  await API.finishRound(S.code, S.scores);
  const win = [...S.players].sort((a, b) => (S.scores[b.id] || 0) - (S.scores[a.id] || 0))[0];
  S.playing = false;
  $("gamePanel").classList.add("hidden");
  S.sub = {}; S.scores = {}; S.feel = {};
  renderPlayers();
  $("winNick").textContent = win ? "🏆 " + win.nick : "—";
  $("winScore").textContent = "";
  $("result").classList.remove("hidden");
  $("btnPlay").classList.remove("hidden");
}

$("btnPlay").onclick = () => { resetUI(); lobbyLoop(); };
