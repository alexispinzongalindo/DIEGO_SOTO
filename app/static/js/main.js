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

  function initSpellcheckAutoLang() {
    const targets = Array.prototype.slice.call(document.querySelectorAll('input[spellcheck="true"], textarea[spellcheck="true"]'));
    if (!targets.length) return;

    const spanishCharRe = /[áéíóúñü¡¿]/i;
    const englishWordRe = /\b(the|and|for|with|from|this|that|invoice|quote|bill|purchase|order)\b/i;
    const spanishWordRe = /\b(el|la|los|las|de|del|que|y|para|con|por|una|un|factura|cotizaci[oó]n|cuenta|orden)\b/i;

    function detectLang(text) {
      const t = (text || '').toString();
      if (!t.trim()) return null;

      let scoreEs = 0;
      let scoreEn = 0;

      if (spanishCharRe.test(t)) scoreEs += 3;
      const esMatches = t.match(spanishWordRe);
      const enMatches = t.match(englishWordRe);
      if (esMatches) scoreEs += 2;
      if (enMatches) scoreEn += 2;

      return scoreEs > scoreEn ? 'es' : 'en';
    }

    function setLang(el, lang) {
      if (!lang) return;
      const current = (el.getAttribute('lang') || '').toLowerCase();
      if (current === lang) return;
      el.setAttribute('lang', lang);
    }

    targets.forEach((el) => {
      if (!el.getAttribute('lang')) el.setAttribute('lang', 'en');

      let timer = null;
      const handler = () => {
        if (timer) window.clearTimeout(timer);
        timer = window.setTimeout(() => {
          const lang = detectLang(el.value);
          setLang(el, lang);
        }, 250);
      };

      el.addEventListener('input', handler);
      el.addEventListener('change', handler);
      handler();
    });
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
    try {
      const fmt = new Intl.NumberFormat('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
        useGrouping: true,
      });
      return `$${fmt.format(n)}`;
    } catch (e) {
      return `$${n.toFixed(2)}`;
    }
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

  function initDueDateAuto() {
    function findInvoiceFields() {
      const dateEl = document.querySelector('input[name="date"], input[name$=".date"], input[id$="-date"]');
      const dueEl = document.querySelector('input[name="due_date"], input[name$=".due_date"], input[id$="-due_date"]');
      const termsEl = document.querySelector('input[name="terms"], input[name$=".terms"], input[id$="-terms"]');
      if (!dateEl || !dueEl || !termsEl) return null;
      return { dateEl, dueEl, termsEl };
    }

    function parseDate(value) {
      const raw = (value || '').trim();
      if (!raw) return null;
      if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
        const [y, m, d] = raw.split('-').map(v => parseInt(v, 10));
        return new Date(y, (m || 1) - 1, d || 1);
      }
      if (/^\d{1,2}\/\d{1,2}\/\d{4}$/.test(raw)) {
        const [mm, dd, yyyy] = raw.split('/').map(v => parseInt(v, 10));
        return new Date(yyyy, (mm || 1) - 1, dd || 1);
      }
      const dt = new Date(raw);
      return Number.isFinite(dt.getTime()) ? dt : null;
    }

    function formatDate(dateObj, likeEl) {
      if (!dateObj) return '';
      const y = dateObj.getFullYear();
      const m = String(dateObj.getMonth() + 1).padStart(2, '0');
      const d = String(dateObj.getDate()).padStart(2, '0');
      if (likeEl && (likeEl.type || '').toLowerCase() === 'date') {
        return `${y}-${m}-${d}`;
      }
      return `${m}/${d}/${y}`;
    }

    function parseNetDays(terms) {
      const t = (terms || '').toString().trim().toLowerCase();
      if (!t) return null;
      const m = t.match(/(\d{1,3})/);
      if (!m) return null;
      const n = parseInt(m[1], 10);
      if (!Number.isFinite(n) || n < 0 || n > 3650) return null;
      return n;
    }

    function computeAndSet() {
      const fields = findInvoiceFields();
      if (!fields) return;
      const { dateEl, dueEl, termsEl } = fields;

      if (dueEl.dataset && dueEl.dataset.manual === '1') return;

      const base = parseDate(dateEl.value);
      const days = parseNetDays(termsEl.value);
      if (!base || days === null) return;

      const out = new Date(base.getTime());
      out.setDate(out.getDate() + days);
      dueEl.value = formatDate(out, dueEl);
    }

    const fields = findInvoiceFields();
    if (!fields) return;
    const { dateEl, dueEl, termsEl } = fields;

    dueEl.addEventListener('input', () => {
      if (dueEl.dataset) dueEl.dataset.manual = '1';
    });
    dueEl.addEventListener('change', () => {
      if (dueEl.dataset) dueEl.dataset.manual = '1';
    });

    dateEl.addEventListener('change', computeAndSet);
    termsEl.addEventListener('input', computeAndSet);
    termsEl.addEventListener('change', computeAndSet);

    if (!(dueEl.value || '').trim()) {
      computeAndSet();
    }
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
    const dictationToggleEl = document.getElementById('voiceDictationToggle');
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

    let lastDictationTarget = null;
    function isValidDictationTarget(el) {
      if (!el) return false;
      if (el === transcriptEl || el === responseEl) return false;
      const tag = (el.tagName || '').toLowerCase();
      if (tag === 'textarea') return !el.readOnly && !el.disabled;
      if (tag === 'input') {
        const type = (el.type || '').toLowerCase();
        if (type === 'hidden' || type === 'button' || type === 'submit' || type === 'reset' || type === 'checkbox' || type === 'radio' || type === 'file') {
          return false;
        }
        return !el.readOnly && !el.disabled;
      }
      if (el.isContentEditable) return true;
      return false;
    }

    function insertTextIntoTarget(target, text) {
      if (!isValidDictationTarget(target)) return false;
      const t = (text || '').trim();
      if (!t) return false;

      try {
        if (target.isContentEditable) {
          target.focus();
          document.execCommand('insertText', false, t + ' ');
          return true;
        }

        const start = typeof target.selectionStart === 'number' ? target.selectionStart : (target.value || '').length;
        const end = typeof target.selectionEnd === 'number' ? target.selectionEnd : (target.value || '').length;
        const current = target.value || '';
        const insert = t + ' ';
        target.value = current.slice(0, start) + insert + current.slice(end);
        const nextPos = start + insert.length;
        if (typeof target.setSelectionRange === 'function') {
          target.setSelectionRange(nextPos, nextPos);
        }
        target.dispatchEvent(new Event('input', { bubbles: true }));
        target.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
      } catch (e) {
        return false;
      }
    }

    function isDictationOn() {
      return !!(dictationToggleEl && dictationToggleEl.checked);
    }

    if (dictationToggleEl) {
      const saved = window.localStorage ? window.localStorage.getItem('voice_dictation') : null;
      if (saved === '1') dictationToggleEl.checked = true;
      dictationToggleEl.addEventListener('change', () => {
        if (window.localStorage) {
          window.localStorage.setItem('voice_dictation', dictationToggleEl.checked ? '1' : '0');
        }
      });
    }

    document.addEventListener('focusin', (e) => {
      const target = e.target;
      if (isValidDictationTarget(target)) {
        lastDictationTarget = target;
      }
    });

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

    async function greetThenListen() {
      if (busy) return;
      const activeLang = resolveLang();
      statusEl.textContent = 'Thinking...';
      busy = true;
      try {
        const data = await sendCommand('', activeLang);
        const speakText = data.speak || '';
        responseEl.value = speakText;
        statusEl.textContent = 'Listening...';
        speak(speakText, activeLang, () => {
          setTimeout(() => {
            busy = false;
            startListening(true);
          }, 400);
        });
      } catch (e) {
        busy = false;
        startListening();
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

        greetThenListen();
      });
    }

    recognition.onresult = async (event) => {
      const text = event.results[0][0].transcript;
      transcriptEl.value = text;

      if (isDictationOn()) {
        const ok = insertTextIntoTarget(lastDictationTarget, text);
        if (ok) {
          statusEl.textContent = 'Inserted.';
        } else {
          statusEl.textContent = 'Tap a field first, then try again.';
        }
        return;
      }

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
      initDueDateAuto();
      initSpellcheckAutoLang();
      initVoice();
    });
  } else {
    initTooltips();
    initLineItems();
    initDueDateAuto();
    initSpellcheckAutoLang();
    initVoice();
  }
})();
