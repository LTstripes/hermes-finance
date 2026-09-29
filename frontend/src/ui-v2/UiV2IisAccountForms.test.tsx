import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listAccounts } from "../api/accounts";
import { ApiClientError } from "../api/client";
import {
  createIisContribution,
  createTaxBenefit,
  getIisProfile,
  listIisContributions,
  listTaxBenefits,
  upsertIisProfile,
} from "../api/iis";
import { getTaxIisPlanner } from "../api/taxIisPlanner";
import type { Account, IisContribution, IisProfile, TaxBenefit, TaxIisPlanner } from "../api/types";
import { UiV2IisAccountForms } from "./UiV2IisAccountForms";

vi.mock("../api/accounts", () => ({ listAccounts: vi.fn() }));
vi.mock("../api/iis", () => ({
  createIisContribution: vi.fn(),
  createTaxBenefit: vi.fn(),
  getIisProfile: vi.fn(),
  listIisContributions: vi.fn(),
  listTaxBenefits: vi.fn(),
  upsertIisProfile: vi.fn(),
}));
vi.mock("../api/taxIisPlanner", () => ({ getTaxIisPlanner: vi.fn() }));

const account: Account = {
  id: 7,
  name: "Синтетический ИИС",
  account_type: "iis",
  status: "active",
  external_code: null,
  include_in_capital: true,
  include_in_returns: true,
  notes: null,
};

let profile: IisProfile | null;
let contributions: IisContribution[];
let benefits: TaxBenefit[];
const getProfileMock = vi.mocked(getIisProfile);
const listContributionsMock = vi.mocked(listIisContributions);
const listBenefitsMock = vi.mocked(listTaxBenefits);
const upsertProfileMock = vi.mocked(upsertIisProfile);
const createContributionMock = vi.mocked(createIisContribution);
const createBenefitMock = vi.mocked(createTaxBenefit);
const listAccountsMock = vi.mocked(listAccounts);
const plannerMock = vi.mocked(getTaxIisPlanner);

function renderForms() {
  return render(
    <MemoryRouter>
      <UiV2IisAccountForms account={account} plannerPath="/v2/income/tax-iis?month=12" />
    </MemoryRouter>,
  );
}

