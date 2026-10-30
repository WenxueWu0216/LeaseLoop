import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { InboxRow, Message } from "../../api/types";
import { mockFetch, renderWithQuery } from "../../test/render";
import { ConversationList } from "./ConversationList";
import { ConversationView } from "./ConversationView";

const row = (over: Partial<InboxRow> = {}): InboxRow => ({
  id: 1, channel: "SMS", subject: "", last_message_at: new Date().toISOString(), is_unread: true,
  needs_handoff: false, open_handoffs: 0,
  prospect: { id: 5, name: "Jane Rivera", email: "jane@example.com", phone: "+12015550123", status: "NEW", assigned_agent: null },
  last_message: { body: "Is parking included?", direction: "IN", is_assistant: false },
  ...over,
});

describe("ConversationList", () => {
  test("shows channel, handoff and assistant badges", () => {
    render(
      <ConversationList
        rows={[
          row(),
          row({ id: 2, needs_handoff: true, open_handoffs: 2, channel: "CHAT", prospect: { ...row().prospect, name: "" },
                last_message: { body: "We welcome everyone…", direction: "OUT", is_assistant: true } }),
        ]}
        selectedId={2}
        onSelect={jest.fn()}
      />,
    );
    expect(screen.getByText("Jane Rivera")).toHaveClass("font-semibold"); // unread
    expect(screen.getByText("Handoff ×2")).toBeInTheDocument();
    expect(screen.getByText("Website visitor")).toBeInTheDocument();
    expect(screen.getByText("Assistant")).toBeInTheDocument();
    expect(screen.getAllByRole("button")[1]).toHaveAttribute("aria-current", "true");
  });

  test("selecting a row reports its id", async () => {
    const onSelect = jest.fn();
    render(<ConversationList rows={[row({ id: 9 })]} selectedId={null} onSelect={onSelect} />);
    await userEvent.click(screen.getByRole("button", { name: /Jane Rivera/ }));
    expect(onSelect).toHaveBeenCalledWith(9);
  });
});

describe("ConversationView", () => {
  const thread: Message[] = [
    { id: 1, conversation: 1, direction: "IN", channel: "SMS", body: "Is parking included?", sender: null, is_assistant: false, sent_at: "2026-11-02T14:00:00Z" },
  ];

  test("suggested reply can be used and sent", async () => {
    const calls = mockFetch([
      { path: "/api/conversations/1/messages/", body: thread },
      { method: "POST", path: "/api/conversations/1/suggest-reply/", body: { suggestion: "One surface spot is included at no charge.", handoff_reason: null, tools_called: ["get_policy"] } },
      { method: "POST", path: "/api/conversations/1/messages/", body: [...thread, { ...thread[0], id: 2, direction: "OUT", body: "One surface spot is included at no charge." }] },
      { path: /\/api\/conversations\/\?/, body: { count: 0, next: null, previous: null, results: [] } },
    ]);
    renderWithQuery(<ConversationView conversation={row()} />);
    expect(await screen.findByText("Is parking included?")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Suggest reply" }));
    const panel = await screen.findByRole("region", { name: "Assistant suggestion" });
    expect(panel).toHaveTextContent("Assistant suggested reply");
    expect(panel).toHaveTextContent("checked: get_policy");

    await userEvent.click(screen.getByRole("button", { name: "Use this reply" }));
    expect(screen.getByLabelText("Reply")).toHaveValue("One surface spot is included at no charge.");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByLabelText("Reply")).toHaveValue(""));
    expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/messages/"))?.body)
      .toEqual({ body: "One surface spot is included at no charge." });
  });

  test("shows a handoff recommendation instead of a reply", async () => {
    mockFetch([
      { path: "/api/conversations/1/messages/", body: thread },
      { method: "POST", path: "/api/conversations/1/suggest-reply/", body: { suggestion: "…", handoff_reason: "FAIR_HOUSING", tools_called: [] } },
    ]);
    renderWithQuery(<ConversationView conversation={row({ needs_handoff: true })} />);
    expect(screen.getByText("Needs a human")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Suggest reply" }));
    expect(await screen.findByText("Handoff recommended")).toBeInTheDocument();
    expect(screen.getByText("Reason: fair housing")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use this reply" })).not.toBeInTheDocument();
  });
});
