import { describe, expect, it } from "vitest";

import {
  actionName,
  controlEn,
  controlSv,
  trashedWhen,
} from "@/features/control-app/labels";

describe("Swedish memory sentences use the definite form of the domain", () => {
  it.each([
    ["journal", "dagboken", "Dagboken"],
    ["contacts", "kontakterna", "Kontakterna"],
    ["projects", "projekten", "Projekten"],
    ["tasks", "uppgifterna", "Uppgifterna"],
  ] as const)("%s", (domain, definite, capitalised) => {
    expect(controlSv.confirmTitle(domain)).toBe(
      `Slå av minnet av ${definite}?`,
    );
    expect(controlSv.confirmYes(domain)).toBe(
      `Ja, radera minnet av ${definite}`,
    );
    expect(controlSv.confirmCount(domain, null)).toBe(
      `Bara Sidekicks minne av ${definite} raderas. ${capitalised} ändras inte.`,
    );
    expect(controlSv.deletionStarted(domain)).toBe(
      `Minnet av ${definite} är avslaget. Det Sidekick mindes raderas inom några minuter.`,
    );
  });

  it("counts records in the confirmation without changing the form", () => {
    expect(controlSv.confirmCount("journal", 1)).toBe(
      "Bara Sidekicks minne av dagboken raderas (1 post). Dagboken ändras inte.",
    );
    expect(controlSv.confirmCount("tasks", 3)).toBe(
      "Bara Sidekicks minne av uppgifterna raderas (3 poster). Uppgifterna ändras inte.",
    );
  });
});

describe("English memory sentences", () => {
  it("name the domain with a possessive and the memory, not the domain itself", () => {
    expect(controlEn.confirmTitle("journal")).toBe(
      "Turn off memory for your journal?",
    );
    expect(controlEn.confirmYes("tasks")).toBe(
      "Yes, delete what Sidekick remembers about your tasks",
    );
    expect(controlEn.confirmCount("contacts", 2)).toBe(
      "This deletes only what Sidekick remembers about your contacts (2 records). Your contacts won’t change.",
    );
    expect(controlEn.deletionStarted("projects")).toBe(
      "Memory is off for your projects. What Sidekick remembered will be deleted within a few minutes.",
    );
    expect(controlEn.forget("contacts")).toBe("Forget the contact");
    expect(controlEn.countStuck(2)).toBe("2 waiting for memory");
  });
});

describe("Swedish forget sentences name the record", () => {
  it.each([
    ["journal", "anteckningen"],
    ["contacts", "kontakten"],
    ["projects", "projektet"],
    ["tasks", "uppgiften"],
  ] as const)("%s", (domain, definite) => {
    expect(controlSv.forget(domain)).toBe(`Glöm ${definite}`);
    expect(controlSv.forgetYes(domain)).toBe(`Ja, glöm ${definite}`);
    expect(controlSv.forgetTitle(domain, null)).toBe(`Glöm ${definite}?`);
    expect(controlSv.forgetBody(domain)).toContain(
      `Själva ${definite} ändras inte`,
    );
  });
});

describe("Swedish participles follow the gender of the kind", () => {
  it("uses the neuter form after a neuter noun and the common form otherwise", () => {
    expect(trashedWhen(controlSv, "igår 14:30", "project")).toBe(
      "borttaget igår 14:30",
    );
    expect(trashedWhen(controlSv, "igår 14:30", "task")).toBe(
      "borttagen igår 14:30",
    );
    expect(actionName(controlSv, "created", "project")).toBe("skapat");
    expect(actionName(controlSv, "updated", "domain")).toBe("ändrat");
    expect(actionName(controlSv, "created", "task")).toBe("skapad");
    expect(actionName(controlEn, "created", "project")).toBe("created");
    expect(actionName(controlSv, "unknown", "project")).toBe("unknown");
  });
});

describe("Control tabs", () => {
  it("are Deleted, History, Memory in both languages, with the same keys", () => {
    expect(Object.keys(controlSv.views)).toEqual([
      "trash",
      "history",
      "memory",
    ]);
    expect(Object.keys(controlEn.views)).toEqual(Object.keys(controlSv.views));
    expect(Object.values(controlSv.views)).toEqual([
      "Borttaget",
      "Historik",
      "Sidekicks minne",
    ]);
    expect(Object.values(controlEn.views)).toEqual([
      "Deleted",
      "History",
      "Sidekick’s memory",
    ]);
  });
});

