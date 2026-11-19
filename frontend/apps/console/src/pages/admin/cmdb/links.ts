/** Where a CI type's Fields page is (a parent's "From <type>" link leads there; 0175 part 2). */
export function ciTypeFieldsHref(typeId: string): string {
  return `/admin/cmdb/types/${typeId}/fields`;
}
