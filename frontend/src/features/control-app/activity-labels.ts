/**
 * What an activity row says in History, by the entry's operation (activity-rows.ts). The server stores an English
 * summary; the app words the row itself so it follows the app language. An operation not listed here shows the stored
 * summary. Swedish "AI-steg" is neuter, so its participles end in -at/-et.
 */
export type ActivityLabels = {
  activityOperations: Record<string, string>;
  /** An AI step run's row, by the run's state; it says more than the operation does (to_review, accepted). */
  activityRunStates: Record<string, string>;
};

export const activityEn: ActivityLabels = {
  activityOperations: {
    plan_set: "AI plan saved",
    plan_approved: "AI plan approved",
    plan_withdrawn: "AI plan withdrawn",
    run_queued: "AI step queued",
    run_started: "AI step started",
    run_reported: "AI step reported back",
    run_cancelled: "AI step cancelled",
    run_abandoned: "AI step dropped without an answer",
    create_task: "Task created",
    update_task: "Task updated",
    complete_task: "Task done",
    archive_task: "Task archived",
    restore_task: "Task restored",
    create_tasks: "Tasks created",
    reschedule_tasks: "Tasks rescheduled",
    review_tasks: "Tasks reviewed",
  },
  activityRunStates: {
    queued: "AI step queued",
    running: "AI step running",
    to_review: "AI step waiting for your review",
    needs_input: "AI step waiting for your answer",
    failed: "AI step failed",
    cancelled: "AI step cancelled",
    accepted: "AI step accepted",
    rejected: "AI step rejected",
    redo: "AI step being redone",
    answered: "AI step got your answer",
  },
};

export const activitySv: ActivityLabels = {
  activityOperations: {
    plan_set: "AI-plan sparad",
    plan_approved: "AI-plan godkänd",
    plan_withdrawn: "AI-plan återkallad",
    run_queued: "AI-steg köat",
    run_started: "AI-steg startat",
    run_reported: "AI-steg har rapporterat",
    run_cancelled: "AI-steg avbrutet",
    run_abandoned: "AI-steg avbrutet utan svar",
    create_task: "Uppgift skapad",
    update_task: "Uppgift ändrad",
    complete_task: "Uppgift klar",
    archive_task: "Uppgift arkiverad",
    restore_task: "Uppgift återställd",
    create_tasks: "Uppgifter skapade",
    reschedule_tasks: "Uppgifter omplanerade",
    review_tasks: "Uppgifter genomgångna",
  },
  activityRunStates: {
    queued: "AI-steg köat",
    running: "AI-steg pågår",
    to_review: "AI-steg väntar på din granskning",
    needs_input: "AI-steg väntar på ditt svar",
    failed: "AI-steg misslyckades",
    cancelled: "AI-steg avbrutet",
    accepted: "AI-steg godkänt",
    rejected: "AI-steg avvisat",
    redo: "AI-steg körs om",
    answered: "AI-steg fick ditt svar",
  },
};
