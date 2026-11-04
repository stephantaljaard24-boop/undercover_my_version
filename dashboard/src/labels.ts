import type { SectionRead, Status, TodoStatus, Verdict } from "./api";

export const STATUS_LABELS: Record<Status, string> = {
  waiting: "Waiting",
  in_progress: "In progress",
  awaiting_sign_off: "Waiting for sign-off",
  decided: "Decided",
  needs_handler: "Left for a handler",
};

export const TODO_LABELS: Record<TodoStatus, string> = {
  todo: "To do",
  in_progress: "In progress",
  done: "Done",
  left_for_handler: "Left for a handler",
};

export const DOCUMENT_LABELS: Record<SectionRead["document"], string> = {
  policy_wording: "Policy wording",
  claims_manual: "Claims manual",
};

export const VERDICT_LABELS: Record<Verdict, string> = {
  approve: "Approved",
  decline: "Declined",
  refer: "Referred",
};

/** Show "trip_delay" as "Trip delay". */
export function formatType(type: string): string {
  const words = type.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Show "2026-06-24" as "Jun 24, 2026". */
export function formatDate(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
