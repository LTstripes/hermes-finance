import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClientError } from "../../api/client";
import * as api from "../../api/months";
import type {
  CloseReadiness,
  IntentionalEmptyCloseCommand,
  IntentionalEmptyCloseReceipt,
  ReportingMonth,
} from "../../api/types";
import { IntentionalEmptyClose } from "./IntentionalEmptyClose";

vi.mock("../../api/months", () => ({
  closeIntentionallyEmptyMonth: vi.fn(),
  getCloseReadiness: vi.fn(),
  getIntentionalEmptyCloseReceipt: vi.fn(),
  getMonth: vi.fn(),
}));
const month = { id: 25, year: 2035, month: 2, snapshot_date: "2035-02-28" };
function ready(): CloseReadiness {
  return {
    ...month,
    status: "draft",
    source: "manual",
    can_close: false,
    items: [
      { code: "empty_manual_month", severity: "hard_blocker", message: "Empty", context: {} },
    ],
    intentional_empty_close: {
      month_id: month.id,
      year: month.year,
      month: month.month,
      snapshot_date: month.snapshot_date,
      expected_identity: "a".repeat(64),
      eligible: true,
      command: "close_intentionally_empty_manual_month",
      policy_version: "intentional_empty_manual_month_v1",
    },
  };
}
function receipt(command: IntentionalEmptyCloseCommand): IntentionalEmptyCloseReceipt {
  return { ...command, result_status: "closed", closed_at: "2035-03-01T00:00:00Z" };
}
function mount(available = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IntentionalEmptyClose month={month} available={available} />
    </QueryClientProvider>,
  );
}
async function prepare() {
  fireEvent.click(screen.getByRole("button", { name: "Закрыть намеренно пустой период…" }));
  await screen.findByRole("alertdialog");
}
async function send() {
  await prepare();
  fireEvent.change(screen.getByLabelText("Причина пустого периода"), {
    target: { value: "Синтетический пустой период" },
  });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить пустой Close" }));
}
beforeEach(() => {
  sessionStorage.clear();
  vi.resetAllMocks();
  vi.mocked(api.getCloseReadiness).mockResolvedValue(ready());
  vi.mocked(api.getMonth).mockResolvedValue({ ...month, status: "closed" } as ReportingMonth);
  vi.mocked(api.closeIntentionallyEmptyMonth).mockImplementation(async (_id, command) =>
    receipt(command),
  );
  vi.mocked(api.getIntentionalEmptyCloseReceipt).mockImplementation(async () => {
    const command = JSON.parse(
      sessionStorage.getItem(`hermes:empty-close:v1:${month.id}`) ?? "null",
    );
    return receipt(command);
  });
});
afterEach(cleanup);

