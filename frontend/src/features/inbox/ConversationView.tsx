import { useState } from "react";

import { useSendReply, useSuggestReply, useThread } from "../../api/hooks";
import type { InboxRow } from "../../api/types";
import { Badge, humanize } from "../../components/Badge";

export function ConversationView({ conversation }: { conversation: InboxRow }) {
  const thread = useThread(conversation.id);
  const send = useSendReply(conversation.id);
  const suggest = useSuggestReply(conversation.id);
  const [draft, setDraft] = useState("");
  const suggestion = suggest.data;

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <h2 className="font-semibold">{conversation.prospect.name || "Website visitor"}</h2>
        <span className="text-sm text-slate-500">{conversation.prospect.email || conversation.prospect.phone}</span>
        {conversation.needs_handoff && <Badge tone="red">Needs a human</Badge>}
      </header>

      <ol className="flex-1 space-y-2 overflow-y-auto p-4" aria-label="Messages">
        {thread.isLoading && <li className="text-sm text-slate-500">Loading…</li>}
        {thread.data?.map((m) => (
          <li key={m.id} className={`flex ${m.direction === "OUT" ? "justify-end" : ""}`}>
            <div
              className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${
                m.direction === "IN" ? "bg-white shadow-sm" : m.is_assistant ? "bg-violet-100" : "bg-sky-600 text-white"
              }`}
            >
              {m.is_assistant && <div className="mb-0.5 text-xs font-medium text-violet-700">Assistant</div>}
              <p className="whitespace-pre-wrap">{m.body}</p>
            </div>
          </li>
        ))}
      </ol>

      {suggestion && (
        <section aria-label="Assistant suggestion" className="mx-4 mb-2 rounded-lg border border-violet-200 bg-violet-50 p-3 text-sm">
          {suggestion.handoff_reason ? (
            <p>
              <Badge tone="red">Handoff recommended</Badge>{" "}
              <span className="text-slate-700">Reason: {humanize(suggestion.handoff_reason)}</span>
            </p>
          ) : (
            <>
              <div className="mb-1 flex items-center gap-2">
                <Badge tone="violet">Assistant suggested reply</Badge>
                {suggestion.tools_called.length > 0 && (
                  <span className="text-xs text-slate-500">checked: {suggestion.tools_called.join(", ")}</span>
                )}
              </div>
              <p className="text-slate-800">{suggestion.suggestion}</p>
              <button type="button" className="mt-2 text-sm font-medium text-violet-700 hover:underline" onClick={() => setDraft(suggestion.suggestion)}>
                Use this reply
              </button>
            </>
          )}
        </section>
      )}

      <form
        className="flex gap-2 border-t p-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (!draft.trim()) return;
          send.mutate(draft, { onSuccess: () => setDraft("") });
        }}
      >
        <button
          type="button"
          onClick={() => suggest.mutate()}
          disabled={suggest.isPending}
          className="rounded border border-violet-300 px-3 text-sm text-violet-700 hover:bg-violet-50 disabled:opacity-50"
        >
          {suggest.isPending ? "Thinking…" : "Suggest reply"}
        </button>
        <input
          aria-label="Reply"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={`Reply by ${conversation.channel.toLowerCase()}…`}
          className="flex-1 rounded border px-3 py-2 text-sm"
        />
        <button type="submit" disabled={send.isPending || !draft.trim()} className="rounded bg-sky-600 px-4 text-sm font-medium text-white disabled:opacity-50">
          Send
        </button>
      </form>
    </div>
  );
}
