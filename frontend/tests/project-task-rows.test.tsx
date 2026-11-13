import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { workSv } from "@/features/work-app/shared/labels";
import { WorkView } from "@/features/work-app/view/work-view";
import { cssRules, declares, readCss, valueOf } from "./helpers/css-contract";
import {
  projectA,
  transport as fakeTransport,
} from "./helpers/work-app-fixtures";

/* The Task rows of a Project's and a Process's page are the detail rows of a Task or a Contact: no padding of their own,
   and a row without a meta line holds its line in the middle of its 48 (measured on the simulated host). */

const rules = cssRules(readCss("work-app/hierarchy/hierarchy.css"));
const PAGES = ":is(.work-project, .work-process)";

it("names the Project page, so its rows can be styled as a page's", async () => {
  render(
    <WorkView
      transport={fakeTransport({
        getProject: vi.fn().mockResolvedValue({ project: projectA }),
      })}
      initial={{ kind: "project", id: projectA.id }}
      labels={workSv}
    />,
  );
  const title = await screen.findByRole("heading", { name: projectA.title });
  expect(title.closest("article")).toHaveClass("work-project");
});

it("gives the page's Task rows no padding of their own", () => {
  const rule = rules.find(
    (r) =>
      r.selector === `.sidekick-work ${PAGES} .work-list > li.work-agenda-row`,
  );
  expect(rule && declares(rule, "padding", "0")).toBe(true);
});

it("puts a row without a meta line in the middle of its 48, ring, title and › together", () => {
  const rule = rules.find(
    (r) =>
      r.selector ===
      `.sidekick-work ${PAGES} .work-agenda-line:not(:has(.work-card-meta))`,
  );
  expect(rule).toBeDefined();
  expect(valueOf(rule!.body, "--sk-row-pad")).toBe(
    "calc(6px + var(--sk-row-air-extra))",
  );
  expect(valueOf(rule!.body, "--sk-lead-h")).toContain("var(--sk-row-pad)");
});
