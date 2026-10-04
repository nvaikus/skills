// Row geometry shared by the task column and the timeline lanes: both sides draw
// the same rows at the same heights, so a task's name and its lane line up.
export const ROW = {
  /** top bar above the header row: list title + search | time controls */
  bar: "h-10",
  head: "h-10 border-b border-line-soft",
  group: "h-8 border-b border-line-soft",
  task: "h-14 border-b border-line-soft",
} as const;
/** Width of the task column; the footer's left part matches it so the legend sits under the lanes. */
export const COL_W = "w-36 shrink-0 sm:w-60 lg:w-72";
/** The same heights in px (h-8 / h-14), for reserving the rows' space. */
export const ROW_PX = { group: 32, task: 56 } as const;
/** Height kept for the rows while a search/filter hides some: never under 2 task rows. */
export const MIN_BODY_PX = 2 * ROW_PX.task;
