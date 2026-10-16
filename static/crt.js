/* Decorative terminal feeds projected onto inward-curved side screens. */
(() => {
  'use strict';
  const programs = [
    'struct signal { u32 id; f32 gain; };',
    'rx.lock(carrier, CHANNEL_07);',
    'while (stream.available()) {',
    '  frame = decode(buffer.next());',
    '  if (frame.valid) route(frame);',
    '  memory.sync(SHELL_ADDRESS);',
    '  yield signal.phase();',
    '}',
    'const link = await oni.connect();',
    'packet.flags |= SYNC_READY;',
    'return carrier.checksum(0xFF);',
    'void acquire(signal_t *source) {',
    '  source->state = RECEIVING;',
    '  dispatch(source, LOCAL_BUS);',
    '}',
    'export { signal, buffer, session };',
    'route /media -> /local/output',
    'MOV  R07, [SIGNAL_BASE + 0x20]',
    'XOR  R12, R12 // clear register',
    'CALL CYAC::HANDSHAKE',
    'CMP  RX_STATE, READY',
    'JNE  .await_signal',
    '0x00FF :: carrier acquired',
    'session.persist({ mode: "local" });',
    'gate.open() && buffer.commit();',
    'if (checksum !== expected) retry();',
    'nexus.bind("tau-ceti", shell.id);',
    'signal.origin = [0.0, 0.0, 1.0];',
  ];
  const cache = new Map();
  function random(seed) {
    let value = seed >>> 0;
    return () => {
      value = (Math.imul(value, 1664525) + 1013904223) >>> 0;
      return value / 4294967296;
    };
  }
  function texture(makeCanvas, side, tick) {
    if (!cache.has(side)) cache.set(side, makeCanvas(440, 1040));
    const canvas = cache.get(side);
    const context = canvas.getContext('2d');
    const rng = random(7907 + side * 1701 + Math.floor(tick / 3));
    const hex = (length) => Array.from({ length }, () => Math.floor(rng() * 16).toString(16).toUpperCase()).join('');
    context.clearRect(0, 0, 440, 1040);
    context.fillStyle = '#050a2855';
    context.fillRect(0, 0, 440, 1040);
    context.strokeStyle = '#66c7ec28';
    context.strokeRect(8, 8, 424, 1024);
    context.fillStyle = '#bdff91';
    context.font = '13px Consolas, monospace';
    context.fillText(side ? 'CYAC // MEMORY BUS 09' : 'CYAC // CARRIER BUS 07', 22, 33);
    context.fillStyle = '#87c7d8';
    context.font = '10px Consolas, monospace';
    context.fillText(`0x${hex(8)}  /  LINK ESTABLISHED`, 22, 53);
    for (let row = 0; row < 35; row += 1) {
      const y = 88 + row * 17;
      const highlight = row === tick % 35;
      if (highlight) {
        context.fillStyle = '#b9ff661a';
        context.fillRect(15, y - 12, 410, 17);
      }
      context.fillStyle = '#6886b5';
      context.font = '10px Consolas, monospace';
      context.fillText((side * 6144 + row * 16).toString(16).toUpperCase().padStart(4, '0'), 21, y);
      context.fillStyle = highlight ? '#dcffdc' : (row % 5 === 0 ? '#a0e966' : '#91cddd');
      context.font = '12px Consolas, monospace';
      const line = row % 7 === 0 ? `${hex(4)} ${hex(4)} ${hex(4)}  ::  SYNC` : programs[(row + side * 9) % programs.length];
      context.fillText(line, 64, y);
    }
    context.strokeStyle = '#86cfd650';
    context.beginPath(); context.moveTo(20, 700); context.lineTo(420, 700); context.stroke();
    context.fillStyle = '#bafda1'; context.font = '11px Consolas, monospace';
    context.fillText(side ? 'NEURAL ARRAY / 64 NODES' : 'FREQUENCY / RX SPECTRUM', 22, 725);
    for (let index = 0; index < 43; index += 1) {
      const height = 12 + rng() * 70;
      context.fillStyle = index % 4 ? '#55c6e877' : '#b9ff66b3';
      context.fillRect(23 + index * 9, 820 - height, 5, height);
    }
    for (let row = 0; row < 8; row += 1) {
      context.fillStyle = row === tick % 8 ? '#b9ffbf' : '#7d9fbe';
      context.font = '11px Consolas, monospace';
      context.fillText(`${hex(8)}  ${hex(8)}  ${hex(8)}`, 22, 864 + row * 18);
    }
    context.fillStyle = '#99c8db'; context.font = '10px Consolas, monospace';
    context.fillText('PERSISTENT CONNECTION  /  0 PACKETS LOST', 22, 1020);
    return canvas;
  }

  function drawTelemetry(context, width, height, bounds, tick, makeCanvas) {
    context.clearRect(0, 0, width, height);
    if (width < 1050) return;
    const gap = 28;
    const outer = 48;
    for (const side of [0, 1]) {
      const start = side ? bounds.right + gap : -outer;
      const end = side ? width + outer : bounds.left - gap;
      if (end - start < 90) continue;
      const source = texture(makeCanvas, side, tick);
      const panelWidth = end - start;
      const centerY = height * .53;
      const panelHeight = height * .79;
      context.save();
      context.globalAlpha = .78;
      // Vary each strip's depth across the screen: the outer edge is closer,
      // bowing every code baseline and making the sides wrap around the user.
      for (let x = 0; x < source.width; x += 3) {
        const u = x / source.width;
        const distance = side ? u : 1 - u;
        const depth = 1 + .48 * distance * distance;
        const destinationHeight = panelHeight * depth;
        const stripWidth = Math.min(3, source.width - x);
        context.drawImage(source, x, 0, stripWidth, source.height,
          start + u * panelWidth, centerY - destinationHeight / 2,
          panelWidth * stripWidth / source.width + .6, destinationHeight);
      }
      context.restore();
    }
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { drawTelemetry };
  if (typeof document === 'undefined') return;
  const canvas = document.getElementById('crt-telemetry');
  const consolePanel = document.getElementById('console');
  if (!canvas || !consolePanel) return;
  const context = canvas.getContext('2d');
  if (!context) return;
  let motion = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let tick = 0;
  let timer = null;
  let resizeFrame = null;
  const makeCanvas = (width, height) => {
    const surface = document.createElement('canvas');
    surface.width = width; surface.height = height;
    return surface;
  };
  function paint() {
    drawTelemetry(context, canvas.width, canvas.height, consolePanel.getBoundingClientRect(), tick, makeCanvas);
  }
  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    paint();
  }
  function updateMotion() {
    clearInterval(timer);
    timer = null;
    if (motion && !document.hidden && window.innerWidth >= 1050) {
      timer = setInterval(() => { tick += 1; paint(); }, 900);
    }
  }
  window.addEventListener('resize', () => {
    if (resizeFrame !== null) return;
    resizeFrame = requestAnimationFrame(() => { resizeFrame = null; resize(); updateMotion(); });
  }, { passive: true });
  document.addEventListener('oni:motion', (event) => { motion = event.detail.enabled; updateMotion(); });
  document.addEventListener('visibilitychange', updateMotion);
  resize();
  updateMotion();
})();
