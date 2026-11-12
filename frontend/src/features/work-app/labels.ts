export const workEn = {
  title: "Work",
  back: "Back",
  empty: "No task or contact to show.",
  hierarchy: "Projects",
  hierarchyEmpty: "No areas, processes, or projects yet.",
  hierarchyTruncated: "There are more items than shown.",
  hierarchyMore: (count: number) => `+${count}`,
  hierarchyMoreLabel: (count: number) => `${count} more`,
  progressOf: (done: number, total: number) => `${done} of ${total} done`,
  task: "Task",
  contact: "Contact",
  status: "Status",
  taskStatus: {
    todo: "To do",
    in_progress: "In progress",
    blocked: "Blocked",
    completed: "Done",
  },
  due: "Due",
  /** The Task's due date as a label (screen readers, editors): "Due". The detail line itself is "Fri 6 Nov · in 2 days". */
  dueDate: "Due",
  /** The compact button beside the due line that opens the date choices. */
  changeDue: "Change date",
  /** The same button when the Task has no due date. */
  addDue: "Add date",
  /** The Task detail's button in place of "Mark done" when the Task is done. */
  reopenTask: "Reopen",
  /** Agenda: moves every open overdue Task to tomorrow with one call; the count is always in the text. */
  moveAllOverdue: (n: number) => `Move ${n} overdue to tomorrow`,
  priority: "Priority",
  priorityLevel: {
    low: "Low",
    normal: "Normal",
    high: "High",
    urgent: "Urgent",
  },
  contacts: "Contacts",
  noContacts: "No contacts linked to this task.",
  contactsForbidden: "You don’t have access to contacts.",
  tasks: "Tasks",
  noTasks: "No tasks linked to this contact.",
  journalEntries: "Journal entries",
  journalUnavailable: "The journal isn’t available to this connection",
  more: "Show more",
  loading: "Loading…",
  failed: "Couldn’t load this. Try again.",
  retry: "Try again",
  queued: "Waiting…",
  /** A tick kept on the phone until it has a network (the widget's too). */
  sending: "Sending…",
  /** Over an agenda read from the phone's offline copy, with when it was last fetched. */
  offlineCopy: (time: string) => `No connection · last fetched ${time}`,
  /** The meta line of a Step whose Task is done. */
  agendaParentDone: "Task done",
  steps: "Steps",
  stepsForbidden: "You don’t have access to steps.",
  stepConflict:
    "A step was changed elsewhere. Reload to see the latest version.",
  stepSaveFailed: "Couldn’t update the step. Try again.",
  stepsShowMore: "Show more steps",
  stepsReadMoreFailed: "Couldn’t load more steps.",
  noSteps: "No steps yet.",
  invalidChange: "That change wasn’t accepted. Check the values.",
  dueIncomplete: "Enter a full date.",
  dateIncomplete: "Enter a full date.",
  edit: "Edit",
  markDone: "Mark as done",
  save: "Save",
  cancel: "Cancel",
  saved: "Saved",
  titleLabel: "Title",
  titleRequired: "Enter a title.",
  titleTooLong: "The title can be up to 200 characters.",
  clearDue: "Clear due date",
  /** The date shortcuts above the due date field of the Task editor. */
  dueShortcuts: "Date shortcuts",
  dueToday: "Today",
  dueTomorrow: "Tomorrow",
  dueNextWeek: "Next week",
  dueNone: "No date",
  /** Expands and collapses the Task description in the Task view. */
  descriptionMore: "Show more",
  descriptionLess: "Show less",
  conflict:
    "This task was changed elsewhere. Reload to see the latest version.",
  reload: "Reload",
  forbiddenWrite: "You don’t have permission to change this.",
  saveFailed: "Couldn’t save. Try again.",
  project: "Project",
  projectStatus: {
    active: "Active",
    paused: "Paused",
    completed: "Completed",
  },
  projectConflict:
    "This project was changed elsewhere. Reload to see the latest version.",
  description: "Description",
  descriptionTooLong: "The description can be up to 10,000 characters.",
  startDate: "Start date",
  targetDate: "Target date",
  clearStartDate: "Clear start date",
  clearTargetDate: "Clear target date",
  noProjectTasks: "No tasks in this project.",
  tasksForbidden: "You don’t have access to this project’s tasks.",
  newTask: "New task",
  newTaskTitle: "Task name",
  newTaskDue: "Due date",
  createTask: "Create task",
  taskCreated: "Task created.",
  taskCreateFailed: "Couldn’t create the task. Try again.",
  createConflict:
    "Something was changed elsewhere. Check the list and try again.",
  stepTitle: "Step name",
  /** The example shown in the empty new-step field. */
  stepPlaceholder: "New step, e.g. call Anna",
  /** The accessible name of × in the empty new-step field. */
  closeStepField: "Close",
  addStep: "Add step",
  stepAdded: "Step added.",
  stepsProgress: (done: number, total: number) =>
    `Steps · ${done} of ${total} done`,
  /** The meta line of a Step just checked or unchecked, beside its Undo. */
  stepDone: "Done",
  stepReopened: "Open again",
  stepCreateFailed: "Couldn’t add the step. Try again.",
  linkContact: "Link contact",
  contactSearchHint: "Type at least two characters to search.",
  noContactMatches: (q: string) => `No contact matches “${q}”.`,
  contactConflict:
    "The contact links were changed elsewhere. Reload to see the latest list.",
  contactWriteFailed: "Couldn’t update the link. Try again.",
  /** The example in the empty search field of the link sheet. */
  contactSearchPlaceholder: "Search by name",
  /** The accessible name of × in the link sheet's search field. */
  closeContactSearch: "Close",
  /** A search hit that is already linked to the Task: shown, not offered. */
  contactAlreadyLinked: "Already linked",
  /** The action row when no Contact matches: creates the Contact and links it to the Task. */
  createAndLinkContact: (name: string) => `Create contact “${name}”`,
  searchContacts: "Search contacts",
  showArchived: "Show archived",
  allContacts: "All contacts",
  noAnyContacts: "No contacts yet.",
  newContact: "New contact",
  createContact: "Create contact",
  contactCreateFailed: "Couldn’t create the contact. Try again.",
  nameLabel: "Name",
  email: "Email",
  phone: "Phone",
  contextNote: "Note",
  relationship: "Relationship",
  organization: "Organization",
  role: "Role",
  address: "Address",
  nameRequired: "Enter a name.",
  nameTooLong: "The name can be up to 200 characters.",
  phoneTooLong: "The phone number can be up to 64 characters.",
  contextNoteTooLong: "The note can be up to 10,000 characters.",
  contactEditConflict:
    "This contact was changed elsewhere. Reload to see the latest version.",
  contactSaveFailed: "Couldn’t save the contact. Try again.",
  archivedLabel: "Archived",
  archivedReadOnly: "Archived contacts are read-only.",
  archiveContact: "Archive",
  restoreContact: "Restore",
  confirmChange: "Confirm",
  aliases: "Also known as",
  aliasLabel: "Also known as",
  /** The heading of the nickname list inside the Contact editor. */
  aliasesHeading: "Nicknames",
  noAliases: "No nicknames.",
  aliasValue: "New nickname",
  aliasRequired: "Enter a nickname.",
  aliasTooLong: "The nickname can be up to 200 characters.",
  addAlias: "Add nickname",
  removeAlias: "Remove",
  removeAliasFor: (value: string) => `Remove nickname ${value}`,
  projects: "Projects",
  board: "Board",
  agenda: "Agenda",
  refresh: "Refresh",
  /** The "⋯" button of the agenda row; it opens Saved views and Refresh. */
  moreActions: "More options",
  /** Deleting a Task (move to the trash, with Undo): the ⋯ entry, the line after it and the failures. */
  deleteTask: "Delete task",
  taskTrashed: "Task deleted.",
  taskTrashedWhere: (control: string) =>
    `You can also restore it in ${control} › Deleted.`,
  taskTrashFailed: "Couldn’t delete the task. Try again.",
  taskRestoreFailed: "Couldn’t undo the deletion. Try again.",
  undo: "Undo",
  noCards: "Nothing here.",
  boardEmpty: "Nothing on the board.",
  /** The empty Status: what the view is for, under "Nothing on the board." */
  boardEmptyHint: "Your tasks by status: to do, in progress, blocked and done.",
  boardForbidden: "You don’t have access to the board.",
  openBoard: "Open Status",
  boardNearestOverdue: "Longest overdue",
  boardNearest: "Due soonest",
  /** Under the inline board summary, and last in the text to the model, when the page has more records. */
  boardMore: "More not shown",
  /** The inline board summary's one line for records the nearest-due list does not show; {count} is the number. */
  boardHiddenCount: "{count} more",
  /** The inline board card's title: "5 overdue of 13 open", "13 open" with none overdue; "+" after the counts while more pages exist. */
  boardHeadline: (overdue: number, open: number, more: boolean) => {
    const plus = more ? "+" : "";
    return overdue
      ? `${overdue}${plus} overdue of ${open}${plus} open`
      : `${open}${plus} open`;
  },
  /** The inline card's Open button while the host answers the fullscreen request. */
  opening: "Opening…",
  /** A refused change in the board, the agenda or To sort: the text names no view, since all three show it. */
  boardConflict: "The list was reloaded. Try again.",
  /** A change to a record that no longer exists: no Try again, since it cannot come back. */
  notFound: "This no longer exists. It may have been deleted in another chat.",
  /** A Task, Project or Contact that was removed (or never existed) when it is read: calm, with no Try again. */
  goneTask: "This task no longer exists",
  goneProject: "This project no longer exists",
  goneContact: "This contact no longer exists",
  /** The row's long-press hint (aria-description), also the tip last in Agenda and Status. */
  rowMenuHint: "Touch and hold a task for more options.",
  /** The same hint with a fine pointer (mouse, trackpad), where a long press does nothing. */
  rowMenuKeys: "Right-click a task or press Shift+F10 for more options.",
  /** The same two for a Step in the Task: its ⋯ is gone; a long press opens its menu. */
  stepMenuHint: "Touch and hold a step for more options.",
  stepMenuKeys: "Right-click a step or press Shift+F10 for more options.",
  /** Moves a card one place up in its Task status column. */
  moveUp: "Move up",
  /** Moves a card one place down in its Task status column. */
  moveDown: "Move down",
  moveListFor: (title: string) => `Choose a status for ${title}`,
  /** The row menu's button for a screen reader (not drawn), on a row of Arbete and on a Step. */
  rowMenuButton: (title: string) => `More options for ${title}`,
  dragTaskFor: (title: string) =>
    `Drag ${title}, or use the left and right arrow keys to move it to the neighboring column`,
  /** "Moved to {status}" after a status change; the Undo button follows it. */
  movedTo: "Moved to {status}",
  moveFailed: "Couldn’t change the status.",
  agendaEmpty: "Nothing on the agenda.",
  /** The empty Agenda: what the view is for, under "Nothing on the agenda." */
  agendaEmptyHint: "What you have to do, sorted by when.",
  /** The example under "Tell Claude:" in the empty Agenda and Status. */
  workEmptyAsk: "Remind me to pay the rent on Friday",
  /** The empty Agenda's and Status's own way to start: it opens the tab row's new-Task field, as + does. */
  emptyAddTask: "Add a task",
  agendaUndo: "Undo",
  /** The Undo line while a status move is written and read again; it has no Undo button then. */
  agendaMoving: "Moving…",
  /** The Undo line of a Task marked done in the Agenda: where it went. Status says only "Done". */
  agendaDoneInStatus: "Done · in Status",
  /** A recurring Task marked done: the server reopened it for its next date. Its Undo line, and its row once Undo
   *  has run out: "Done · next: Fri 27 Nov". */
  recurringDone: "Done · next: {date}",
  /** The same, when the rule gives no next date in the reply. */
  recurringDoneNoDate: "Done · repeats",
  /** The fold last in the Agenda: the Tasks marked done here since the list was read; the count follows ("Done here (2)"),
   *  and the meta line under it says what "here" is. */
  agendaDoneToday: "Done here",
  agendaDoneSince: "Since you opened the agenda",
  /** The visible label above the agenda's search field; it is also the field's accessible name. */
  agendaFilter: "Filter tasks",
  agendaNoMatches: "No tasks match the filter.",
  /** An agenda search with no hit, naming the search text. */
  agendaNoMatch: "No tasks match “{q}”.",
  /** Text button under an empty search result: empties the search field. */
  agendaClearSearch: "Clear search",
  /** Glyph action of a task that is not done. */
  agendaComplete: "Mark {title} as done",
  stepOf: "Step in: {title}",
  /** Glyph action of a task that is done. */
  agendaReopen: "Mark {title} as not done",
  /** Triage: moves an overdue Task to 23:59 tomorrow. */
  triageTomorrow: "Tomorrow",
  /** Triage: moves an overdue Task to 23:59 on next Monday. */
  triageNextWeek: "Next week",
  /** Names the date choices in a Task's ⋯ menu in the agenda: Tomorrow, Next week and Choose … */
  rescheduleGroup: "New date",
  /** The date chip of a row's quick choices; the platform's date input lies invisibly over it and opens the picker for any day. */
  rescheduleChoose: "Choose date…",
  rescheduleRow: "Date",
  /** Closes a row's quick choices; "Klar" would read as the status. */
  closeMenu: "Close",
  /** The accessible name of that date input. */
  rescheduleDate: "Choose date",
  /** The row above the agenda that opens the sorting view; the count follows in brackets. */
  unsortedOpen: (count: string) => `Unsorted (${count})`,
  /** Heading of the sorting view, opened from the row above the agenda and closed with Back. */
  unsortedHeading: "Unsorted",
  /** The sorting view has no Task left to sort. */
  unsortedEmpty: "Nothing to sort.",
  /** The sorting view has no Domain to sort into. */
  unsortedNoDomains: "No areas yet.",
  /** Names the row of one Task in the sorting view: its Domain buttons are grouped under this name. */
  unsortedRowFor: (title: string) => `Sort ${title}`,
  /** Agenda group headings, in display order; the dates of a group follow the heading. */
  agendaGroup: {
    overdue: "Overdue",
    today: "Today",
    thisWeek: "This week",
    nextWeek: "Next week",
    later: "Later",
    undated: "No date",
  },
  kindName: {
    task: "Task",
    project: "Project",
    domain: "Area",
    process: "Process",
    step: "Step",
    action: "Action",
  },
  dateLocale: "en-GB",
};
export type WorkLabels = typeof workEn;
export const workSv: WorkLabels = {
  title: "Arbete",
  back: "Tillbaka",
  empty: "Ingen uppgift eller kontakt att visa.",
  hierarchy: "Projekt",
  hierarchyEmpty: "Inga domäner, processer eller projekt ännu.",
  hierarchyTruncated: "Fler noder finns än som visas.",
  hierarchyMore: (count: number) => `+${count}`,
  hierarchyMoreLabel: (count: number) => `${count} fler`,
  progressOf: (done: number, total: number) => `${done} av ${total} klara`,
  task: "Uppgift",
  contact: "Kontakt",
  status: "Status",
  taskStatus: {
    todo: "Att göra",
    in_progress: "Pågår",
    blocked: "Blockerad",
    completed: "Klar",
  },
  due: "Förfaller",
  /** The Task's due date as a label (screen readers, editing). The detail row itself reads "fre 6 nov · om 2 dagar". */
  dueDate: "Förfaller",
  changeDue: "Ändra datum",
  addDue: "Lägg till datum",
  reopenTask: "Återöppna",
  /** The agenda: moves every overdue Task to tomorrow with one call; the text always states the count and what
   *  is moved. */
  moveAllOverdue: (n: number) =>
    `Flytta ${n} ${n === 1 ? "försenad" : "försenade"} till imorgon`,
  priority: "Prioritet",
  priorityLevel: {
    low: "Låg",
    normal: "Normal",
    high: "Hög",
    urgent: "Brådskande",
  },
  contacts: "Kontakter",
  noContacts: "Inga kontakter kopplade till uppgiften.",
  contactsForbidden: "Du har inte behörighet att se kontakter.",
  tasks: "Uppgifter",
  noTasks: "Inga uppgifter kopplade till kontakten.",
  journalEntries: "Anteckningar",
  journalUnavailable: "Dagboken är inte tillgänglig för den här anslutningen",
  more: "Visa fler",
  loading: "Laddar…",
  failed: "Det gick inte att läsa. Försök igen.",
  retry: "Försök igen",
  queued: "Väntar…",
  sending: "Skickas…",
  offlineCopy: (time: string) => `Ingen anslutning · senast hämtad ${time}`,
  agendaParentDone: "Uppgiften är klar",
  steps: "Steg",
  stepsForbidden: "Du har inte behörighet att se steg.",
  stepConflict:
    "Ett steg ändrades någon annanstans. Ladda om för att se senaste versionen.",
  stepSaveFailed: "Det gick inte att uppdatera steget. Försök igen.",
  stepsShowMore: "Visa fler steg",
  stepsReadMoreFailed: "Det gick inte att läsa fler steg.",
  noSteps: "Inga steg än.",
  invalidChange: "Ändringen godtogs inte. Kontrollera värdena.",
  dueIncomplete: "Ange ett fullständigt datum.",
  dateIncomplete: "Ange ett fullständigt datum.",
  edit: "Redigera",
  /** The Task view's button that writes the Task as Klar, through the same path as the status select. */
  markDone: "Markera klar",
  save: "Spara",
  cancel: "Avbryt",
  saved: "Sparat",
  titleLabel: "Titel",
  titleRequired: "Ange en titel.",
  titleTooLong: "Titeln får vara högst 200 tecken.",
  clearDue: "Rensa förfallodatum",
  /** The date shortcuts above the due date field of the Task editor. */
  dueShortcuts: "Snabbval för datum",
  dueToday: "Idag",
  dueTomorrow: "Imorgon",
  dueNextWeek: "Nästa vecka",
  dueNone: "Inget datum",
  /** Expands and collapses the Task description in the Task view. */
  descriptionMore: "Visa mer",
  descriptionLess: "Visa mindre",
  conflict:
    "Uppgiften ändrades någon annanstans. Ladda om för att se senaste versionen.",
  reload: "Ladda om",
  forbiddenWrite: "Du har inte behörighet att ändra det här.",
  saveFailed: "Det gick inte att spara. Försök igen.",
  project: "Projekt",
  projectStatus: {
    active: "Aktivt",
    paused: "Pausat",
    completed: "Avslutat",
  },
  projectConflict:
    "Projektet ändrades någon annanstans. Ladda om för att se senaste versionen.",
  description: "Beskrivning",
  descriptionTooLong: "Beskrivningen får vara högst 10 000 tecken.",
  startDate: "Startdatum",
  targetDate: "Måldatum",
  clearStartDate: "Rensa startdatum",
  clearTargetDate: "Rensa måldatum",
  noProjectTasks: "Inga uppgifter i projektet.",
  tasksForbidden: "Du har inte behörighet att se projektets uppgifter.",
  newTask: "Ny uppgift",
  newTaskTitle: "Uppgiftens namn",
  newTaskDue: "Förfallodatum",
  createTask: "Skapa uppgift",
  taskCreated: "Uppgiften skapades.",
  taskCreateFailed: "Det gick inte att skapa uppgiften. Försök igen.",
  createConflict:
    "Något ändrades någon annanstans. Kontrollera listan och försök igen.",
  stepTitle: "Stegets namn",
  stepPlaceholder: "Nytt steg, t.ex. ring Anna",
  closeStepField: "Stäng",
  addStep: "Lägg till steg",
  stepAdded: "Steget lades till.",
  stepsProgress: (done: number, total: number) =>
    `Steg · ${done} av ${total} klara`,
  stepDone: "Klar",
  stepReopened: "Öppen igen",
  stepCreateFailed: "Det gick inte att lägga till steget. Försök igen.",
  linkContact: "Koppla kontakt",
  contactSearchHint: "Skriv minst två tecken för att söka.",
  noContactMatches: (q: string) => `Ingen kontakt matchar ”${q}”.`,
  contactConflict:
    "Kopplingarna ändrades någon annanstans. Ladda om för att se senaste listan.",
  contactWriteFailed: "Det gick inte att ändra kopplingen. Försök igen.",
  contactSearchPlaceholder: "Sök på namn",
  closeContactSearch: "Stäng",
  contactAlreadyLinked: "Redan kopplad",
  createAndLinkContact: (name: string) => `Skapa kontakt ”${name}”`,
  searchContacts: "Sök kontakter",
  showArchived: "Visa arkiverade",
  allContacts: "Alla kontakter",
  noAnyContacts: "Inga kontakter än.",
  newContact: "Ny kontakt",
  createContact: "Skapa kontakt",
  contactCreateFailed: "Det gick inte att skapa kontakten. Försök igen.",
  nameLabel: "Namn",
  email: "E-post",
  phone: "Telefon",
  contextNote: "Anteckning",
  relationship: "Relation",
  organization: "Organisation",
  role: "Roll",
  address: "Adress",
  nameRequired: "Ange ett namn.",
  nameTooLong: "Namnet får vara högst 200 tecken.",
  phoneTooLong: "Telefonnumret får vara högst 64 tecken.",
  contextNoteTooLong: "Anteckningen får vara högst 10 000 tecken.",
  contactEditConflict:
    "Kontakten ändrades någon annanstans. Ladda om för att se senaste versionen.",
  contactSaveFailed: "Det gick inte att ändra kontakten. Försök igen.",
  archivedLabel: "Arkiverad",
  archivedReadOnly: "Arkiverade kontakter är skrivskyddade.",
  archiveContact: "Arkivera",
  restoreContact: "Återställ",
  confirmChange: "Bekräfta",
  aliases: "Även kallad",
  aliasLabel: "Även kallad",
  aliasesHeading: "Smeknamn",
  noAliases: "Inga smeknamn.",
  aliasValue: "Nytt smeknamn",
  aliasRequired: "Ange ett smeknamn.",
  aliasTooLong: "Smeknamnet får vara högst 200 tecken.",
  addAlias: "Lägg till smeknamn",
  removeAlias: "Ta bort",
  removeAliasFor: (value: string) => `Ta bort smeknamnet ${value}`,
  projects: "Projekt",
  board: "Tavla",
  agenda: "Agenda",
  refresh: "Uppdatera",
  /** The "⋯" button in the agenda's row; it opens "Sparade vyer" and "Uppdatera". */
  moreActions: "Fler alternativ",
  /** Deleting a Task (move to the trash, with Undo): the ⋯ entry, the line after it and the failures. */
  deleteTask: "Ta bort uppgift",
  taskTrashed: "Uppgiften är borttagen.",
  taskTrashedWhere: (control: string) =>
    `Du kan också återställa den i ${control} › Borttaget.`,
  taskTrashFailed: "Det gick inte att ta bort uppgiften. Försök igen.",
  taskRestoreFailed: "Det gick inte att ångra borttagningen. Försök igen.",
  undo: "Ångra",
  noCards: "Inget här.",
  boardEmpty: "Inga poster på tavlan.",
  boardEmptyHint:
    "Dina uppgifter efter status: att göra, pågår, blockerad och klar.",
  boardForbidden: "Du har inte behörighet att se tavlan.",
  openBoard: "Öppna Status",
  boardNearestOverdue: "Äldst försenade",
  boardNearest: "Närmast i tid",
  /** Under the inline board summary, and last in the text to the model, when the page has more records. */
  boardMore: "Fler finns",
  /** The inline board summary's one line for records the nearest-due list does not show; {count} is the number. */
  boardHiddenCount: "{count} fler",
  boardHeadline: (overdue, open, more) => {
    const plus = more ? "+" : "";
    return overdue
      ? `${overdue}${plus} försenad${overdue > 1 ? "e" : ""} av ${open}${plus} öppna`
      : `${open}${plus} öppna`;
  },
  /** The inline card's Open button while the host answers the fullscreen request. */
  opening: "Öppnar…",
  /** A refused change on the board, the agenda or "Att sortera": the text names no view, since all three show it. */
  boardConflict: "Listan har lästs om, försök igen.",
  /** A change to something that no longer exists: no "Försök igen", since it will not come back. */
  notFound: "Den finns inte längre. Den kan ha tagits bort i en annan chatt.",
  /** A Task, Project or Contact that was deleted (or is missing) when it is read: calm, without "Försök igen". */
  goneTask: "Uppgiften finns inte längre",
  goneProject: "Projektet finns inte längre",
  goneContact: "Kontakten finns inte längre",
  rowMenuHint: "Håll inne en uppgift för fler val.",
  rowMenuKeys: "Högerklicka på en uppgift eller tryck Shift+F10 för fler val.",
  stepMenuHint: "Håll inne ett steg för fler val.",
  stepMenuKeys: "Högerklicka på ett steg eller tryck Shift+F10 för fler val.",
  /** Names the board's columns in the single-column layout (the visually hidden heading of a segment). */
  /** Moves a card one place up in its Task status column. */
  moveUp: "Flytta upp",
  /** Moves a card one place down in its Task status column. */
  moveDown: "Flytta ned",
  moveListFor: (title: string) => `Välj status för ${title}`,
  /** The row menu's button for screen readers (not drawn), on a row in the Work room and on a Step. */
  rowMenuButton: (title: string) => `Fler val för ${title}`,
  dragTaskFor: (title: string) =>
    `Dra ${title}, eller använd pilarna vänster och höger för att flytta till närliggande kolumn`,
  /** "Flyttad till {status}" after a status change; "Ångra" follows. */
  movedTo: "Flyttad till {status}",
  moveFailed: "Det gick inte att ändra status.",
  agendaEmpty: "Inget på agendan.",
  agendaEmptyHint: "Det du ska göra, sorterat efter när.",
  workEmptyAsk: "Påminn mig att betala hyran på fredag",
  emptyAddTask: "Lägg till en uppgift",
  agendaUndo: "Ångra",
  /** The undo line while a move is written and read back; there is no "Ångra" button then. */
  agendaMoving: "Flyttar…",
  agendaDoneInStatus: "Klar · finns i Status",
  recurringDone: "Klar · nästa: {date}",
  recurringDoneNoDate: "Klar · upprepas",
  agendaDoneToday: "Klara här",
  agendaDoneSince: "Sedan du öppnade agendan",
  /** The visible label above the agenda's search field; it is also the field's accessible name. */
  agendaFilter: "Filtrera uppgifter",
  agendaNoMatches: "Inga uppgifter matchar filtret.",
  /** An agenda search with no match; the search text stands in quotation marks. */
  agendaNoMatch: "Inga uppgifter matchar ”{q}”.",
  /** Text button under a search with no match: empties the search field. */
  agendaClearSearch: "Rensa sökningen",
  /** Glyph action of a task that is not done. */
  agendaComplete: "Markera {title} som klar",
  stepOf: "Steg i: {title}",
  /** Glyph action of a task that is done. */
  agendaReopen: "Markera {title} som ej klar",
  /** Triage: moves an overdue Task to 23:59 tomorrow. */
  triageTomorrow: "Imorgon",
  /** Triage: moves an overdue Task to 23:59 next Monday. */
  triageNextWeek: "Nästa vecka",
  /** Names the date choices in a Task's ⋯ menu in the agenda: "Imorgon", "Nästa vecka" and "Välj …". */
  rescheduleGroup: "Nytt datum",
  /** The date chip in a row's quick choices; the platform's date field lies invisibly over it and opens the picker for any day. */
  rescheduleChoose: "Välj datum …",
  rescheduleRow: "Datum",
  closeMenu: "Stäng",
  /** The accessible name of the date input. */
  rescheduleDate: "Välj datum",
  /** The row above the agenda that opens the "Att sortera" view; the count stands in parentheses. */
  unsortedOpen: (count: string) => `Att sortera (${count})`,
  /** The heading of the "Att sortera" view, which opens from the row above the agenda and closes with "Tillbaka". */
  unsortedHeading: "Att sortera",
  /** The "Att sortera" view has no Task left to sort. */
  unsortedEmpty: "Inget att sortera.",
  /** The "Att sortera" view has no Domain to sort into. */
  unsortedNoDomains: "Inga domäner ännu.",
  /** Names the row of a Task in the "Att sortera" view: its Domain buttons are grouped under that name. */
  unsortedRowFor: (title: string) => `Sortera ${title}`,
  /** Agenda group headings, in display order; the dates of a group follow the heading. */
  agendaGroup: {
    overdue: "Försenade",
    today: "Idag",
    thisWeek: "Denna vecka",
    nextWeek: "Nästa vecka",
    later: "Senare",
    undated: "Utan datum",
  },
  kindName: {
    task: "Uppgift",
    project: "Projekt",
    domain: "Domän",
    process: "Process",
    step: "Steg",
    action: "Åtgärd",
  },
  dateLocale: "sv-SE",
};

