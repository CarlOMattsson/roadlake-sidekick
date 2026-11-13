# Work

[Svenska](work.sv.md)

<!-- description: The Work room shows an agenda, a status board and projects. How to create tasks, check them off, change dates and split them into steps. -->

Work (Arbete) is the room for tasks and projects. It has three tabs: Agenda, Status and Projects (Projekt).

![The Work room with the status board in dark mode and a To do group of fictitious tasks.](../images/rooms/work-status-board-dark.png)

*Simulated host, fictitious data*

## What the room shows

- **Agenda** shows tasks with dates: overdue, today, upcoming and later.
- **Status** shows the tasks grouped by state: To do, In progress, Blocked and Done.
- **Projects** shows your projects and the tasks in them.

## Create a task

1. Tap + at the top right.
2. Type the task.
3. Press Return. The field stays open, so you can type the next one straight away.

## Check off a task

Tap the ring in front of the task. The row stays for a short while with an "Ångra" (Undo) button, in case you tapped by mistake.

## Change status or date

1. Press and hold a task in the list. On a computer, right-click or press Shift+F10.
2. Choose a new status, or a date: today, tomorrow, next week or a day you pick.

You can also open the task and tap the date or the status under the title.

## Move overdue tasks to tomorrow

When the agenda has overdue tasks, the row "Flytta … försenade till imorgon" (Move … overdue to tomorrow) sits under the Overdue heading. Tap it and confirm the question "Flytta N till imorgon?" (Move N to tomorrow?) with "Flytta" (Move); "Avbryt" (Cancel) leaves it. The tasks move together, and a line "N flyttade till imorgon" with "Ångra" (Undo) stays for a short while, so you can put them back.

## Split a task into steps

1. Open the task.
2. Tap "+ Lägg till steg" (Add step).
3. Type the step and press Return.

You check steps off inside the task, one at a time. Press and hold a step (on a computer, right-click or press Shift+F10) to move it up or down or archive it.

## Actions on a step

A step can have actions (åtgärder), smaller things to do within the step. A step that has actions says how many under its title, for example "2 åtgärder" (2 actions), and once any is done "1 av 2 åtgärder klara" (1 of 2 actions done). Tap that line to show or hide the actions.

- Tick the box in front of an action to mark it done, and untick it to open it again. The row stays for a short while with "Ångra" (Undo).
- Under the title an action shows its due day, red once it has passed, and its note.
- Press and hold an action (on a computer, right-click or press Shift+F10) to move it up or down or archive it.

You add actions and set their due day and note by asking Claude.

## Tags and tag filters

Tasks and projects can carry tags. Chips show on the rows, and under the title of an open task or project you tap "Lägg till tagg" (Add tag), or "Ändra taggar" (Edit tags) if it already has some, to change them in place. Type a tag and press Return, or tap one of "Dina taggar" (Your tags) to reuse one.

When any task or project has a tag, Agenda and Status show a row "Filtrera på tagg" (Filter by tag). Tap one or more tags, at most five at once, to narrow the list to the items that have all of them. "Rensa (N)" (Clear (N)), where N is the number of tags chosen, takes you back.

## Saved views

In the full-screen Work room, "Sparade vyer" (Saved views) is the first item in the ⋯ menu ("Fler val", More options) at the end of the tab row. "Spara nuvarande vy" (Save current view) stores the filters the list shows right now, including the tags you chose, under a name of up to 120 characters. You can open, rename and archive a view later, and show the archived ones again with "Visa arkiverade". A single project's board cannot be saved as a view.

## Edit a task, its place or how it repeats

Open the task and choose ⋯ and then "Redigera" (Edit) to change the title, description, priority and date. You can also tap the title. Under the title, the chip "Plats" (Place) moves the task to a project, process or domain, and the repeat chip makes it repeat every day, week, month or year.

## Link a contact to a task

Open the task and tap "+ Koppla kontakt" (Link contact). The link then shows both in the task and on the contact.

## What you would rather ask Claude for

- Creating several tasks at once, for example from a list or a photo of a whiteboard.
- Setting up projects, domains and processes.
- Repeating on given weekdays or at other intervals.
- Setting tags and time estimates.
- Adding actions to a step, with a due day or a note.
- Moving many tasks to a given date.
- Finding a task when you only remember roughly what it was about.

## Scopes the room needs

A scope is a permission that the server checks on every call.

| To | Scopes |
| --- | --- |
| Read | `tasks:read`, `projects:read` |
| Change tasks and steps | `tasks:write` |
| Change projects and domains | `projects:write` |

Every tool and its scopes are listed in the [MCP tool reference](../reference/mcp/index.md).
