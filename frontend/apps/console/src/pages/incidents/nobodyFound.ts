/** What an empty person search says: one letter is too few to search (QA9-F-04). */
export function nobodyFound(search: string): string {
  return search.trim().length === 1 ? 'incidents.type_two_letters' : 'incidents.nobody_found';
}
