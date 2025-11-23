// frontend/src/pages/Chatbot.jsx
import React from "react";
import ChatInterface from "../components/ChatInterface";

/**
 * Chatbot page wrapper
 * - Uses ChatInterface for the chat UI/logic
 * - Displays a small header with a local image (path provided)
 *
 * NOTE: The image source is a local path from the environment:
 * "/mnt/data/81426f6c-b328-42ce-b4b0-d3650ffbbe18.png"
 * Your deployment/tooling should transform this path into a served URL.
 */

export default function Chatbot() {
  const localImagePath = "/mnt/data/81426f6c-b328-42ce-b4b0-d3650ffbbe18.png";

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-slate-50">
      <div className="w-full max-w-4xl bg-white shadow-xl rounded-2xl p-6 h-full">
        <header className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            {/* local image -> tool/hosting should map this path to a URL */}
            <img
              src={localImagePath}
              alt="Chatbot logo"
              className="w-14 h-14 rounded-md object-cover border"
            />
            <div>
              <h1 className="text-2xl font-semibold">Ayurvedic Nutrition — Knowledge Chat</h1>
              <p className="text-sm text-slate-500">Multilingual • RAG-powered</p>
            </div>
          </div>

          <div className="text-sm text-slate-400">
            Backend: <span className="font-medium">http://localhost:8001</span>
          </div>
        </header>

        <main className="h-[calc(100vh-180px)]">
          <ChatInterface />
        </main>

        <footer className="mt-4 text-center text-xs text-slate-400">
          This is a dev UI — use for testing retrieval + LLM flows.
        </footer>
      </div>
    </div>
  );
}