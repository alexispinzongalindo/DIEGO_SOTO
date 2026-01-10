(function () {
  'use strict';

  function speak(text) {
    if (!('speechSynthesis' in window)) return;
    if (!text) return;
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.rate = 1;
    utter.pitch = 1;
    window.speechSynthesis.speak(utter);
  }

  async function sendCommand(text) {
    const res = await fetch('/office/assistant/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
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
    if (!startBtn || !statusEl || !transcriptEl || !responseEl) return;

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      statusEl.textContent = 'Voice recognition is not supported in this browser.';
      startBtn.disabled = true;
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = 'en-US';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    let busy = false;

    startBtn.addEventListener('click', () => {
      if (busy) return;
      transcriptEl.value = '';
      responseEl.value = '';
      statusEl.textContent = 'Listening...';
      try {
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
        const data = await sendCommand(text);
        const speakText = data.speak || '';
        responseEl.value = speakText;
        statusEl.textContent = 'Done.';
        speak(speakText);
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
