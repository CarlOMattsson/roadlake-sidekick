import { createContext } from "react";

/**
 * Opens the tab row's new-Task field (the + of the fullscreen Work shell), for the empty Agenda and Status, whose
 * `newTask` is the hand-made way next to `askLead`. Absent where the host cannot create a Task or the
 * view has no tab row (an inline card): the empty state then offers only the example.
 */
export const WorkNewTaskContext = createContext<(() => void) | undefined>(
  undefined,
);
