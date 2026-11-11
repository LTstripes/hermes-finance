import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { AccountLink } from "./model";
import { useAccountName } from "./useAccountName";

afterEach(() => vi.unstubAllGlobals());

test.each([false, true])(
  "catalogue loading and failure never expose contract labels (failure=%s)",
  async (failure) => {
    let finish: (response: Response) => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      ),
    );
    const links: AccountLink[] = ["iis", "brokerage", null].map((type, index) => ({
      source_account_id: `SYNTH-CONTRACT-${index}`,
      financial_account_id: index + 1,
      account_type: type as AccountLink["account_type"],
      label: `Confidential SYNTH-CONTRACT-${index}`,
      status: "linked",
      reason_codes: [],
    }));
    function Labels() {
      const name = useAccountName(links);
      return (
        <>
          {links.map((link) => (
            <span key={link.financial_account_id} title={link.source_account_id}>
              {name(link, link.label)}
            </span>
          ))}
        </>
      );
    }
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <Labels />
      </QueryClientProvider>,
    );
    expect(screen.getByText("ИИС")).toHaveAttribute("title", "SYNTH-CONTRACT-0");
    expect(screen.getByText("Брокерский")).toBeVisible();
    expect(screen.getByText("Счёт")).toBeVisible();
    expect(screen.queryByText(/Confidential/)).toBeNull();
    await act(async () =>
      finish(
        new Response(JSON.stringify([{ id: 1, name: "Учебный ИИС" }]), {
          status: failure ? 503 : 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    expect(await screen.findByText(failure ? "ИИС" : "Учебный ИИС")).toBeVisible();
    expect(screen.queryByText(/Confidential/)).toBeNull();
  },
);