describe("Control tab meta lines", () => {
  it("say how many are deleted and that they can be restored, in both languages", () => {
    expect(controlSv.trashMeta(1)).toBe("1 borttagen · kan återställas");
    expect(controlSv.trashMeta(3)).toBe("3 borttagna · kan återställas");
    expect(controlEn.trashMeta(1)).toBe("1 deleted · can be restored");
    expect(controlEn.trashMeta(3)).toBe("3 deleted · can be restored");
  });

  it("say how many sources are on, and name the source list", () => {
    expect(controlSv.sourcesOn(3, 4)).toBe("3 av 4 källor på");
    expect(controlEn.sourcesOn(3, 4)).toBe("3 of 4 sources on");
    expect(controlSv.sourcesTitle).toBe("Källor");
    expect(controlEn.sourcesTitle).toBe("Sources");
  });

  it("say the count in memory with the source's own noun in the right number, and a domain that is off as 'inte med i minnet' after 'Av'", () => {
    expect(controlSv.countStored(214, "journal")).toBe(
      "214 anteckningar i minnet",
    );
    expect(controlEn.countStored(214, "journal")).toBe("214 entries in memory");
    expect(controlSv.countStored(1, "journal")).toBe("1 anteckning i minnet");
    expect(controlEn.countStored(1, "journal")).toBe("1 entry in memory");
    expect(controlSv.countStored(38, "contacts")).toBe("38 kontakter i minnet");
    expect(controlEn.countStored(38, "contacts")).toBe("38 contacts in memory");
    expect(controlSv.countStored(1, "contacts")).toBe("1 kontakt i minnet");
    expect(controlEn.countStored(1, "contacts")).toBe("1 contact in memory");
    expect(controlSv.countStored(1, "tasks")).toBe("1 uppgift i minnet");
    expect(controlEn.countStored(1, "tasks")).toBe("1 task in memory");
    expect(controlSv.countStored(5, "tasks")).toBe("5 uppgifter i minnet");
    expect(controlEn.countStored(5, "tasks")).toBe("5 tasks in memory");
    // «projekt» is the same word in both numbers in Swedish.
    expect(controlSv.countStored(1, "projects")).toBe("1 projekt i minnet");
    expect(controlSv.countStored(7, "projects")).toBe("7 projekt i minnet");
    expect(controlEn.countStored(1, "projects")).toBe("1 project in memory");
    expect(controlEn.countStored(7, "projects")).toBe("7 projects in memory");
    expect(controlSv.countOff).toBe("inte med i minnet");
    expect(controlEn.countOff).toBe("not in memory");
  });

  it("name the stored records for every memory domain in both languages (locale parity)", () => {
    for (const domain of [
      "journal",
      "contacts",
      "projects",
      "tasks",
    ] as const) {
      for (const count of [0, 1, 2]) {
        expect(controlSv.countStored(count, domain)).toMatch(
          new RegExp(`^${count} \\S+ i minnet$`),
        );
        expect(controlEn.countStored(count, domain)).toMatch(
          new RegExp(`^${count} \\S+ in memory$`),
        );
      }
    }
  });

  it("keep the history meta and drop the old tab sentences and the trash count", () => {
    expect(controlSv.historyMeta).toBe(
      "Det du och Claude har gjort, senaste först",
    );
    expect(controlEn.historyMeta).toBe(
      "What you and Claude have done, newest first",
    );
    expect(controlSv).not.toHaveProperty("viewIntro");
    expect(controlSv).not.toHaveProperty("trashCount");
    expect(controlEn).not.toHaveProperty("viewIntro");
    expect(controlEn).not.toHaveProperty("trashCount");
  });
});

describe("Control deleted-items wording", () => {
  it("calls the tab's contents the deleted, not the trash, in both languages", () => {
    expect(controlSv.trashEmpty).toBe("Inget borttaget.");
    expect(controlSv.trashEmptyHint).toMatch(
      /^Det du tar bort hamnar här först/,
    );
    expect(controlEn.trashEmpty).toBe("Nothing deleted.");
    expect(controlEn.trashEmptyHint).toMatch(
      /^What you delete lands here first/,
    );
  });

  it("does not state an exact count when more rows exist", () => {
    expect(controlSv.trashMeta(30, true)).toBe(
      "30+ borttagna · kan återställas",
    );
    expect(controlEn.trashMeta(30, true)).toBe("30+ deleted · can be restored");
    expect(controlSv.trashMeta(1)).toBe("1 borttagen · kan återställas");
    expect(controlSv.showAll(30, true)).toBe("Visa alla (30+)");
    expect(controlEn.showAll(30, true)).toBe("Show all (30+)");
    expect(controlEn.showAll(30)).toBe("Show all (30)");
  });

  it("says Claude asks Sidekick about the memory", () => {
    expect(controlSv.memoryExplain).toMatch(/Claude kan fråga Sidekick om det/);
    expect(controlEn.memoryExplain).toMatch(/Claude can ask Sidekick about it/);
  });
});
