import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { SourceReturnProofPanel } from "./SourceReturnProofPanel";

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const preview = {
  source_account: "SYNTH",
  version: "source_return_custody_v1",
  preview_digest: "a".repeat(64),
  form_token: "synthetic-form-token",
  source_count: 2,
  cancellation_months: ["2030-05-01"],
  table_deltas: { source_return_proofs: 1 },
  other_table_deltas: 0,
  trigger_deltas: 0,
  financial_effects: 0,
  financial_authority: "none",
};
const props = {
  account: "SYNTH",
  expected: [{ intake_id: 1, manifest_digest: "b".repeat(64) }],
  loading: false,
};
afterEach(() => vi.unstubAllGlobals());

it("requires explicit Preview consent and recovers a lost ACK by GET without another POST", async () => {
  const user = userEvent.setup();
  let savedRequest = "";
  const fetcher = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url);
    if (path.endsWith("/preview")) return json(preview);
    if (path.endsWith("/confirm")) {
      savedRequest = JSON.parse(String(init?.body)).request_id;
      throw new TypeError("Synthetic ACK loss");
    }
    return json({
      request_id: savedRequest,
      source_account: "SYNTH",
      proof: { status: "current" },
      replay: true,
    });
  });
  vi.stubGlobal("fetch", fetcher);
  const refresh = vi.fn(async () => undefined);
  render(<SourceReturnProofPanel {...props} refresh={refresh} />);
  await user.upload(
    screen.getByLabelText("Оригиналы для подтверждения"),
    new File(["synthetic"], "source.xml", { type: "application/xml" }),
  );
  await user.click(screen.getByRole("button", { name: "Проверить оригиналы" }));
  const save = await screen.findByRole("button", { name: "Сохранить подтверждение" });
  expect(save).toBeDisabled();
  await user.click(screen.getByRole("checkbox"));
  await user.click(save);
  await screen.findByText(/Результат команды нужно проверить чтением/);
  expect(screen.queryByRole("button", { name: "Сохранить подтверждение" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Проверить результат сохранения" }));
  await screen.findByText("Сохранение подтверждено чтением.");
  expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/confirm"))).toHaveLength(1);
  expect(fetcher.mock.calls.at(-1)?.[1]?.method).toBeUndefined();
  expect(refresh).toHaveBeenCalledOnce();
});

it("discards late Preview after originals change and never enables an old confirmation", async () => {
  const user = userEvent.setup();
  let finish!: (reply: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    ),
  );
  const view = render(
    <SourceReturnProofPanel key="SYNTH" {...props} refresh={async () => undefined} />,
  );
  const input = screen.getByLabelText("Оригиналы для подтверждения");
  await user.upload(input, new File(["first"], "first.xml", { type: "application/xml" }));
  await user.click(screen.getByRole("button", { name: "Проверить оригиналы" }));
  // Leaving the account unmounts this ephemeral form; a late response has no authority.
  view.rerender(
    <SourceReturnProofPanel
      key="OTHER"
      {...props}
      account="OTHER"
      refresh={async () => undefined}
    />,
  );
  await act(async () => finish(json(preview)));
  expect(screen.getByText("Счёт источника: OTHER")).toBeVisible();
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "Сохранить подтверждение" }),
    ).not.toBeInTheDocument(),
  );
});
