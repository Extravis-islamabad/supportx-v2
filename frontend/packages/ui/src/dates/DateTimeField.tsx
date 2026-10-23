import { DatePicker, Space, Typography } from 'antd';

import { useLabel } from '../appearance';

import { fromPicker, toPicker, useTimeZone } from './time';

const FORMAT = 'YYYY-MM-DD HH:mm';
const TIME = { format: 'HH:mm' } as const;

function ZoneNote({ zone }: { zone: string }) {
  const t = useLabel();
  return (
    <Typography.Text type="secondary" style={{ fontSize: 12 }} data-testid="time-zone-note">
      {t('datetime.time_zone_note', { zone })}
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
  return (
    <Space direction="vertical" size={2}>
      <DatePicker
        id={id}
        showTime={TIME}
        showNow={false}
        format={FORMAT}
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
  return (
    <Space direction="vertical" size={2}>
      <DatePicker.RangePicker
        id={id}
        showTime={TIME}
        format={FORMAT}
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
