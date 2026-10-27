/** The label key of a person field code (`site_id` → the Site label; employee_id stays). */
export function personFieldKey(field: string): string {
  const name = ['site_id', 'department_id', 'manager_id'].includes(field)
    ? field.replace(/_id$/, '')
    : field;
  return `people.field.${name}`;
}
