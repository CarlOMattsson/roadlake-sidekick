import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ViewTabs } from "@/features/work-app/shell/view-tabs";

const options = [
  { value: "agenda", label: "Agenda" },
  { value: "board", label: "Status" },
  { value: "hierarchy", label: "Projects" },
] as const;

/** jsdom lays nothing out: the tab row reports the widths a phone at 200 % text would. */
function rowWidths(scroll: number, client: number) {
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("work-view-tabs") ? scroll : 0;
    },
  );
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("work-view-tabs") ? client : 0;
    },
  );
}

afterEach(() => vi.restoreAllMocks());

describe("ViewTabs", () => {
  it("shows the tabs when they fit, and no picker", () => {
    rowWidths(240, 240);
    render(
      <ViewTabs
        label="Views"
        options={options}
        value="board"
        onChange={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Status" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(document.querySelector(".work-view-pick")).toBeNull();
    expect(document.querySelector(".work-view-tabs")).not.toHaveAttribute(
      "data-narrow",
    );
  });

  it("gives way to the view picker when the tabs do not fit, with one menuitemradio per view and ✓ on the chosen", async () => {
    rowWidths(300, 180);
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <ViewTabs
        label="Views"
        options={options}
        value="board"
        onChange={onChange}
      />,
    );
    const pick = document.querySelector<HTMLButtonElement>(".work-view-pick")!;
    expect(pick).toHaveTextContent("Status");
    expect(pick).toHaveAttribute("aria-haspopup", "menu");
    expect(pick).toHaveAttribute("aria-expanded", "false");
    expect(document.querySelector(".work-view-tabs")).toHaveAttribute(
      "data-narrow",
    );

    await user.click(pick);
    const menu = screen.getByRole("menu", { name: "Views" });
    const items = screen.getAllByRole("menuitemradio");
    expect(items.map((item) => item.textContent)).toEqual([
      "Agenda",
      "Status",
      "Projects",
    ]);
    expect(items.map((item) => item.getAttribute("aria-checked"))).toEqual([
      "false",
      "true",
      "false",
    ]);
    expect(menu).toContainElement(document.activeElement as HTMLElement);
    expect(items[1]).toHaveFocus();

    await user.keyboard("{ArrowDown}");
    expect(items[2]).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith("hierarchy");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(pick).toHaveFocus();
  });

  it("closes the menu on Escape and gives the focus back to the picker", async () => {
    rowWidths(300, 180);
    const user = userEvent.setup();
    render(
      <ViewTabs
        label="Views"
        options={options}
        value="agenda"
        onChange={() => {}}
      />,
    );
    const pick = document.querySelector<HTMLButtonElement>(".work-view-pick")!;
    await user.click(pick);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(pick).toHaveFocus();
  });
});
