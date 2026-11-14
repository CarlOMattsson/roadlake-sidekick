import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { manageLabelsSv } from "@/features/work-app/shared/manage-labels";
import { savedViewsLabelsSv } from "@/features/work-app/saved-views/saved-views-labels";
import {
  meetings,
  otherAgenda,
  fakeTransport,
  renderBar,
  openPanel,
  unfoldEdit,
} from "@tests/helpers/saved-views-fixtures";

describe("SavedViewsBar: rename, archive and restore", () => {
  it("renames a view in place and returns the focus to its Edit button", async () => {
    const fake = fakeTransport([meetings]);
    fake.updateSavedWorkView.mockResolvedValue({
      saved_view: { ...meetings, name: "Veckomöten", version: 3 },
    });
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });

    await openPanel(user);
    await unfoldEdit(user, "Möten");
    await user.click(screen.getByRole("button", { name: "Byt namn: Möten" }));
    const edit = screen.getByRole("form", { name: "Byt namn: Möten" });
    const input = within(edit).getByRole("textbox");
    expect(input).toHaveFocus();
    await user.clear(input);
    await user.type(input, "Veckomöten");
    await user.click(within(edit).getByRole("button", { name: "Spara" }));

    expect(fake.updateSavedWorkView).toHaveBeenCalledWith(
      meetings.id,
      2,
      { name: "Veckomöten" },
      expect.any(String),
    );
    expect(
      await screen.findByRole("button", { name: "Ändra: Veckomöten" }),
    ).toHaveFocus();
    expect(screen.getByText("Veckomöten")).toBeInTheDocument();
  });

  it("cancels a rename without a write and returns the focus to Edit", async () => {
    const fake = fakeTransport([meetings]);
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });

    await openPanel(user);
    await unfoldEdit(user, "Möten");
    await user.click(screen.getByRole("button", { name: "Byt namn: Möten" }));
    const edit = screen.getByRole("form", { name: "Byt namn: Möten" });
    await user.click(within(edit).getByRole("button", { name: "Avbryt" }));
    expect(screen.getByRole("button", { name: "Ändra: Möten" })).toHaveFocus();
    expect(fake.updateSavedWorkView).not.toHaveBeenCalled();
  });

  it("archives a view with an Undo line that restores it, and focuses Undo, then the view", async () => {
    const archived = {
      ...meetings,
      archived_at: "2026-11-01T10:00:00Z",
      version: 3,
    };
    const fake = fakeTransport([meetings]);
    fake.archiveSavedWorkView.mockResolvedValue({ saved_view: archived });
    fake.restoreSavedWorkView.mockResolvedValue({
      saved_view: { ...archived, archived_at: null, version: 4 },
    });
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });

    await openPanel(user);
    await unfoldEdit(user, "Möten");
    await user.click(screen.getByRole("button", { name: "Arkivera: Möten" }));

    expect(fake.archiveSavedWorkView).toHaveBeenCalledWith(
      meetings.id,
      2,
      expect.any(String),
    );
    expect(
      await screen.findByText("Arkiverade vyn ”Möten”."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Möten" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ångra" })).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Ångra" }));
    expect(fake.restoreSavedWorkView).toHaveBeenCalledWith(
      meetings.id,
      3,
      expect.any(String),
    );
    expect(await screen.findByRole("button", { name: "Möten" })).toHaveFocus();
    expect(
      screen.queryByRole("button", { name: "Ångra" }),
    ).not.toBeInTheDocument();
  });

  it("shows archived views when the switch is on, and restores one into the active list", async () => {
    const archived = {
      ...meetings,
      archived_at: "2026-10-30T09:00:00Z",
      version: 5,
    };
    const fake = fakeTransport([meetings]);
    fake.listSavedWorkViews
      .mockResolvedValueOnce([meetings])
      .mockResolvedValueOnce([archived]);
    fake.restoreSavedWorkView.mockResolvedValue({
      saved_view: { ...archived, archived_at: null, version: 6 },
    });
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });

    await openPanel(user);
    await screen.findByText("Möten");
    await user.click(screen.getByRole("checkbox", { name: "Visa arkiverade" }));
    expect(fake.listSavedWorkViews).toHaveBeenLastCalledWith(true);

    await user.click(
      await screen.findByRole("button", { name: "Återställ: Möten" }),
    );
    expect(fake.restoreSavedWorkView).toHaveBeenCalledWith(
      meetings.id,
      5,
      expect.any(String),
    );
    expect(await screen.findByRole("button", { name: "Möten" })).toHaveFocus();
    expect(
      screen.queryByRole("button", { name: "Återställ: Möten" }),
    ).not.toBeInTheDocument();
  });

  it("says so when the switch is on and nothing is archived", async () => {
    const fake = fakeTransport([meetings]);
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });

    await openPanel(user);
    await screen.findByText("Möten");
    await user.click(screen.getByRole("checkbox", { name: "Visa arkiverade" }));
    expect(
      await screen.findByText("Inga arkiverade vyer."),
    ).toBeInTheDocument();
  });

  it("reads the list again on a conflict and keeps the reason in view", async () => {
    const fake = fakeTransport([meetings]);
    fake.updateSavedWorkView.mockRejectedValueOnce(
      Object.assign(new Error("stale"), { code: "conflict" }),
    );
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });

    await openPanel(user);
    await unfoldEdit(user, "Möten");
    await user.click(screen.getByRole("button", { name: "Byt namn: Möten" }));
    const edit = screen.getByRole("form", { name: "Byt namn: Möten" });
    await user.clear(within(edit).getByRole("textbox"));
    await user.type(within(edit).getByRole("textbox"), "Nytt");
    await user.click(within(edit).getByRole("button", { name: "Spara" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(manageLabelsSv.conflict);
    await user.click(within(alert).getByRole("button", { name: "Uppdatera" }));
    expect(fake.listSavedWorkViews).toHaveBeenCalledTimes(2);
  });
});

