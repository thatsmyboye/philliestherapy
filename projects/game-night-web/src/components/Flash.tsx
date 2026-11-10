import { ERRORS, first, NOTICES } from "@/lib/messages";

type Search = Record<string, string | string[] | undefined>;

/** Renders the message for ?error= / ?notice= if there is one. */
export function Flash({ search }: { search: Search }) {
  const error = ERRORS[first(search.error) ?? ""];
  const notice = NOTICES[first(search.notice) ?? ""];
  if (!error && !notice) return null;
  return (
    <div className={`notice ${error ? "notice-error" : "notice-ok"}`} role={error ? "alert" : "status"}>
      {error ?? notice}
    </div>
  );
}
