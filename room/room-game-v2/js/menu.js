/* Главное меню: навигация, GitHub, виджеты (часы, настроение) */

// Переходы между экранами: любая кнопка с data-go="id-экрана"
document.querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => show(b.dataset.go)));

// Ссылка на GitHub берётся из CFG.GITHUB_URL (js/config.js)
const gh = $("btnGithub");
if (CFG.GITHUB_URL) gh.href = CFG.GITHUB_URL;
else gh.addEventListener("click", e => { e.preventDefault(); $("ghHint").textContent = "Ссылка на GitHub пока не добавлена (js/config.js → GITHUB_URL)"; });

// Виджет: часы и дата
function updClock() {
  const d = new Date();
  $("wClock").textContent = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  $("wDate").textContent = d.toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long" });
}
updClock(); setInterval(updClock, 15000);

// Виджет: настроение дня
const MOODS = ["🌸 Нежность", "✨ Азарт", "🍓 Сладость", "☁️ Спокойствие", "💗 Влюблённость", "🎀 Игривость", "🌷 Мечтательность"];
$("wMoodBtn").onclick = () => { $("wMood").textContent = MOODS[Math.random() * MOODS.length | 0]; };
$("wMood").textContent = MOODS[new Date().getDate() % MOODS.length];
