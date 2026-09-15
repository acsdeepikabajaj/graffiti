/* Little Blossoms arcade — shared cursor client.
   Used by index.html (launcher), birds.html, fruit.html.
   graffiti.html keeps its original inline client (it also owns calibration UI). */
window.GG = (() => {
  const PALETTE = ['#e0475f','#2f7fd6','#2aa876','#e8a020'];
  const INK = '#6b5d54', PAPER = '#faf6ee', LINE = '#e2d9cc';

  /* ---- players from URL ---- */
  function playersFromURL(def = 2) {
    const p = +(new URLSearchParams(location.search).get('p') || def);
    return Math.min(4, Math.max(1, p || def));
  }
  function diffFromURL(def = 'med') {
    const d = (new URLSearchParams(location.search).get('d') || def).toLowerCase();
    return ['easy','med','hard'].includes(d) ? d : def;
  }

  /* ---- homography (loaded from backend, written by graffiti's C-calibration) ---- */
  let HMAT = null;
  fetch('http://localhost:8766/cal').then(r => r.json())
    .then(j => { if (j && j.length === 8) HMAT = j; }).catch(() => {});
  function applyH(x, y) {
    if (!HMAT) return [x, y];
    const d = HMAT[6]*x + HMAT[7]*y + 1;
    return [Math.min(1, Math.max(0, (HMAT[0]*x + HMAT[1]*y + HMAT[2]) / d)),
            Math.min(1, Math.max(0, (HMAT[3]*x + HMAT[4]*y + HMAT[5]) / d))];
  }

  /* ---- cursor state + edge events ----
     opts: {players, status(el|fn), onB(pl,x,y), onBUp(pl), onA, onHome, onUp, onDown, onLeft, onRight}
     cur fields kept per player: x,y,visible,b,sep,ndots  (normalized, homography applied) */
  const state = {};             // player -> latest cursor
  function connect(opts) {
    const N = opts.players || 4;
    const setStatus = t => { if (typeof opts.status === 'function') opts.status(t);
                             else if (opts.status) opts.status.textContent = t; };
    (function loop() {
      const ws = new WebSocket('ws://localhost:8765');
      ws.onopen = () => setStatus('backend connected');
      ws.onclose = () => { setStatus('backend offline — mouse mode (keys 1-4, click = shoot/slice)');
                           setTimeout(loop, 2000); };
      ws.onmessage = ev => {
        for (const cur of JSON.parse(ev.data).cursors) {
          if (cur.player >= N) continue;
          const [cx, cy] = applyH(cur.x, cur.y);
          const cc = { ...cur, x: cx, y: cy };
          const prev = state[cur.player];
          /* second-stage smoothing (on top of the driver's):
             adaptive EMA — steady when slow, instant when swiping */
          if (opts.smooth !== false && prev && prev._sx != null && cc.visible) {
            const dx = cc.x - prev._sx, dy = cc.y - prev._sy;
            const sp = Math.hypot(dx, dy);
            const a = Math.min(1, (opts.smoothMin ?? 0.22) + sp * 16);
            cc._sx = prev._sx + a * dx; cc._sy = prev._sy + a * dy;
          } else { cc._sx = cc.x; cc._sy = cc.y; }
          cc.rawx = cc.x; cc.rawy = cc.y;
          cc.x = cc._sx; cc.y = cc._sy;
          const edge = k => cc[k] && !(prev && prev[k]);
          if (edge('b')    && opts.onB)    opts.onB(cc.player, cc.x, cc.y);
          if (prev && prev.b && !cc.b && opts.onBUp) opts.onBUp(cc.player);
          if (edge('a')    && opts.onA)    opts.onA(cc.player, cc.x, cc.y);
          if (edge('home') && opts.onHome) opts.onHome(cc.player);
          if (edge('up')    && opts.onUp)    opts.onUp(cc.player);
          if (edge('down')  && opts.onDown)  opts.onDown(cc.player);
          if (edge('left')  && opts.onLeft)  opts.onLeft(cc.player);
          if (edge('right') && opts.onRight) opts.onRight(cc.player);
          state[cc.player] = cc;
        }
      };
    })();

    /* mouse fallback: keys 1-4 pick which player the mouse drives */
    let mP = 0, mB = false;
    addEventListener('keydown', e => {
      const n = +e.key; if (n >= 1 && n <= N) mP = n - 1;
    });
    addEventListener('mousemove', e => {
      const cc = { player: mP, x: e.clientX / innerWidth, y: e.clientY / innerHeight,
                   visible: true, b: mB, sep: 0.12, ndots: 2, mouse: true };
      state[mP] = { ...state[mP], ...cc };
    });
    addEventListener('mousedown', e => {
      mB = true;
      const x = e.clientX / innerWidth, y = e.clientY / innerHeight;
      state[mP] = { ...state[mP], player: mP, x, y, visible: true, b: true };
      if (opts.onB) opts.onB(mP, x, y);
    });
    addEventListener('mouseup', () => { mB = false;
      if (state[mP]) state[mP].b = false;
      if (opts.onBUp) opts.onBUp(mP); });
    return state;
  }

  /* ---- procedural audio: sfx + tiny 8-step music loops (no assets) ---- */
  const audio = (() => {
    let ctx = null, muted = false, musTimer = null, step = 0;
    function ensure() {
      if (!ctx) { try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {} }
      if (ctx && ctx.state === 'suspended') ctx.resume().catch(() => {});
      return ctx && ctx.state === 'running' ? ctx : ctx;
    }
    for (const ev of ['mousedown', 'keydown', 'touchstart'])
      addEventListener(ev, () => ensure());
    function env(t0, dur, vol) {
      const g = ctx.createGain();
      g.gain.setValueAtTime(vol, t0);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
      g.connect(ctx.destination); return g;
    }
    function tone(f, dur = 0.15, type = 'triangle', vol = 0.12, when = 0) {
      const c2 = ensure(); if (!c2 || muted || c2.state !== 'running') return;
      const t0 = c2.currentTime + when;
      const o = c2.createOscillator(); o.type = type; o.frequency.value = f;
      o.connect(env(t0, dur, vol)); o.start(t0); o.stop(t0 + dur + 0.02);
    }
    function noise(dur = 0.12, vol = 0.1, when = 0, freq = 1200, kind = 'highpass') {
      const c2 = ensure(); if (!c2 || muted || c2.state !== 'running') return;
      const t0 = c2.currentTime + when;
      const n = c2.createBufferSource();
      const b = c2.createBuffer(1, Math.max(1, c2.sampleRate * dur), c2.sampleRate);
      const d = b.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
      n.buffer = b;
      const f = c2.createBiquadFilter(); f.type = kind; f.frequency.value = freq;
      n.connect(f); f.connect(env(t0, dur, vol)); n.start(t0);
    }
    function jingle()  { [262, 330, 392, 523].forEach((f, i) => tone(f, .14, 'triangle', .15, i * .09)); }
    function fanfare() { [523, 392, 523, 659, 784].forEach((f, i) => tone(f, .18, 'triangle', .16, i * .12));
                         noise(.35, .05, .6, 500); }
    function tick(go)  { tone(go ? 880 : 440, go ? .28 : .12, 'square', .14); }
    const PATS = {
      birds: { bpm: 132, bass: [131,0,164,0,131,0,196,0], lead: [523,659,784,659,880,784,659,523] },
      fruit: { bpm: 120, bass: [110,0,138,0,110,0,146,0], lead: [440,523,587,523,659,587,523,440] },
      paint: { bpm: 96,  bass: [98,0,0,0,110,0,0,0],      lead: [392,0,440,0,523,0,440,0] },
      menu:  { bpm: 84,  bass: [98,0,0,0,0,0,0,0],        lead: [392,0,0,494,0,0,440,0] } };
    function music(name) {
      stopMusic(); const p = PATS[name]; if (!p) return;
      step = 0;
      musTimer = setInterval(() => {
        const c2 = ensure(); if (!c2 || muted || c2.state !== 'running') return;
        const b = p.bass[step % 8], l = p.lead[step % 8];
        if (b) tone(b, .22, 'square', .03);
        if (l && step % 2 === 0) tone(l, .16, 'triangle', .045);
        step++;
      }, 60 / p.bpm / 2 * 1000);
    }
    function stopMusic() { clearInterval(musTimer); musTimer = null; }
    function setMuted(m) { muted = m; }
    function running() { return !!(ctx && ctx.state === 'running'); }
    return { ensure, tone, noise, jingle, fanfare, tick, music, stopMusic,
             setMuted, running, get muted() { return muted; } };
  })();

  function goHome() { audio.stopMusic(); location.href = 'index.html'; }

  return { PALETTE, INK, PAPER, LINE, playersFromURL, diffFromURL, applyH, connect, state, goHome, audio };
})();
