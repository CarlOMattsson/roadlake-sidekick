import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  WorkShell,
  type WorkShellProps,
} from "@/features/work-app/shell/work-shell";
import { workShellLabelsSv } from "@/features/work-app/shell/work-shell-labels";

// jsdom joins a nested span to its label without the space ("Att sortera3"); a browser keeps it.
const SORT3 = "Att sortera 3";

const base: Pick<WorkShellProps, "agenda" | "board" | "hierarchy"> = {
  agenda: <p>Innehåll agenda</p>,
  board: <p>Innehåll board</p>,
  hierarchy: <p>Innehåll hierarki</p>,
};

const unsorted = {
  label: "Att sortera",
  count: 3,
  content: <p>Innehåll att sortera</p>,
};

function tabNames() {
  const strip = screen.getByRole("group", { name: "Vyer" });
  return within(strip)
    .getAllByRole("button")
    .map((button) => button.textContent);
}

describe("WorkShell with the To sort tab", () => {
  it("puts 'Att sortera 3' last, and shows its content when it is pressed", async () => {
    const user = userEvent.setup();
    const onTabChange = vi.fn();
    render(
      <WorkShell
        labels={workShellLabelsSv}
        {...base}
        unsorted={unsorted}
        onTabChange={onTabChange}
      />,
    );
    expect(tabNames()).toEqual([
      "Agenda",
      "Status",
      "Projekt",
      "Att sortera 3",
    ]);

    await user.click(screen.getByRole("button", { name: SORT3 }));

    expect(onTabChange).toHaveBeenCalledWith("unsorted");
    expect(screen.getByText("Innehåll att sortera")).toBeVisible();
    expect(
      screen.getByRole("region", { name: "Att sortera" }),
    ).toBeInTheDocument();
  });

  it("is chosen on g and t", () => {
    const onTabChange = vi.fn();
    render(
      <WorkShell
        labels={workShellLabelsSv}
        {...base}
        unsorted={unsorted}
        onTabChange={onTabChange}
      />,
    );
    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "t" });

    expect(onTabChange).toHaveBeenCalledWith("unsorted");
    expect(screen.getByRole("button", { name: SORT3 })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("has no such tab without `unsorted`", () => {
    render(<WorkShell labels={workShellLabelsSv} {...base} />);
    expect(tabNames()).toEqual(["Agenda", "Status", "Projekt"]);
    expect(
      screen.queryByRole("button", { name: /Att sortera/ }),
    ).not.toBeInTheDocument();
  });

  it("gives way to the first tab, and reports it, when `unsorted` goes while its tab is shown", async () => {
    const user = userEvent.setup();
    const onTabChange = vi.fn();
    const { rerender } = render(
      <WorkShell
        labels={workShellLabelsSv}
        {...base}
        unsorted={unsorted}
        onTabChange={onTabChange}
      />,
    );
    await user.click(screen.getByRole("button", { name: SORT3 }));
    onTabChange.mockClear();

    rerender(
      <WorkShell
        labels={workShellLabelsSv}
        {...base}
        onTabChange={onTabChange}
      />,
    );

    expect(onTabChange).toHaveBeenCalledWith("agenda");
    expect(screen.getByRole("button", { name: "Agenda" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Innehåll agenda")).toBeVisible();
    expect(screen.queryByText("Innehåll att sortera")).not.toBeInTheDocument();
  });
});
