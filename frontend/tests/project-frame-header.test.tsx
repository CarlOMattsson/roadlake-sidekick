import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import type {
  WorkProject,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";
import {
  projectA,
  transport as fakeTransport,
} from "./helpers/work-app-fixtures";

/* The Project page's head: a line "Hem · 1 av 3 klara" under the title, and the status chip only when not active. */

const DOMAIN_ID = "019f0000-0000-7000-8000-0000000000f1";

function renderProject(
  project: WorkProject,
  getDomain: WorkTransport["getDomain"],
  labels = workSv,
) {
  return render(
    <WorkView
      transport={fakeTransport({
        getProject: vi.fn().mockResolvedValue({ project }),
        getDomain,
      })}
      initial={{ kind: "project", id: project.id }}
      labels={labels}
    />,
  );
}

describe("the Project page's head", () => {
  it("shows the Area name and the progress on one line", async () => {
    renderProject(
      { ...projectA, domain_id: DOMAIN_ID, tasks_done: 1, tasks_total: 3 },
      vi.fn().mockResolvedValue({ domain: { id: DOMAIN_ID, name: "Hem" } }),
    );
    const progress = await screen.findByText("1 av 3 klara");
    await waitFor(() => expect(progress.closest("p")).toHaveTextContent("Hem"));
    // An active Project carries no status chip.
    expect(screen.queryByText(new RegExp(`^${workSv.status}:`))).toBeNull();
  });

  it("words the progress in English", async () => {
    renderProject(
      { ...projectA, domain_id: DOMAIN_ID, tasks_done: 2, tasks_total: 5 },
      vi.fn().mockResolvedValue({ domain: { id: DOMAIN_ID, name: "Home" } }),
      workEn,
    );
    expect(await screen.findByText("2 of 5 done")).toBeInTheDocument();
  });

  it("goes without the Area name, and without an error, when the Area cannot be read", async () => {
    const getDomain = vi.fn().mockRejectedValue(new Error("nope"));
    renderProject(
      { ...projectA, domain_id: DOMAIN_ID, tasks_done: 0, tasks_total: 2 },
      getDomain,
    );
    const progress = await screen.findByText("0 av 2 klara");
    await waitFor(() => expect(getDomain).toHaveBeenCalledWith(DOMAIN_ID));
    expect(progress.closest("p")).toHaveTextContent(/^0 av 2 klara/);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("names the status when the Project is not active", async () => {
    renderProject({ ...projectA, status: "paused" }, vi.fn());
    expect(
      await screen.findByText(new RegExp(`^${workSv.status}:`)),
    ).toBeInTheDocument();
  });

  it("draws no line when there is neither an Area nor a count", async () => {
    const { container } = renderProject(projectA, vi.fn());
    await screen.findByText(projectA.description as string);
    expect(container.querySelector(".work-frame-meta")).toBeNull();
  });
});
