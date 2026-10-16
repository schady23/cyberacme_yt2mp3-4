/* A soft, low-resolution color hologram with depth and ordered dithering. */
(() => {
  'use strict';
  const bayer = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
  const channelLevels = [0, 32, 72, 128, 196, 255];
  const sampleWidth = 176;
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const gaussian = (value) => Math.exp(-(value * value));

  function buildCloud(data, width, height) {
    const colors = new Map();
    for (let row = 0; row < height; row += 1) {
      for (let col = 0; col < width; col += 1) {
        const index = (row * width + col) * 4;
        const alpha = data[index + 3] / 255;
        const threshold = bayer[(row % 4) * 4 + col % 4] / 16;
        if (alpha < .1 || alpha < threshold * .8) continue;
        const u = (col + .5) / width;
        const v = (row + .5) / height;
        // Quantize each channel independently, keeping the reference's blue hair
        // and green face. The PNG alpha preserves the full flared data strands.
        const quantize = (channel) => channelLevels[clamp(Math.floor(channel * 5 / 255 + .5 + (threshold - .5) * .65), 0, 5)];
        const red = quantize(data[index]);
        const green = quantize(data[index + 1]);
        const blue = quantize(data[index + 2]);
        const color = `rgb(${red},${green},${blue})`;
        if (!colors.has(color)) colors.set(color, []);
        const x = u - .5;
        const y = (v - .5) * height / width;
        const volume = Math.sqrt(Math.max(0, 1 - ((u - .5) / .30) ** 2 - ((v - .32) / .34) ** 2));
        const nose = gaussian((u - .5) / .04) * gaussian((v - .49) / .09) * .10;
        const eyeSockets = (gaussian((u - .409) / .055) + gaussian((u - .614) / .055)) * gaussian((v - .376) / .035) * .025;
        const z = volume * .23 + nose - eyeSockets - .10;
        const eye = data[index + 1] > 140 && data[index + 2] > 140 ? Math.max(
          gaussian((u - .409) / .017) * gaussian((v - .376) / .012),
          gaussian((u - .614) / .017) * gaussian((v - .376) / .012),
        ) : 0;
        colors.get(color).push(x, y, z, eye);
      }
    }
    return {
      groups: Array.from(colors, ([color, points]) => ({ color, points: new Float32Array(points) })),
      aspect: height / width,
      sampleWidth: width,
    };
  }

  function drawCloud(context, cloud, width, height, yaw, pitch) {
    context.clearRect(0, 0, width, height);
    const scale = Math.min(width * .96, height / (cloud.aspect * 1.05));
    const size = Math.max(1, scale / cloud.sampleWidth * 1.1);
    const sinY = Math.sin(yaw), cosY = Math.cos(yaw);
    const sinX = Math.sin(pitch), cosX = Math.cos(pitch);
    cloud.groups.forEach(({ points, color }) => {
      context.fillStyle = color;
      for (let i = 0; i < points.length; i += 4) {
        const x = points[i] + points[i + 3] * yaw * .055;
        const y = points[i + 1] + points[i + 3] * pitch * .035;
        const z = points[i + 2];
        const rx = x * cosY + z * sinY;
        const rz = z * cosY - x * sinY;
        const ry = y * cosX - rz * sinX;
        const depth = y * sinX + rz * cosX;
        const perspective = 3.5 / (3.5 - depth);
        context.fillRect(
          Math.round(width * .5 + rx * scale * perspective),
          Math.round(height * .5 + ry * scale * perspective),
          size, size,
        );
      }
    });
  }

  // Pure render functions also support local rendering and geometry verification.
  if (typeof module !== 'undefined' && module.exports) module.exports = { buildCloud, drawCloud };
  if (typeof document === 'undefined') return;
  const stage = document.getElementById('oni-stage');
  const image = document.getElementById('oni-image');
  const canvas = document.getElementById('oni-canvas');
  const context = canvas.getContext('2d');
  if (!context) return; // The original portrait remains visible without canvas.
  let groups = null;
  let motion = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let yaw = 0, pitch = 0, targetYaw = 0, targetPitch = 0;
  let frame = null;
  let previousTime = 0;

  function paint() {
    if (groups) drawCloud(context, groups, canvas.width, canvas.height, yaw, pitch);
  }
  function animate(time) {
    frame = null;
    if (!motion || document.hidden) return;
    if (time - previousTime >= 30) {
      previousTime = time;
      yaw += (targetYaw - yaw) * .16;
      pitch += (targetPitch - pitch) * .16;
      paint();
    }
    if (Math.abs(targetYaw - yaw) + Math.abs(targetPitch - pitch) > .0003) frame = requestAnimationFrame(animate);
  }
  function schedule() {
    if (frame === null && motion && !document.hidden && groups) frame = requestAnimationFrame(animate);
  }
  function resize() {
    const rect = stage.getBoundingClientRect();
    const ratio = Math.min(1, 900 / rect.width, 1300 / rect.height);
    canvas.width = Math.max(1, Math.round(rect.width * ratio));
    canvas.height = Math.max(1, Math.round(rect.height * ratio));
    paint();
  }
  function load() {
    if (!image.naturalWidth) return;
    try {
      const sample = document.createElement('canvas');
      sample.width = sampleWidth;
      sample.height = Math.round(sampleWidth * image.naturalHeight / image.naturalWidth);
      const sampling = sample.getContext('2d', { willReadFrequently: true });
      sampling.drawImage(image, 0, 0, sample.width, sample.height);
      groups = buildCloud(sampling.getImageData(0, 0, sample.width, sample.height).data, sample.width, sample.height);
      resize();
      stage.classList.add('is-rendered');
    } catch (error) { console.warn('ONI portrait fallback:', error); }
  }

  window.addEventListener('pointermove', (event) => {
    if (!motion || event.pointerType === 'touch') return;
    const rect = stage.getBoundingClientRect();
    const cx = rect.left + rect.width * .5;
    targetYaw = clamp((event.clientX - cx) / (window.innerWidth * .56), -1, 1) * .36;
    targetPitch = -clamp((event.clientY - window.innerHeight * .44) / (window.innerHeight * .65), -1, 1) * .20;
    document.getElementById('gaze-coordinates').textContent = `${String(Math.round(event.clientX / window.innerWidth * 1000)).padStart(4, '0')} : ${String(Math.round(event.clientY / window.innerHeight * 1000)).padStart(4, '0')}`;
    schedule();
  }, { passive: true });
  document.addEventListener('pointerout', (event) => {
    if (!event.relatedTarget) { targetYaw = targetPitch = 0; schedule(); }
  });
  document.addEventListener('oni:motion', (event) => {
    motion = event.detail.enabled;
    if (!motion) {
      cancelAnimationFrame(frame);
      frame = null;
      yaw = pitch = targetYaw = targetPitch = 0;
      paint();
      document.getElementById('gaze-coordinates').textContent = '0500 : 0500';
    } else schedule();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { cancelAnimationFrame(frame); frame = null; }
    else schedule();
  });
  window.addEventListener('resize', resize, { passive: true });
  if (image.complete) load();
  else image.addEventListener('load', load, { once: true });
})();
