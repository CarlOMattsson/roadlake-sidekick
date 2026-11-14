import { createRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DetailTitle } from "@/features/work-app/view/parts/detail-title";

describe("DetailTitle", () => {
  it("renders a heading that can take focus by script and hands its ref to the frame", () => {
    const heading = createRef<HTMLHeadingElement>();
    render(<DetailTitle heading={heading}>Pay the invoice</DetailTitle>);
    const title = screen.getByRole("heading", {
      level: 2,
      name: "Pay the invoice",
    });
    expect(heading.current).toBe(title);
    expect(title.tabIndex).toBe(-1);
    heading.current?.focus();
    expect(document.activeElement).toBe(title);
  });

  it("opens the editor on a click when editing is offered", () => {
    const onEdit = vi.fn();
    render(
      <DetailTitle heading={createRef<HTMLHeadingElement>()} onEdit={onEdit}>
        Title
      </DetailTitle>,
    );
    fireEvent.click(screen.getByRole("heading", { name: "Title" }));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it("does nothing on a click when editing is not offered", () => {
    render(
      <DetailTitle heading={createRef<HTMLHeadingElement>()}>
        Title
      </DetailTitle>,
    );
    expect(() =>
      fireEvent.click(screen.getByRole("heading", { name: "Title" })),
    ).not.toThrow();
  });
});