describe("intentional empty Close", () => {
  it("requires reason and exact period consent; cancellation sends no command", async () => {
    mount();
    await prepare();
    expect(screen.getByRole("alertdialog")).toHaveTextContent("2035");
    expect(screen.getByRole("alertdialog")).toHaveTextContent("ID 25");
    expect(screen.getByRole("alertdialog")).toHaveTextContent("28.02.2035");
    const confirm = screen.getByRole("button", { name: "Подтвердить пустой Close" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Причина пустого периода"), { target: { value: "  " } });
    fireEvent.click(screen.getByRole("checkbox"));
    expect(confirm).toBeDisabled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(api.closeIntentionallyEmptyMonth).not.toHaveBeenCalled();
  });

  it("sends only the typed identity/reason, then verifies receipt and current month", async () => {
    mount();
    await send();
    await screen.findByText(/Закрытие пустого периода подтверждено/);
    expect(api.closeIntentionallyEmptyMonth).toHaveBeenCalledTimes(1);
    const sent = vi.mocked(api.closeIntentionallyEmptyMonth).mock.calls[0][1];
    expect(sent).toEqual({
      ...ready().intentional_empty_close,
      eligible: undefined,
      request_id: expect.any(String),
      reason: "Синтетический пустой период",
    });
    expect(api.getCloseReadiness).toHaveBeenCalledTimes(2);
    expect(api.getIntentionalEmptyCloseReceipt).toHaveBeenCalledWith(25, sent.request_id);
    expect(api.getMonth).toHaveBeenCalledWith(25);
    expect(sessionStorage.length).toBe(0);
  });

  it.each([
    "ineligible",
    "other_guard",
    "nonempty",
    "wrong_period",
    "wrong_snapshot",
    "unsupported",
  ])("refuses server option %s", async (kind) => {
    const value = ready();
    if (!value.intentional_empty_close) throw Error("fixture");
    if (kind === "ineligible") value.intentional_empty_close.eligible = false;
    if (kind === "other_guard")
      value.items.push({
        code: "source_unresolved",
        severity: "hard_blocker",
        message: "Source",
        context: {},
      });
    if (kind === "nonempty") {
      value.can_close = true;
      value.items = [];
    }
    if (kind === "wrong_period") value.intentional_empty_close.month = 3;
    if (kind === "wrong_snapshot") value.intentional_empty_close.snapshot_date = "2035-03-01";
    if (kind === "unsupported") value.intentional_empty_close.policy_version = "future" as never;
    vi.mocked(api.getCloseReadiness).mockResolvedValue(value);
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Закрыть намеренно пустой период…" }));
    await screen.findByRole("alert");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(api.closeIntentionallyEmptyMonth).not.toHaveBeenCalled();
  });

  it("retires consent when identity changes during confirmation", async () => {
    const changed = ready();
    if (changed.intentional_empty_close)
      changed.intentional_empty_close.expected_identity = "b".repeat(64);
    vi.mocked(api.getCloseReadiness).mockResolvedValueOnce(ready()).mockResolvedValue(changed);
    mount();
    await send();
    await screen.findByText(/Период изменился/);
    expect(api.closeIntentionallyEmptyMonth).not.toHaveBeenCalled();
  });

  it.each([409, 422])("keeps server rejection %s authoritative without retry", async (status) => {
    vi.mocked(api.closeIntentionallyEmptyMonth).mockRejectedValue(
      new ApiClientError(status, {
        code: "source_blocker",
        details: [],
        message: "Источник блокирует Close",
      }),
    );
    mount();
    await send();
    await screen.findByRole("alert");
    expect(api.closeIntentionallyEmptyMonth).toHaveBeenCalledTimes(1);
    expect(sessionStorage.length).toBe(0);
    expect(screen.queryByText(/подтверждено квитанцией/)).not.toBeInTheDocument();
  });

  it.each(["lost_ack", "failed_readback"])(
    "%s recovers only by GET across remount/Reload even after a 404",
    async (kind) => {
      if (kind === "lost_ack")
        vi.mocked(api.closeIntentionallyEmptyMonth).mockRejectedValue(new Error("Lost ACK"));
      vi.mocked(api.getIntentionalEmptyCloseReceipt).mockRejectedValueOnce(
        new ApiClientError(404, { code: "not_found", details: [], message: "Pending" }),
      );
      const first = mount();
      await send();
      await screen.findByRole("alert");
      expect(sessionStorage.length).toBe(1);
      expect(
        screen.queryByRole("button", { name: "Закрыть намеренно пустой период…" }),
      ).not.toBeInTheDocument();
      first.unmount();
      mount(false);
      await screen.findByText(/Закрытие пустого периода подтверждено/);
      expect(api.closeIntentionallyEmptyMonth).toHaveBeenCalledTimes(1);
      expect(api.getIntentionalEmptyCloseReceipt).toHaveBeenCalledTimes(2);
    },
  );

  it("rejects mismatching receipt and permits only GET recovery", async () => {
    vi.mocked(api.getIntentionalEmptyCloseReceipt).mockResolvedValue({
      ...receipt({} as IntentionalEmptyCloseCommand),
      month_id: 99,
    });
    mount();
    await send();
    await screen.findByRole("alert");
    expect(sessionStorage.length).toBe(1);
    expect(api.getMonth).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Проверить результат закрытия" }));
    await waitFor(() => expect(api.getIntentionalEmptyCloseReceipt).toHaveBeenCalledTimes(2));
    expect(api.closeIntentionallyEmptyMonth).toHaveBeenCalledTimes(1);
  });

  it("historical receipt after Reopen does not assert current CLOSED or reclose", async () => {
    vi.mocked(api.getMonth).mockResolvedValue({ ...month, status: "draft" } as ReportingMonth);
    mount();
    await send();
    await screen.findByText(/Историческая квитанция закрытия найдена/);
    expect(api.closeIntentionallyEmptyMonth).toHaveBeenCalledTimes(1);
  });

  it("blocks repeat clicks while POST is outstanding and storage exists before dispatch", async () => {
    let resolve!: (value: IntentionalEmptyCloseReceipt) => void;
    vi.mocked(api.closeIntentionallyEmptyMonth).mockImplementation(() => {
      expect(sessionStorage.length).toBe(1);
      return new Promise((done) => {
        resolve = done;
      });
    });
    mount();
    await send();
    await waitFor(() => expect(api.closeIntentionallyEmptyMonth).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: "Проверить результат закрытия" })).toBeDisabled();
    await act(async () =>
      resolve(receipt(vi.mocked(api.closeIntentionallyEmptyMonth).mock.calls[0][1])),
    );
    await screen.findByText(/подтверждено квитанцией/);
  });

  it("does not send when durable session storage is unavailable", async () => {
    mount();
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    await send();
    await screen.findByRole("alert");
    expect(api.closeIntentionallyEmptyMonth).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("does not dispatch a late preflight after Back/unmount or period replacement", async () => {
    let resolve!: (value: CloseReadiness) => void;
    vi.mocked(api.getCloseReadiness)
      .mockResolvedValueOnce(ready())
      .mockImplementationOnce(
        () =>
          new Promise((done) => {
            resolve = done;
          }),
      );
    const first = mount();
    await send();
    await waitFor(() => expect(api.getCloseReadiness).toHaveBeenCalledTimes(2));
    first.unmount();
    await act(async () => resolve(ready()));
    expect(api.closeIntentionallyEmptyMonth).not.toHaveBeenCalled();
    expect(sessionStorage.length).toBe(0);
  });

  it("resolves historical receipt after Reopen and snapshot edit without transferring consent", async () => {
    vi.mocked(api.getMonth).mockResolvedValue({
      ...month,
      status: "draft",
      snapshot_date: "2035-02-27",
    } as ReportingMonth);
    mount();
    await send();
    await screen.findByText(/Историческая квитанция/);
    expect(sessionStorage.length).toBe(0);
    expect(api.closeIntentionallyEmptyMonth).toHaveBeenCalledTimes(1);
  });
});
