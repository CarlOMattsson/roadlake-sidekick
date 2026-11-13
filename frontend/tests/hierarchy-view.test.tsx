import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState, type ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  HIERARCHY_MAX_ROWS,
  HierarchyView as PlainHierarchyView,
  groupCounts,
  hierarchyChildren,
  hierarchyItems,
  hierarchyProgress,
  mergeHierarchyPage,
  projectsLayout,
} from "@/features/work-app/hierarchy/hierarchy-view";
import {
  hierarchyDetailLabelsEn,
  hierarchyDetailLabelsSv,
} from "@/features/work-app/hierarchy/hierarchy-detail-labels";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import {
  rootFromToolResult,
  type WorkHierarchyFrame,
  type WorkHierarchyNode,
} from "@/features/work-app/transport/transport";
import {
  domain,
  frameOf,
  processNode,
  project,
  taskOf,
  transport,
} from "./helpers/hierarchy-view-fixtures";

const PAST = "2020-01-01T00:00:00Z";
const FUTURE = "2999-01-01T00:00:00Z";

type ViewProps = ComponentProps<typeof PlainHierarchyView>;

/** The view as the app shows it: rows open a page. Tests of the read-only look use PlainHierarchyView. */
function HierarchyView(props: ViewProps) {
  return <PlainHierarchyView onOpen={vi.fn()} {...props} />;
}

function node(
  kind: string,
  id: string,
  title: string,
  parent: WorkHierarchyNode | null,
  fields: Partial<WorkHierarchyNode> = {},
): WorkHierarchyNode {
  return {
    kind,
    id,
    parent_id: parent?.id ?? null,
    title,
    status: "active",
    version: 1,
    ...fields,
  };
}

function buttonTitles(): string[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(".work-tree-open"),
  ).map((button) => button.textContent ?? "");
}

describe("get_work_hierarchy result", () => {
  it("opens a hierarchy frame from the nodes and truncated flag", () => {
    expect(
      rootFromToolResult({ nodes: [domain, project], truncated: false }),
    ).toEqual(frameOf([domain, project]));
  });

  it("keeps the Tasks the server sends with include_tasks", () => {
    const task = taskOf("t1", project);
    expect(
      rootFromToolResult({
        nodes: [domain, project],
        truncated: false,
        tasks: [task],
      }),
    ).toEqual(frameOf([domain, project], [task]));
  });

  it("keeps the other shapes unchanged and ignores a malformed hierarchy", () => {
    expect(rootFromToolResult({ task: { id: "t1" } })).toEqual({
      kind: "task",
      id: "t1",
    });
    expect(
      rootFromToolResult({ nodes: [{ id: 3 }], truncated: false }),
    ).toBeUndefined();
    expect(rootFromToolResult({ nodes: [domain] })).toBeUndefined();
  });
});

describe("hierarchy helpers", () => {
  const task = taskOf("t1", project, {
    steps: [
      { id: "s1", title: "Ring", status: "completed" },
      { id: "s2", title: "Mejla", status: "todo" },
    ],
  });

  it("lists the nodes, then each Task under its parent followed by its Steps", () => {
    const items = hierarchyItems(frameOf([domain, project], [task]));
    expect(items.map((item) => [item.kind, item.id, item.parent_id])).toEqual([
      ["domain", domain.id, null],
      ["project", project.id, domain.id],
      ["task", "t1", project.id],
      ["step", "s1", "t1"],
      ["step", "s2", "t1"],
    ]);
    expect(hierarchyItems(frameOf([domain]))).toHaveLength(1);
  });

  it("gives the children of a node in order and none to a node whose parent is missing", () => {
    const children = hierarchyChildren([domain, processNode, project]);
    expect(children.get(domain.id)?.map((child) => child.title)).toEqual([
      "Fakturering",
      "Offert till Anna",
    ]);
    expect(hierarchyChildren([project]).size).toBe(0);
  });

  it("sums progress: a Task counts Steps, a Domain counts every Task beneath it", () => {
    const items = hierarchyItems(
      frameOf(
        [domain, project],
        [task, taskOf("t2", project, { status: "completed" })],
      ),
    );
    const children = hierarchyChildren(items);
    const byId = (id: string) => items.find((item) => item.id === id);
    expect(hierarchyProgress(byId("t1")!, children)).toEqual({
      done: 1,
      total: 2,
    });
    expect(hierarchyProgress(domain, children)).toEqual({ done: 1, total: 2 });
    expect(hierarchyProgress(byId("s1")!, children)).toBeNull();
    expect(hierarchyProgress(processNode, children)).toBeNull();
  });

  it("counts done, total and overdue per group, and is undefined without Tasks", () => {
    const now = new Date("2026-11-11T12:00:00Z");
    const counts = groupCounts(
      frameOf(
        [domain, project, processNode],
        [
          taskOf("a", project, { status: "completed", due_at: PAST }),
          taskOf("b", project, { due_at: PAST }),
          taskOf("c", project, { due_at: FUTURE }),
          taskOf("d", processNode),
        ],
      ),
      now,
    );
    expect(counts?.get(project.id)).toEqual({ done: 1, total: 3, overdue: 1 });
    expect(counts?.get(processNode.id)).toEqual({
      done: 0,
      total: 1,
      overdue: 0,
    });
    expect(groupCounts(frameOf([domain, project]))).toBeUndefined();
  });
});

