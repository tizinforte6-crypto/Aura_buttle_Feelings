/* Титульный экран: создание, подключение, админ-панель */
let createdCode = null;

$("btnCreate").onclick = async () => {
  const n = $("hostNick").value.trim();
  if (!n) { $("hostNick").focus(); return; }
  createdCode = rand();
  await API.createRoom(createdCode);
  await API.joinRoom(createdCode, n);
  $("newCode").textContent = createdCode;
  $("codeBox").classList.remove("hidden");
  $("btnEnterOwn").classList.remove("hidden");
};
$("btnEnterOwn").onclick = () => enter(createdCode, false);

$("btnJoin").onclick = async () => {
  const c = $("joinCode").value.trim(), n = $("joinNick").value.trim();
  if (!c || !n) { $("joinErr").textContent = "Введите номер и ник"; return; }
  const r = await API.joinRoom(c, n);
  if (!r.ok) { $("joinErr").textContent = r.error; return; }
  $("joinErr").textContent = "";
  enter(c, false);
};

$("adm").onclick = () => $("admPanel").classList.toggle("hidden");
$("btnAdmin").onclick = async () => {
  const c = "TEST";
  if (CFG.USE_MOCK && !DB.rooms[c]) await API.createRoom(c);
  if (CFG.USE_MOCK && !DB.rooms[c].players.length) await API.joinRoom(c, "Админ");
  enter(c, true);
};
