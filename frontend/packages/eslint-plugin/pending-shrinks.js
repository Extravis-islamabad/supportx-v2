// The `channel-covers` exemption list only shrinks (architecture.md §8.3): compared with the target
// branch, a file may leave the list but never join it, and once the list is gone it never comes
// back. CI calls the command line below (scripts/covers-pending-shrinks.js).

/**
 * What's wrong with this branch's list against the target branch's, or null when it's fine.
 *
 * @param {object} state
 * @param {string[] | null} state.base The target branch's list; null when it has none.
 * @param {boolean} state.baseHasRule Whether the target branch has the `channel-covers` rule:
 *   without it, the target is from before the rule (nothing to compare); with it and no list,
 *   the list was finished and deleted.
 * @param {string[] | null} state.current This branch's list; null when it has none.
 * @returns {string | null}
 */
export function shrinkProblem({ base, baseHasRule, current }) {
  if (current === null) return null; // deleting the list (or never having it) is always fine
  if (base === null) {
    if (!baseHasRule) return null; // the target is from before the rule: the list starts here
    return (
      'channel-covers-pending.json was finished and deleted on the target branch; it never ' +
      'comes back. Give these channel hooks `covers` instead (architecture.md §8.3):\n' +
      current.map((file) => `  ${file}`).join('\n')
    );
  }
  const before = new Set(base);
  const added = current.filter((file) => !before.has(file)).sort();
  if (added.length === 0) return null;
  return (
    'These files joined channel-covers-pending.json; the list only shrinks. Give their channel ' +
    'hooks `covers` instead (architecture.md §8.3):\n' +
    added.map((file) => `  ${file}`).join('\n')
  );
}
