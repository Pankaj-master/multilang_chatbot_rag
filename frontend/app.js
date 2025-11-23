// frontend/app.js
const BACKEND = (function(){
  // change this if your node backend runs on a different host/port
  return (window.__BACKEND_URL__ && window.__BACKEND_URL__) || 'http://localhost:8001';
})();

const chatWindow = document.getElementById('chat-window');
const input = document.getElementById('user-text');
const sendBtn = document.getElementById('send');
const clearBtn = document.getElementById('clear');
const backendUrlEl = document.getElementById('backend-url');

backendUrlEl.textContent = BACKEND;

// returns the wrapper element (so caller can remove/replace it if needed)
function appendMessage(role, text) {
  const wrapper = document.createElement('div');
  wrapper.className = role === 'user' ? 'flex justify-end' : 'flex justify-start';

  const bubble = document.createElement('div');
  bubble.className = role === 'user'
    ? 'bg-sky-600 text-white px-4 py-2 rounded-2xl rounded-br-none max-w-[80%] whitespace-pre-wrap'
    : 'bg-slate-100 text-slate-900 px-4 py-2 rounded-2xl rounded-bl-none max-w-[80%] whitespace-pre-wrap';

  // allow passing an Element as text (for details block etc)
  if (typeof text === 'string') {
    bubble.textContent = text;
  } else if (text instanceof Node) {
    bubble.appendChild(text);
  } else {
    bubble.textContent = String(text);
  }

  wrapper.appendChild(bubble);
  chatWindow.appendChild(wrapper);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return wrapper;
}

async function sendMessage(text) {
  if (!text) return;
  // append user message
  appendMessage('user', text);

  // create assistant placeholder (so we can replace it later)
  const placeholder = appendMessage('assistant', '…Thinking…');

  // disable UI while awaiting
  sendBtn.disabled = true;
  input.disabled = true;

  try {
    const resp = await fetch(`${BACKEND}/chat/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, language: 'en', history: [] })
    });

    // try parse JSON even for non-200 to get debug field
    const data = await resp.json().catch(() => null);

    // remove placeholder
    placeholder.remove();

    if (resp.ok && data && data.answer) {
      appendMessage('assistant', data.answer);

      // optionally show retrieved sources in console
      if (data.sources) console.log('Sources:', data.sources);

      // if you want a collapsed raw view in dev:
      if (data.raw) {
        const details = document.createElement('details');
        details.className = 'text-xs text-slate-400 mt-2';
        const summary = document.createElement('summary');
        summary.textContent = 'Show raw response';
        const pre = document.createElement('pre');
        pre.style.whiteSpace = 'pre-wrap';
        pre.style.maxHeight = '240px';
        pre.style.overflow = 'auto';
        pre.textContent = (typeof data.raw === 'string') ? data.raw : JSON.stringify(data.raw, null, 2);
        details.appendChild(summary);
        details.appendChild(pre);
        const detailsWrapper = document.createElement('div');
        detailsWrapper.className = 'flex justify-start';
        const bubble = document.createElement('div');
        bubble.className = 'bg-white border px-4 py-2 rounded-2xl rounded-bl-none max-w-[80%] whitespace-pre-wrap';
        bubble.appendChild(details);
        detailsWrapper.appendChild(bubble);
        chatWindow.appendChild(detailsWrapper);
        chatWindow.scrollTop = chatWindow.scrollHeight;
      }
    } else {
      // non-200 or missing reply
      const err = (data && (data.debug || data.error)) ? (data.debug || data.error) : (resp.statusText || 'Unknown error');
      appendMessage('assistant', `Error: ${typeof err === 'object' ? JSON.stringify(err) : err}`);
    }
  } catch (e) {
    // network or other failure
    placeholder.remove();
    appendMessage('assistant', `Network error: ${e.message || e}`);
  } finally {
    sendBtn.disabled = false;
    input.disabled = false;
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }
}

// wire UI actions
sendBtn.addEventListener('click', () => {
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  sendMessage(text);
});

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendBtn.click();
  }
});

clearBtn.addEventListener('click', () => {
  chatWindow.innerHTML = '';
  input.focus();
});