describe("projectsLayout", () => {
  const second = node("domain", "dom-2", "Hälsa", null);
  const early = node("process", "proc-0", "Rutin", second);
  const done = node("project", "done-1", "Klart", domain, {
    status: "completed",
  });
  const paused = node("project", "pro-2", "Pausat", domain, {
    status: "paused",
  });

  it("puts each Domain's open Projects before its Processes, in server order", () => {
    const layout = projectsLayout([
      domain,
      processNode,
      project,
      paused,
      second,
      early,
    ]);
    expect(layout.sections.map((s) => s.domain?.title)).toEqual([
      "Ekonomi",
      "Hälsa",
    ]);
    expect(layout.sections[0]?.groups.map((g) => g.title)).toEqual([
      "Offert till Anna",
      "Pausat",
      "Fakturering",
    ]);
    expect(layout.completed).toEqual([]);
  });

  it("moves completed Projects to the completed group, but not completed Processes", () => {
    const completedProcess = { ...processNode, status: "completed" };
    const layout = projectsLayout([domain, done, completedProcess, project]);
    expect(layout.completed.map((g) => g.title)).toEqual(["Klart"]);
    expect(layout.sections[0]?.groups.map((g) => g.title)).toEqual([
      "Offert till Anna",
      "Fakturering",
    ]);
  });

  it("keeps a Domain without groups when unfiltered and leaves it out when a filter is on", () => {
    expect(projectsLayout([domain, second]).sections).toHaveLength(2);
    expect(
      projectsLayout([domain, project, second], "offert").sections,
    ).toEqual([{ domain, groups: [project] }]);
  });

  it("matches a Domain's name to keep all its groups, case-insensitively", () => {
    const layout = projectsLayout([domain, project, processNode], "ekonomi");
    expect(layout.sections[0]?.groups).toHaveLength(2);
  });

  it("puts groups whose Domain is not on the page first, in a section with no Domain", () => {
    const layout = projectsLayout([domain, project, early]);
    expect(layout.sections[0]?.domain).toBeNull();
    expect(layout.sections[0]?.groups).toEqual([early]);
    expect(layout.sections[1]?.domain).toBe(domain);
  });
});

