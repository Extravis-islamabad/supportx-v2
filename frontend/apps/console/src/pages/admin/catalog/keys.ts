// Question and option keys (WP-031 plan D6): the API's rule, lower case letters, digits, _.

/** A key from the English label: lower case, letters, digits and underscores (the API's rule). */
export function keyFrom(label: string, taken: Set<string>): string {
  const base =
    label
      .toLowerCase()
      .normalize('NFKD')
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .replace(/^(\d)/, 'q_$1')
      .slice(0, 36) || 'question';
  let key = base;
  for (let n = 2; taken.has(key); n += 1) key = `${base}_${String(n)}`;
  return key;
}
