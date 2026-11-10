// Show times are entered and displayed in Eastern time. Pure helpers.

const ET = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hourCycle: "h23",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

function easternWallClockAsUtc(instant: number): number {
  const p = Object.fromEntries(ET.formatToParts(new Date(instant)).map((x) => [x.type, x.value]));
  return Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), Number(p.hour), Number(p.minute));
}

/** "2026-12-08T20:00" (Eastern wall clock, from a datetime-local input) → ISO UTC. Null if blank or invalid. */
export function easternLocalToIso(local: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(local.trim());
  if (!m) return null;
  const wall = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  // First guess using the offset in effect at that wall time read as UTC, then
  // once more so times near a daylight-saving change land on the right side.
  let instant = wall - (easternWallClockAsUtc(wall) - wall);
  instant = wall - (easternWallClockAsUtc(instant) - instant);
  return new Date(instant).toISOString();
}

/** ISO UTC → "2026-12-08T20:00" Eastern, for a datetime-local input's value. */
export function isoToEasternLocal(iso: string | null): string {
  if (!iso) return "";
  return new Date(easternWallClockAsUtc(Date.parse(iso))).toISOString().slice(0, 16);
}
