import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InstrumentFormDialog } from "./InstrumentFormDialog";

describe("InstrumentFormDialog", () => {
  it("explains exact money storage without implementation wording", () => {
    render(
      <InstrumentFormDialog
        busy={false}
        error={null}
        instrument={null}
        onCancel={vi.fn()}
        onSubmit={vi.fn(async () => undefined)}
        open
      />,
    );

    expect(
      screen.getByText("Денежные значения сохраняются точно, без округления."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/на стороне формы/i)).toBeNull();
  });
});
