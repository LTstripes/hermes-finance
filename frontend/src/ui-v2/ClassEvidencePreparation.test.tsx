import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listAccounts } from "../api/accounts";
import { type ClassCoverage, listClassCoverages, saveClassCoverage } from "../api/classEvidence";
import { ApiClientError } from "../api/client";
import { listInstruments } from "../api/instruments";
import { listMonths } from "../api/months";
import { getClassReturns } from "../api/performance";
import { listPositions, updatePosition } from "../api/positions";
import type { PositionSnapshot, ReportingMonth } from "../api/types";
import { createQueryClient } from "../queryClient";
import { classReturnsFixture } from "../test/classReturnsFixture";
import { ClassEvidencePreparation } from "./ClassEvidencePreparation";

vi.mock("../api/classEvidence", () => ({
  listClassCoverages: vi.fn(),
  saveClassCoverage: vi.fn(),
}));
vi.mock("../api/months", () => ({ listMonths: vi.fn() }));
vi.mock("../api/accounts", () => ({ listAccounts: vi.fn() }));
vi.mock("../api/instruments", () => ({ listInstruments: vi.fn() }));
vi.mock("../api/performance", () => ({ getClassReturns: vi.fn() }));
vi.mock("../api/positions", () => ({ listPositions: vi.fn(), updatePosition: vi.fn() }));
const start = "2030-01-31";
const end = "2030-02-28";
let months: ReportingMonth[];
let positions: PositionSnapshot[];
let coverages: ClassCoverage[];

beforeEach(() => {
  vi.resetAllMocks();
  months = [1, 2].map((id) => ({
    id,
    year: 2030,
    month: id,
    snapshot_date: id === 1 ? start : end,
    status: "draft",
    source: "manual",
  }));
  positions = [
    {
      id: 7,
      reporting_month_id: 1,
      account_id: 3,
      instrument_id: 4,
      historical_instrument_type: null,
      updated_at: "2030-03-01T00:00:00",
    } as PositionSnapshot,
  ];
  coverages = [];
  vi.mocked(listAccounts).mockResolvedValue([]);
  vi.mocked(listInstruments).mockResolvedValue([]);
  vi.mocked(listMonths).mockImplementation(async () => structuredClone(months));
  vi.mocked(listPositions).mockImplementation(async (id) =>
    structuredClone(positions.filter((p) => p.reporting_month_id === id)),
  );
  vi.mocked(listClassCoverages).mockImplementation(async () => structuredClone(coverages));
  vi.mocked(getClassReturns).mockImplementation(async (cls, from, to) => {
    const result = classReturnsFixture(cls, from, to);
    result.coverage_state = "unknown";
    result.coverage_provenance = structuredClone(coverages);
    result.evidence_reason_codes = ["historical_class_unknown", "reporting_month_not_closed"];
    return result;
  });
});
afterEach(cleanup);

async function setup() {
  const client = createQueryClient();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ClassEvidencePreparation start={start} end={end} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByText("Подготовить подтверждения классов"));
  await screen.findByText(/Авторитетные ограничения/);
  return client;
}
async function claims() {
  fireEvent.change(screen.getByLabelText("Состояние подтверждения"), {
    target: { value: "complete" },
  });
  fireEvent.click(screen.getByLabelText(/пересечений границы класса/));
  fireEvent.click(screen.getByLabelText(/Полный состав класса на начало/));
  fireEvent.click(screen.getByLabelText(/Полный состав класса на конец/));
  fireEvent.click(
    screen.getByLabelText("Подтверждаю выбранное состояние и обе декларации состава"),
  );
}

