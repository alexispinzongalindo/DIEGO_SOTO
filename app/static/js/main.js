(function () {
  'use strict';

  function speak(text, lang) {
    if (!('speechSynthesis' in window)) return;
    if (!text) return;
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    if (lang) {
      utter.lang = lang;
      const voices = window.speechSynthesis.getVoices ? window.speechSynthesis.getVoices() : [];
      const match = voices.find(v => (v.lang || '').toLowerCase() === lang.toLowerCase()) ||
        voices.find(v => (v.lang || '').toLowerCase().startsWith(lang.slice(0, 2).toLowerCase()));
      if (match) utter.voice = match;
    }
    utter.rate = 1;
    utter.pitch = 1;
    window.speechSynthesis.speak(utter);
  }

  async function sendCommand(text, lang) {
    const res = await fetch('/office/assistant/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, lang })
    });
    if (!res.ok) {
      throw new Error('Request failed');
    }
    return await res.json();
  }

  function initVoice() {
    const startBtn = document.getElementById('voiceStartBtn');
    const statusEl = document.getElementById('voiceStatus');
    const transcriptEl = document.getElementById('voiceTranscript');
    const responseEl = document.getElementById('voiceResponse');
    const langEl = document.getElementById('voiceLang');
    if (!startBtn || !statusEl || !transcriptEl || !responseEl) return;

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      statusEl.textContent = 'Voice recognition is not supported in this browser.';
      startBtn.disabled = true;
      return;
    }

    const recognition = new SpeechRecognition();
    function resolveLang() {
      const selected = langEl ? (langEl.value || 'auto') : 'auto';
      if (selected !== 'auto') return selected;
      return (navigator.language || 'en-US');
    }

    if (langEl) {
      const saved = window.localStorage ? window.localStorage.getItem('voice_lang') : null;
      if (saved) {
        langEl.value = saved;
      } else {
        const guess = (navigator.language || '').toLowerCase();
        if (guess.startsWith('es')) langEl.value = 'es-ES';
      }
      langEl.addEventListener('change', () => {
        if (window.localStorage) {
          window.localStorage.setItem('voice_lang', langEl.value);
        }
      });
    }

    recognition.lang = resolveLang();
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    let busy = false;

    startBtn.addEventListener('click', () => {
      if (busy) return;
      transcriptEl.value = '';
      responseEl.value = '';
      statusEl.textContent = 'Listening...';
      try {
        recognition.lang = resolveLang();
        recognition.start();
      } catch (e) {
        // ignore
      }
    });

    recognition.onresult = async (event) => {
      const text = event.results[0][0].transcript;
      transcriptEl.value = text;
      statusEl.textContent = 'Thinking...';
      busy = true;
      try {
        const activeLang = resolveLang();
        const data = await sendCommand(text, activeLang);
        const speakText = data.speak || '';
        responseEl.value = speakText;
        statusEl.textContent = 'Done.';
        speak(speakText, activeLang);
        if (data.redirect_url) {
          setTimeout(() => {
            window.location.href = data.redirect_url;
          }, 800);
        }
      } catch (e) {
        statusEl.textContent = 'Error. Try again.';
      } finally {
        busy = false;
      }
    };

    recognition.onerror = () => {
      statusEl.textContent = 'Could not hear you. Try again.';
    };

    recognition.onend = () => {
      if (!busy && statusEl.textContent === 'Listening...') {
        statusEl.textContent = 'No speech detected.';
      }
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initVoice);
  } else {
    initVoice();
  }
})();
