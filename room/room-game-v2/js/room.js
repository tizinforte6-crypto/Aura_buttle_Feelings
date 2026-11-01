/* Лобби и отрисовка игроков */
function enter(code, admin, me, host) {
  S = { ...S, code, admin, me, host: !!host, playing: false, mySub: "", prevCount: 0 };
  $("rCode").textContent = code;
  $("lobbyCode").textContent = code;
  Tts.warmup();                // заранее грузим голос Piper
  show("s-room");
  resetUI();
  lobbyLoop();
  const started = !CFG.USE_MOCK && Session.gameStarted();
  if (started) {
    document.dispatchEvent(new CustomEvent("live:started", { detail: started }));
  }
}

function resetUI() {
  clearTimers(); Tts.stop(); S.playing = false;
  ["gamePanel", "result", "btnPlay"].forEach(i => $(i).classList.add("hidden"));
  $("btnStart").classList.remove("hidden");
  $("codeCard").classList.remove("hidden");     // код комнаты виден до начала раунда
  $("adminTools").classList.toggle("hidden", !S.admin);
  $("adminToolsHint").textContent = "";
  renderPlayers();
}

async function lobbyLoop() {
  clearTimers();
  await refreshPlayers();
  S.timers.push(setInterval(() => { if (!S.playing) refreshPlayers(); }, CFG.LOBBY_MS));
}

async function refreshPlayers() {
  S.players = await API.getPlayers(S.code);
  const n = S.players.length, can = n > 0;
  $("rInfo").textContent = `Игроков: ${n}` + (S.admin ? " · админ-режим" : "");
  $("btnStart").disabled = !can;
  $("hint").textContent = "";
  // состояние ожидания в карточке кода
  $("waitText").textContent = n === 1
    ? "Можно начинать одному — или подождать друзей"
    : "Можно начинать, не дожидаясь остальных";
  $("waitDots").classList.toggle("hidden", can);
  $("waitText").parentElement.classList.toggle("ready", can);
  if (n > (S.prevCount || 0) && S.prevCount) Sfx.pop();     // подключился новый игрок
  S.prevCount = n;
  renderPlayers();
}

function renderPlayers() {
  $("players").innerHTML = S.players.map((p, i) => {
    const src = API.getVideoSrc(p.id);
    const v = src ? `<img id="cam-${p.id}" class="cam" src="${src}" alt="Камера игрока ${esc(p.nick)}">` : "Ожидаем изображение с камеры";
    const mine = p.id === S.me;
    // субтитры показываем только в карточке самого игрока
    const subBlock = mine
      ? `<div class="sub" id="sub-me">${esc(S.mySub)}</div>`
      : `<div class="sub-locked">личные фразы видны только их автору</div>`;
    const game = S.playing ? `
      ${subBlock}
      <div class="player-stat"><span>Баллы</span><strong class="score" id="sc-${p.id}">${S.scores[p.id] != null ? S.scores[p.id] : (CFG.USE_MOCK ? 0 : "—")}</strong></div>
      <div class="round-feeling">
        <span>Покажи эмоцию:</span>
        <strong id="fl-${p.id}">${esc(S.feel[p.id] || S.currentFeeling || "Ждём…")}</strong>
      </div>` : "";
    return `<div class="pl${p.id === S.me ? " me" : ""}"><div class="vid">${v}</div>
      <div class="pid"><span style="color:${COLORS[i % 8]}">●</span> ${esc(p.nick)}${p.id === S.me ? ' <span class="you">вы</span>' : ""} <small>#${p.id}</small></div>
      <div class="pn">${game}</div></div>`;
  }).join("");
}

$("btnCopy").onclick = async () => {
  try { await navigator.clipboard.writeText(S.code); $("btnCopy").textContent = "Скопировано"; }
  catch (e) { $("btnCopy").textContent = "Код: " + S.code; }
  setTimeout(() => { $("btnCopy").textContent = "Скопировать код"; }, 1800);
};
$("btnAddBot").onclick = async () => {
  if (!S.admin) return;
  const result = await API.addTestPlayer(S.code);
  $("adminToolsHint").textContent = result.ok ? "Тестовый игрок добавлен" : (result.error || "Не удалось добавить игрока");
  await refreshPlayers();
};
$("btnLeave").onclick = () => { clearTimers(); Tts.stop(); Session.leave(); S.playing = false; show("s-menu"); };
