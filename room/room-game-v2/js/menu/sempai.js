/* Секретная картинка: появляется в случайном месте экрана и плавно исчезает. */
(() => {
  const trigger = $("sempaiTrigger");
  const pop = $("sempaiPop");
  if (!trigger || !pop) return;
  let hideTimer = null;
  function showPop() {
    Sfx.pop()
    const margin = 14;
    const w = Math.min(230, Math.floor(window.innerWidth * .42));
    const h = w * (pop.querySelector("img").naturalHeight / pop.querySelector("img").naturalWidth || 1);
    const maxX = Math.max(margin, window.innerWidth - w - margin);
    const maxY = Math.max(margin, window.innerHeight - h - margin);
    pop.style.width = w + "px";
    pop.style.left = (margin + Math.random() * (maxX - margin)) + "px";
    pop.style.top = (margin + Math.random() * (maxY - margin)) + "px";
    pop.classList.remove("hidden");
    pop.style.animation = "none";
    void pop.offsetWidth;
    pop.style.animation = "";
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => pop.classList.add("hidden"), 3900);
  }
  trigger.addEventListener("click", showPop);
  trigger.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showPop(); }
  });
})();
