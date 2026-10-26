/** File sizes in the user's language ("2.4 MB", "٢٫٤ ميغابايت"), decimal units like the API. */
export function formatSize(bytes: number, locale: string): string {
  const units = [
    { unit: 'gigabyte', size: 1e9 },
    { unit: 'megabyte', size: 1e6 },
    { unit: 'kilobyte', size: 1e3 },
  ] as const;
  for (const { unit, size } of units) {
    if (bytes >= size) {
      return new Intl.NumberFormat(locale, {
        style: 'unit',
        unit,
        unitDisplay: 'short',
        maximumFractionDigits: 1,
      }).format(bytes / size);
    }
  }
  return new Intl.NumberFormat(locale, {
    style: 'unit',
    unit: 'byte',
    unitDisplay: 'short',
  }).format(bytes);
}

/** The lower-case extension without the dot ('' when there is none), as the API reads it. */
export function extensionOf(name: string): string {
  const base = name.split('/').pop() ?? name;
  const trimmed = base.replace(/^\.+|\.+$/g, '');
  const dot = trimmed.lastIndexOf('.');
  return dot <= 0 ? '' : trimmed.slice(dot + 1).toLowerCase();
}
