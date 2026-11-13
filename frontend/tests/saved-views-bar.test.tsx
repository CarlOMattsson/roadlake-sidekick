import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { savedViewsLabelsSv } from "@/features/work-app/saved-views/saved-views-labels";
import type {
  WorkSavedView,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import {
  meetings,
  boardView,
  fakeTransport,
  renderBar,
  openPanel,
} from "./helpers/saved-views-fixtures";
import { deferred } from "./helpers/deferred";

describe("SavedViewsBar: the panel and the list", () => {
  it("shows the toggle with aria-expanded and reads nothing until the panel opens", async () => {
    const fake = fakeTransport([meetings]);
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });

    const toggle = screen.getByRole("button", { name: "Sparade vyer" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(fake.listSavedWorkViews).not.toHaveBeenCalled();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("Möten")).toBeInTheDocument();
    expect(fake.listSavedWorkViews).toHaveBeenCalledWith(false);
  });

  it("lists only the views saved for this tab", async () => {
    const fake = fakeTransport([meetings, boardView]);
    const user = userEvent.setup();
    renderBar({ transport: fake.transport, tab: "agenda" });

    await openPanel(user);
    expect(await screen.findByText("Möten")).toBeInTheDocument();
    expect(screen.queryByText("Bräde")).not.toBeInTheDocument();
  });

  it("says there are no saved views when the tab has none", async () => {
    const fake = fakeTransport([boardView]);
    const user = userEvent.setup();
    renderBar({ transport: fake.transport, tab: "agenda" });

    await openPanel(user);
    expect(
      await screen.findByText(savedViewsLabelsSv.empty),
    ).toBeInTheDocument();
  });

  it("shows an error with Try again when the read fails, and reads again on Try again", async () => {
    const fake = fakeTransport([meetings]);
    fake.listSavedWorkViews
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce([meetings]);
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });

    await openPanel(user);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(savedViewsLabelsSv.listFailed);
    await user.click(
      within(alert).getByRole("button", { name: "Försök igen" }),
    );
    expect(await screen.findByText("Möten")).toBeInTheDocument();
    expect(fake.listSavedWorkViews).toHaveBeenCalledTimes(2);
  });

  it("shows the read error, without throwing, when the transport has no saved-view method", async () => {
    const user = userEvent.setup();
    renderBar({ transport: {} as unknown as WorkTransport });

    await openPanel(user);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      savedViewsLabelsSv.listFailed,
    );
  });

  it("drops a read that answers after the panel was closed", async () => {
    const fake = fakeTransport([meetings]);
    const late = deferred<WorkSavedView[]>();
    fake.listSavedWorkViews.mockReturnValueOnce(late.promise);
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });

    await openPanel(user);
    await user.click(screen.getByRole("button", { name: "Sparade vyer" }));
    act(() => {
      late.resolve([]);
    });
    await openPanel(user);
    // The late answer (an empty list) was dropped; the newer read shows the view.
    expect(await screen.findByText("Möten")).toBeInTheDocument();
    expect(
      screen.queryByText(savedViewsLabelsSv.empty),
    ).not.toBeInTheDocument();
  });
});

describe("SavedViewsBar: the order of the panel", () => {
  it("lists the views first, then the archived switch, then the save form", async () => {
    const fake = fakeTransport([meetings]);
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });

    await openPanel(user);
    const list = await screen.findByRole("list");
    const form = screen.getByRole("form", { name: "Spara nuvarande vy" });
    const archived = screen.getByRole("checkbox", { name: "Visa arkiverade" });
    const before = Node.DOCUMENT_POSITION_FOLLOWING;
    expect(list.compareDocumentPosition(archived) & before).toBe(before);
    expect(archived.compareDocumentPosition(form) & before).toBe(before);
  });

  it("says what Save will save, from the tab's filters", async () => {
    const fake = fakeTransport([]);
    const user = userEvent.setup();
    renderBar({
      transport: fake.transport,
      filters: { tags: ["viktig", "kund"], priority: "high" },
    });

    await openPanel(user);
    expect(
      await screen.findByText(
        "Det här sparas: Taggar: viktig, kund · Prioritet: Hög",
      ),
    ).toBeInTheDocument();
  });

  it("says it saves all tasks when no filter is set", async () => {
    const fake = fakeTransport([]);
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });

    await openPanel(user);
    expect(
      await screen.findByText("Det här sparas: Alla uppgifter"),
    ).toBeInTheDocument();
  });
});

describe("SavedViewsBar: saving the current view", () => {
  it("saves the tab's filters under the typed name, lists it on top and clears the field", async () => {
    const created: WorkSavedView = {
      ...meetings,
      id: "019f0000-0000-7000-8000-0000000000v3",
      name: "Mina möten",
    };
    const fake = fakeTransport([meetings]);
    fake.createSavedWorkView.mockResolvedValue({ saved_view: created });
    const user = userEvent.setup();
    renderBar({ transport: fake.transport, filters: { status: "todo" } });

    await openPanel(user);
    await screen.findByText("Möten");
    const name = screen.getByLabelText(savedViewsLabelsSv.nameLabel);
    await user.type(name, "  Mina möten ");
    await user.click(screen.getByRole("button", { name: "Spara" }));

    expect(fake.createSavedWorkView).toHaveBeenCalledWith(
      "Mina möten",
      { view: "agenda", context: "all", status: "todo" },
      expect.any(String),
    );
    expect(
      await screen.findByText("Sparade vyn ”Mina möten”."),
    ).toBeInTheDocument();
    const rows = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Mina möten");
    expect(name).toHaveValue("");
    expect(name).toHaveFocus();
  });

  it("saves an empty filter set as a view of everything", async () => {
    const fake = fakeTransport();
    fake.createSavedWorkView.mockResolvedValue({
      saved_view: {
        ...meetings,
        name: "Allt",
        definition: { view: "board", context: "all" },
      },
    });
    const user = userEvent.setup();
    renderBar({ transport: fake.transport, tab: "board" });

    await openPanel(user);
    await user.type(
      screen.getByLabelText(savedViewsLabelsSv.nameLabel),
      "Allt",
    );
    await user.click(screen.getByRole("button", { name: "Spara" }));
    expect(fake.createSavedWorkView).toHaveBeenCalledWith(
      "Allt",
      { view: "board", context: "all" },
      expect.any(String),
    );
  });

  it("refuses a blank name with a message and sends nothing", async () => {
    const fake = fakeTransport();
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });

    await openPanel(user);
    await user.type(screen.getByLabelText(savedViewsLabelsSv.nameLabel), "   ");
    await user.click(screen.getByRole("button", { name: "Spara" }));
    expect(await screen.findByText("Skriv ett namn.")).toBeInTheDocument();
    expect(screen.getByLabelText(savedViewsLabelsSv.nameLabel)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(fake.createSavedWorkView).not.toHaveBeenCalled();
  });

  it("blocks the save of a single Project's board, with the reason shown", async () => {
    const fake = fakeTransport();
    const user = userEvent.setup();
    renderBar({
      transport: fake.transport,
      tab: "board",
      filters: { project_id: "019f0000-0000-7000-8000-0000000000p1" },
    });

    await openPanel(user);
    expect(
      await screen.findByText(
        "Ett enskilt projekts bräde kan inte sparas som vy.",
      ),
    ).toBeInTheDocument();
    await user.type(
      screen.getByLabelText(savedViewsLabelsSv.nameLabel),
      "Projekt",
    );
    expect(screen.getByRole("button", { name: "Spara" })).toBeDisabled();
    expect(fake.createSavedWorkView).not.toHaveBeenCalled();
  });
});
