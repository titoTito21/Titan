// Titan-Net settings page — TTS + notification sounds
(function () {
  'use strict';
  const t = Titan.t;

  const $saved = document.getElementById('settings-saved');

  function flashSaved() {
    $saved.textContent = t('settings.saved');
    clearTimeout(flashSaved._t);
    flashSaved._t = setTimeout(() => { $saved.textContent = ''; }, 1500);
  }

  // ---- TTS ----
  const $ttsEnabled = document.getElementById('tts-enabled');
  const $ttsVoice = document.getElementById('tts-voice');
  const $ttsRate = document.getElementById('tts-rate');
  const $ttsPitch = document.getElementById('tts-pitch');
  const $ttsVolume = document.getElementById('tts-volume');
  const $ttsRateOut = document.getElementById('tts-rate-out');
  const $ttsPitchOut = document.getElementById('tts-pitch-out');
  const $ttsVolumeOut = document.getElementById('tts-volume-out');
  const $ttsEvMsg = document.getElementById('tts-ev-msg');
  const $ttsEvPriv = document.getElementById('tts-ev-priv');
  const $ttsEvPres = document.getElementById('tts-ev-pres');
  const $ttsEvVoice = document.getElementById('tts-ev-voice');
  const $ttsTest = document.getElementById('tts-test');

  function refreshVoiceOptions() {
    if (!Titan.tts) return;
    const voices = Titan.tts.listVoices();
    const p = Titan.tts.getPrefs();
    $ttsVoice.innerHTML = '';
    const def = document.createElement('option');
    def.value = '';
    def.textContent = t('tts.voice.default');
    $ttsVoice.appendChild(def);
    voices.forEach((v) => {
      const opt = document.createElement('option');
      opt.value = v.name;
      opt.textContent = v.name + ' (' + v.lang + ')';
      $ttsVoice.appendChild(opt);
    });
    $ttsVoice.value = p.voice || '';
  }

  function loadTtsFromPrefs() {
    if (!Titan.tts) return;
    const p = Titan.tts.getPrefs();
    $ttsEnabled.checked = !!p.enabled;
    $ttsRate.value = p.rate;
    $ttsPitch.value = p.pitch;
    $ttsVolume.value = p.volume;
    $ttsRateOut.value = Number(p.rate).toFixed(1);
    $ttsPitchOut.value = Number(p.pitch).toFixed(1);
    $ttsVolumeOut.value = Math.round(p.volume * 100) + '%';
    $ttsEvMsg.checked = p.announceMessages;
    $ttsEvPriv.checked = p.announcePrivate;
    $ttsEvPres.checked = p.announcePresence;
    $ttsEvVoice.checked = p.announceVoice;
    refreshVoiceOptions();
  }

  function applyTts() {
    if (!Titan.tts) return;
    Titan.tts.setPrefs({
      enabled: $ttsEnabled.checked,
      voice: $ttsVoice.value,
      rate: parseFloat($ttsRate.value),
      pitch: parseFloat($ttsPitch.value),
      volume: parseFloat($ttsVolume.value),
      announceMessages: $ttsEvMsg.checked,
      announcePrivate: $ttsEvPriv.checked,
      announcePresence: $ttsEvPres.checked,
      announceVoice: $ttsEvVoice.checked,
    });
    $ttsRateOut.value = Number($ttsRate.value).toFixed(1);
    $ttsPitchOut.value = Number($ttsPitch.value).toFixed(1);
    $ttsVolumeOut.value = Math.round(parseFloat($ttsVolume.value) * 100) + '%';
    flashSaved();
  }

  [$ttsEnabled, $ttsVoice, $ttsRate, $ttsPitch, $ttsVolume,
   $ttsEvMsg, $ttsEvPriv, $ttsEvPres, $ttsEvVoice].forEach((el) => {
    el.addEventListener('change', applyTts);
  });
  // Smooth slider feedback without firing setPrefs on every pixel
  [$ttsRate, $ttsPitch, $ttsVolume].forEach((el) => {
    el.addEventListener('input', () => {
      $ttsRateOut.value = Number($ttsRate.value).toFixed(1);
      $ttsPitchOut.value = Number($ttsPitch.value).toFixed(1);
      $ttsVolumeOut.value = Math.round(parseFloat($ttsVolume.value) * 100) + '%';
    });
  });

  $ttsTest.addEventListener('click', () => {
    applyTts();
    Titan.tts.speak(t('tts.test_phrase'), { interrupt: true });
  });

  if (typeof speechSynthesis !== 'undefined'
      && speechSynthesis.addEventListener) {
    speechSynthesis.addEventListener('voiceschanged', refreshVoiceOptions);
  }

  // ---- Sounds ----
  const $sndEnabled = document.getElementById('snd-enabled');
  const $sndVolume = document.getElementById('snd-volume');
  const $sndVolumeOut = document.getElementById('snd-volume-out');
  const $sndEvents = document.getElementById('snd-events');

  function buildEventCheckboxes() {
    if (!Titan.sounds) return;
    const events = Titan.sounds.listEvents();
    const p = Titan.sounds.getPrefs();
    $sndEvents.innerHTML = '';
    events.forEach((ev) => {
      const row = document.createElement('div');
      row.style.display = 'flex';
      row.style.alignItems = 'center';
      row.style.gap = '.5rem';

      const label = document.createElement('label');
      label.style.flex = '1';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.style.minHeight = 'auto';
      cb.style.width = 'auto';
      cb.id = 'snd-ev-' + ev.id;
      cb.dataset.event = ev.id;
      cb.checked = p.events[ev.id] !== false;
      cb.addEventListener('change', applySounds);
      const txt = document.createElement('span');
      txt.textContent = t(ev.labelKey);
      label.appendChild(cb);
      label.appendChild(document.createTextNode(' '));
      label.appendChild(txt);

      const test = document.createElement('button');
      test.type = 'button';
      test.className = 'btn btn-secondary';
      test.textContent = t('settings.sounds.test');
      test.addEventListener('click', () => Titan.sounds.playFile(ev.file));

      row.appendChild(label);
      row.appendChild(test);
      $sndEvents.appendChild(row);
    });
  }

  function loadSoundsFromPrefs() {
    if (!Titan.sounds) return;
    const p = Titan.sounds.getPrefs();
    $sndEnabled.checked = !!p.enabled;
    $sndVolume.value = p.volume;
    $sndVolumeOut.value = Math.round(p.volume * 100) + '%';
    buildEventCheckboxes();
  }

  function applySounds() {
    if (!Titan.sounds) return;
    const eventsPatch = {};
    $sndEvents.querySelectorAll('input[type="checkbox"][data-event]').forEach((cb) => {
      eventsPatch[cb.dataset.event] = cb.checked;
    });
    Titan.sounds.setPrefs({
      enabled: $sndEnabled.checked,
      volume: parseFloat($sndVolume.value),
      events: eventsPatch,
    });
    $sndVolumeOut.value = Math.round(parseFloat($sndVolume.value) * 100) + '%';
    flashSaved();
  }

  $sndEnabled.addEventListener('change', applySounds);
  $sndVolume.addEventListener('change', applySounds);
  $sndVolume.addEventListener('input', () => {
    $sndVolumeOut.value = Math.round(parseFloat($sndVolume.value) * 100) + '%';
  });

  // ---- Reset ----
  document.getElementById('settings-reset').addEventListener('click', () => {
    if (!confirm(t('settings.reset.confirm'))) return;
    try { localStorage.removeItem('titan.tts'); } catch (e) {}
    try { localStorage.removeItem('titan.sounds'); } catch (e) {}
    location.reload();
  });

  // ---- Re-translate dynamic content when language switches ----
  window.onLangChanged = function () {
    buildEventCheckboxes();
  };

  loadTtsFromPrefs();
  loadSoundsFromPrefs();
})();