/** A translated label; a value this view does not know is shown as it arrived. */
export function knownLabel(
  labels: Record<string, string>,
  value: string,
): string {
  return Object.prototype.hasOwnProperty.call(labels, value)
    ? (labels[value] ?? value)
    : value;
}

/** Translated Task status; a value this view does not know is shown as it arrived. */
export function taskStatusLabel(t: WorkLabels, value: string): string {
  return knownLabel(t.taskStatus, value);
}

/** Translated Task priority; a value this view does not know is shown as it arrived. */
export function priorityLabel(t: WorkLabels, value: string): string {
  return knownLabel(t.priorityLevel, value);
}

/** Translated Project status; a value this view does not know is shown as it arrived. */
export function projectStatusLabel(t: WorkLabels, value: string): string {
  return knownLabel(t.projectStatus, value);
}

/**
 * Status of a Work record on the board or in the agenda: a Task status or a Project status, since
 * both appear there. A value neither label set knows is shown as it arrived.
 */
export function workStatusLabel(t: WorkLabels, value: string): string {
  if (Object.prototype.hasOwnProperty.call(t.taskStatus, value))
    return taskStatusLabel(t, value);
  return projectStatusLabel(t, value);
}

/**
 * Status of one node in the Work hierarchy, by its kind. A Task or Step uses the Task words; a Project,
 * a Domain or a Process uses the Project words, so a Project "completed" reads "Avslutat", not the Task's
 * "Klar". An archived Domain or Process reads with the archived word. A value neither set knows is shown
 * as it arrived.
 */
export function hierarchyStatusLabel(
  t: WorkLabels,
  kind: string,
  value: string,
): string {
  if (kind === "task" || kind === "step") return taskStatusLabel(t, value);
  if (value === "archived") return t.archivedLabel;
  return projectStatusLabel(t, value);
}

/** Translated kind of a Work record (Task, Project, Domain, Process, Step or Action). */
export function workKindLabel(t: WorkLabels, value: string): string {
  return knownLabel(t.kindName, value);
}

/** Translated agenda group heading. */
export function agendaGroupLabel(t: WorkLabels, value: string): string {
  return knownLabel(t.agendaGroup, value);
}
