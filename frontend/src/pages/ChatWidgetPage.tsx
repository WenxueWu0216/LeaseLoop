import { useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { ChatReply } from "../api/types";

type Line = { from: "renter" | "assistant"; text: string; handoff?: boolean };

function storedSession(key: string): string | undefined {
  try {
    return window.localStorage.getItem(key) ?? undefined;
  } catch {
    return undefined;
  }
}

/** Public, unauthenticated renter chat that talks to the leasing assistant. */
export function ChatWidgetPage() {
  const propertyId = Number(useParams().propertyId);
  const storageKey = `leaseloop.chat.${propertyId}`;
  const [lines, setLines] = useState<Line[]>([
    { from: "assistant", text: "Hi! Ask me about pricing, availability, pets, parking or booking a tour." },
  ]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const message = text.trim();
    if (!message || busy) return;
    setText("");
    setLines((l) => [...l, { from: "renter", text: message }]);
    setBusy(true);
    try {
      const reply = await api<ChatReply>("/assistant/chat/", {
        method: "POST", json: { property: propertyId, message, session: storedSession(storageKey) },
      });
      try { window.localStorage.setItem(storageKey, reply.session); } catch { /* private mode */ }
      setLines((l) => [...l, { from: "assistant", text: reply.reply, handoff: reply.handoff }]);
    } catch {
      setLines((l) => [...l, { from: "assistant", text: "Sorry, something went wrong. Please try again." }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex h-screen max-w-md flex-col p-4">
      <h1 className="mb-2 text-lg font-semibold">Chat with our leasing team</h1>
      <ol className="flex-1 space-y-2 overflow-y-auto rounded-lg border bg-white p-3" aria-label="Chat">
        {lines.map((l, i) => (
          <li key={i} className={`flex ${l.from === "renter" ? "justify-end" : ""}`}>
            <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${l.from === "renter" ? "bg-sky-600 text-white" : "bg-slate-100"}`}>
              {l.text}
              {l.handoff && <div className="mt-1 text-xs text-slate-500">A leasing agent will follow up.</div>}
            </div>
          </li>
        ))}
        {busy && <li className="text-sm text-slate-400">Typing…</li>}
      </ol>
      <form onSubmit={send} className="mt-2 flex gap-2">
        <input aria-label="Message" value={text} onChange={(e) => setText(e.target.value)} className="flex-1 rounded border px-3 py-2 text-sm" placeholder="Type your question…" />
        <button type="submit" disabled={busy} className="rounded bg-sky-600 px-4 text-sm font-medium text-white disabled:opacity-50">Send</button>
      </form>
    </div>
  );
}
