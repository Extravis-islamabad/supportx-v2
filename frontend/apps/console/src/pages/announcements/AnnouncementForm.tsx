import { Flex, Form, Input, Radio, Select, Spin, Switch } from 'antd';
import { useDeferredValue, useState, type ReactNode } from 'react';

import { useAnnouncementOwnerCandidates, useUnits } from '@supportx/api-client';
import { FormField, type UseFormReturn } from '@supportx/forms';
import {
  DateTimeField,
  FIELD_WIDTH,
  FieldRow,
  FormSection,
  SPACE,
  TimeZoneNote,
  useAccess,
  useLabel,
  lengthLimit,
} from '@supportx/ui';

import { AUDIENCES, BODY_MAX, SEVERITIES, TITLE_MAX, type Values } from './form';

/**
 * Who owns it: a searchable list of only the people who may manage announcements (the API
 * refuses anyone else). The current owner is always named, even outside the first page.
 */
function OwnerPicker({
  value,
  onChange,
  id,
}: {
  value: string | null;
  onChange: (value: string | null) => void;
  id: string;
}) {
  const t = useLabel();
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(false);
  const typed = useDeferredValue(search.trim());
  const candidates = useAnnouncementOwnerCandidates(typed, value, open || value !== null);
  return (
    <Select
      id={id}
      showSearch
      value={value ?? undefined}
      placeholder={t('announcement.owner_search')}
      filterOption={false}
      onSearch={setSearch}
      onOpenChange={(visible) => {
        setOpen(visible);
        // Reopening asks again: someone may have gained or lost the permission meanwhile.
        if (visible) void candidates.refetch();
        else setSearch('');
      }}
      onChange={(next: string) => {
        onChange(next);
      }}
      loading={candidates.isFetching}
      notFoundContent={candidates.isFetching ? <Spin size="small" /> : undefined}
      options={(candidates.data ?? []).map((user) => ({
        value: user.id,
        label: user.display_name,
      }))}
      data-testid="ann-owner"
      style={{ width: FIELD_WIDTH.medium, maxWidth: '100%' }}
    />
  );
}

/**
 * The fields of an announcement (create and edit share it), in template B's sections (D-147):
 * the message, who sees it, and when and whose. `footer` is the edit page's own bar; the new
 * page puts its actions in FormPage's sticky footer instead.
 */
export function AnnouncementFields({
  form,
  footer,
}: {
  form: UseFormReturn<Values>;
  footer?: ReactNode;
}) {
  const t = useLabel();
  const { can } = useAccess();
  const audience = form.watch('audience');
  const sites = useUnits('sites', audience === 'sites' && can('sites.view'));
  const groups = useUnits('groups', audience === 'groups' && can('groups.view'));
  const units = audience === 'sites' ? sites : groups;
  return (
    <Form layout="vertical" component="div">
      <Flex vertical gap={SPACE.md}>
        <FormSection title={t('announcement.section.message')} testId="ann-section-message">
          <FormField
            control={form.control}
            name="title"
            labelKey="announcement.field.title"
            render={(field) => (
              <Input {...field} count={lengthLimit(TITLE_MAX)} data-testid="ann-title" />
            )}
          />
          <FormField
            control={form.control}
            name="body"
            labelKey="announcement.field.body"
            helpKey="announcement.body_help"
            render={(field) => (
              <Input.TextArea
                {...field}
                rows={6}
                count={lengthLimit(BODY_MAX)}
                data-testid="ann-body"
              />
            )}
          />
          <FieldRow>
            <FormField
              control={form.control}
              name="severity"
              labelKey="announcement.field.severity"
              render={(field) => (
                <Select
                  {...field}
                  data-testid="ann-severity"
                  style={{ width: FIELD_WIDTH.short, maxWidth: '100%' }}
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
          </FieldRow>
        </FormSection>
        <FormSection title={t('announcement.section.audience')} testId="ann-section-audience">
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
          {(audience === 'sites' || audience === 'groups') && (
            <FormField
              control={form.control}
              name={audience === 'sites' ? 'site_ids' : 'group_ids'}
              labelKey={
                audience === 'sites'
                  ? 'announcement.field.site_ids'
                  : 'announcement.field.group_ids'
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
        </FormSection>
        <FormSection title={t('announcement.section.schedule')} testId="ann-section-schedule">
          <FormField
            control={form.control}
            name="owner_id"
            labelKey="announcement.field.owner_id"
            helpKey="announcement.owner_help"
            render={({ value, onChange, id }) => (
              <OwnerPicker value={value} onChange={onChange} id={id} />
            )}
          />
          <FieldRow>
            <FormField
              control={form.control}
              name="publish_from"
              labelKey="announcement.field.publish_from"
              helpKey="announcement.publish_from_help"
              render={({ value, onChange, id }) => (
                <DateTimeField
                  value={value}
                  onChange={onChange}
                  id={id}
                  testId="ann-from"
                  hideZone
                />
              )}
            />
            <FormField
              control={form.control}
              name="publish_until"
              labelKey="announcement.field.publish_until"
              helpKey="announcement.publish_until_help"
              render={({ value, onChange, id }) => (
                <DateTimeField
                  value={value}
                  onChange={onChange}
                  id={id}
                  testId="ann-until"
                  hideZone
                />
              )}
            />
          </FieldRow>
          {/* One time-zone note for both times (D-147), not one under each field. It sits below
              the fields' own help, never pulled up over it (QA10-P4-12). */}
          <div style={{ marginBottom: SPACE.sm }}>
            <TimeZoneNote />
          </div>
        </FormSection>
        {footer}
      </Flex>
    </Form>
  );
}
