/* Виджет «Сейчас»: время и дата */
function updClock() {
  const d = new Date();
  $("wClock").textContent = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  $("wDate").textContent = d.toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long" });
}
updClock();
setInterval(updClock, 15000);