describe("HierarchyView", () => {
  it("gives each Domain an h3 with its Projects first and then its Processes", () => {
    const hälsa = node("domain", "dom-2", "Hälsa", null);
    const løp = node("project", "pro-9", "Löpning", hälsa);
    render(
      <HierarchyView
        frame={frameOf([domain, processNode, project, hälsa, løp])}
        transport={transport()}
        labels={workSv}
      />,
    );
    const headings = screen.getAllByRole("heading", { level: 3 });
    expect(headings.map((h) => h.textContent)).toEqual(["Ekonomi", "Hälsa"]);
    expect(buttonTitles().map((t) => t.replace(/, Projekt$/, ""))).toEqual([
      "Offert till Anna",
      "Fakturering",
      "Löpning",
    ]);
    expect(screen.getByRole("region", { name: "Ekonomi" })).toContainElement(
      screen.getByRole("button", { name: /Offert till Anna/ }),
    );
    // No tree any more: plain lists of plain buttons.
    expect(screen.queryByRole("tree")).not.toBeInTheDocument();
    expect(screen.queryByRole("treeitem")).not.toBeInTheDocument();
    expect(screen.getAllByRole("list")).toHaveLength(2);
  });

  it("says the word Process on a Process row and says Project only to screen readers", () => {
    const { container } = render(
      <HierarchyView
        frame={frameOf([domain, processNode, project])}
        transport={transport()}
        labels={workEn}
      />,
    );
    const processRow = container.querySelector('[data-kind="process"]')!;
    expect(processRow.querySelector(".work-card-meta")).toHaveTextContent(
      workEn.kindName.process,
    );
    expect(processRow.querySelector("svg")).not.toBeNull();
    const projectRow = container.querySelector('[data-kind="project"]')!;
    expect(projectRow.querySelector(".work-card-meta")).not.toHaveTextContent(
      workEn.kindName.project,
    );
    expect(projectRow.querySelector(".work-visually-hidden")).toHaveTextContent(
      workEn.kindName.project,
    );
    expect(
      screen.getByRole("button", { name: "Offert till Anna, Project" }),
    ).toBeInTheDocument();
  });

  it("shows how far a Project has come and how many Tasks are overdue", () => {
    const { container } = render(
      <HierarchyView
        frame={frameOf(
          [domain, project],
          [
            taskOf("a", project, { status: "completed" }),
            taskOf("b", project, { due_at: PAST }),
            taskOf("c", project),
          ],
        )}
        transport={transport()}
        labels={workSv}
      />,
    );
    const meta = container.querySelector(".work-card-meta")!;
    expect(meta).toHaveTextContent("1 av 3 klara");
    expect(meta.querySelector(".work-tree-overdue")).toHaveTextContent(
      "1 försenad",
    );
  });

  it("says no Tasks yet for an empty Project, open Tasks for a Process, and nothing without Tasks in the frame", () => {
    const { container, rerender } = render(
      <HierarchyView
        frame={frameOf(
          [domain, project, processNode],
          [
            taskOf("a", processNode, { status: "completed" }),
            taskOf("b", processNode),
            taskOf("c", processNode),
          ],
        )}
        transport={transport()}
        labels={workSv}
      />,
    );
    const meta = (kind: string) =>
      container.querySelector(`[data-kind="${kind}"] .work-card-meta`);
    expect(meta("project")).toHaveTextContent(hierarchyDetailLabelsSv.noTasks);
    expect(meta("process")).toHaveTextContent("2 öppna uppgifter");

    rerender(
      <HierarchyView
        frame={frameOf([domain, project, processNode], [])}
        transport={transport()}
        labels={workSv}
      />,
    );
    expect(meta("process")).toHaveTextContent("Inga öppna uppgifter");

    // A frame read without include_tasks has no counts: nothing is claimed about the Tasks.
    rerender(
      <HierarchyView
        frame={frameOf([domain, project, processNode])}
        transport={transport()}
        labels={workSv}
        stale={false}
      />,
    );
    expect(meta("project")).toHaveTextContent("");
    expect(meta("process")).not.toHaveTextContent(/uppgift/);
  });

  it("shows a status only when it is not active, and a Domain's status in its heading", () => {
    const archived = node("domain", "dom-a", "Gammalt", null, {
      status: "archived",
    });
    const paused = node("project", "pro-p", "Väntar på svar", domain, {
      status: "paused",
    });
    render(
      <HierarchyView
        frame={frameOf([domain, project, paused, archived])}
        transport={transport()}
        labels={workSv}
      />,
    );
    expect(screen.getAllByText(workSv.projectStatus.paused)).toHaveLength(1);
    expect(
      screen.queryByText(workSv.projectStatus.active),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: /Gammalt/ }),
    ).toHaveTextContent(workSv.archivedLabel);
    expect(
      screen.getByRole("heading", { level: 3, name: "Ekonomi" }),
    ).not.toHaveTextContent(workSv.projectStatus.active);
  });

  it("says a Domain with nothing under it has no Projects or Processes yet", () => {
    render(
      <HierarchyView
        frame={frameOf([domain])}
        transport={transport()}
        labels={workEn}
      />,
    );
    expect(screen.getByText(hierarchyDetailLabelsEn.noGroups)).toBeVisible();
  });

  it("heads the Projects outside every Domain 'Utan domän' when there is a Domain, and lists them in that region", () => {
    const loose = node("project", "pro-loose", "Lös projekt", null);
    render(
      <HierarchyView
        frame={frameOf([domain, project, loose])}
        transport={transport()}
        labels={workSv}
      />,
    );
    expect(
      screen.getByRole("heading", { level: 3, name: "Utan domän" }),
    ).toBeVisible();
    expect(screen.getByRole("region", { name: "Utan domän" })).toContainElement(
      screen.getByRole("button", { name: /Lös projekt/ }),
    );
    expect(
      screen.getByRole("region", { name: "Ekonomi" }),
    ).not.toContainElement(screen.getByRole("button", { name: /Lös projekt/ }));
  });

  it("draws no 'Not in an area' heading when no Domain is on the page at all", () => {
    render(
      <HierarchyView
        frame={frameOf([project, processNode])}
        transport={transport()}
        labels={workEn}
      />,
    );
    expect(
      screen.queryByRole("heading", { name: "Not in an area" }),
    ).toBeNull();
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Offert/ })).toBeInTheDocument();
  });

  it("lists a group whose Domain is not on the page without a heading", () => {
    render(
      <HierarchyView
        frame={frameOf([project])}
        transport={transport()}
        labels={workEn}
      />,
    );
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Offert/ })).toBeInTheDocument();
  });

  it("shows an empty text and no list for an empty hierarchy", () => {
    render(
      <HierarchyView
        frame={frameOf([])}
        transport={transport()}
        labels={workEn}
      />,
    );
    expect(screen.getByText(workEn.hierarchyEmpty)).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("draws the Domain's accent dot in its heading", () => {
    const { container } = render(
      <HierarchyView
        frame={frameOf([{ ...domain, accent: "teal" }, project])}
        transport={transport()}
        labels={workEn}
      />,
    );
    const heading = screen.getByRole("heading", { level: 3 });
    expect(heading.querySelector(".hierarchy-accent")).toHaveAttribute(
      "data-accent",
      "teal",
    );
    expect(container.querySelectorAll(".hierarchy-accent")).toHaveLength(1);
  });

  describe("completed Projects", () => {
    const done = node("project", "done-1", "Avslutat jobb", domain, {
      status: "completed",
    });
    const frame = frameOf([domain, project, done]);

    it("folds them in a closed group last that the whole row opens and closes", () => {
      const { container } = render(
        <HierarchyView frame={frame} transport={transport()} labels={workSv} />,
      );
      const fold = screen.getByRole("button", {
        name: hierarchyDetailLabelsSv.completedGroup(1),
      });
      expect(fold).toHaveClass("work-tree-fold");
      expect(fold).toHaveAttribute("aria-expanded", "false");
      expect(screen.queryByText("Avslutat jobb")).not.toBeInTheDocument();
      expect(
        container.querySelector(".work-tree")!.lastElementChild,
      ).toContainElement(fold);

      // A tap on the label inside the row counts: the row is the button.
      fireEvent.click(fold.querySelector(".work-tree-fold-label")!);
      expect(fold).toHaveAttribute("aria-expanded", "true");
      const row = screen.getByRole("button", { name: /Avslutat jobb/ });
      // The completed Project says which Domain it belonged to.
      expect(row.closest("li")).toHaveTextContent("Ekonomi");
      fireEvent.click(fold);
      expect(fold).toHaveAttribute("aria-expanded", "false");
      expect(screen.queryByText("Avslutat jobb")).not.toBeInTheDocument();
    });

    it("leaves the group out when no Project is completed", () => {
      render(
        <HierarchyView
          frame={frameOf([domain, project])}
          transport={transport()}
          labels={workSv}
        />,
      );
      expect(document.querySelector(".work-tree-fold")).not.toBeInTheDocument();
    });

    it("opens a completed Project through onOpen and claims no Tasks for one with none", () => {
      const onOpen = vi.fn();
      render(
        <HierarchyView
          frame={frameOf([domain, project, done], [])}
          transport={transport()}
          labels={workSv}
          onOpen={onOpen}
        />,
      );
      fireEvent.click(
        screen.getByRole("button", {
          name: hierarchyDetailLabelsSv.completedGroup(1),
        }),
      );
      const row = screen.getByRole("button", { name: /Avslutat jobb/ });
      expect(row.closest("li")).not.toHaveTextContent(
        hierarchyDetailLabelsSv.noTasks,
      );
      fireEvent.click(row);
      expect(onOpen).toHaveBeenCalledWith(
        { kind: "project", id: done.id },
        "Avslutat jobb",
      );
    });
  });

  describe("filter", () => {
    const other = node("project", "pro-3", "Semesterplan", domain);
    const hälsa = node("domain", "dom-2", "Hälsa", null);
    const løp = node("project", "pro-9", "Löpning", hälsa);
    const frame = frameOf([domain, project, other, hälsa, løp]);

    it("has its own search field that filters by title and drops Domains with nothing left", () => {
      render(
        <HierarchyView frame={frame} transport={transport()} labels={workSv} />,
      );
      const field = screen.getByRole("searchbox", {
        name: hierarchyDetailLabelsSv.filter,
      });
      fireEvent.input(field, { target: { value: "  SEMESTER " } });
      expect(buttonTitles()).toEqual(["Semesterplan, Projekt"]);
      expect(
        screen.queryByRole("heading", { level: 3, name: "Hälsa" }),
      ).not.toBeInTheDocument();
    });

    it("shows all of a Domain's groups when the Domain's name matches", () => {
      render(
        <HierarchyView frame={frame} transport={transport()} labels={workSv} />,
      );
      fireEvent.input(screen.getByRole("searchbox"), {
        target: { value: "ekonomi" },
      });
      expect(buttonTitles()).toHaveLength(2);
    });

    it("says there are no matches", () => {
      render(
        <HierarchyView frame={frame} transport={transport()} labels={workSv} />,
      );
      fireEvent.input(screen.getByRole("searchbox"), {
        target: { value: "zzz" },
      });
      expect(
        screen.getByText(hierarchyDetailLabelsSv.noMatches),
      ).toBeInTheDocument();
      expect(screen.queryByRole("list")).not.toBeInTheDocument();
    });

    it("uses the query prop of the tab row and then shows no field of its own", () => {
      render(
        <HierarchyView
          frame={frame}
          transport={transport()}
          labels={workSv}
          query="löp"
        />,
      );
      expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
      expect(buttonTitles()).toEqual(["Löpning, Projekt"]);
    });

    it("shows a completed Project at once when the filter matches it", () => {
      const done = node("project", "done-1", "Avslutat jobb", domain, {
        status: "completed",
      });
      render(
        <HierarchyView
          frame={frameOf([domain, project, done])}
          transport={transport()}
          labels={workSv}
          query="avslutat"
        />,
      );
      expect(
        screen.getByRole("button", { name: /Avslutat jobb/ }),
      ).toBeInTheDocument();
      expect(document.querySelector(".work-tree-fold")).toHaveAttribute(
        "aria-expanded",
        "true",
      );
    });
  });

  describe("opening a page", () => {
    it("calls onOpen with the Project and its title, and with the Process and its title", () => {
      const onOpen = vi.fn();
      render(
        <HierarchyView
          frame={frameOf([domain, project, processNode])}
          transport={transport()}
          labels={workSv}
          onOpen={onOpen}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: /Offert till Anna/ }));
      expect(onOpen).toHaveBeenLastCalledWith(
        { kind: "project", id: project.id },
        "Offert till Anna",
      );
      fireEvent.click(screen.getByRole("button", { name: /Fakturering/ }));
      expect(onOpen).toHaveBeenLastCalledWith(
        { kind: "process", id: processNode.id },
        "Fakturering",
      );
      expect(onOpen).toHaveBeenCalledTimes(2);
    });

    it("shows plain titles and no buttons or chevrons without onOpen", () => {
      render(
        <PlainHierarchyView
          frame={frameOf([domain, project])}
          transport={transport()}
          labels={workSv}
        />,
      );
      expect(screen.getByText("Offert till Anna")).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /Offert/ }),
      ).not.toBeInTheDocument();
    });

    it("moves focus between rows with j and k only when shortcuts are on", () => {
      const props = {
        frame: frameOf([domain, project, processNode]),
        transport: transport(),
        labels: workSv,
        onOpen: vi.fn(),
      };
      const { unmount } = render(<HierarchyView {...props} shortcuts />);
      const [first, second] = Array.from(
        document.querySelectorAll<HTMLElement>(".work-tree-open"),
      );
      first!.focus();
      fireEvent.keyDown(window, { key: "j" });
      expect(second).toHaveFocus();
      fireEvent.keyDown(window, { key: "k" });
      expect(first).toHaveFocus();
      unmount();

      render(<HierarchyView {...props} />);
      const [again] = Array.from(
        document.querySelectorAll<HTMLElement>(".work-tree-open"),
      );
      again!.focus();
      fireEvent.keyDown(window, { key: "j" });
      expect(again).toHaveFocus();
    });
  });

  describe("headings and the row limit", () => {
    it("says Projekt in an h2 only when headingHidden is false, and always labels the region", () => {
      const { rerender } = render(
        <HierarchyView
          frame={frameOf([])}
          transport={transport()}
          labels={workSv}
        />,
      );
      expect(
        screen.queryByRole("heading", { level: 2 }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("region", { name: workSv.hierarchy }),
      ).toBeInTheDocument();
      rerender(
        <HierarchyView
          frame={frameOf([])}
          transport={transport()}
          labels={workSv}
          headingHidden={false}
        />,
      );
      expect(
        screen.getByRole("heading", { level: 2, name: "Projekt" }),
      ).toBeInTheDocument();
    });

    const many: WorkHierarchyFrame = frameOf([
      domain,
      ...Array.from({ length: 14 }, (_, index) =>
        node("project", `pro-${index}`, `Projekt ${index}`, domain),
      ),
    ]);

    it("shows at most twelve rows and then the count of the rest, named in full", () => {
      render(
        <HierarchyView
          frame={{ ...many, truncated: true }}
          transport={transport()}
          labels={workEn}
        />,
      );
      expect(buttonTitles()).toHaveLength(HIERARCHY_MAX_ROWS);
      const more = screen.getByRole("note", { name: "2 more" });
      expect(more).toHaveTextContent("+2");
      expect(more).toHaveAttribute("title", "2 more");
      expect(screen.getByText(workEn.hierarchyTruncated)).toBeInTheDocument();
    });

    it("shows every row and no +N line when rowLimit is Infinity", () => {
      render(
        <HierarchyView
          frame={many}
          transport={transport()}
          labels={workSv}
          rowLimit={Infinity}
        />,
      );
      expect(buttonTitles()).toHaveLength(14);
      expect(screen.queryByText(/^\+\d+$/)).not.toBeInTheDocument();
      expect(screen.queryByText(workSv.hierarchyTruncated)).toBeNull();
    });

    it("counts the rows cut from an open completed group in the +N line", () => {
      const done = Array.from({ length: 3 }, (_, index) =>
        node("project", `done-${index}`, `Klar ${index}`, domain, {
          status: "completed",
        }),
      );
      render(
        <HierarchyView
          frame={frameOf([domain, project, ...done])}
          transport={transport()}
          labels={workSv}
          rowLimit={2}
        />,
      );
      expect(screen.queryByText(/^\+\d+$/)).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /Avslutade/ }));
      // One open row plus one of three completed rows fit; two are cut.
      expect(buttonTitles().filter((t) => t.startsWith("Klar"))).toHaveLength(
        1,
      );
      expect(screen.getByText("+2")).toBeInTheDocument();
    });
  });
});

