/**
 * antigravity-bg.js - Vanilla JS port of GoogleAntigravityBackground
 * Original: Adnan Ashfaq  github.com/MAdnanAshfaq/Gravity-UI-BG
 *
 * Zero-dependency IIFE. Creates a fixed <canvas> behind all content.
 * pointer-events:none -> completely invisible to UI interactions.
 *
 * Features (1:1 with original TSX):
 *   340 glowing seed particles in golden-angle vortex ring
 *   Google 4-color palette (Blue/Red/Yellow/Green) blinking cycle
 *   Cursor attraction (ATTRACTION_RADIUS=260) + clearance (CLEARANCE=76)
 *   Hover ripples + click shockwaves
 *   DPR-aware, auto-resize, pauses on hidden tab
 */
(function () {
  "use strict";

  /* ---- Google 4-color palette ---------------------------------------- */
  var COLORS = [
    { r: 26,  g: 115, b: 232 }, /* Blue   */
    { r: 234, g: 67,  b: 53  }, /* Red    */
    { r: 251, g: 188, b: 4   }, /* Yellow */
    { r: 52,  g: 168, b: 83  }, /* Green  */
  ];
  function rndColor(ex) {
    var pool = [0,1,2,3].filter(function(i){return i!==ex;});
    return pool[Math.floor(Math.random()*pool.length)];
  }

  /* ---- Config --------------------------------------------------------- */
  var PCOUNT  = 340;
  var ATTR_R  = 260;
  var CLEAR_R = 76;

  /* ---- State ---------------------------------------------------------- */
  var canvas, ctx;
  var particles = [], ripples = [], shocks = [];
  var rafId = null, paused = false, rpId = 0;
  var dims = { w: 0, h: 0 };
  var mouse = { x: -9999, y: -9999, active: false };
  var lastRpT = 0, lastRpPos = { x: -9999, y: -9999 };

  /* ---- Init particle ring --------------------------------------------- */
  function initParticles(w, h) {
    particles = [];
    if (!w || !h) return;
    var n   = Math.min(Math.max(PCOUNT, 260), 420);
    var cx  = w / 2, cy = h / 2;
    var mnd = Math.min(w, h), mxd = Math.max(w, h);
    var inn = Math.max(120, Math.min(210, mnd * 0.22));
    var out = Math.max(inn + 200, Math.min(mxd * 0.60, mnd * 0.52 + 150));
    var gld = Math.PI * (3 - Math.sqrt(5)); /* golden angle ~2.3999 rad */

    for (var i = 0; i < n; i++) {
      var frac = Math.pow(i / n, 0.78);
      var jit  = Math.sin(i * 1.8) * 18 + Math.cos(i * 2.4) * 10;
      var r    = inn + frac * (out - inn) + jit;
      var ba   = i * gld + (r / out) * 2.5;
      var x    = cx + Math.cos(ba) * r;
      var y    = cy + Math.sin(ba) * (r * 0.95);
      var asp  = 0.0011 * (1 + 100 / Math.max(r, 80));
      var ci   = (i + Math.floor(Math.random() * 2)) % 4;
      var ti   = rndColor(ci);
      var col  = COLORS[ci], tc = COLORS[ti];
      var ba0  = 0.55 + (i % 5) * 0.06;
      particles.push({
        x: x, y: y, baseX: x, baseY: y,
        vx: 0, vy: 0,
        len: 5.6 + (i % 5) * 0.32,
        wid: 2.3 + (i % 3) * 0.25,
        cr: col.r, cg: col.g, cb: col.b,
        tr: tc.r,  tg: tc.g,  tb: tc.b,
        ci: ci, switched: false,
        alpha: ba0, ba0: ba0,
        bp: (i * 1.45 + (i % 3) * 0.7) % (Math.PI * 2),
        bs: 1.2 + (i % 7) * 0.35,
        angle: ba + Math.PI / 2 + 0.22,
        ba: ba,  /* current base angle (mutates each frame) */
        r: r, asp: asp,
      });
    }
  }

  /* ---- Resize + reinit ----------------------------------------------- */
  function resize() {
    var dpr = window.devicePixelRatio || 1;
    var w = window.innerWidth, h = window.innerHeight;
    dims = { w: w, h: h };
    canvas.width  = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width  = w + "px";
    canvas.style.height = h + "px";
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
    initParticles(w, h);
  }

  /* ---- Main animation frame ------------------------------------------ */
  function frame() {
    rafId = requestAnimationFrame(frame);
    if (paused) return;

    var w = dims.w, h = dims.h;
    var mx = mouse.x, my = mouse.y, ia = mouse.active;
    ctx.clearRect(0, 0, w, h);

    /* Advance ripples */
    for (var ri = ripples.length - 1; ri >= 0; ri--) {
      var rp = ripples[ri];
      rp.radius += 3.5;
      rp.strength *= rp.decay;
      if (rp.strength < 0.01 || rp.radius > rp.maxR) ripples.splice(ri, 1);
    }
    /* Advance shockwaves */
    for (var si = shocks.length - 1; si >= 0; si--) {
      var sw = shocks[si];
      sw.radius += 9;
      sw.strength *= sw.decay;
      if (sw.strength < 0.01 || sw.radius > sw.maxR) shocks.splice(si, 1);
    }

    var cx = w / 2, cy = h / 2;

    for (var pi = 0; pi < particles.length; pi++) {
      var p = particles[pi];

      /* 1. Orbital base movement */
      p.ba += p.asp;
      p.baseX = cx + Math.cos(p.ba) * p.r;
      p.baseY = cy + Math.sin(p.ba) * (p.r * 0.95);

      /* 2. Cursor attraction / clearance */
      var fx = 0, fy = 0;
      if (ia) {
        var dx = mx - p.x, dy = my - p.y, d = Math.sqrt(dx*dx + dy*dy);
        if (d > 0 && d < ATTR_R) {
          if (d < CLEAR_R) {
            var rep = ((CLEAR_R - d) / CLEAR_R) * 2.8;
            fx -= (dx / d) * rep;
            fy -= (dy / d) * rep;
          } else {
            var nm = (ATTR_R - d) / ATTR_R, pull = nm * nm * 1.6;
            fx += (dx / d) * pull;
            fy += (dy / d) * pull;
          }
        }
      }

      /* 3. Ripple forces */
      for (var rj = 0; rj < ripples.length; rj++) {
        var rpj = ripples[rj];
        var rdx = p.x - rpj.x, rdy = p.y - rpj.y;
        var rd = Math.sqrt(rdx*rdx + rdy*rdy);
        var wv = Math.abs(rd - rpj.radius);
        if (wv < 30 && rd > 0) {
          var rs = rpj.strength * (1 - wv / 30);
          fx += (rdx / rd) * rs;
          fy += (rdy / rd) * rs;
        }
      }

      /* 4. Shockwave forces */
      for (var sj = 0; sj < shocks.length; sj++) {
        var swj = shocks[sj];
        var sdx = p.x - swj.x, sdy = p.y - swj.y;
        var sd = Math.sqrt(sdx*sdx + sdy*sdy);
        var sw2 = Math.abs(sd - swj.radius);
        if (sw2 < 50 && sd > 0) {
          var ss = swj.strength * (1 - sw2 / 50) * 1.8;
          fx += (sdx / sd) * ss;
          fy += (sdy / sd) * ss;
        }
      }

      /* 5. Spring toward base position */
      fx += (p.baseX - p.x) * 0.08;
      fy += (p.baseY - p.y) * 0.08;

      /* 6. Velocity + damping */
      p.vx = (p.vx + fx) * 0.82;
      p.vy = (p.vy + fy) * 0.82;
      p.x += p.vx;
      p.y += p.vy;

      /* 7. Angle follows velocity (seed tumble) */
      var spd = Math.sqrt(p.vx*p.vx + p.vy*p.vy);
      if (spd > 0.12) {
        var tA = Math.atan2(p.vy, p.vx);
        var dA = ((tA - p.angle + Math.PI*3) % (Math.PI*2)) - Math.PI;
        p.angle += dA * 0.18;
      } else {
        p.angle += p.asp;
      }

      /* 8. Independent blink */
      p.bp += p.bs * 0.016;
      var blink = (Math.sin(p.bp) + 1) / 2;
      p.alpha = p.ba0 * (0.45 + blink * 0.55);

      /* 9. Colour smooth-lerp + cycle */
      p.cr += (p.tr - p.cr) * 0.018;
      p.cg += (p.tg - p.cg) * 0.018;
      p.cb += (p.tb - p.cb) * 0.018;
      var cd = Math.abs(p.cr - p.tr) + Math.abs(p.cg - p.tg) + Math.abs(p.cb - p.tb);
      if (cd < 8 && !p.switched) {
        p.switched = true;
      } else if (cd < 2 && p.switched) {
        p.ci = rndColor(p.ci);
        var nc = COLORS[p.ci];
        p.tr = nc.r; p.tg = nc.g; p.tb = nc.b;
        p.switched = false;
      }

      /* 10. Draw particle */
      var CR = (p.cr + 0.5) | 0;
      var CG = (p.cg + 0.5) | 0;
      var CB = (p.cb + 0.5) | 0;
      var AL = Math.max(0, Math.min(1, p.alpha));

      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.angle);

      /* Outer radial glow */
      var glowR = p.len * 2.2 + spd * 0.6;
      var grd = ctx.createRadialGradient(0, 0, 0, 0, 0, glowR);
      grd.addColorStop(0,   "rgba(" + CR + "," + CG + "," + CB + "," + (AL * 0.55).toFixed(3) + ")");
      grd.addColorStop(0.4, "rgba(" + CR + "," + CG + "," + CB + "," + (AL * 0.22).toFixed(3) + ")");
      grd.addColorStop(1,   "rgba(" + CR + "," + CG + "," + CB + ",0)");
      ctx.fillStyle = grd;
      ctx.beginPath();
      ctx.arc(0, 0, glowR, 0, Math.PI * 2);
      ctx.fill();

      /* Core seed capsule */
      ctx.shadowColor  = "rgba(" + CR + "," + CG + "," + CB + "," + (AL * 0.9).toFixed(3) + ")";
      ctx.shadowBlur   = 6 + spd * 0.8;
      ctx.fillStyle    = "rgba(" + CR + "," + CG + "," + CB + "," + AL.toFixed(3) + ")";
      var hw = p.wid / 2, hl = p.len / 2;
      ctx.beginPath();
      ctx.arc(-hl + hw, 0, hw, Math.PI / 2, 3 * Math.PI / 2);
      ctx.lineTo(hl - hw, -hw);
      ctx.arc(hl - hw, 0, hw, -Math.PI / 2, Math.PI / 2);
      ctx.closePath();
      ctx.fill();

      ctx.restore();
    }
  }

  /* ---- Event listeners ----------------------------------------------- */
  function onMove(e) {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
    mouse.active = true;
    var now = performance.now();
    var dx = mouse.x - lastRpPos.x, dy = mouse.y - lastRpPos.y;
    if (now - lastRpT > 60 && Math.sqrt(dx*dx + dy*dy) > 18) {
      ripples.push({
        id: rpId++, x: mouse.x, y: mouse.y,
        radius: 0, maxR: 90 + Math.random() * 40,
        strength: 0.38 + Math.random() * 0.18, decay: 0.88,
      });
      lastRpT = now;
      lastRpPos = { x: mouse.x, y: mouse.y };
    }
  }
  function onLeave() { mouse.active = false; mouse.x = mouse.y = -9999; }
  function onTouch(e) {
    if (e.touches && e.touches.length > 0) {
      mouse.x = e.touches[0].clientX;
      mouse.y = e.touches[0].clientY;
      mouse.active = true;
    }
  }
  function onTouchEnd() { mouse.active = false; mouse.x = mouse.y = -9999; }
  function onClick(e) {
    var tag = (e.target || {}).tagName;
    if (tag === "BUTTON" || tag === "INPUT" || tag === "TEXTAREA" ||
        tag === "SELECT"  || tag === "A"     || tag === "LABEL") return;
    shocks.push({
      x: e.clientX, y: e.clientY,
      radius: 0, maxR: 220 + Math.random() * 80,
      strength: 1.6 + Math.random() * 0.6, decay: 0.90,
    });
  }

  var resizeTimeout = null;
  function onResize() {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(resize, 120);
  }

  /* ---- Bootstrap ------------------------------------------------------ */
  function init() {
    canvas = document.createElement("canvas");
    canvas.id = "antigravity-bg-canvas";
    canvas.setAttribute("aria-hidden", "true");
    /* Fixed behind everything, transparent to mouse */
    canvas.style.position = "fixed";
    canvas.style.top = "0";
    canvas.style.left = "0";
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.pointerEvents = "none";
    canvas.style.zIndex = "0";
    canvas.style.display = "block";

    /* Prepend so it sits behind the splash overlay, header, and all panels */
    document.body.insertBefore(canvas, document.body.firstChild);
    ctx = canvas.getContext("2d");

    resize();

    var opt = { passive: true };
    window.addEventListener("resize", onResize, opt);
    document.addEventListener("mousemove",  onMove,     opt);
    document.addEventListener("mouseleave", onLeave,    opt);
    document.addEventListener("touchstart", onTouch,    opt);
    document.addEventListener("touchmove",  onTouch,    opt);
    document.addEventListener("touchend",   onTouchEnd, opt);
    document.addEventListener("click",      onClick,    opt);
    document.addEventListener("visibilitychange", function () {
      paused = document.hidden;
    });

    rafId = requestAnimationFrame(frame);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
