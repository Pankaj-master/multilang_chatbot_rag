# Frontend for multilang_chatbot_rag (React + Tailwind)

This single file contains the full frontend scaffold you'll drop into `frontend/src/`.

---

## package.json

```json
{
  "name": "multilang-chatbot-rag-frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "18.2.0",
    "react-dom": "18.2.0",
    "axios": "1.4.0",
    "clsx": "1.2.1"
  },
  "devDependencies": {
    "vite": "5.0.0",
    "tailwindcss": "3.5.0",
    "autoprefixer": "10.4.14",
    "postcss": "8.4.24"
  }
}
```

---

## Tailwind setup (put this in `tailwind.config.cjs` and `postcss.config.cjs`)

`tailwind.config.cjs`:

```js
module.exports = {
  content: ["./index.html","./src/**/*.{js,jsx,ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
}
```

`postcss.config.cjs`:

```js
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  }
}
```

---

## src/index.css

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #root { height: 100%; }
body { @apply bg-slate-50 text-slate-900; }
```

---

## src/main.jsx

```jsx
import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

---

## src/App.jsx

```jsx
import React from 'react'
import Chatbot from './pages/Chatbot'

export default function App(){
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-4xl">
        <Chatbot />
      </div>
    </div>
  )
}
```

---

## src/pages/Chatbot.jsx
```jsx
import { useState } from "react";
import ChatInterface from "../components/ChatInterface";

export default function Chatbot() {
  const [messages, setMessages] = useState([]);

  return (
    <div className="w-full h-screen bg-gray-100 flex items-center justify-center p-4">
      <div className="w-full max-w-3xl bg-white shadow-xl rounded-2xl p-4 h-full overflow-hidden">
        <ChatInterface messages={messages} setMessages={setMessages} />
      </div>
    </div>
  );
}
```jsx
import React, { useState, useEffect } from 'react'
import ChatInterface from '../components/ChatInterface'

export default function Chatbot(){
  return (
    <div className="bg-white rounded-2xl shadow p-6">
      <header className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold">Ayurvedic Nutrition — Knowledge Chat</h1>
        <div className="text-sm text-slate-500">Multilingual • RAG-powered</div>
      </header>

      <ChatInterface />
    </div>
  )
}
```

---

## src/components/ChatInterface.jsx
```jsx
import { useState } from "react";
import { sendMessage } from "../api/rag";

export default function ChatInterface({ messages, setMessages }) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSend = async () => {
    if (!input.trim()) return;

    const userMessage = { sender: "user", text: input };
    setMessages((prev) => [...prev, userMessage]);

    setLoading(true);
    const response = await sendMessage(input);
    setLoading(false);

    const botMessage = { sender: "bot", text: response?.answer || "No response" };
    setMessages((prev) => [...prev, botMessage]);
    setInput("");
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto space-y-3 p-3 bg-gray-50 rounded-xl">
        {messages.map((msg, index) => (
          <div
            key={index}
            className={`p-3 rounded-xl max-w-[80%] ${msg.sender === "user" ? "bg-blue-500 text-white self-end" : "bg-gray-200 text-black self-start"}`}
          >
            {msg.text}
          </div>
        ))}

        {loading && <div className="text-gray-400">Thinking...</div>}
      </div>

      <div className="flex items-center gap-2 mt-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="flex-1 p-3 border rounded-xl"
          placeholder="Ask something..."
        />
        <button
          onClick={handleSend}
          className="px-4 py-3 bg-green-600 text-white rounded-xl"
        >
          Send
        </button>
      </div>
    </div>
  );
}
```jsx
import React, { useState, useRef } from 'react'
import axios from 'axios'
import Carousel from './Carousel'
import ImageCard from './ImageCard'

export default function ChatInterface(){
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [language, setLanguage] = useState('en')
  const messagesRef = useRef(null)

  function appendMessage(msg){
    setMessages(m => [...m, msg])
    setTimeout(()=> messagesRef.current?.scrollTo({ top: messagesRef.current.scrollHeight, behavior: 'smooth' }), 50)
  }

  async function handleSend(e){
    e?.preventDefault()
    if(!input.trim()) return
    const userMsg = {role:'user', text: input, lang: language, id: Date.now()}
    appendMessage(userMsg)
    setInput('')
    setLoading(true)
    try{
      const payload = {query: userMsg.text, lang: userMsg.lang}
      const res = await axios.post('/chat', payload)
      // expect backend schema: {answer:..., cards:[{title,desc,image,action}], citations:[]}
      const data = res.data
      const botMsg = {role:'assistant', text: data.answer||'No answer found', meta: data, id: Date.now()+1}
      appendMessage(botMsg)
      // if cards provided show carousel
      if(data.cards && Array.isArray(data.cards) && data.cards.length>0){
        appendMessage({role:'assistant_cards', cards: data.cards, id: Date.now()+2})
      }
    }catch(err){
      appendMessage({role:'assistant', text: 'Error: '+(err?.message||'request failed')})
    }finally{ setLoading(false) }
  }

  return (
    <div>
      <div ref={messagesRef} className="h-80 overflow-y-auto border rounded p-4 mb-4 bg-slate-50">
        {messages.map(m => (
          <div key={m.id} className={m.role==='user'? 'text-right mb-3':'text-left mb-3'}>
            <div className={`inline-block p-3 rounded-lg ${m.role==='user'? 'bg-indigo-600 text-white' : 'bg-white text-slate-800 border'}`}>
              {m.text}
            </div>
            {m.role==='assistant_cards' && (
              <div className="mt-2">
                <Carousel items={m.cards} />
              </div>
            )}
          </div>
        ))}
      </div>

      <form onSubmit={handleSend} className="flex gap-2">
        <select value={language} onChange={e=>setLanguage(e.target.value)} className="border rounded px-2">
          <option value="en">English</option>
          <option value="hi">हिन्दी</option>
          <option value="mr">मराठी</option>
          <option value="ta">தமிழ்</option>
        </select>
        <input value={input} onChange={e=>setInput(e.target.value)} placeholder="Ask about grains, lentils, vegetables..." className="flex-1 border rounded px-3 py-2" />
        <button type="submit" disabled={loading} className="bg-indigo-600 text-white px-4 rounded">{loading? '...' : 'Send'}</button>
      </form>
    </div>
  )
}
```

