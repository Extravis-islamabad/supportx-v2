/**
 * Last-resort conversion of a system code into readable text (architecture.md §9.5 safety net).
 * The label dictionary is the source of truth; this only runs when a label is missing.
 *
 * "INCIDENT_MANAGEMENT" and "incident_management" -> "Incident Management"
 * "cmdb.ci_type.network_switch" -> "Network Switch" (namespaced codes use their last segment)
 */
export function humanize(code: string): string {
  const lastSegment = code.split('.').pop() ?? code;
  return lastSegment
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .split(/[\s_-]+/)
    .filter((word) => word.length > 0)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
}