describe("HierarchyView reads itself in place", () => {
  const fresh: WorkHierarchyFrame = frameOf(
    [domain, project],
    [taskOf("a", project)],
  );

  it("reads with include_tasks at mount when the frame has no Tasks and hands the answer to onChange", async () => {
    const getWorkHierarchy = vi.fn().mockResolvedValue(fresh);
    const onChange = vi.fn();
    render(
      <HierarchyView
        frame={frameOf([domain, project])}
        transport={transport(getWorkHierarchy)}
        onChange={onChange}
        labels={workSv}
      />,
    );
    expect(getWorkHierarchy).toHaveBeenCalledTimes(1);
    expect(getWorkHierarchy).toHaveBeenCalledWith({ includeTasks: true });
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(fresh));
  });

  it("does not read at mount when the frame already carries its Tasks", () => {
    const getWorkHierarchy = vi.fn().mockResolvedValue(fresh);
    render(
      <HierarchyView
        frame={frameOf([domain, project], [])}
        transport={transport(getWorkHierarchy)}
        onChange={vi.fn()}
        labels={workSv}
      />,
    );
    expect(getWorkHierarchy).not.toHaveBeenCalled();
  });

  it("does not read at mount when the host refuses include_tasks, and asks without Tasks when stale", async () => {
    const getWorkHierarchy = vi.fn().mockResolvedValue(fresh);
    const host = { supportsCall: vi.fn().mockReturnValue(false) };
    const { unmount } = render(
      <HierarchyView
        frame={frameOf([domain, project])}
        transport={transport(getWorkHierarchy, host)}
        onChange={vi.fn()}
        labels={workSv}
      />,
    );
    expect(host.supportsCall).toHaveBeenCalledWith("get_work_hierarchy", {
      include_tasks: true,
    });
    expect(getWorkHierarchy).not.toHaveBeenCalled();
    unmount();

    const onRead = vi.fn();
    render(
      <HierarchyView
        frame={frameOf([domain, project])}
        transport={transport(getWorkHierarchy, host)}
        onChange={vi.fn()}
        labels={workSv}
        stale
        onRead={onRead}
      />,
    );
    expect(getWorkHierarchy).toHaveBeenCalledWith({ includeTasks: false });
    await waitFor(() => expect(onRead).toHaveBeenCalledTimes(1));
  });

  it("reads once at mount when stale even though the frame has Tasks", () => {
    const getWorkHierarchy = vi.fn().mockResolvedValue(fresh);
    render(
      <HierarchyView
        frame={fresh}
        transport={transport(getWorkHierarchy)}
        onChange={vi.fn()}
        labels={workSv}
        stale
      />,
    );
    expect(getWorkHierarchy).toHaveBeenCalledTimes(1);
  });

  it("reads again for each new refreshKey but not for the first value or an unchanged one", async () => {
    const getWorkHierarchy = vi.fn().mockResolvedValue(fresh);
    const onChange = vi.fn();
    const view = (key: number) => (
      <HierarchyView
        frame={fresh}
        transport={transport(getWorkHierarchy)}
        onChange={onChange}
        labels={workSv}
        refreshKey={key}
      />
    );
    const { rerender } = render(view(1));
    expect(getWorkHierarchy).not.toHaveBeenCalled();
    rerender(view(1));
    expect(getWorkHierarchy).not.toHaveBeenCalled();
    rerender(view(2));
    expect(getWorkHierarchy).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    rerender(view(3));
    expect(getWorkHierarchy).toHaveBeenCalledTimes(2);
  });

  it("runs one read after the one in flight when several requests arrive meanwhile", async () => {
    const replies: Array<(frame: WorkHierarchyFrame) => void> = [];
    const getWorkHierarchy = vi.fn(
      () =>
        new Promise<WorkHierarchyFrame>((resolve) => {
          replies.push(resolve);
        }),
    );
    const onChange = vi.fn();
    const view = (key: number) => (
      <HierarchyView
        frame={fresh}
        transport={transport(getWorkHierarchy)}
        onChange={onChange}
        labels={workSv}
        refreshKey={key}
      />
    );
    const { rerender } = render(view(1));
    rerender(view(2));
    expect(getWorkHierarchy).toHaveBeenCalledTimes(1);
    // Two more signals while the first read is on its way: neither starts a read, none is lost.
    rerender(view(3));
    rerender(view(4));
    expect(getWorkHierarchy).toHaveBeenCalledTimes(1);
    replies[0]!(fresh);
    await waitFor(() => expect(getWorkHierarchy).toHaveBeenCalledTimes(2));
    expect(onChange).toHaveBeenCalledTimes(1);
    replies[1]!(fresh);
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2));
    expect(getWorkHierarchy).toHaveBeenCalledTimes(2);
  });

  it("keeps what is shown when a read fails, and reads again on the next request", async () => {
    const getWorkHierarchy = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(fresh);
    const onChange = vi.fn();
    const view = (key: number) => (
      <HierarchyView
        frame={frameOf([domain, project])}
        transport={transport(getWorkHierarchy)}
        onChange={onChange}
        labels={workSv}
        refreshKey={key}
        stale
      />
    );
    const { rerender } = render(view(1));
    await waitFor(() => expect(getWorkHierarchy).toHaveBeenCalledTimes(1));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText("Offert till Anna")).toBeInTheDocument();
    rerender(view(2));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(fresh));
  });

  it("makes no read without onChange or transport", () => {
    const getWorkHierarchy = vi.fn().mockResolvedValue(fresh);
    render(
      <HierarchyView
        frame={frameOf([domain, project])}
        transport={transport(getWorkHierarchy)}
        labels={workSv}
      />,
    );
    expect(getWorkHierarchy).not.toHaveBeenCalled();
    render(<HierarchyView frame={frameOf([domain])} labels={workSv} stale />);
  });
});

