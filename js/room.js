/* Лобби и отрисовка игроков */
function enter(code, admin) {
  S = { ...S, code, admin, playing: false };
  $("rCode").textContent = code;
  show("s-room");
  resetUI();
  lobbyLoop();
}

function resetUI() {
  clearTimers(); S.playing = false;
  ["gamePanel", "result", "btnPlay"].forEach(i => $(i).classList.add("hidden"));
  $("btnStart").classList.remove("hidden");
  $("btnAddBot").classList.toggle("hidden", !S.admin);
  renderPlayers();
}

async function lobbyLoop() {
  clearTimers();
  await refreshPlayers();
  S.timers.push(setInterval(() => { if (!S.playing) refreshPlayers(); }, CFG.LOBBY_MS));
}

async function refreshPlayers() {
  S.players = await API.getPlayers(S.code);
  const n = S.players.length, can = S.admin || n >= CFG.MIN_PLAYERS;
  $("rInfo").textContent = `Игроков: ${n}` + (S.admin ? " · админ-режим" : "");
  $("btnStart").disabled = !can;
  $("hint").textContent = can ? "" : `Для старта нужно минимум ${CFG.MIN_PLAYERS} игрока…`;
  renderPlayers();
}

function renderPlayers() {
  $("players").innerHTML = S.players.map((p, i) => {
    const src = API.getVideoSrc(p.id);
    const v = src ? `<video src="${src}" autoplay muted playsinline></video>` : "Здесь будет веб-камера";
    const game = S.playing ? `
      <div class="sub" id="sub-${p.id}">${esc(S.sub[p.id] || "")}</div>
      <div>Очки: <span class="score" id="sc-${p.id}">${S.scores[p.id] || 0}</span></div>
      <div>Чувство: <b id="fl-${p.id}">${esc(S.feel[p.id] || "—")}</b></div>` : "";
    return `<div class="pl"><div class="vid">${v}</div>
      <div class="pid"><span style="color:${COLORS[i % 8]}">●</span> ${esc(p.nick)} <small>#${p.id}</small></div>
      <div class="pn">${game}</div></div>`;
  }).join("");
}

$("btnAddBot").onclick = async () => { await API.joinRoom(S.code, "Бот" + (S.players.length + 1)); refreshPlayers(); };
$("btnLeave").onclick = () => { clearTimers(); show("s-title"); };
