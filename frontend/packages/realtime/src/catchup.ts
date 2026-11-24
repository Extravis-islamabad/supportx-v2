/**
 * The first-subscribe catch-up (architecture.md §8.3): a screen fetches its data, then subscribes,
 * and a change published in between was never shown until the next event. When a channel's
 * subscription first goes live, its screens get one `refresh`, delivered inside `duringCatchUp`
 * with the moment it went live. `refreshList` and `refreshRecord` then fetch each of that channel's
 * active queries once more: a query with data now (restarting a refetch in flight), a first fetch
 * still in flight once it lands. One catch-up fetch per query, never a storm.
 *
 * Delivery is synchronous and the helpers read the moment synchronously, so it is visible exactly
 * while the catch-up is delivered.
 */

let liveSince: number | null = null;

/** Run `deliver` as a first-subscribe catch-up for a subscription that went live at `since`. */
export function duringCatchUp(since: number, deliver: () => void): void {
  const previous = liveSince;
  liveSince = since;
  try {
    deliver();
  } finally {
    liveSince = previous;
  }
}

/** The live moment while a catch-up is being delivered, else null (an ordinary message). */
export function catchUpSince(): number | null {
  return liveSince;
}
