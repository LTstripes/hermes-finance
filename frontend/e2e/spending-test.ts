import { test as base } from "@playwright/test";

export { expect } from "@playwright/test";
export const test = base.extend({
  // biome-ignore lint/correctness/noEmptyPattern: Playwright requires destructuring the fixture dependencies.
  baseURL: async ({}, use) => {
    const url = process.env.HERMES_SPENDING_BOUND_URL;
    if (!url) throw new Error("Missing the isolated spending fixture URL");
    await use(url);
  },
});
