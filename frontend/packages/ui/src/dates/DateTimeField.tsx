import { DatePicker, Space, Typography } from 'antd';
import dayjs from 'dayjs';

import { useAppearance, useLabel } from '../appearance';

import { pickerFormat } from './format';
import { fromPicker, toPicker, useTimeZone, zoneName } from './time';

/**
 * "Times are in <zone>", said once under a group of date fields (a range, a row of start, end
 * and duration) that hide their own notes (D-147: one note, not one per field).
 */
export function TimeZoneNote() {
  return <ZoneNote zone={useTimeZone()} />;
}

function ZoneNote({ zone }: { zone: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  return (
    <Typography.Text
      type="secondary"
      style={{ fontSize: 12 }}
      // The exact zone stays one hover away for admins checking it.
      title={zone}
      data-testid="time-zone-note"
    >
      {t('datetime.time_zone_note', { zone: zoneName(zone, locale) })}
    </Typography.Text>
  );
}

export interface DateTimeFieldProps {
  /** ISO instant (UTC) or null. */
  value: string | null;
  onChange: (value: string | null) => void;
  id?: string;
  testId?: string;
  disabled?: boolean;
  /** Hide the "times are in …" note (e.g. when a range shows it once). */
  hideZone?: boolean;
}

/**
 * Date and time entry for every form (D-035): Ant Design's DatePicker in the user's profile time
 * zone, keyboard friendly and mirrored in RTL. Values in and out are ISO instants, so forms and
 * the API never see local time. The picker's own "Now" is hidden: it would use the browser's
 * clock, which may be in another zone than the profile.
 */
export function DateTimeField({
  value,
  onChange,
  id,
  testId,
  disabled,
  hideZone,
}: DateTimeFieldProps) {
  const zone = useTimeZone();
  const { dates } = useAppearance();
  return (
    <Space direction="vertical" size={2}>
      <DatePicker
        id={id}
        showTime={{ format: dates.timeFormat === '12h' ? 'hh:mm A' : 'HH:mm' }}
        showNow={false}
        format={pickerFormat(dates, true)}
        allowClear
        disabled={disabled}
        value={toPicker(value, zone)}
        onChange={(picked) => {
          onChange(fromPicker(picked, zone));
        }}
        data-testid={testId}
        style={{ minWidth: 220 }}
      />
      {hideZone !== true && <ZoneNote zone={zone} />}
    </Space>
  );
}

export interface DateFieldProps {
  /** A calendar day "YYYY-MM-DD" or null; no time, no zone. */
  value: string | null;
  onChange: (value: string | null) => void;
  id?: string;
  testId?: string;
  disabled?: boolean;
  ariaLabel?: string;
}

/** A calendar day (custom date fields, WP-026): the same day for everyone, in every zone. */
export function DateField({ value, onChange, id, testId, disabled, ariaLabel }: DateFieldProps) {
  const { dates } = useAppearance();
  return (
    <DatePicker
      id={id}
      format={pickerFormat(dates, false)}
      allowClear
      disabled={disabled}
      aria-label={ariaLabel}
      value={value === null || value === '' ? null : dayjs(value)}
      onChange={(picked) => {
        // Cleared: antd passes null at run time although its type says Dayjs.
        const day = picked as typeof picked | null;
        onChange(day === null ? null : day.format('YYYY-MM-DD'));
      }}
      data-testid={testId}
      style={{ minWidth: 180 }}
    />
  );
}

export interface DateTimeRangeFieldProps {
  /** [start, end] as ISO instants; either may be null (open-ended). */
  value: [string | null, string | null];
  onChange: (value: [string | null, string | null]) => void;
  id?: string;
  testId?: string;
  disabled?: boolean;
}

/** A start–end range in the user's time zone (filters, windows); either end may stay empty. */
export function DateTimeRangeField({
  value,
  onChange,
  id,
  testId,
  disabled,
}: DateTimeRangeFieldProps) {
  const zone = useTimeZone();
  const { dates } = useAppearance();
  return (
    <Space direction="vertical" size={2}>
      <DatePicker.RangePicker
        id={id}
        showTime={{ format: dates.timeFormat === '12h' ? 'hh:mm A' : 'HH:mm' }}
        format={pickerFormat(dates, true)}
        allowEmpty={[true, true]}
        allowClear
        disabled={disabled}
        value={[toPicker(value[0], zone), toPicker(value[1], zone)]}
        onChange={(picked) => {
          onChange([fromPicker(picked?.[0] ?? null, zone), fromPicker(picked?.[1] ?? null, zone)]);
        }}
        data-testid={testId}
      />
      <ZoneNote zone={zone} />
    </Space>
  );
}
