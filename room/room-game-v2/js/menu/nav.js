/* Навигация между экранами с плавными переходами.
   show("s-play") — старый экран тускнеет и уходит, новый появляется (CSS: css/transitions.css).
   Любая кнопка с data-go="id-экрана" работает как переход. */
const SCREENS = ["s-menu", "s-play", "s-info", "s-room", "s-leaderboard"];
const LEAVE_MS = 320;
let navToken = 0;

const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const currentScreen = () => SCREENS.find(id => !$(id).classList.contains("hidden"));

// показать экран: элементы .reveal появляются по очереди
function enterScreen(el) {
  el.classList.remove("hidden", "leaving");
  el.querySelectorAll(".reveal").forEach((r, i) => r.style.setProperty("--i", i));
  el.classList.add("entering");
  setTimeout(() => el.classList.remove("entering"), 1200);
}

function show(id) {
  const cur = currentScreen(), next = $(id);
  if (cur === id) return;
  const token = ++navToken;

  const finish = () => {
    if (token !== navToken) return;               // был более новый переход
    SCREENS.forEach(x => { if (x !== id) $(x).classList.add("hidden"); $(x).classList.remove("leaving"); });
    enterScreen(next);
    document.dispatchEvent(new CustomEvent("screen:show", { detail: id }));
  };

  if (!cur || reduceMotion()) return finish();
  Sfx.whoosh();                                   // шорох перехода
  $(cur).classList.add("leaving");                // старое тускнеет и уходит
  setTimeout(finish, LEAVE_MS);                   // затем появляется новое
}

document.querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => show(b.dataset.go)));
enterScreen($("s-menu"));                         // красивое появление меню при загрузке
