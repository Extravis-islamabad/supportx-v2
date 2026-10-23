import { Form, Input, Radio, Select, Space, Switch } from 'antd';
import type { ReactNode } from 'react';

import { useUnits } from '@supportx/api-client';
import { FormField, type UseFormReturn } from '@supportx/forms';
import { useAccess, useLabel } from '@supportx/ui';

import { AUDIENCES, BODY_MAX, SEVERITIES, TITLE_MAX, type Values } from './form';

/** ISO instant → the value of a local `datetime-local` input (the user's own clock time). */
function toLocalInput(value: string | null): string {
  if (value === null) return '';
  const date = new Date(value);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${String(date.getFullYear())}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Date and time in the browser's own picker (keyboard friendly, mirrors in RTL). */
function DateTime({
  value,
  onChange,
  id,
  testId,
}: {
  value: string | null;
  onChange: (value: string | null) => void;
  id: string;
  testId: string;
}) {
  return (
    <Input
      id={id}
      type="datetime-local"
      allowClear
      value={toLocalInput(value)}
      onChange={(event) => {
        const raw = event.target.value;
        onChange(raw === '' ? null : new Date(raw).toISOString());
      }}
      data-testid={testId}
      style={{ minWidth: 240 }}
    />
  );
}

/** The fields of an announcement (create and edit share it). */
export function AnnouncementFields({
  form,
  footer,
}: {
  form: UseFormReturn<Values>;
  footer: ReactNode;
}) {
  const t = useLabel();
  const { can } = useAccess();
  const audience = form.watch('audience');
  const sites = useUnits('sites', audience === 'sites' && can('sites.view'));
  const groups = useUnits('groups', audience === 'groups' && can('groups.view'));
  const units = audience === 'sites' ? sites : groups;
  return (
    <Form layout="vertical" component="div">
      <FormField
        control={form.control}
        name="title"
        labelKey="announcement.field.title"
        render={(field) => <Input {...field} maxLength={TITLE_MAX} data-testid="ann-title" />}
      />
      <FormField
        control={form.control}
        name="body"
        labelKey="announcement.field.body"
        helpKey="announcement.body_help"
        render={(field) => (
          <Input.TextArea {...field} rows={6} maxLength={BODY_MAX} data-testid="ann-body" />
        )}
      />
      <Space size="large" wrap align="start">
        <FormField
          control={form.control}
          name="severity"
          labelKey="announcement.field.severity"
          render={(field) => (
            <Select
              {...field}
              data-testid="ann-severity"
              style={{ minWidth: 160 }}
              options={SEVERITIES.map((value) => ({
                value,
                label: t(`announcement_severity.${value}`),
              }))}
            />
          )}
        />
        <FormField
          control={form.control}
          name="show_as_banner"
          labelKey="announcement.field.show_as_banner"
          render={({ value, onChange, id }) => (
            <Switch id={id} checked={value} onChange={onChange} data-testid="ann-banner" />
          )}
        />
      </Space>
      <FormField
        control={form.control}
        name="audience"
        labelKey="announcement.field.audience"
        render={({ value, onChange, id }) => (
          <Radio.Group
            id={id}
            value={value}
            onChange={(event) => {
              onChange(event.target.value);
            }}
            data-testid="ann-audience"
            options={AUDIENCES.map((option) => ({
              value: option,
              label: t(`announcement_audience.${option}`),
            }))}
          />
        )}
      />
      {audience !== 'everyone' && (
        <FormField
          control={form.control}
          name={audience === 'sites' ? 'site_ids' : 'group_ids'}
          labelKey={
            audience === 'sites' ? 'announcement.field.site_ids' : 'announcement.field.group_ids'
          }
          render={(field) => (
            <Select
              {...field}
              mode="multiple"
              loading={units.isPending && units.fetchStatus === 'fetching'}
              data-testid="ann-units"
              optionFilterProp="label"
              options={(units.data ?? []).map((unit) => ({ value: unit.id, label: unit.name }))}
            />
          )}
        />
      )}
      <Space size="large" wrap align="start">
        <FormField
          control={form.control}
          name="publish_from"
          labelKey="announcement.field.publish_from"
          helpKey="announcement.publish_from_help"
          render={({ value, onChange, id }) => (
            <DateTime value={value} onChange={onChange} id={id} testId="ann-from" />
          )}
        />
        <FormField
          control={form.control}
          name="publish_until"
          labelKey="announcement.field.publish_until"
          helpKey="announcement.publish_until_help"
          render={({ value, onChange, id }) => (
            <DateTime value={value} onChange={onChange} id={id} testId="ann-until" />
          )}
        />
      </Space>
      {footer}
    </Form>
  );
}
