(function () {
  const box = document.getElementById('messages');
  const form = document.getElementById('chat-form');
  const input = document.getElementById('chat-text');
  const sendBtn = document.getElementById('send-btn');
  const suggest = document.getElementById('suggest');
  if (!box || !form) return;

  // conversation history sent to the server each turn
  const history = [];

  function add(role, text) {
    const el = document.createElement('div');
    el.className = 'msg ' + (role === 'assistant' ? 'bot' : 'user');
    el.textContent = text;
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
    return el;
  }

  async function ask(text) {
    add('user', text);
    history.push({ role: 'user', text });
    input.value = '';
    input.style.height = 'auto';
    sendBtn.disabled = true;

    const typing = add('assistant', '…');
    typing.classList.add('typing');
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: history }),
      });
      const data = await res.json();
      typing.remove();
      const reply = data.reply || 'Something went wrong.';
      add('assistant', reply);
      if (!data.error) history.push({ role: 'assistant', text: reply });
    } catch (e) {
      typing.remove();
      add('assistant', 'Network error — please try again.');
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const t = input.value.trim();
    if (t) ask(t);
  });

  // Enter to send, Shift+Enter for newline; auto-grow textarea
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  });

  if (suggest) {
    suggest.addEventListener('click', (e) => {
      const q = e.target.dataset.q;
      if (q) ask(q);
    });
  }

  input.focus();
})();
