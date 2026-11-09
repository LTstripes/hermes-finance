import { QueryObserver, focusManager, onlineManager } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { createQueryClient } from "./queryClient";

describe("saved read policy", () => {
  it("does not retry a failed read merely on remount", async () => {
    const client = createQueryClient();
    const queryFn = vi.fn().mockRejectedValue(new Error("Synthetic read failure"));
    const options = { queryKey: ["capital", "synthetic"], queryFn };
    await expect(client.fetchQuery(options)).rejects.toThrow("Synthetic read failure");
    const stop = new QueryObserver(client, options).subscribe(() => {});
    await Promise.resolve();
    expect(queryFn).toHaveBeenCalledTimes(1);
    stop();
    client.clear();
  });
  it("reuses even aged reads on remount and fetches invalidated data", async () => {
    const client = createQueryClient();
    const queryFn = vi.fn().mockResolvedValue("saved");
    const options = { queryKey: ["returns", "synthetic"], queryFn };
    await client.fetchQuery(options);
    client.setQueryData(options.queryKey, "saved", { updatedAt: 1 });
    const observer = new QueryObserver(client, options);
    const stop = observer.subscribe(() => {});
    client.mount();
    focusManager.setFocused(false);
    focusManager.setFocused(true);
    onlineManager.setOnline(false);
    onlineManager.setOnline(true);
    await Promise.resolve();
    expect(queryFn).toHaveBeenCalledTimes(1);
    stop();
    await client.invalidateQueries({ refetchType: "none" });
    const next = new QueryObserver(client, options);
    const stopNext = next.subscribe(() => {});
    await vi.waitFor(() => expect(queryFn).toHaveBeenCalledTimes(2));
    stopNext();
    client.unmount();
    client.clear();
    focusManager.setFocused(undefined);
  });
});