---

## src/components/Carousel.jsx

```jsx
import React from 'react'
import ImageCard from './ImageCard'

export default function Carousel({items=[]}){
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {items.map((c, idx)=> (
        <ImageCard key={idx} item={c} />
      ))}
    </div>
  )
}
```

---

## src/components/ImageCard.jsx

```jsx
import React from 'react'

export default function ImageCard({item}){
  return (
    <div className="bg-white border rounded-lg p-3 shadow-sm">
      {item.image && <img src={item.image} alt={item.title} className="w-full h-36 object-cover rounded" />}
      <h3 className="mt-2 font-semibold">{item.title}</h3>
      <p className="text-sm text-slate-600">{item.description || item.desc}</p>
      {item.action && <div className="mt-2"><a href={item.action.url||'#'} className="text-indigo-600 text-sm">{item.action.label||'Learn more'}</a></div>}
    </div>
  )
}
```

---

## src/api/rag.js

```js
import axios from 'axios'

export async function queryChat(query, lang='en'){
  const res = await axios.post('/chat', { query, lang })
  return res.data
}

export default { queryChat }
```

---

## src/utils/converters.js

```js
export function safeTrim(s){ return typeof s==='string'? s.trim(): s }

export function toCardsFromKB(v){
  // converts knowledge-base citations to UI cards; placeholder mapping
  if(!v) return []
  return v.map(item=>({title: item.title || item.doc_id, description: item.snippet||item.text_snippet, image: item.image, action: {url: item.url}}))
}
```

---

## src/utils/parser.js

```js
export function parseBackendResponse(resp){
  // generic parser to normalize backend responses into {answer,cards}
  if(!resp) return { answer: '', cards: [] }
  const answer = resp.answer || resp.text || resp.output || ''
  let cards = resp.cards || resp.items || []
  // if citations exist, convert
  if(resp.citations && resp.citations.length>0){
    cards = cards.concat(resp.citations.map(c=>({ title: c.title||c.doc_id, description: c.snippet||c.text_snippet })) )
  }
  return { answer, cards }
}
```

---

## Notes

- The frontend expects the backend `/chat` to accept `{query, lang}` and return `{answer, cards, citations}`. Adjust `ChatInterface.jsx` parsing if your schema differs.
- Image fetching: backend can attach `items[].image` with an absolute URL which the ImageCard will display.
- Multilingual: selected `lang` is sent to backend payload; backend should use it to pick language-specific responses.

---

Drop these files into `frontend/src/` and run:

```bash
npm install
npm run dev
```

Then open http://localhost:5173 (vite default) and test chat UI.
