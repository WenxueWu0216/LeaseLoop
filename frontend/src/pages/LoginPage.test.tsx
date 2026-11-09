import { fireEvent, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { AuthProvider } from "../auth/AuthContext";
import { mockFetch, renderWithQuery } from "../test/render";
import { LoginPage } from "./LoginPage";

async function submit(status: number, body: unknown) {
  mockFetch([
    { method: "POST", path: "/api/auth/refresh/", status: 401, body: {} },
    { method: "POST", path: "/api/auth/login/", status, body },
  ]);
  renderWithQuery(
    <MemoryRouter>
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    </MemoryRouter>,
  );
  fireEvent.change(await screen.findByLabelText(/email/i), { target: { value: "a@b.co" } });
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "x" } });
  fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
  return screen.findByRole("alert");
}

test("wrong credentials show the generic message", async () => {
  expect(await submit(401, { detail: "No active account" })).toHaveTextContent(/incorrect/i);
});

test("a throttled login tells the user to wait", async () => {
  expect(await submit(429, { detail: "Request was throttled." })).toHaveTextContent(/too many/i);
});
