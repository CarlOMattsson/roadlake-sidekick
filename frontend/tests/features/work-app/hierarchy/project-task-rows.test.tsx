import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { workSv } from "@/features/work-app/shared/labels";
import { WorkView } from "@/features/work-app/view/work-view";
import {
  projectA,
  transport as fakeTransport,
} from "@tests/helpers/work-app-fixtures";

/* The Task rows of a Project's and a Process's page are the rows of agenda.css, shared with a Task's and a Contact's
   lists. How they look (no padding of their own, a row without a meta line holding its line in the middle of its 48)
   is measured on the simulated host in e2e/work-lists-styles-mcp-app.spec.ts; this file keeps the class the styles
   hang on. */

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
