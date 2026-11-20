/**
 * People's names withheld from a vendor support session (WP-057 S4c-3, D-173): the API sends an
 * empty name, and every screen shows this labelled stand-in instead. Set by the support banner
 * from the session (null for everyone else, so an empty name stays empty). The one switch, so
 * mention chips can use the same stand-in when Haider decides (the coordinator's condition 4).
 */
let hiddenLabel: string | null = null;

export function setHiddenPersonLabel(label: string | null): void {
  hiddenLabel = label;
}

/** A person's name as shown: the stand-in when the session masks it, else the name itself. */
export function shownName(name: string | null | undefined): string {
  if (hiddenLabel !== null && (name ?? '') === '') return hiddenLabel;
  return name ?? '';
}
