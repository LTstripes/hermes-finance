import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { contextFixture, overviewFixture } from "./fixtures";
import { getContext, getOverview } from "./model";
import { useReturnsPrefetch } from "./useReturnsPrefetch";

vi.mock("./model", async (original) => ({
  ...(await original<typeof import("./model")>()),
  getContext: vi.fn(),
  getOverview: vi.fn(),
}));

function mount(ready: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(({ settled }) => useReturnsPrefetch("overall", settled), {
    wrapper,
    initialProps: { settled: ready },
  });
  return { client, ...hook };
}

afterEach(() => {
  vi.useRealTimers();
  vi.resetAllMocks();
});

test("defers neighbour reads until useful data and warms the exact default selection", async () => {
  vi.useFakeTimers();
  vi.mocked(getContext).mockResolvedValue(contextFixture);
  vi.mocked(getOverview).mockResolvedValue(overviewFixture());
  const { client, rerender, unmount } = mount(false);
  await act(() => vi.advanceTimersByTimeAsync(1500));
  expect(getContext).not.toHaveBeenCalled();
  rerender({ settled: true });
  await act(() => vi.advanceTimersByTimeAsync(1000));
  const period =
    contextFixture.default_period ?? contextFixture.source_periods["source:SYNTH-A"].at(-1);
  expect(getOverview).toHaveBeenCalledWith("source:SYNTH-A", period, expect.any(AbortSignal));
  expect(client.getQueryData(["returns", "context"])).toEqual(contextFixture);
  unmount();
  client.clear();
});

test("a write cancelling inactive reads retires the entire prefetch chain", async () => {
  vi.useFakeTimers();
  let finish = (_value: typeof contextFixture) => {};
  vi.mocked(getContext).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const { client, unmount } = mount(true);
  await act(() => vi.advanceTimersByTimeAsync(1000));
  expect(getContext).toHaveBeenCalledOnce();
  await act(async () => {
    await client.cancelQueries({ type: "inactive" });
    await client.invalidateQueries({ refetchType: "none" });
    finish(contextFixture);
  });
  expect(getOverview).not.toHaveBeenCalled();
  expect(client.getQueryData(["returns", "context"])).toBeUndefined();
  unmount();
  client.clear();
});
