import { describe, expect, it, vi } from "vitest";
import { isRecordEntry } from "@/features/mcp-apps/nav-state";
import { routeForShape, routeForTool } from "@/features/mcp-apps/router";
import { workEn, workSv } from "@/features/work-app/labels";
import {
  parentLabel,
  routeOfFrame,
} from "@/features/work-app/work-view-parts/frame-routing";
import {
  rootFromToolResult,
  type WorkFrame,
} from "@/features/work-app/transport";
import { createWorkTransport } from "@/features/work-app/work-transport";

/* How a Process page is reached: tool result, route, shell entry, Back name and the Tasks read. */

const ID = "019f0000-0000-7000-8000-0000000000e1";

describe("the Process page wiring", () => {
  it("a get_process result opens a Process page and routes to the work room", () => {
    expect(rootFromToolResult({ process: { id: ID, name: "X" } })).toEqual({
      kind: "process",
      id: ID,
    });
    expect(routeForTool("get_process")).toEqual({
      room: "work",
      view: "process",
    });
    expect(routeForShape({ process: { id: ID } })).toEqual({
      room: "work",
      view: "process",
    });
  });

  it("a Process is a record of the work room", () => {
    expect(isRecordEntry({ room: "work", view: "process", id: ID })).toBe(true);
  });

  it("routes a Process frame with its name, and names the list it was opened from", () => {
    const hierarchy: WorkFrame = {
      kind: "hierarchy",
      nodes: [],
      truncated: false,
    };
    expect(
      routeOfFrame({ kind: "process", id: ID }, "Fakturering", hierarchy),
    ).toEqual({
      room: "work",
      view: "process",
      id: ID,
      label: "Fakturering",
      from: "hierarchy",
    });
    expect(routeOfFrame({ kind: "project", id: ID }, "P")).not.toHaveProperty(
      "from",
    );
    expect(
      routeOfFrame({ kind: "task", id: ID }, "T", { kind: "error" }),
    ).not.toHaveProperty("from");
  });

  it("names a Process as the parent of a deeper frame", () => {
    expect(parentLabel({ kind: "process", id: ID }, workSv)).toBe("Process");
    expect(parentLabel({ kind: "process", id: ID }, workEn)).toBe("Process");
  });

  it("lists a Process's Tasks with process_id and a page of 20", async () => {
    const call = vi
      .fn()
      .mockResolvedValue({ tasks: [{ id: "t1" }], next_cursor: "c2" });
    const page = await createWorkTransport(call).listProcessTasks(ID, "c1");
    expect(call).toHaveBeenCalledWith("list_tasks", {
      process_id: ID,
      limit: 20,
      cursor: "c1",
    });
    expect(page).toEqual({ items: [{ id: "t1" }], next_cursor: "c2" });
  });
});
