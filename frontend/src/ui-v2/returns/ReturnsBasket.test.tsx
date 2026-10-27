import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate, useSearchParams } from "react-router";
import { afterEach, expect, test, vi } from "vitest";
import { april, basketFixture, may } from "./fixtures";
import { ReturnsBasket } from "./ReturnsBasket";

const response = (value: unknown) =>
  new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());
function Harness() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="url">
        {location.search}
        {location.hash}
      </output>
      <button type="button" onClick={() => navigate(-1)}>
        Back
      </button>
      <button
        type="button"
        onClick={() => {
          const next = new URLSearchParams(params);
          next.set("start", april.start);
          next.set("end", april.end);
          setParams(next);
        }}
      >
        April
      </button>
      <ReturnsBasket
        period={{ start: params.get("start") ?? may.start, end: params.get("end") ?? may.end }}
        refreshing={false}
      />
    </>
  );
}
function setup(
  path = `/v2/returns?start=${may.start}&end=${may.end}#details`,
  override?: (url: URL) => Promise<Response> | undefined,
) {
  const calls: URL[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const url = new URL(input, "http://localhost");
      calls.push(url);
      return (
        override?.(url) ??
        Promise.resolve(
          response(
            basketFixture(
              {
                start: url.searchParams.get("start") ?? "",
                end: url.searchParams.get("end") ?? "",
              },
              url.searchParams.get("categories") ?? "",
            ),
          ),
        )
      );
    }),
  );
  const view = render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[path]}>
        <Harness />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { calls, view };
}

test("all categories default ON; source signed partial and deposit receipts stay separate, gold unavailable", async () => {
  const { calls } = setup();
  const panel = screen.getByRole("region", { name: "Моя доходность" });
  for (const checkbox of within(panel).getAllByRole("checkbox")) expect(checkbox).toBeChecked();
  await within(panel).findByText("−20 ₽");
  expect(within(panel).getByText("+3 ₽")).toBeVisible();
  expect(calls.at(-1)?.searchParams.get("categories")).toBe("brokerage,iis,deposits,gold");
  fireEvent.click(within(panel).getByText("Покрытие и причины по категориям"));
  expect(within(panel).getByText(/Текущая стоимость и прирост от цены покупки/)).toBeVisible();
  expect(within(panel).queryByText("−17 ₽")).toBeNull();
});

test("one / none / Back and remount preserve selection and exact dates/hash", async () => {
  const { calls, view } = setup();
  await screen.findByText("−20 ₽");
  for (const name of ["Брокерские счета", "ИИС", "Физическое золото"])
    fireEvent.click(screen.getByRole("checkbox", { name }));
  await screen.findByText("+3 ₽");
  expect(calls.at(-1)?.searchParams.get("categories")).toBe("deposits");
  fireEvent.click(screen.getByRole("checkbox", { name: "Депозиты и накопительные" }));
  expect(screen.getByText("Выбери хотя бы одну категорию")).toBeVisible();
  await waitFor(() => expect(calls.at(-1)?.searchParams.get("categories")).toBe(""));
  expect(screen.queryByText("+3 ₽")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Back" }));
  await screen.findByText("+3 ₽");
  const path = `/v2/returns${screen.getByTestId("url").textContent}`;
  expect(path).toContain("#details");
  view.unmount();
  setup(path);
  await screen.findByText("+3 ₽");
  expect(screen.getByRole("checkbox", { name: "Депозиты и накопительные" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "ИИС" })).not.toBeChecked();
});

test.each(["gold,gold", "other", "gold&categories=iis"])(
  "invalid categories %s never fetch or show a result",
  async (raw) => {
    const { calls } = setup(`/v2/returns?start=${may.start}&end=${may.end}&categories=${raw}`);
    expect(screen.getByText("Выберите корректный период и категории.")).toBeVisible();
    expect(calls).toHaveLength(0);
  },
);

test("ABA late response and selected-period change cannot display an obsolete basket", async () => {
  let release: ((response: Response) => void) | undefined;
  let initial = true;
  const { calls } = setup(undefined, () => {
    if (initial) {
      initial = false;
      return new Promise((resolve) => {
        release = resolve;
      });
    }
    return undefined;
  });
  await waitFor(() => expect(calls).toHaveLength(1));
  const iis = screen.getByRole("checkbox", { name: "ИИС" });
  fireEvent.click(iis);
  await waitFor(() => expect(screen.queryByText("Пересчитываем выбранное…")).toBeNull());
  fireEvent.click(iis);
  await screen.findByText("−20 ₽");
  await act(async () =>
    release?.(response({ ...basketFixture(may), known_partial_subtotal_kopecks: "9999900" })),
  );
  expect(screen.queryByText("+99 999 ₽")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "April" }));
  await waitFor(() => expect(calls.at(-1)?.searchParams.get("start")).toBe(april.start));
  expect(screen.getByTestId("url")).toHaveTextContent(`start=${april.start}`);
});
