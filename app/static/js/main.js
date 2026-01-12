(function () {
  'use strict';

  function speak(text, lang, onEnd) {
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
    if (typeof onEnd === 'function') {
      utter.onend = () => {
        try {
          onEnd();
        } catch (e) {
          // ignore
        }
      };
    }
    window.speechSynthesis.speak(utter);
  }

  function initTooltips() {
    if (!window.bootstrap || !window.bootstrap.Tooltip) return;
    const triggers = Array.prototype.slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    triggers.forEach((el) => {
      try {
        new window.bootstrap.Tooltip(el);
      } catch (e) {
        // ignore
      }
    });
  }

  function parseNumber(val) {
    const n = parseFloat((val || '').toString().replace(/[^0-9.-]/g, ''));
    return Number.isFinite(n) ? n : 0;
  }

  function formatMoney(amount) {
    const n = Number.isFinite(amount) ? amount : 0;
    return `$${n.toFixed(2)}`;
  }

  function initLineItems() {
    const tables = Array.prototype.slice.call(document.querySelectorAll('[data-line-items-table]'));
    if (!tables.length) return;

    function getRowInputs(row) {
      const inputs = row.querySelectorAll('input, select, textarea');
      const out = {};
      inputs.forEach((el) => {
        const name = (el.getAttribute('name') || '').toLowerCase();
        if (name.endsWith('quantity')) out.qty = el;
        if (name.endsWith('unit_price')) out.price = el;
        if (name.endsWith('description')) out.desc = el;
      });
      return out;
    }

    function isRowBlank(row) {
      const { qty, price, desc } = getRowInputs(row);
      const d = (desc && desc.value ? desc.value : '').trim();
      const q = qty ? qty.value : '';
      const p = price ? price.value : '';
      return !d && !q && !p;
    }

    function renumberAndToggleRows(table) {
      const tbody = table.tBodies && table.tBodies[0];
      if (!tbody) return;
      const rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));

      let lastNonBlankIndex = -1;
      rows.forEach((row, idx) => {
        const numCell = row.querySelector('[data-line-number]');
        if (numCell) numCell.textContent = String(idx + 1);
        if (!isRowBlank(row)) lastNonBlankIndex = idx;
      });

      rows.forEach((row, idx) => {
        const show = idx <= lastNonBlankIndex + 1;
        row.classList.toggle('d-none', !show);
      });
    }

    function findTaxAmountInput(root) {
      // Works for invoice/quote/bill/po pages where `tax` is a single input in the form
      const scope = root || document;
      return scope.querySelector('input[name$="tax"]');
    }

    function findTotalsContainer(table) {
      // Prefer the nearest card (invoice/quote/bill), but support PO where totals live outside a card
      let el = table.closest('.card');
      if (el && el.querySelector('[data-subtotal], [data-tax], [data-total]')) return el;

      // Walk up the DOM until we find a container that has the totals spans
      let cur = table.parentElement;
      while (cur) {
        if (cur.querySelector && cur.querySelector('[data-subtotal], [data-tax], [data-total]')) {
          return cur;
        }
        cur = cur.parentElement;
      }
      return null;
    }

    function calculateTotals(table) {
      const tbody = table.tBodies && table.tBodies[0];
      if (!tbody) return;
      const rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));

      let subtotal = 0;
      rows.forEach((row) => {
        const { qty, price } = getRowInputs(row);
        const q = parseNumber(qty ? qty.value : 0);
        const p = parseNumber(price ? price.value : 0);
        if (q > 0 && p >= 0) subtotal += q * p;
      });

      const root = table.closest('form') || document;
      const taxRateEl = root.querySelector('[data-tax-rate]');
      const taxAmountEl = findTaxAmountInput(root);
      let taxAmount = parseNumber(taxAmountEl ? taxAmountEl.value : 0);

      if (taxRateEl && taxRateEl === document.activeElement) {
        // user is editing %, keep amount in sync
        const rate = parseNumber(taxRateEl.value);
        taxAmount = subtotal * (rate / 100);
        if (taxAmountEl) taxAmountEl.value = taxAmount ? taxAmount.toFixed(2) : '';
      } else if (taxRateEl && taxAmountEl && taxAmountEl === document.activeElement) {
        // user is editing amount, leave it
      } else if (taxRateEl && taxRateEl.value) {
        // if % is set, recompute amount to stay consistent
        const rate = parseNumber(taxRateEl.value);
        taxAmount = subtotal * (rate / 100);
        if (taxAmountEl) taxAmountEl.value = taxAmount ? taxAmount.toFixed(2) : '';
      } else {
        // no % set, use typed amount
        taxAmount = parseNumber(taxAmountEl ? taxAmountEl.value : 0);
      }

      const total = subtotal + taxAmount;
      const totalsContainer = findTotalsContainer(table);
      const subtotalEl = totalsContainer ? totalsContainer.querySelector('[data-subtotal]') : null;
      const taxEl = totalsContainer ? totalsContainer.querySelector('[data-tax]') : null;
      const totalEl = totalsContainer ? totalsContainer.querySelector('[data-total]') : null;
      if (subtotalEl) subtotalEl.textContent = formatMoney(subtotal);
      if (taxEl) taxEl.textContent = formatMoney(taxAmount);
      if (totalEl) totalEl.textContent = formatMoney(total);
    }

    function wireTable(table) {
      renumberAndToggleRows(table);
      calculateTotals(table);

      table.addEventListener('input', () => {
        renumberAndToggleRows(table);
        calculateTotals(table);
      });

      const addBtn = document.querySelector(`[data-add-line-for="${table.id}"]`);
      if (addBtn) {
        addBtn.addEventListener('click', () => {
          const tbody = table.tBodies && table.tBodies[0];
          if (!tbody) return;
          const rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
          const hidden = rows.find(r => r.classList.contains('d-none'));
          if (hidden) {
            hidden.classList.remove('d-none');
            const { desc } = getRowInputs(hidden);
            if (desc) desc.focus();
          }
          renumberAndToggleRows(table);
          calculateTotals(table);
        });
      }

      const root = table.closest('form') || document;
      const taxRateEl = root.querySelector('[data-tax-rate]');
      const taxAmountEl = findTaxAmountInput(root);
      if (taxRateEl) {
        taxRateEl.addEventListener('input', () => calculateTotals(table));
      }
      if (taxAmountEl) {
        taxAmountEl.addEventListener('input', () => calculateTotals(table));
      }
    }

    tables.forEach(wireTable);
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
    const micBtn = document.getElementById('voiceMicBtn');
    const modalEl = document.getElementById('voiceAssistantModal');
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
    let collecting = false;
    let pendingQuestions = [];
    let collectedAnswers = [];
    let lastIntent = '';
    let awaitingConfirm = false;
    let confirmCommandText = '';
    let confirmLang = '';

    function isYes(text) {
      const t = (text || '').trim().toLowerCase();
      return t === 'yes' || t === 'y' || t === 'si' || t === 'sí' || t === 'ok' || t === 'okay' || t === 'confirm' || t === 'confirmar';
    }

    function isNo(text) {
      const t = (text || '').trim().toLowerCase();
      return t === 'no' || t === 'n' || t === 'cancel' || t === 'cancelar';
    }

    function extractNumberedQuestions(text) {
      if (!text) return [];
      const out = [];
      const re = /(?:^|\n)\s*\d+\.\s*([^\n]+)/g;
      let m;
      while ((m = re.exec(text)) !== null) {
        const q = (m[1] || '').trim();
        if (q) out.push(q);
      }
      return out;
    }

    function askNextQuestion() {
      const activeLang = resolveLang();
      const q = pendingQuestions[0];
      responseEl.value = q || '';
      statusEl.textContent = 'Answer...';
      speak(q, activeLang, () => {
        setTimeout(() => {
          startListening(true);
        }, 1200);
      });
    }

    async function finalizeCollected() {
      const activeLang = resolveLang();
      const parts = [];
      for (let i = 0; i < collectedAnswers.length; i++) {
        const q = collectedAnswers[i].q;
        const a = collectedAnswers[i].a;
        parts.push(`${i + 1}. ${q}: ${a}`);
      }
      const finalText = `${lastIntent}\n\nDetails:\n${parts.join('\n')}`.trim();
      statusEl.textContent = 'Thinking...';
      busy = true;
      try {
        const data = await sendCommand(finalText, activeLang);
        const speakText = data.speak || '';
        responseEl.value = speakText;
        statusEl.textContent = 'Done.';
        if (data.needs_confirm) {
          awaitingConfirm = true;
          confirmLang = activeLang;
          confirmCommandText = `${finalText} confirm=true`;
          statusEl.textContent = 'Confirm?';
          speak(speakText, activeLang, () => {
            setTimeout(() => {
              startListening(true);
            }, 800);
          });
          return;
        }

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
    }

    function startListening(preserveResponse) {
      if (busy) return;
      transcriptEl.value = '';
      if (!preserveResponse) {
        responseEl.value = '';
      }
      statusEl.textContent = 'Listening...';
      try {
        recognition.lang = resolveLang();
        recognition.start();
      } catch (e) {
        // ignore
      }
    }

    startBtn.addEventListener('click', () => {
      startListening();
    });

    if (micBtn) {
      micBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === 'function') {
          e.stopImmediatePropagation();
        }

        if (modalEl && window.bootstrap && window.bootstrap.Modal) {
          try {
            window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
          } catch (err) {
            // ignore
          }
        }

        startListening();
      });
    }

    recognition.onresult = async (event) => {
      const text = event.results[0][0].transcript;
      transcriptEl.value = text;

      if (awaitingConfirm) {
        if (isYes(text)) {
          awaitingConfirm = false;
          const activeLang = confirmLang || resolveLang();
          statusEl.textContent = 'Thinking...';
          busy = true;
          try {
            const data = await sendCommand(confirmCommandText, activeLang);
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
          return;
        }

        if (isNo(text)) {
          awaitingConfirm = false;
          confirmCommandText = '';
          confirmLang = '';
          const activeLang = confirmLang || resolveLang();
          const msg = (activeLang || '').toLowerCase().startsWith('es') ? 'Cancelado.' : 'Cancelled.';
          responseEl.value = msg;
          statusEl.textContent = 'Done.';
          speak(msg, activeLang);
          return;
        }

        statusEl.textContent = 'Say yes or no.';
        const activeLang = confirmLang || resolveLang();
        speak((activeLang || '').toLowerCase().startsWith('es') ? 'Di sí o no.' : 'Say yes or no.', activeLang, () => {
          setTimeout(() => {
            startListening(true);
          }, 600);
        });
        return;
      }

      if (collecting) {
        const currentQ = pendingQuestions.shift();
        collectedAnswers.push({ q: currentQ, a: text });
        if (pendingQuestions.length > 0) {
          askNextQuestion();
          return;
        }
        collecting = false;
        await finalizeCollected();
        return;
      }

      statusEl.textContent = 'Thinking...';
      busy = true;
      try {
        const activeLang = resolveLang();
        const data = await sendCommand(text, activeLang);
        const speakText = data.speak || '';

        const questions = extractNumberedQuestions(speakText);
        if (questions.length >= 2) {
          collecting = true;
          pendingQuestions = questions.slice();
          collectedAnswers = [];
          lastIntent = text;
          busy = false;
          askNextQuestion();
          return;
        }

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
        if (!collecting) {
          busy = false;
        }
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
    document.addEventListener('DOMContentLoaded', () => {
      initTooltips();
      initLineItems();
      initVoice();
    });
  } else {
    initTooltips();
    initLineItems();
    initVoice();
  }
})();
