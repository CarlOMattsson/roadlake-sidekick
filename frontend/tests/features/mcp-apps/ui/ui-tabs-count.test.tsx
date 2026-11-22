import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Tabs } from "@/features/mcp-apps/ui/tabs";

// jsdom joins a nested span to its label without the space ("Att sortera3"); a browser keeps it.
const SORT3 = "Att sortera 3";

describe("Tabs with a count", () => {
  function renderTabs() {
    return render(
      <Tabs
        label="Vyer"
        options={[
          { value: "agenda", label: "Agenda" },
          { value: "unsorted", label: "Att sortera", count: 3 },
        ]}
        value="agenda"
        onChange={() => {}}
      />,
    );
  }

  it("draws the count after the label in the same button, named 'Att sortera 3'", () => {
    renderTabs();
    const tab = screen.getByRole("button", { name: SORT3 });
    const count = tab.querySelector(".sk-tabs__count");
    expect(count).not.toBeNull();
    expect(count?.textContent?.trim()).toBe("3");
    // The label and the count share one span, so they stand on one line in the tab's column.
    expect(count?.parentElement?.parentElement).toBe(tab);
    expect(count?.parentElement?.textContent).toBe("Att sortera 3");
    expect(tab.textContent).toBe("Att sortera 3");
    expect(tab).toHaveAttribute("data-label", "Att sortera 3");
  });

  it("leaves a tab without a count as its bare label", () => {
    renderTabs();
    const tab = screen.getByRole("button", { name: "Agenda" });
    expect(tab.querySelector(".sk-tabs__count")).toBeNull();
    expect(tab).toHaveAttribute("data-label", "Agenda");
  });

  it("draws a count of 0 as well, as a count is only absent when undefined", () => {
    render(
      <Tabs
        label="Vyer"
        options={[{ value: "unsorted", label: "Att sortera", count: 0 }]}
        value={null}
        onChange={() => {}}
      />,
    );
    expect(
      screen.getByRole("button", { name: /^Att sortera ?0$/ }),
    ).toBeInTheDocument();
  });
});