describe("class Owner preparation", () => {
  it("shows exact blockers and legacy NULL without catalogue fallback; patches C1 only and rereads", async () => {
    vi.mocked(updatePosition).mockImplementation(async (_id, body) => {
      positions[0].historical_instrument_type = body.historical_instrument_type;
      positions[0].updated_at = "2030-03-02T00:00:00";
      return structuredClone(positions[0]);
    });
    const client = await setup();
    const invalidation = vi.spyOn(client, "invalidateQueries");
    expect(screen.getByText("historical_class_unknown")).toBeVisible();
    fireEvent.click(screen.getByText(/Исторический класс C1: все/));
    expect(screen.getByText(/Не подтверждён \/ неизвестно/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Исторический класс позиции 7"), {
      target: { value: "bond" },
    });
    fireEvent.click(screen.getByLabelText(/исторический класс позиции 7 с источником/));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить C1 позиции 7" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить C1 позиции 7" }));
    await screen.findByText(/Данные перечитаны/);
    expect(screen.getByText(/Данные перечитаны/)).toHaveFocus();
    expect(updatePosition).toHaveBeenCalledExactlyOnceWith(
      7,
      { historical_instrument_type: "bond" },
      "2030-03-01T00:00:00",
    );
    expect(invalidation).toHaveBeenCalled();
    expect(vi.mocked(listPositions).mock.calls.length).toBeGreaterThan(2);
    expect(vi.mocked(getClassReturns).mock.calls.length).toBeGreaterThan(1);
    expect(screen.getByRole("button", { name: "Сохранить C1 позиции 7" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Исторический класс позиции 7"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByLabelText(/исторический класс позиции 7 с источником/));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить C1 позиции 7" }));
    await waitFor(() =>
      expect(updatePosition).toHaveBeenLastCalledWith(
        7,
        { historical_instrument_type: null },
        "2030-03-02T00:00:00",
      ),
    );
  });

  it("creates explicit no-crossing and independent inventory claims; rereads rather than promoting returns", async () => {
    vi.mocked(saveClassCoverage).mockImplementation(async (body) => {
      const saved = { ...body, id: 5, revision: 1 };
      coverages = [saved];
      return saved;
    });
    await setup();
    const button = screen.getByRole("button", { name: "Сохранить подтверждение класса" });
    expect(button).toBeDisabled();
    await claims();
    fireEvent.click(button);
    await screen.findByText(/Данные перечитаны/);
    expect(saveClassCoverage).toHaveBeenCalledExactlyOnceWith(
      {
        asset_class: "stock",
        covered_from: start,
        covered_to: end,
        coverage_state: "complete",
        provenance_kind: "owner_attestation",
        provenance_reference: null,
        opening_inventory_complete: true,
        closing_inventory_complete: true,
      },
      undefined,
    );
    expect(button).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сохранить подтверждение класса" })).toBeDisabled();
    expect(screen.getByText("reporting_month_not_closed")).toBeVisible();
  });

  it("corrects/revokes with the read revision and blocks stale writes until an explicit reread", async () => {
    coverages = [
      { ...classReturnsFixture("stock", start, end).coverage_provenance[0], id: 5, revision: 8 },
    ];
    vi.mocked(saveClassCoverage).mockRejectedValue(
      new ApiClientError(409, { code: "conflict", message: "revision changed", details: [] }),
    );
    await setup();
    fireEvent.change(screen.getByLabelText("Состояние подтверждения"), {
      target: { value: "revoked" },
    });
    fireEvent.click(
      screen.getByLabelText("Подтверждаю выбранное состояние и обе декларации состава"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Сохранить подтверждение класса" }));
    await screen.findByText(/Форма устарела/);
    expect(saveClassCoverage).toHaveBeenCalledWith(
      expect.objectContaining({
        coverage_state: "revoked",
        opening_inventory_complete: false,
        closing_inventory_complete: false,
      }),
      expect.objectContaining({ id: 5, revision: 8 }),
    );
    expect(screen.getByRole("button", { name: "Сохранить подтверждение класса" })).toBeDisabled();
    coverages[0].revision = 9;
    fireEvent.click(screen.getByRole("button", { name: "Перечитать подготовку класса" }));
    await screen.findByText(/Исправление \/ отзыв подтверждения 5 · версия 9/);
    expect(saveClassCoverage).toHaveBeenCalledTimes(1);
  });

  it("guards CLOSED including periods whose snapshot is outside the requested interval", async () => {
    months[0].status = "closed";
    months[0].snapshot_date = "2030-03-01";
    await setup();
    await claims();
    expect(screen.getByRole("button", { name: "Сохранить подтверждение класса" })).toBeDisabled();
    expect(screen.getAllByRole("link", { name: /2030-01/ })[0]).toHaveAttribute(
      "href",
      "/months/1",
    );
    expect(saveClassCoverage).not.toHaveBeenCalled();
  });

  it("locks a CLOSED C1 row", async () => {
    months[0].status = "closed";
    await setup();
    fireEvent.click(screen.getByText(/Исторический класс C1: все/));
    expect(screen.getByLabelText("Исторический класс позиции 7")).toBeDisabled();
    expect(updatePosition).not.toHaveBeenCalled();
  });

  it("keeps ambiguous writes locked through failed rereads and resets claims after successful reread", async () => {
    vi.mocked(saveClassCoverage).mockRejectedValue(
      new ApiClientError(0, { code: "network_error", message: "lost", details: [] }),
    );
    await setup();
    await claims();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить подтверждение класса" }));
    await screen.findByText(/Запись не подтверждена/);
    vi.mocked(listClassCoverages).mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(screen.getByRole("button", { name: "Перечитать подготовку класса" }));
    await screen.findByText(/Запись заблокирована/);
    fireEvent.click(screen.getByRole("button", { name: "Перечитать подготовку класса" }));
    await screen.findByText(/Данные перечитаны/);
    expect(screen.getByLabelText(/пересечений границы класса/)).not.toBeChecked();
    expect(saveClassCoverage).toHaveBeenCalledTimes(1);
  });

  it("resets fresh claims on class/date changes and offers only supported classes with native keyboard controls", async () => {
    const user = userEvent.setup();
    await setup();
    await claims();
    fireEvent.change(screen.getByLabelText("Начало подтверждения"), {
      target: { value: "2030-01-30" },
    });
    expect(screen.getByLabelText(/пересечений границы класса/)).not.toBeChecked();
    expect(screen.getByLabelText(/Полный состав класса на начало/)).not.toBeChecked();
    const selector = screen.getByLabelText("Класс для подготовки");
    selector.focus();
    await user.selectOptions(selector, "gold");
    await screen.findByText(/Авторитетные ограничения: Золото/);
    expect(getClassReturns).toHaveBeenLastCalledWith("gold", start, end, expect.any(AbortSignal));
    expect(screen.queryByRole("option", { name: "Депозиты" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сохранить подтверждение класса" })).toBeDisabled();
  });

  it("hides mismatched authoritative responses", async () => {
    vi.mocked(getClassReturns).mockResolvedValue(classReturnsFixture("bond", start, end));
    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter>
          <ClassEvidencePreparation start={start} end={end} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByText("Подготовить подтверждения классов"));
    await screen.findByRole("alert");
    expect(
      screen.queryByRole("button", { name: "Сохранить подтверждение класса" }),
    ).not.toBeInTheDocument();
  });
});