describe("UiV2IisAccountForms", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    profile = null;
    contributions = [];
    benefits = [];
    getProfileMock.mockImplementation(async () => {
      if (!profile)
        throw new ApiClientError(404, { code: "not_found", message: "missing", details: [] });
      return profile;
    });
    listContributionsMock.mockImplementation(async () => [...contributions]);
    listBenefitsMock.mockImplementation(async () => [...benefits]);
    listAccountsMock.mockResolvedValue([account]);
    plannerMock.mockImplementation(
      async () =>
        ({
          iis_accounts: profile ? [{ account_id: account.id }] : [],
        }) as TaxIisPlanner,
    );
    upsertProfileMock.mockImplementation(async (_id, payload) => {
      profile = {
        id: 11,
        account_id: account.id,
        iis_type: payload.iis_type,
        opened_at: payload.opened_at,
        eligible_close_at: payload.eligible_close_at ?? null,
        notes: payload.notes ?? null,
      };
      return profile;
    });
    createContributionMock.mockImplementation(async (_id, payload) => {
      const row: IisContribution = {
        id: 21,
        account_id: account.id,
        tax_year: payload.tax_year,
        amount: payload.amount,
        is_target_reached: false,
        notes: null,
      };
      contributions = [...contributions, row];
      return row;
    });
    createBenefitMock.mockImplementation(async (_id, payload) => {
      const row: TaxBenefit = {
        id: 31,
        account_id: account.id,
        tax_year: payload.tax_year,
        benefit_type: payload.benefit_type,
        status: payload.status,
        amount: payload.amount,
        received_at: null,
        notes: null,
      };
      benefits = [...benefits, row];
      return row;
    });
  });

  it("preserves profile metadata and confirms the account planner after saving", async () => {
    profile = {
      id: 11,
      account_id: 7,
      iis_type: "type_a",
      opened_at: "2028-01-12",
      eligible_close_at: "2031-01-12",
      notes: "Синтетика",
    };
    const user = userEvent.setup();
    renderForms();
    await screen.findByText("Дата доступного закрытия: 2031-01-12");
    await user.selectOptions(screen.getByLabelText("Тип ИИС"), "type_b");
    await user.click(screen.getByRole("button", { name: "Сохранить профиль" }));
    await waitFor(() =>
      expect(upsertProfileMock).toHaveBeenCalledWith(7, {
        iis_type: "type_b",
        opened_at: "2028-01-12",
        eligible_close_at: "2031-01-12",
        notes: "Синтетика",
      }),
    );
    expect(await screen.findByText(/Профиль ИИС сохранён и подтверждён/)).toBeInTheDocument();
    expect(plannerMock).toHaveBeenCalledWith({ accountId: 7 });
    expect(screen.getByRole("link", { name: /Открыть планировщик/ })).toHaveAttribute(
      "href",
      "/v2/income/tax-iis?month=12",
    );
  });

  it("validates date, year and exact nonnegative amount before a write", async () => {
    const user = userEvent.setup();
    renderForms();
    await screen.findByRole("button", { name: "Сохранить профиль" });
    await user.type(screen.getByLabelText("Дата открытия"), "2028-02-30");
    await user.click(screen.getByRole("button", { name: "Сохранить профиль" }));
    expect(upsertProfileMock).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText("Налоговый год взноса"));
    await user.type(screen.getByLabelText("Налоговый год взноса"), "1899");
    await user.type(screen.getByLabelText("Сумма взноса, ₽"), "-1");
    await user.click(screen.getByRole("button", { name: "Добавить взнос" }));
    expect(createContributionMock).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText("Налоговый год взноса"));
    await user.type(screen.getByLabelText("Налоговый год взноса"), "2031");
    await user.clear(screen.getByLabelText("Сумма взноса, ₽"));
    await user.type(screen.getByLabelText("Сумма взноса, ₽"), "0,00");
    await user.click(screen.getByRole("button", { name: "Добавить взнос" }));
    await waitFor(() =>
      expect(createContributionMock).toHaveBeenCalledWith(7, {
        tax_year: 2031,
        amount: { amount: "0.00", currency: "RUB" },
      }),
    );
    expect(plannerMock).toHaveBeenCalledWith({});
  });

  it("prevents duplicate submit and keeps a single tax-year contribution", async () => {
    let finish: ((row: IisContribution) => void) | undefined;
    createContributionMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const user = userEvent.setup();
    renderForms();
    await screen.findByRole("button", { name: "Добавить взнос" });
    await user.clear(screen.getByLabelText("Налоговый год взноса"));
    await user.type(screen.getByLabelText("Налоговый год взноса"), "2032");
    await user.type(screen.getByLabelText("Сумма взноса, ₽"), "1000,50");
    await user.dblClick(screen.getByRole("button", { name: "Добавить взнос" }));
    await waitFor(() => expect(createContributionMock).toHaveBeenCalledTimes(1));
    const row: IisContribution = {
      id: 21,
      account_id: 7,
      tax_year: 2032,
      amount: { amount: "1000.50", currency: "RUB" },
      is_target_reached: false,
      notes: null,
    };
    contributions = [row];
    finish?.(row);
    expect(await screen.findByText(/Взнос за 2032 год сохранён/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Добавить взнос" })).toBeDisabled();
  });

  it("records a supported deduction status without treating it as received", async () => {
    const user = userEvent.setup();
    renderForms();
    await screen.findByRole("button", { name: "Добавить вычет типа А" });
    await user.clear(screen.getByLabelText("Налоговый год вычета"));
    await user.type(screen.getByLabelText("Налоговый год вычета"), "2030");
    await user.selectOptions(screen.getByLabelText("Статус вычета"), "submitted");
    await user.type(screen.getByLabelText("Сумма вычета, ₽"), "123,45");
    await user.click(screen.getByRole("button", { name: "Добавить вычет типа А" }));
    await waitFor(() =>
      expect(createBenefitMock).toHaveBeenCalledWith(7, {
        tax_year: 2030,
        benefit_type: "type_a",
        status: "submitted",
        amount: { amount: "123.45", currency: "RUB" },
      }),
    );
    expect(await screen.findByText(/Вычет за 2030 год сохранён/)).toBeInTheDocument();
    expect(screen.getByText(/2030 · Тип А · Подано/)).toBeInTheDocument();
  });

  it("blocks writes when account identity changed before submit", async () => {
    const user = userEvent.setup();
    renderForms();
    await screen.findByRole("button", { name: "Добавить взнос" });
    listAccountsMock.mockResolvedValueOnce([{ ...account, status: "closed" }]);
    await user.type(screen.getByLabelText("Сумма взноса, ₽"), "1");
    await user.click(screen.getByRole("button", { name: "Добавить взнос" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("больше не является активным ИИС");
    expect(createContributionMock).not.toHaveBeenCalled();
  });

  it("rejects a tax-year duplicate discovered in the fresh preflight read", async () => {
    const user = userEvent.setup();
    renderForms();
    await screen.findByRole("button", { name: "Добавить взнос" });
    await user.clear(screen.getByLabelText("Налоговый год взноса"));
    await user.type(screen.getByLabelText("Налоговый год взноса"), "2033");
    await user.type(screen.getByLabelText("Сумма взноса, ₽"), "10");
    contributions = [
      {
        id: 21,
        account_id: 7,
        tax_year: 2033,
        amount: { amount: "10.00", currency: "RUB" },
        is_target_reached: false,
        notes: null,
      },
    ];
    await user.click(screen.getByRole("button", { name: "Добавить взнос" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("уже есть");
    expect(createContributionMock).not.toHaveBeenCalled();
  });

  it("fails closed when the account-scoped API returns another account's row", async () => {
    listContributionsMock.mockResolvedValue([
      {
        id: 21,
        account_id: 99,
        tax_year: 2033,
        amount: { amount: "10.00", currency: "RUB" },
        is_target_reached: false,
        notes: null,
      },
    ]);
    renderForms();
    expect(await screen.findByRole("alert")).toHaveTextContent("другого счёта ИИС");
    expect(screen.queryByRole("button", { name: "Добавить взнос" })).not.toBeInTheDocument();
  });

  it("locks an ambiguous write result against a duplicate retry", async () => {
    createContributionMock.mockRejectedValue(
      new ApiClientError(500, { code: "http_error", message: "error", details: [] }),
    );
    const user = userEvent.setup();
    renderForms();
    await screen.findByRole("button", { name: "Добавить взнос" });
    await user.type(screen.getByLabelText("Сумма взноса, ₽"), "5");
    await user.click(screen.getByRole("button", { name: "Добавить взнос" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Результат записи неясен");
    await user.click(screen.getByRole("button", { name: "Обновить ИИС" }));
    await waitFor(() => expect(listContributionsMock).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Добавить взнос" })).toBeDisabled();
    expect(createContributionMock).toHaveBeenCalledTimes(1);
  });
});
