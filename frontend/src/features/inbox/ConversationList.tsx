import type { InboxRow } from "../../api/types";
import { Badge } from "../../components/Badge";
import { relative } from "../../lib/time";

type Props = { rows: InboxRow[]; selectedId: number | null; onSelect: (id: number) => void };

export function ConversationList({ rows, selectedId, onSelect }: Props) {
  if (rows.length === 0) return <p className="p-4 text-sm text-slate-500">No conversations.</p>;
  return (
    <ul className="divide-y" aria-label="Conversations">
      {rows.map((c) => (
        <li key={c.id}>
          <button
            type="button"
            onClick={() => onSelect(c.id)}
            aria-current={c.id === selectedId}
            className={`w-full px-3 py-2.5 text-left hover:bg-slate-50 ${c.id === selectedId ? "bg-sky-50" : ""}`}
          >
            <div className="flex items-center gap-2">
              <span className={`truncate ${c.is_unread ? "font-semibold" : ""}`}>{c.prospect.name || "Website visitor"}</span>
              <Badge tone="slate">{c.channel.toLowerCase()}</Badge>
              {c.needs_handoff && (
                <Badge tone="red">Handoff{c.open_handoffs > 1 ? ` ×${c.open_handoffs}` : ""}</Badge>
              )}
              <span className="ml-auto shrink-0 text-xs text-slate-400">{relative(c.last_message_at)}</span>
            </div>
            {c.last_message && (
              <p className="mt-0.5 truncate text-sm text-slate-500">
                {c.last_message.is_assistant && <Badge tone="violet">Assistant</Badge>}{" "}
                {c.last_message.direction === "OUT" && !c.last_message.is_assistant ? "You: " : ""}
                {c.last_message.body}
              </p>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}
