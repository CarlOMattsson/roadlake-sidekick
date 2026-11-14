import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { workEn } from "@/features/work-app/shared/labels";
import {
  projectA,
  rootProject,
  rootTask,
  taskA,
  transport,
} from "@tests/helpers/work-app-fixtures";

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("shows the Project's editor in place of its values, not under them", async () => {
  const user = userEvent.setup();
  render(rootProject(transport({})));
  expect(await screen.findByText(projectA.description!)).toBeInTheDocument();
  // Edit sits in the ⋯ menu of the header row now.
  await user.click(
    await screen.findByRole("button", { name: workEn.moreActions }),
  );
  await user.click(screen.getByRole("button", { name: workEn.edit }));
  // The description is a field of the editor now, not a paragraph above it as well.
  expect(screen.getByLabelText(workEn.description)).toHaveValue(
    projectA.description,
  );
  expect(
    screen.queryByText(projectA.description!, { selector: "p" }),
  ).toBeNull();
  await user.click(screen.getByRole("button", { name: workEn.cancel }));
  expect(
    screen.getByText(projectA.description!, { selector: "p" }),
  ).toBeInTheDocument();
});

it("offers Show more only when the two drawn lines cut the description", async () => {
  // A wide box: the measured paragraph shows the whole text in its two lines. The observer reports once it observes,
  // as a browser's does.
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(40);
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(40);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private readonly report: () => void) {}
      observe() {
        queueMicrotask(this.report);
      }
      disconnect() {}
    },
  );
  const description =
    "Fakturan ska innehålla timmar för oktober, uppdelade per kund och med momsen angiven för varje rad.";
  const work = transport({
    getTask: vi.fn().mockResolvedValue({ task: { ...taskA, description } }),
  });
  render(rootTask(work));
  expect(await screen.findByText(description)).toBeInTheDocument();
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: workEn.descriptionMore }),
    ).toBeNull(),
  );
});
