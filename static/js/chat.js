(function () {
  const box = document.getElementById('messages');
  const form = document.getElementById('chat-form');
  const input = document.getElementById('chat-text');
  const sendBtn = document.getElementById('send-btn');
  const suggest = document.getElementById('suggest');
  if (!box || !form) return;

  // ---- config libs ----
  if (window.marked) marked.setOptions({ breaks: true, gfm: true });
  if (window.mermaid) mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral' });

  // ---- state (persisted server-side for logged-in users) ----
  const data = JSON.parse(document.getElementById('nova-data').textContent || '{}');
  let conversationId = data.conversationId || null;
  const history = [];

  function renderRich(el, text) {
    // markdown -> sanitized HTML
    let html = window.marked ? marked.parse(text) : text.replace(/&/g, '&amp;').replace(/</g, '&lt;');
    el.innerHTML = window.DOMPurify ? DOMPurify.sanitize(html) : html;
    // mermaid: turn ```mermaid code blocks into diagrams
    el.querySelectorAll('pre code.language-mermaid').forEach((code, i) => {
      const holder = document.createElement('div');
      holder.className = 'mermaid';
      holder.textContent = code.textContent;
      code.closest('pre').replaceWith(holder);
    });
    if (window.mermaid) {
      try { mermaid.run({ nodes: el.querySelectorAll('.mermaid') }); } catch (e) {}
    }
    // syntax highlight remaining code blocks
    if (window.hljs) el.querySelectorAll('pre code').forEach((c) => { try { hljs.highlightElement(c); } catch (e) {} });
    // math
    if (window.renderMathInElement) {
      try {
        renderMathInElement(el, {
          delimiters: [{ left: '$$', right: '$$', display: true },
                       { left: '\\(', right: '\\)', display: false },
                       { left: '\\[', right: '\\]', display: true }],
          throwOnError: false,
        });
      } catch (e) {}
    }
  }

  function add(role, text, rich) {
    const el = document.createElement('div');
    el.className = 'msg ' + (role === 'assistant' ? 'bot' : 'user');
    if (rich && role === 'assistant') renderRich(el, text);
    else el.textContent = text;
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
    return el;
  }

  async function ask(text) {
    add('user', text);
    history.push({ role: 'user', text });
    input.value = ''; input.style.height = 'auto'; sendBtn.disabled = true;
    const typing = add('assistant', '● ● ●'); typing.classList.add('typing');
    try {
      const personaEl = document.getElementById('persona');
      const res = await fetch('/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: history, conversation_id: conversationId,
                               persona: personaEl ? personaEl.value : 'default' }),
      });
      const d = await res.json();
      typing.remove();
      const reply = d.reply || 'Something went wrong.';
      add('assistant', reply, !d.error);
      if (!d.error) {
        history.push({ role: 'assistant', text: reply });
        if (d.conversation_id) conversationId = d.conversation_id;
        if (d.notice) add('assistant', 'ℹ️ ' + d.notice);
      }
    } catch (e) {
      typing.remove();
      add('assistant', 'Network error — please try again.');
    } finally {
      sendBtn.disabled = false; input.focus();
    }
  }

  // preload a saved conversation
  if (Array.isArray(data.preload) && data.preload.length) {
    data.preload.forEach((m) => {
      add(m.role, m.text, m.role === 'assistant');
      history.push({ role: m.role, text: m.text });
    });
  } else {
    add('assistant', "Hi! I'm Nova. Ask me anything — I can format code, tables, math and diagrams.");
  }

  form.addEventListener('submit', (e) => { e.preventDefault(); const t = input.value.trim(); if (t) ask(t); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
  input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 160) + 'px'; });
  if (suggest) suggest.addEventListener('click', (e) => { const q = e.target.dataset.q; if (q) ask(q); });
  input.focus();
})();
