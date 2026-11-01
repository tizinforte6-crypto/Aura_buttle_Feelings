/* ============================================================
   ЗВУКИ ИНТЕРФЕЙСА — тихие и мягкие, синтезируются на лету (Web Audio), файлы не нужны.
   Sfx.click()   — щелчок кнопки          Sfx.whoosh() — шорох перехода между экранами
   Sfx.pop()     — подключился игрок      Sfx.start()/Sfx.end() — начало / конец раунда
   Кнопка «Звуки» (слева внизу) включает/выключает всё это; выбор запоминается.
   ============================================================ */
const Sfx = (() => {
  const KEY = "sfx-on", MASTER = 0.9;
  let ctx = null, noise = null;
  let on = true;
  try { on = localStorage.getItem(KEY) !== "0"; } catch (e) {}

  function ac() {
    if (!ctx) { const A = window.AudioContext || window.webkitAudioContext; if (!A) return null; ctx = new A(); }
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }

  // мягкий «пузырьковый» тон: быстрая атака, плавное затухание
  function tone(freq, { dur = 0.12, vol = 0.06, type = "sine", delay = 0, to = null, lp = 3000 } = {}) {
    const c = ac(); if (!c) return;
    const t0 = c.currentTime + delay;
    const o = c.createOscillator(), g = c.createGain(), f = c.createBiquadFilter();
    o.type = type; o.frequency.setValueAtTime(freq, t0);
    if (to) o.frequency.exponentialRampToValueAtTime(to, t0 + dur);
    f.type = "lowpass"; f.frequency.value = lp;
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol * MASTER, t0 + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    o.connect(f).connect(g).connect(c.destination);
    o.start(t0); o.stop(t0 + dur + 0.05);
  }

  function noiseBuf(c) {
    if (noise) return noise;
    const len = c.sampleRate * 1;
    noise = c.createBuffer(1, len, c.sampleRate);
    const d = noise.getChannelData(0); let last = 0;
    for (let i = 0; i < len; i++) { last = (last + 0.04 * (Math.random() * 2 - 1)) / 1.04; d[i] = last * 6; } // «розоватый» шум — мягче белого
    return noise;
  }

  return {
    get on() { return on; },
    toggle() { on = !on; try { localStorage.setItem(KEY, on ? "1" : "0"); } catch (e) {} if (on) this.click(); return on; },

    click() { if (!on) return; tone(720, { dur: 0.09, vol: 0.07, to: 520 }); tone(1440, { dur: 0.05, vol: 0.02 }); },

    whoosh() {                                      // шорох: фильтрованный шум со «скольжением»
      if (!on) return;
      const c = ac(); if (!c) return;
      const t0 = c.currentTime;
      const s = c.createBufferSource(); s.buffer = noiseBuf(c);
      const f = c.createBiquadFilter(); f.type = "bandpass"; f.Q.value = 0.7;
      f.frequency.setValueAtTime(500, t0); f.frequency.exponentialRampToValueAtTime(2200, t0 + 0.42);
      const g = c.createGain();
      g.gain.setValueAtTime(0.0001, t0);
      g.gain.exponentialRampToValueAtTime(0.05 * MASTER, t0 + 0.12);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.5);
      s.connect(f).connect(g).connect(c.destination);
      s.start(t0); s.stop(t0 + 0.55);
    },

    pop()   { if (!on) return; tone(520, { dur: 0.14, vol: 0.07, to: 880 }); },
    start() { if (!on) return; [523, 659, 784].forEach((f, i) => tone(f, { dur: 0.35, vol: 0.05, delay: i * 0.11 })); },
    end()   { if (!on) return; [784, 659, 523].forEach((f, i) => tone(f, { dur: 0.4, vol: 0.05, delay: i * 0.13 })); },
    winner(){ if (!on) return; [523, 659, 784, 1047].forEach((f, i) => tone(f, { dur: 0.32, vol: 0.075, delay: i * 0.16, type: "triangle" })); }
  };
})();

// щелчок на любой активной кнопке (кроме переключателя звука — у него свой)
document.addEventListener("click", e => {
  const b = e.target.closest("button, a.mbtn");
  if (b && !b.disabled && b.id !== "btnSound") Sfx.click();
});

$("btnSound").onclick = () => { $("btnSound").textContent = "Звуки: " + (Sfx.toggle() ? "вкл" : "выкл"); };
$("btnSound").textContent = "Звуки: " + (Sfx.on ? "вкл" : "выкл");