describe("get_work_hierarchy cursor", () => {
  it("keeps the next cursor of a page and leaves it out of the last page", () => {
    expect(
      rootFromToolResult({
        nodes: [domain],
        truncated: true,
        next_cursor: "c2",
      }),
    ).toEqual({ ...frameOf([domain]), truncated: true, next_cursor: "c2" });
    expect(
      rootFromToolResult({
        nodes: [domain],
        truncated: false,
        next_cursor: null,
      }),
    ).toEqual(frameOf([domain]));
  });
});

describe("HierarchyView Show more", () => {
  const pageOf = (
    nodes: WorkHierarchyNode[],
    next: string | null,
  ): WorkHierarchyFrame => ({
    ...frameOf(nodes),
    truncated: next !== null,
    ...(next === null ? {} : { next_cursor: next }),
  });
  const projects = (from: number, to: number) =>
    Array.from({ length: to - from }, (_, index) =>
      node("project", `pro-${from + index}`, `Projekt ${from + index}`, domain),
    );

  /** The view with its frame in state, as the shell holds it: a page read replaces the frame. */
  function Held({
    first,
    getWorkHierarchy,
    labels,
  }: {
    first: WorkHierarchyFrame;
    getWorkHierarchy: Parameters<typeof transport>[0];
    labels: typeof workSv;
  }) {
    const [frame, setFrame] = useState(first);
    return (
      <HierarchyView
        frame={frame}
        transport={transport(getWorkHierarchy, { supportsCall: () => false })}
        onChange={setFrame}
        labels={labels}
        rowLimit={Infinity}
      />
    );
  }

  it.each([
    ["sv", workSv, "Visa fler"],
    ["en", workEn, "Show more"],
  ])(
    "walks the pages with the cursor until none is left (%s)",
    async (_name, labels, word) => {
      const getWorkHierarchy = vi
        .fn()
        .mockResolvedValueOnce(pageOf(projects(2, 4), "c3"))
        .mockResolvedValueOnce(pageOf(projects(4, 5), null));
      render(
        <Held
          first={pageOf([domain, ...projects(0, 2)], "c2")}
          getWorkHierarchy={getWorkHierarchy}
          labels={labels}
        />,
      );
      expect(buttonTitles().map((title) => title.split(",")[0])).toEqual([
        "Projekt 0",
        "Projekt 1",
      ]);
      expect(
        screen.queryByText(labels.hierarchyTruncated),
      ).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: word }));
      await waitFor(() => expect(buttonTitles()).toHaveLength(4));
      expect(getWorkHierarchy).toHaveBeenNthCalledWith(1, {
        includeTasks: false,
        cursor: "c2",
      });

      fireEvent.click(screen.getByRole("button", { name: word }));
      await waitFor(() => expect(buttonTitles()).toHaveLength(5));
      expect(getWorkHierarchy).toHaveBeenNthCalledWith(2, {
        includeTasks: false,
        cursor: "c3",
      });
      expect(
        screen.queryByRole("button", { name: word }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText(labels.hierarchyTruncated),
      ).not.toBeInTheDocument();
    },
  );

  it("appends the Tasks of the next page and does not repeat a node", () => {
    const shown = {
      ...frameOf([domain, project], [taskOf("a", project)]),
      next_cursor: "c2",
    };
    const next = frameOf([project, processNode], [taskOf("b", processNode)]);
    const merged = mergeHierarchyPage(shown, next);
    expect(merged.nodes.map((n) => n.id)).toEqual([
      domain.id,
      project.id,
      processNode.id,
    ]);
    expect(merged.tasks?.map((task) => task.id)).toEqual(["a", "b"]);
    expect(merged.next_cursor).toBeUndefined();
  });

  it("says so and offers Show more again when a page cannot be read", async () => {
    const getWorkHierarchy = vi
      .fn()
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValueOnce(pageOf(projects(2, 3), null));
    render(
      <Held
        first={pageOf([domain, ...projects(0, 2)], "c2")}
        getWorkHierarchy={getWorkHierarchy}
        labels={workEn}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(workEn.failed);
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() => expect(buttonTitles()).toHaveLength(3));
  });

  it("keeps the truncation line when a cut has no cursor to follow", () => {
    render(
      <HierarchyView
        frame={{
          ...pageOf([domain, ...projects(0, 2)], null),
          truncated: true,
        }}
        transport={transport(vi.fn(), { supportsCall: () => false })}
        onChange={vi.fn()}
        labels={workEn}
      />,
    );
    expect(screen.getByText(workEn.hierarchyTruncated)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Show more" }),
    ).not.toBeInTheDocument();
  });
});
