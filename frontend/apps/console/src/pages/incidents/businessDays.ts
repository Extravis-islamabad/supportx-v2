/** `days` business days (Monday to Friday) after `start`, as the server counts (D-107 D4). */
export function addBusinessDays(start: Date, days: number): Date {
  const moment = new Date(start.getTime());
  let left = days;
  while (left > 0) {
    moment.setUTCDate(moment.getUTCDate() + 1);
    const day = moment.getUTCDay();
    if (day !== 0 && day !== 6) left -= 1;
  }
  return moment;
}
