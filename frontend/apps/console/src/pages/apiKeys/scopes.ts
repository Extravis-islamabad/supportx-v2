// WP-041: a key's scopes from the per-area choice on the new-key form.

export type Access = 'none' | 'read' | 'write';

/** read: `<area>:read`; read and write: both (a write scope never comes without its read). */
export function scopesOf(access: Record<string, Access>): string[] {
  return Object.entries(access)
    .filter(([, level]) => level !== 'none')
    .flatMap(([area, level]) =>
      level === 'write' ? [`${area}:read`, `${area}:write`] : [`${area}:read`],
    )
    .sort();
}
