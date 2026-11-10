import { Select, Space, Tag } from 'antd';

import { DateTimeRangeField, useDateTime, useLabel } from '@supportx/ui';

import type { ReportWords } from '../../reports/names';
import { PRESETS, RANGE_FIELDS, type Preset, type RangeField, type TimeRangeValue } from './model';

// The quick time range above the list (REQ-INC-108): a date field, a preset or a custom range,
// always naming its field (AC2). Presets are computed by the server in the user's time zone
// (relative operators); "this quarter" and custom ranges are exact instants from that zone.

/** The control: field, preset, and (for custom) the range; plus the active range as a tag. */
export function TimeRange({
  value,
  onChange,
  words,
}: {
  value: TimeRangeValue | undefined;
  onChange: (value: TimeRangeValue | undefined) => void;
  words: ReportWords;
}) {
  const t = useLabel();
  const field = value?.field ?? 'created_at';
  return (
    <Space wrap data-testid="inc-time-range">
      <Select<RangeField>
        aria-label={t('incidents.time.field')}
        prefix={`${t('incidents.time.field')}:`}
        value={field}
        onChange={(next) => {
          onChange(value === undefined ? undefined : { ...value, field: next });
        }}
        options={RANGE_FIELDS.map((name) => ({ value: name, label: words.field(name) }))}
        style={{ minWidth: 'min(220px, 100%)' }}
        data-testid="inc-time-field"
      />
      <Select<Preset | ''>
        aria-label={t('incidents.time.range')}
        prefix={`${t('incidents.time.range')}:`}
        value={value?.preset ?? ''}
        onChange={(preset) => {
          onChange(preset === '' ? undefined : { field, preset, range: value?.range });
        }}
        options={[
          { value: '', label: t('incidents.time.any') },
          ...PRESETS.map((preset) => ({ value: preset, label: t(`incidents.time.${preset}`) })),
        ]}
        style={{ minWidth: 'min(200px, 100%)' }}
        data-testid="inc-time-preset"
      />
      {value?.preset === 'custom' && (
        <DateTimeRangeField
          value={value.range ?? [null, null]}
          onChange={(range) => {
            onChange({ ...value, range });
          }}
        />
      )}
      <ActiveRange value={value} onChange={onChange} words={words} />
    </Space>
  );
}

/** The active range as a closable tag naming its field (AC2); also shown on the list itself
 * while the filters drawer is closed (QA10-P1-17). */
export function ActiveRange({
  value,
  onChange,
  words,
  testId = 'inc-time-active',
}: {
  value: TimeRangeValue | undefined;
  onChange: (value: TimeRangeValue | undefined) => void;
  words: ReportWords;
  testId?: string;
}) {
  const t = useLabel();
  const dates = useDateTime();
  if (value === undefined) return null;
  return (
    <Tag
      closable
      onClose={() => {
        onChange(undefined);
      }}
      data-testid={testId}
    >
      {value.preset === 'custom'
        ? t('incidents.time.active_range', {
            field: words.field(value.field),
            from: dates.format(value.range?.[0] ?? null) || '…',
            to: dates.format(value.range?.[1] ?? null) || '…',
          })
        : t('incidents.time.active', {
            field: words.field(value.field),
            range: t(`incidents.time.${value.preset}`),
          })}
    </Tag>
  );
}
