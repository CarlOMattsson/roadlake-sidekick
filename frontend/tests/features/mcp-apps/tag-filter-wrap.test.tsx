import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TagFilter } from "@/features/mcp-apps/ui/tags";
import { tagEn } from "@/features/mcp-apps/ui/tag-labels";

const options = [
  { slug: "finance", label: "finance", count: 5 },
  { slug: "client", label: "client", count: 4 },
  { slug: "family", label: "family", count: 3 },
];

function chips(): string[] {
  const group = screen.getByRole("group", { name: tagEn.filter });
  return within(group)
    .getAllByRole("button")
    .map((button) => button.textContent ?? "")
    .filter((name) => options.some((tag) => tag.label === name));
}

describe("TagFilter wrap", () => {
  it("leads with the chosen tag in a row that scrolls", () => {
    render(
      <TagFilter
        options={options}
        selected={["family"]}
        onChange={vi.fn()}
        locale="en-GB"
      />,
    );
    expect(chips()).toEqual(["family", "finance", "client"]);
  });

  it("keeps the order when the row wraps, so a chosen chip stays under the pointer", () => {
    render(
      <TagFilter
        options={options}
        selected={["family"]}
        onChange={vi.fn()}
        locale="en-GB"
        wrap
      />,
    );
    expect(chips()).toEqual(["finance", "client", "family"]);
  });
});
