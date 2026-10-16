'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  const form = $('convert-form');
  const controls = $('job-controls');
  const urlInput = $('url');
  const startInput = $('start-time');
  const endInput = $('end-time');
  const startSlider = $('start-slider');
  const endSlider = $('end-slider');
  const maxDuration = Number(document.body.dataset.maxDuration);
  let source = null;
  let busy = false;
  let inspecting = false;
  let inspectVersion = 0;
  let pollTimer = null;
  let sectionTouched = false;
  let mode = 'full';
  const outputFormat = () => form.elements.format.value;
  const metadataInputs = [...form.querySelectorAll('[data-metadata]')];
  const show = (element, visible = true) => element.classList.toggle('hidden', !visible);

  function timestamp(seconds) {
    const milliseconds = Math.round(Math.max(0, seconds) * 1000);
    const whole = Math.floor(milliseconds / 1000);
    const hours = Math.floor(whole / 3600);
    const minutes = Math.floor((whole % 3600) / 60);
    const secs = whole % 60;
    const parts = [minutes, secs].map((part) => String(part).padStart(2, '0'));
    if (hours) parts.unshift(String(hours).padStart(2, '0'));
    const fraction = milliseconds % 1000;
    return parts.join(':') + (fraction ? `.${String(fraction).padStart(3, '0').replace(/0+$/, '')}` : '');
  }

  function parseTime(value) {
    const text = value.trim();
    if (text.length > 32 || !/^\d+(?::\d{1,2}){0,2}(?:\.\d{1,3})?$/.test(text)) return null;
    const parts = text.split(':').map(Number);
    if (parts.slice(1).some((part) => part >= 60)) return null;
    const seconds = parts.reverse().reduce((total, part, index) => total + part * 60 ** index, 0);
    return Number.isFinite(seconds) ? Math.round(seconds * 1000) / 1000 : null;
  }

  function getSection() {
    if (mode === 'full') return { start: null, end: null, error: '' };
    const start = parseTime(startInput.value);
    const end = parseTime(endInput.value);
    let error = '';
    if (source?.is_live) error = 'Sections require a finished video. Live streams cannot be trimmed.';
    else if (start === null || end === null) error = 'Enter both times as MM:SS, HH:MM:SS, or seconds.';
    else if (end <= start) error = 'The end time must be after the start time.';
    else if (source?.duration && end > source.duration) error = `Your section must fit within the source (${timestamp(source.duration)}).`;
    else if (maxDuration > 0 && end - start > maxDuration) error = `Choose a section of ${maxDuration / 60} minutes or less.`;
    return { start, end, error };
  }

  function updateRange() {
    const isSection = mode === 'section';
    const section = getSection();
    const valid = !section.error;
    const duration = source?.duration;
    $('trim-fields').hidden = !isSection;
    $('section-help').hidden = !isSection;
    startInput.disabled = busy || !isSection;
    endInput.disabled = busy || !isSection;
    startInput.required = endInput.required = isSection;
    const hasTimeline = isSection && Boolean(duration) && !source.is_live;
    $('timeline-controls').hidden = !hasTimeline;
    startSlider.disabled = endSlider.disabled = !hasTimeline || busy;
    $('timeline').dataset.ready = String(hasTimeline);
    $('range-label').textContent = isSection ? 'SELECTED SECTION' : 'FULL LENGTH';
    $('selection-duration').textContent = valid && isSection ? timestamp(section.end - section.start) : '—:—';
    $('selection-caption').textContent = valid ? `${timestamp(section.start || 0)} → ${timestamp(section.end || 0)}` : 'SET YOUR IN / OUT POINTS';
    $('trim-error').textContent = isSection && sectionTouched ? section.error : '';
    [startInput, endInput].forEach((input) => input.setAttribute('aria-invalid', String(isSection && sectionTouched && !valid)));
    $('timeline-prompt').textContent = isSection ? (hasTimeline ? '' : (source?.is_live ? 'LIVE / NO SECTIONS' : 'LOAD SOURCE FOR TRIM HANDLES')) : 'FULL SOURCE';
    $('timeline-mid').textContent = duration ? timestamp(duration / 2) : '—';
    $('timeline-end').textContent = duration ? timestamp(duration) : 'END';
    let inPercent = 0;
    let outPercent = 100;
    if (hasTimeline) {
      startSlider.max = endSlider.max = String(duration);
      if (valid) {
        startSlider.value = String(section.start);
        endSlider.value = String(section.end);
        inPercent = section.start / duration * 100;
        outPercent = section.end / duration * 100;
      } else {
        startSlider.value = '0';
        endSlider.value = String(duration);
      }
      startSlider.setAttribute('aria-valuetext', timestamp(Number(startSlider.value)));
      endSlider.setAttribute('aria-valuetext', timestamp(Number(endSlider.value)));
      startSlider.style.zIndex = Number(startSlider.value) > duration / 2 ? '5' : '3';
      endSlider.style.zIndex = Number(endSlider.value) <= duration / 2 ? '5' : '4';
    }
    $('timeline').style.setProperty('--in', `${inPercent}%`);
    $('timeline').style.setProperty('--out', `${outPercent}%`);
    const format = outputFormat().toUpperCase();
    $('output-summary').textContent = `${format} / ${isSection ? (valid ? timestamp(section.end - section.start) : 'SECTION') : 'FULL'}`;
    $('output-note').textContent = isSection ? 'ONLY YOUR SELECTED RANGE IS EXPORTED' : (format === 'MP3' ? 'BEST AVAILABLE SOURCE AUDIO' : 'BEST AVAILABLE SOURCE VIDEO + AUDIO');
    $('convert-label').textContent = busy ? 'EXTRACTING…' : `EXTRACT ${format}`;
    $('convert-button').disabled = busy || inspecting;
  }

  function setAccess(text) {
    const led = document.createElement('i');
    led.className = 'led';
    led.setAttribute('aria-hidden', 'true');
    $('access-tag').replaceChildren(led, document.createTextNode(text));
  }

  function setBusy(value) {
    busy = value;
    controls.disabled = value;
    form.setAttribute('aria-busy', String(value));
    updateRange();
  }

  function resetSource() {
    inspectVersion += 1;
    inspecting = false;
    source = null;
    show($('source-info'), false);
    show($('inspect-error'), false);
    $('inspect-button').disabled = false;
    $('inspect-button').innerHTML = 'LOAD <span aria-hidden="true">↗</span>';
    setAccess(urlInput.value.trim() ? 'READY' : 'IDLE');
    updateRange();
  }

  urlInput.addEventListener('input', resetSource);
  // Reveal a collapsed metadata field before native validation focuses it.
  form.addEventListener('invalid', (event) => {
    const details = event.target.closest('details');
    if (details) details.open = true;
  }, true);
  metadataInputs.forEach((input) => input.addEventListener('blur', () => {
    input.value = input.value.trim();
  }));
  form.querySelectorAll('input[name="format"]').forEach((input) => input.addEventListener('change', updateRange));
  form.querySelectorAll('input[name="mode"]').forEach((input) => input.addEventListener('change', () => {
    mode = input.value;
    sectionTouched = false;
    if (mode === 'section' && !endInput.value && source?.duration) endInput.value = timestamp(source.duration);
    updateRange();
  }));
  [startInput, endInput].forEach((input) => {
    input.addEventListener('input', () => { sectionTouched = true; updateRange(); });
    input.addEventListener('blur', () => {
      const seconds = parseTime(input.value);
      if (seconds !== null) input.value = timestamp(seconds);
      updateRange();
    });
  });

  startSlider.addEventListener('input', () => {
    const end = parseTime(endInput.value) ?? source.duration;
    startInput.value = timestamp(Math.max(0, Math.min(Number(startSlider.value), end - 0.1)));
    sectionTouched = true;
    updateRange();
  });
  endSlider.addEventListener('input', () => {
    const start = parseTime(startInput.value) ?? 0;
    endInput.value = timestamp(Math.min(source.duration, Math.max(Number(endSlider.value), start + 0.1)));
    sectionTouched = true;
    updateRange();
  });

  form.querySelectorAll('[data-length]').forEach((button) => button.addEventListener('click', () => {
    const start = parseTime(startInput.value);
    sectionTouched = true;
    if (start !== null) endInput.value = timestamp(start + Number(button.dataset.length));
    updateRange();
  }));
  $('reset-range').addEventListener('click', () => {
    startInput.value = '00:00';
    endInput.value = source?.duration ? timestamp(source.duration) : '';
    sectionTouched = false;
    updateRange();
  });

  async function readResponse(response) {
    let payload;
    try { payload = await response.json(); }
    catch { throw new Error('The local server did not respond. Check that the app is still running.'); }
    if (!response.ok) throw new Error(payload.error || 'The request could not be completed.');
    return payload;
  }

  $('inspect-button').addEventListener('click', async () => {
    if (!urlInput.reportValidity() || busy || inspecting) return;
    const version = ++inspectVersion;
    const requestedUrl = urlInput.value.trim();
    inspecting = true;
    $('inspect-button').disabled = true;
    $('inspect-button').textContent = 'LOADING…';
    show($('inspect-error'), false);
    setAccess('LOADING');
    updateRange();
    try {
      const response = await fetch('/api/inspect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: requestedUrl }) });
      const payload = await readResponse(response);
      if (version !== inspectVersion) return;
      source = payload;
      $('source-title').textContent = source.title;
      $('source-duration').textContent = source.is_live ? 'LIVE' : (source.duration ? timestamp(source.duration) : 'LENGTH UNKNOWN');
      show($('source-info'));
      if (!endInput.value && source.duration) endInput.value = timestamp(source.duration);
      setAccess('LOADED');
    } catch (error) {
      if (version !== inspectVersion) return;
      $('inspect-error').textContent = error.message;
      show($('inspect-error'));
      setAccess('LOAD FAILED');
    } finally {
      if (version === inspectVersion) {
        inspecting = false;
        $('inspect-button').disabled = false;
        $('inspect-button').innerHTML = 'LOAD <span aria-hidden="true">↗</span>';
        updateRange();
      }
    }
  });

  const labels = { queued: 'Queued', inspecting: 'Loading source', retrying: 'Retrying with local cut', downloading: 'Downloading', trimming: 'Cutting section', converting: 'Processing', tagging: 'Writing metadata', saving: 'Saving', done: 'Complete', error: 'Failed' };
  const stages = ['queued', 'inspecting', 'retrying', 'downloading', 'converting', 'trimming', 'tagging', 'saving', 'done'];
  function formatSpeed(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return '';
    const units = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
    let unit = 0;
    while (bytes >= 1024 && unit < units.length - 1) { bytes /= 1024; unit += 1; }
    return `${bytes.toFixed(unit ? 1 : 0)} ${units[unit]}`;
  }

  function fail(message) {
    clearTimeout(pollTimer);
    pollTimer = null;
    setBusy(false);
    show($('status'), false);
    $('error').textContent = message;
    show($('error'));
    setAccess('FAILED');
  }

  function renderJob(job) {
    const hasProgress = Number.isFinite(job.progress);
    const progress = hasProgress ? Math.round(Math.max(0, Math.min(100, job.progress))) : 0;
    $('status-label').textContent = labels[job.status] || 'Processing';
    $('status-percent').textContent = hasProgress ? `${progress}%` : 'WORKING';
    $('progress-bar').style.width = `${progress}%`;
    $('progress-track').classList.toggle('indeterminate', !hasProgress);
    if (hasProgress) $('progress-track').setAttribute('aria-valuenow', String(progress));
    else $('progress-track').removeAttribute('aria-valuenow');
    $('progress-track').setAttribute('aria-valuetext', hasProgress ? `${progress}%` : 'Extracting section; progress unavailable');
    document.querySelectorAll('[data-stage]').forEach((element) => {
      element.classList.toggle('active', element.dataset.stage === job.status);
      element.classList.toggle('complete', stages.indexOf(element.dataset.stage) < stages.indexOf(job.status));
    });
    const details = [];
    if (job.title) details.push(job.title);
    if (Number.isFinite(job.start_time)) details.push(`${timestamp(job.start_time)} → ${timestamp(job.end_time)}`);
    if (job.status === 'downloading' && job.speed) details.push(formatSpeed(job.speed));
    if (job.status === 'downloading' && Number.isFinite(job.eta)) details.push(`ETA ${Math.ceil(job.eta)}s`);
    if (job.message) details.push(job.message);
    $('status-detail').textContent = details.join(' / ');
    if (job.status === 'done') {
      setBusy(false);
      show($('status'), false);
      const format = (job.output_format || outputFormat()).toUpperCase();
      $('result-title').textContent = job.title || `${format} ready`;
      $('result-file').textContent = `Saved in downloads/${job.filename}`;
      $('result-section').textContent = Number.isFinite(job.start_time) ? `${timestamp(job.start_time)} → ${timestamp(job.end_time)} / ${timestamp(job.end_time - job.start_time)} SECTION` : 'FULL SIGNAL / EXTRACTION COMPLETE';
      $('download-link').href = job.download_url;
      $('download-link').textContent = `SAVE ${format} ↗`;
      show($('result'));
      setAccess('COMPLETE');
      return true;
    }
    if (job.status === 'error') { fail(job.error || 'Conversion failed.'); return true; }
    return false;
  }

  async function poll(jobId) {
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { cache: 'no-store' });
      const job = await readResponse(response);
      if (!renderJob(job)) pollTimer = setTimeout(() => poll(jobId), 900);
      else pollTimer = null;
    } catch (error) { fail(`${error.message} Check the terminal before starting another extraction; the current job may still be running.`); }
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (busy || inspecting) return;
    sectionTouched = true;
    updateRange();
    const section = getSection();
    if (section.error) { (parseTime(startInput.value) === null ? startInput : endInput).focus(); return; }
    const payload = { url: urlInput.value.trim(), format: outputFormat() };
    const metadata = Object.fromEntries(metadataInputs.map((input) => [input.dataset.metadata, input.value.trim()]).filter(([, value]) => value));
    if (Object.keys(metadata).length) payload.metadata = metadata;
    if (mode === 'section') { payload.start_time = startInput.value.trim(); payload.end_time = endInput.value.trim(); }
    clearTimeout(pollTimer);
    show($('result'), false);
    show($('error'), false);
    show($('status'));
    $('status-label').textContent = 'Starting';
    $('status-percent').textContent = '0%';
    $('status-detail').textContent = '';
    $('progress-bar').style.width = '0%';
    $('progress-track').classList.remove('indeterminate');
    $('progress-track').setAttribute('aria-valuenow', '0');
    document.querySelectorAll('[data-stage]').forEach((element) => element.classList.remove('active', 'complete'));
    setBusy(true);
    setAccess('EXTRACTING');
    try {
      const response = await fetch('/api/convert', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const job = await readResponse(response);
      await poll(job.job_id);
    } catch (error) { fail(error.message); }
  });

  // Decorative motion never changes native input, keyboard, or touch behavior.
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let motionEnabled = !reducedMotion.matches;
  try { motionEnabled = !reducedMotion.matches && localStorage.getItem('signal-motion') !== 'off'; } catch { /* Storage may be unavailable. */ }
  function applyMotion() {
    document.body.classList.toggle('motion-off', !motionEnabled);
    document.documentElement.style.scrollBehavior = motionEnabled ? '' : 'auto';
    $('motion-toggle').setAttribute('aria-pressed', String(motionEnabled));
    $('motion-toggle').setAttribute('aria-label', reducedMotion.matches ? 'Interface motion disabled by system preference' : 'Interface motion');
    $('motion-state').textContent = motionEnabled ? 'ON' : 'OFF';
    document.dispatchEvent(new CustomEvent('oni:motion', { detail: { enabled: motionEnabled } }));
  }
  $('motion-toggle').addEventListener('click', () => {
    motionEnabled = !motionEnabled && !reducedMotion.matches;
    try { localStorage.setItem('signal-motion', motionEnabled ? 'on' : 'off'); } catch { /* No persistence required. */ }
    applyMotion();
  });
  reducedMotion.addEventListener('change', () => { motionEnabled = !reducedMotion.matches; applyMotion(); });
  applyMotion();
  updateRange();
})();
