import { expect, test } from "@playwright/test";
import { callTool, openRealApp, uniqueTitle } from "./real-backend";

// A journal note written by hand in the day view is stored by the server under that day, with the owner's own text.

/** Today's date as the app, which runs in this machine's time zone, sees it. */
function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

test("a note written in the day view is stored under that day", async ({
  page,
}) => {
  const today = localToday();
  const title = uniqueTitle("Möte med Anna");
  const text = `Vi pratade om offerten ${title}`;

  const { app, failures } = await openRealApp(page, {
    tool: "get_journal_day",
    args: { journal_date: today },
  });
  await app.getByRole("button", { name: "Ny anteckning" }).click();
  await app.getByRole("button", { name: "Skriv själv" }).click();
  const form = app.getByRole("group", { name: "Ny anteckning" });
  await form.getByLabel("Titel").fill(title);
  await form.getByLabel("Din text").fill(text);
  await form.getByRole("button", { name: "Spara anteckningen" }).click();
  await expect(app.getByText("Anteckningen sparades.")).toBeVisible();

  const day = await callTool("get_journal_day", { journal_date: today });
  const entries = day.structuredContent?.entries as {
    source_id: string;
    title: string;
  }[];
  const stored = entries.find((entry) => entry.title === title);
  expect(stored).toBeDefined();
  const read = await callTool("get_journal_source", {
    source_id: stored!.source_id,
    include_content: true,
  });
  expect(JSON.stringify(read.structuredContent)).toContain(text);
  expect(failures).toEqual([]);
});
