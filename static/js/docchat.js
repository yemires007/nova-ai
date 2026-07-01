(function () {
  const wrap = document.querySelector('.doc-chat');
  if (!wrap) return;
  const docId = parseInt(wrap.dataset.doc, 10);
  const box = document.getElementById('messages');
  const form = document.getElementById('doc-form');
  const input = document.getElementById('doc-text');
  const sendBtn = document.getElementById('doc-send');

  function add(role, text, rich) {
    const el = document.createElement('div');
    el.className = 'msg ' + (role === 'assistant' ? 'bot' : 'user');
    if (rich && role === 'assistant' && window.NovaRender) window.NovaRender(el, text);
    else el.textContent = text;
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
    return el;
  }

  async function ask(q) {
    add('user', q);
    input.value = ''; input.style.height = 'auto'; sendBtn.disabled = true;
    const typing = add('assistant', '● ● ●'); typing.classList.add('typing');
    try {
      const res = await fetch('/api/docchat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc_id: docId, question: q }),
      });
      const d = await res.json();
      typing.remove();
      add('assistant', d.reply || 'Something went wrong.', !d.error);
    } catch (e) {
      typing.remove();
      add('assistant', 'Network error — please try again.');
    } finally { sendBtn.disabled = false; input.focus(); }
  }

  form.addEventListener('submit', function (e) { e.preventDefault(); const q = input.value.trim(); if (q) ask(q); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
  input.addEventListener('input', function () { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 160) + 'px'; });
  input.focus();
})();
