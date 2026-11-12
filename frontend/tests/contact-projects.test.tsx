import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ContactProjects } from "@/features/work-app/contacts/contact-projects";
import { projectStatusLabel, workSv } from "@/features/work-app/shared/labels";
import type { WorkProjectSummary } from "@/features/work-app/transport/transport";

const offert: WorkProjectSummary = {
  id: "019f0000-0000-7000-8000-0000000000d1",
  title: "Offert till Anna",
  status: "active",
};
const sajt: WorkProjectSummary = {
  id: "019f0000-0000-7000-8000-0000000000d2",
  title: "Ny webbplats",
  status: "paused",
};
const kok: WorkProjectSummary = {
  id: "019f0000-0000-7000-8000-0000000000d3",
  title: "Köksrenovering",
  status: "completed",
};

describe("ContactProjects", () => {
  it("shows each project as a row with its status alone and a ›, and no remove control", () => {
    render(
      <ContactProjects
        projects={[offert, sajt, kok]}
        onOpen={vi.fn()}
        labels={workSv}
      />,
    );
    expect(
      screen.getByRole("heading", { name: workSv.projects }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: offert.title }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: sajt.title }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(projectStatusLabel(workSv, "active")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(projectStatusLabel(workSv, "paused")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(projectStatusLabel(workSv, "completed")),
    ).toBeInTheDocument();
    // No "Status:" prefix on the meta line.
    expect(
      screen.queryByText(
        `${workSv.status}: ${projectStatusLabel(workSv, "active")}`,
      ),
    ).toBeNull();
    // Each row's only control is its title button: no ⋯ and no unlink.
    expect(screen.getAllByRole("button")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /⋯|Fler|More/ })).toBeNull();
    expect(screen.queryByText(/Ta bort koppling|Remove link/)).toBeNull();
    // The row ends in › (aria-hidden), the same chevron as the note rows.
    const row = screen
      .getByRole("button", { name: offert.title })
      .closest("li");
    expect(row?.querySelector(".work-open-chevron")).not.toBeNull();
  });

  it("opens the Project when its title is pressed", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(
      <ContactProjects
        projects={[offert, sajt]}
        onOpen={onOpen}
        labels={workSv}
      />,
    );
    await user.click(screen.getByRole("button", { name: sajt.title }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledWith(sajt.id);
  });

  it("renders nothing, not even the heading, when no Project is linked", () => {
    const { container } = render(
      <ContactProjects projects={[]} onOpen={vi.fn()} labels={workSv} />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("heading", { name: workSv.projects })).toBeNull();
  });

  it("gives each row its own menu with Ta bort koppling when the host offers the removal", async () => {
    const user = userEvent.setup();
    const onRemove = vi.fn();
    render(
      <ContactProjects
        projects={[offert, sajt]}
        onOpen={vi.fn()}
        onRemove={onRemove}
        labels={workSv}
      />,
    );
    // No visible ⋯: a hidden button per row opens the menu for a screen reader, and the tip says how for everyone.
    expect(
      screen.getByRole("button", { name: workSv.rowMenuButton(sajt.title) }),
    ).toHaveClass("work-visually-hidden");
    expect(screen.getByText(/för fler val\./)).toBeInTheDocument();
    const row = screen
      .getByRole("button", { name: sajt.title })
      .closest("li") as HTMLElement;
    expect(
      within(row).queryByRole("button", { name: "Ta bort koppling" }),
    ).toBeNull();
    fireEvent.contextMenu(row);
    await user.click(
      await within(row).findByRole("button", { name: "Ta bort koppling" }),
    );
    expect(onRemove).toHaveBeenCalledWith(sajt.id);
    expect(onRemove).toHaveBeenCalledTimes(1);
  });
});
