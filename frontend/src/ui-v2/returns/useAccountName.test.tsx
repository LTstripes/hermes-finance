import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { AccountLink } from "./model";
import { useAccountName } from "./useAccountName";

afterEach(() => vi.unstubAllGlobals());

test("uses authoritative labels without a catalogue request or local identity inference", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const links: AccountLink[] = [
    {
      source_account_id: "SYNTH-A",
      financial_account_id: 1,
      account_type: "iis",
      label: "Учебный ИИС",
      status: "linked",
      reason_codes: [],
    },
    {
      source_account_id: "SYNTH-B",
      financial_account_id: null,
      account_type: null,
      label: "SYNTH-B",
      status: "unlinked",
      reason_codes: ["source_account_mapping_missing"],
    },
    {
      source_account_id: "SYNTH-C",
      financial_account_id: 2,
      account_type: "brokerage",
      label: "Брокерский SYNTH-C",
      status: "linked",
      reason_codes: [],
    },
  ];
  function Labels() {
    const name = useAccountName(links);
    return (
      <>
        {links.map((link) => (
          <span key={link.source_account_id}>{name(link, "fallback")}</span>
        ))}
        <span>{name(null, "fallback")}</span>
      </>
    );
  }
  render(<Labels />);
  for (const label of ["Учебный ИИС", "SYNTH-B", "Брокерский SYNTH-C", "fallback"]) {
    expect(screen.getByText(label)).toBeVisible();
  }
  expect(fetch).not.toHaveBeenCalled();
});
