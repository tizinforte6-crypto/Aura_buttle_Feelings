/* Раунд: таймер, очки, субтитры, «Чувство», шкала, победитель */
let startingRound = false;
async function beginRound(requestStart, details = {}) {
  if (S.playing || startingRound) return;
  startingRound = true;
  try {
    Tts.prime();
    if (requestStart) await API.startRound(S.code);
    clearTimers();
    S = { ...S, playing: true, scores: {}, feel: {}, currentFeeling: null, mySub: "",
          left: (!CFG.USE_MOCK && Session.isLive())
            ? Math.max(1, Math.ceil(details.remaining ?? Session.liveLeft()))
            : CFG.ROUND_SEC };
    S.players.forEach(p => S.scores[p.id] = 0);
    $("btnStart").classList.add("hidden");
    $("btnAddBot").classList.add("hidden");
    $("hint").textContent = "";
    $("mySub").textContent = "";
    $("gamePanel").classList.remove("hidden");
    $("codeCard").classList.add("hidden");
    Sfx.start();
    $("result").classList.add("hidden");
    renderPlayers();
    tick(); pullScores(); pullFeel(); pullSub();
    S.timers.push(
      setInterval(tick, 1000),
      setInterval(pullScores, CFG.SCORE_MS),
      setInterval(pullFeel, CFG.FEEL_MS),
      setInterval(pullSub, CFG.SUB_MS)
    );
  } catch (error) {
    console.error("[game] Не удалось начать раунд:", error);
    $("hint").textContent = "Не удалось начать игру. Проверьте соединение и попробуйте ещё раз.";
  } finally {
    startingRound = false;
  }
}

$("btnStart").onclick = () => beginRound(true);
document.addEventListener("live:started", event => {
  if (S.code) beginRound(false, event.detail || {});
});

function tick() {
  if (S.left < 0) return;
  $("timer").textContent = Math.floor(S.left / 60) + ":" + String(S.left % 60).padStart(2, "0");
  if (S.left-- === 0 && (CFG.USE_MOCK || !Session.isLive())) endRound();
}

// Субтитры привязаны к конкретному игроку: запрашиваем только свои и показываем только у себя
async function pullSub() {
  if (!S.me) return;
  const me = S.me;
  const text = await API.getSubtitles(S.code, me);
  if (!S.playing || S.me !== me) return;   // раунд уже закончился
  if (text === S.mySub) return;
  S.mySub = text || "";
  [$("sub-me"), $("mySub")].forEach(e => {
    if (!e) return;
    e.textContent = S.mySub;
    e.classList.remove("fade"); void e.offsetWidth; e.classList.add("fade");
  });
  Tts.speak(S.mySub);   // текст изменился (файл / БД / API) — озвучиваем новый
}
async function pullFeel() {
  const shared = await API.getFeelings(S.code);
  // На всех карточках показываем одно и то же чувство комнаты.
  const common = Object.values(shared || {})[0];
  if (common) showFeeling(common);
}
function showFeeling(feeling) {
  S.currentFeeling = feeling;
  S.feel = Object.fromEntries(S.players.map(p => [p.id, feeling]));
  S.players.forEach(p => {
    const e = $("fl-" + p.id);
    if (e) e.textContent = feeling;
  });
}
document.addEventListener("live:emotion", event => {
  if (event.detail) showFeeling(event.detail);
});
async function pullScores() {
  S.scores = await API.getScores(S.code);
  S.players.forEach(p => { const e = $("sc-" + p.id); if (e) { const v = S.scores[p.id]; e.textContent = v != null ? v : (CFG.USE_MOCK ? 0 : "—"); } });
  drawBar();
}

function drawBar() {
  const known = S.players.filter(p => S.scores[p.id] != null);
  if (!known.length) {
    $("bar").innerHTML = "";
    $("legend").innerHTML = "";
    $("leader").textContent = "—";
    return;
  }
  const tot = S.players.reduce((a, p) => a + (S.scores[p.id] || 0), 0);
  $("bar").innerHTML = S.players.map((p, i) =>
    `<div style="width:${tot ? (S.scores[p.id] || 0) / tot * 100 : 100 / S.players.length}%;background:${COLORS[i % 8]}"></div>`).join("");
  $("legend").innerHTML = S.players.map((p, i) =>
    `<span style="color:${COLORS[i % 8]}">●</span> ${esc(p.nick)}: ${S.scores[p.id] || 0}`).join(" &nbsp; ");
  const top = [...S.players].sort((a, b) => (S.scores[b.id] || 0) - (S.scores[a.id] || 0))[0];
  $("leader").textContent = top && known.length ? top.nick : "—";
}

async function endRound() {
  if (!S.playing) return;
  S.playing = false;
  clearTimers(); Tts.stop(); Sfx.end();
  await pullScores();
  const standings = await API.finishRound(S.code, S.scores);
  const win = standings && standings.winner
    ? { nick: standings.winner }
    : [...S.players].sort((a, b) => (S.scores[b.id] || 0) - (S.scores[a.id] || 0))[0];
  const winRoundScore = standings && standings.winnerScore != null
    ? standings.winnerScore
    : (win && win.id ? (S.scores[win.id] || 0) : 0);
  S.playing = false;
  $("gamePanel").classList.add("hidden");
  S.mySub = ""; S.scores = {}; S.feel = {};
  renderPlayers();
  $("winNick").innerHTML = win
    ? `🏆 ${esc(win.nick)}${standings.rank ? ` <span class="winner-rank">№${standings.rank} в общем рейтинге</span>` : ""}`
    : "—";
  $("winScore").textContent = win ? `${winRoundScore} очков за раунд` : "";
  Sfx.winner();
  $("result").classList.remove("hidden");
  $("btnPlay").classList.remove("hidden");
}

$("btnPlay").onclick = () => { resetUI(); lobbyLoop(); };

document.addEventListener("live:result", () => { if (S.playing) endRound(); });