describe("SavedViewsBar: opening a view", () => {
  it("opens a view through onOpen from its row and folds the panel away", async () => {
    const fake = fakeTransport([meetings]);
    const user = userEvent.setup();
    const { onOpen } = renderBar({ transport: fake.transport });

    await openPanel(user);
    await user.click(await screen.findByRole("button", { name: "Möten" }));

    expect(onOpen).toHaveBeenCalledWith(meetings.definition, "Möten");
    expect(
      screen.getByRole("button", { name: "Sparade vyer" }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Möten")).not.toBeInTheDocument();
  });

  it("marks the open view with aria-current and Öppen, with no separate Open button, and reads it again on a second press", async () => {
    const fake = fakeTransport([meetings, otherAgenda]);
    const user = userEvent.setup();
    const { onOpen } = renderBar({ transport: fake.transport });

    await openPanel(user);
    await user.click(await screen.findByRole("button", { name: "Möten" }));
    await openPanel(user);

    const row = await screen.findByRole("button", { name: "Möten" });
    expect(row).toHaveAttribute("aria-current", "true");
    expect(row).toHaveAccessibleDescription(/Öppen/);
    expect(screen.getByRole("button", { name: "Veckan" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(screen.queryByRole("button", { name: /^Öppna/ })).toBeNull();

    await user.click(row);
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("describes what each view holds under its name", async () => {
    const fake = fakeTransport([meetings]);
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });

    await openPanel(user);
    expect(
      await screen.findByRole("button", { name: "Möten" }),
    ).toHaveAccessibleDescription("Status: Att göra");
  });

  it("unfolds Byt namn and Arkivera behind Ändra, one row at a time", async () => {
    const fake = fakeTransport([meetings, otherAgenda]);
    const user = userEvent.setup();
    renderBar({ transport: fake.transport });

    await openPanel(user);
    const edit = await screen.findByRole("button", { name: "Ändra: Möten" });
    expect(edit).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /^Byt namn/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Arkivera/ })).toBeNull();

    await user.click(edit);
    expect(edit).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("button", { name: "Byt namn: Möten" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Arkivera: Möten" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Ändra: Veckan" }));
    expect(edit).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("button", { name: "Byt namn: Möten" }),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "Byt namn: Veckan" }),
    ).toBeInTheDocument();
  });

  it("shows that the view is opening while the read runs", async () => {
    const fake = fakeTransport([meetings]);
    const user = userEvent.setup();
    renderBar({
      transport: fake.transport,
      onOpen: vi.fn(() => new Promise<boolean>(() => undefined)),
    });

    await openPanel(user);
    await user.click(await screen.findByRole("button", { name: "Möten" }));
    expect(screen.getByText("Öppnar vyn…")).toBeInTheDocument();
  });

  it("shows an error when the view cannot be opened, and Try again opens it", async () => {
    const fake = fakeTransport([meetings]);
    const user = userEvent.setup();
    const onOpen = vi
      .fn()
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(true);
    renderBar({ transport: fake.transport, onOpen });

    await openPanel(user);
    await user.click(await screen.findByRole("button", { name: "Möten" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(savedViewsLabelsSv.openFailed);

    await user.click(
      within(alert).getByRole("button", { name: "Försök igen" }),
    );
    expect(
      screen.getByRole("button", { name: "Sparade vyer" }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onOpen).toHaveBeenCalledTimes(2);
  });
});
