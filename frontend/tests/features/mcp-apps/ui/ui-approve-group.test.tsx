import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  ApproveGroup,
  groupBatch,
  type ApproveGroupItem,
} from "@/features/mcp-apps/ui/approve-group";

const items: ApproveGroupItem[] = [
  { id: "a", label: "Skapa uppgift: Ring Karin" },
  { id: "b", label: "Skapa kontakt: Lena Holm" },
  { id: "c", label: "Koppla anteckning till Flytten" },
  { id: "d", label: "Ändra uppgift: Skicka offert" },
  { id: "e", label: "Skapa uppgift: Boka plattsättare" },
];

function Harness({
  list = items.slice(0, 3),
  max,
  locale = "sv-SE",
  onApproveAll,
}: {
  list?: ApproveGroupItem[];
  max?: number;
  locale?: string;
  onApproveAll: (ids: string[]) => void;
}) {
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  return (
    <ApproveGroup
      locale={locale}
      title="3 säkra förslag"
      items={list}
      excluded={excluded}
      max={max}
      onToggle={(id) =>
        setExcluded((now) => {
          const next = new Set(now);
          if (next.has(id)) next.delete(id);
          else next.add(id);
          return next;
        })
      }
      onApproveAll={onApproveAll}
    />
  );
}

describe("groupBatch", () => {
  it("covers every item without a cap, less the rows taken out", () => {
    expect(groupBatch(items, new Set(["b"]))).toEqual({
      batch: items,
      ids: ["a", "c", "d", "e"],
      beyond: 0,
    });
  });

  it("covers at most max items per confirmation, and a row taken out pulls in none", () => {
    const capped = groupBatch(items, new Set(["b"]), 3);
    expect(capped.batch.map((item) => item.id)).toEqual(["a", "b", "c"]);
    expect(capped.ids).toEqual(["a", "c"]);
    expect(capped.beyond).toBe(2);
    expect(groupBatch(items, new Set(), 0).ids).toEqual([]);
    expect(groupBatch(items.slice(0, 2), new Set(), 3).beyond).toBe(0);
  });
});

describe("ApproveGroup", () => {
  it("counts what is left in the group as rows are taken out and put back", async () => {
    const user = userEvent.setup();
    const approve = vi.fn();
    render(<Harness onApproveAll={approve} />);
    const group = screen.getByRole("region", { name: "3 säkra förslag" });
    const rows = within(group).getAllByRole("button", { pressed: true });
    expect(rows).toHaveLength(3);
    expect(
      within(group).getByRole("button", { name: "Godkänn alla 3" }),
    ).toBeVisible();
    await user.click(rows[1]!);
    expect(rows[1]).toHaveAttribute("aria-pressed", "false");
    await user.click(within(group).getByRole("button", { name: "Godkänn 2" }));
    expect(approve).toHaveBeenCalledWith(["a", "c"]);
    rows[0]!.focus();
    await user.keyboard(" ");
    expect(rows[0]).toHaveAttribute("aria-pressed", "false");
    await user.click(rows[1]!);
    expect(
      within(group).getByRole("button", { name: "Godkänn 2" }),
    ).toBeVisible();
  });

  it("holds the button when nothing is left in the group", async () => {
    const user = userEvent.setup();
    const approve = vi.fn();
    render(<Harness list={items.slice(0, 1)} onApproveAll={approve} />);
    await user.click(
      screen.getByRole("button", { name: "Skapa uppgift: Ring Karin" }),
    );
    const button = screen.getByRole("button", { name: "Godkänn" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    await user.click(button);
    expect(approve).not.toHaveBeenCalled();
  });

  it("caps one confirmation at max and names the rest", async () => {
    const user = userEvent.setup();
    const approve = vi.fn();
    render(<Harness list={items} max={3} onApproveAll={approve} />);
    expect(screen.getAllByRole("button", { pressed: true })).toHaveLength(3);
    expect(
      screen.getByText("2 till efter de här, högst 3 åt gången"),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Godkänn 3" }));
    expect(approve).toHaveBeenCalledWith(["a", "b", "c"]);
  });

  it("does nothing while it runs, and keeps the group with the failure's line", () => {
    const approve = vi.fn();
    const toggle = vi.fn();
    const props = {
      locale: "sv-SE",
      title: "3 säkra förslag",
      items: items.slice(0, 3),
      excluded: new Set<string>(),
      onToggle: toggle,
      onApproveAll: approve,
    };
    const { rerender } = render(<ApproveGroup {...props} busy />);
    fireEvent.click(screen.getByRole("button", { name: "Godkänner…" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Skapa uppgift: Ring Karin" }),
    );
    expect(approve).not.toHaveBeenCalled();
    expect(toggle).not.toHaveBeenCalled();
    rerender(<ApproveGroup {...props} failed />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Det gick inte att godkänna. Försök igen.",
    );
    expect(screen.getAllByRole("button", { pressed: true })).toHaveLength(3);
  });

  it("reads in English", () => {
    render(
      <Harness locale="en-GB" list={items} max={3} onApproveAll={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Approve 3" })).toBeVisible();
    expect(
      screen.getByText("2 more after these, at most 3 at a time"),
    ).toBeVisible();
  });
});
