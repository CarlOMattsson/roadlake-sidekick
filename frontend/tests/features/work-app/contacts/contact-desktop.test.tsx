// A Contact beside its list in a wide frame (desktop spec 3.3): the avatar before the name, Tasks and notes in
// wrappers the stylesheet lays side by side, the ⋯ as a popover that Esc closes with the focus back on ⋯. A simulated
// host: jsdom has no layout, so the widths themselves are measured in the browser spec, not here.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { RoomSurfaceContext } from "@/features/mcp-apps/ui/room-context";
import { workEn } from "@/features/work-app/shared/labels";
import { anna, contactRoot, transport } from "@tests/helpers/work-app-fixtures";

function mount(pane?: "detail") {
  render(
    <RoomSurfaceContext.Provider value={{ active: true, framed: true, pane }}>
      {contactRoot(transport(), workEn)}
    </RoomSurfaceContext.Provider>,
  );
}

it("draws the avatar with the initials before the name beside a list, and none elsewhere", async () => {
  mount("detail");
  const name = await screen.findByRole("heading", { name: anna.display_name });
  const avatar = name
    .closest(".work-contact-ident")
    ?.querySelector(".work-contact-avatar--large");
  expect(avatar).toHaveTextContent("AA");
  expect(avatar).toHaveAttribute("aria-hidden", "true");
});

it("draws no avatar and no wrapper in a single column", async () => {
  mount();
  await screen.findByRole("heading", { name: anna.display_name });
  expect(document.querySelector(".work-contact-ident")).toBeNull();
  expect(document.querySelector(".work-contact-avatar")).toBeNull();
});

it("holds Tasks and notes in a columns wrapper of the page, which draws no box until the stylesheet lays them side by side", async () => {
  mount("detail");
  await screen.findByRole("heading", { name: anna.display_name });
  const columns = document.querySelector(".work-contact-cols");
  expect(columns).not.toBeNull();
  expect(columns?.parentElement?.tagName).toBe("ARTICLE");
});

it("opens ⋯ under its button and gives the focus back to it on Esc", async () => {
  const user = userEvent.setup();
  mount("detail");
  const more = await screen.findByRole("button", { name: workEn.moreActions });
  await user.click(more);
  expect(more).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: workEn.edit })).toBeVisible();
  await user.keyboard("{Escape}");
  expect(
    screen.queryByRole("button", { name: workEn.archiveContact }),
  ).toBeNull();
  expect(more).toHaveFocus();
});
