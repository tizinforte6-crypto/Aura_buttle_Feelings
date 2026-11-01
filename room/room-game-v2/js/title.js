/* Экран входа: первый игрок создаёт комнату введённым кодом, остальные входят в неё. */
$("btnJoin").onclick = async () => {
  Tts.prime();
  const code = $("joinCode").value.trim();
  const nickname = $("joinNick").value.trim();
  if (!/^\d{6}$/.test(code)) {
    $("joinErr").textContent = "Введите код из 6 цифр";
    $("joinCode").focus();
    return;
  }
  if (!nickname) {
    $("joinErr").textContent = "Введите имя";
    $("joinNick").focus();
    return;
  }

  $("joinErr").textContent = "";
  $("btnJoin").disabled = true;
  try {
    const joined = await API.joinRoom(code, nickname);
    if (!joined.ok) {
      $("joinErr").textContent = joined.error || "Не удалось войти в комнату";
      return;
    }
    enter(code, false, joined.playerId);
  } catch (error) {
    console.error("[room] Не удалось войти:", error);
    $("joinErr").textContent = "Нет связи с сервером";
  } finally {
    $("btnJoin").disabled = false;
  }
};
