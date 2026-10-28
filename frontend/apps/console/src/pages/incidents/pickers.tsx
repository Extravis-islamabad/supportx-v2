import { Select, Space, TreeSelect, Typography } from 'antd';
import { useMemo, useState } from 'react';

import {
  useIncidentAssignees,
  useIncidentCategories,
  useUnits,
  useStructure,
  useUsers,
} from '@supportx/api-client';
import { useJoinParts } from '@supportx/labels';
import { useAppearance, useLabel } from '@supportx/ui';

import { categoryLabel, duplicateNames } from './labels';

/**
 * A person with a second line: the email always, so two people with the same display name are
 * never confused (Area 15 lesson). `extra` adds e.g. the open load of a technician.
 */
export function PersonOption({
  name,
  email,
  extra,
}: {
  name: string;
  email: string | null;
  extra?: string;
}) {
  const joinParts = useJoinParts();
  return (
    <Space direction="vertical" size={0}>
      <Typography.Text>{name}</Typography.Text>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {joinParts([email, extra].filter((part): part is string => part != null && part !== ''))}
      </Typography.Text>
    </Space>
  );
}

/**
 * What a screen reader says for an option (QA C7): the name and email, never the ID that
 * Ant Design's hidden accessibility list would otherwise fall back to. Parts of one person,
 * not a list: each isolated in right-to-left languages, paused with the language's comma.
 */
function useSpoken(): (name: string, email: string | null, extra?: string) => string {
  const t = useLabel();
  const joinParts = useJoinParts();
  return (name, email, extra) =>
    joinParts(
      [name, email, extra].filter((part): part is string => part != null && part !== ''),
      t('list.separator'),
    );
}

interface PickerProps {
  id?: string;
  value: string | null;
  onChange: (value: string | null) => void;
  /** Shown when the current value is not in the loaded page (e.g. an existing record's person). */
  current?: { id: string; name: string; email: string | null } | null;
  disabled?: boolean;
  testId: string;
  ariaLabel: string;
}

/** Any user of the tenant, searched by name or email (GET /users?q=). */
export function UserPicker({
  id,
  value,
  onChange,
  current,
  disabled,
  testId,
  ariaLabel,
}: PickerProps) {
  const t = useLabel();
  const spoken = useSpoken();
  const [search, setSearch] = useState('');
  // Server search: half a name, a typo, Arabic or Urdu spellings, or the email (WP-027).
  const users = useUsers({ q: search, sort: 'display_name', limit: 20 });
  const rows = useMemo(() => users.data?.pages.flatMap((p) => p.items) ?? [], [users.data]);
  const options = rows.map((u) => {
    // Deactivated people stay findable (old records), marked as such (WP-021).
    const extra = u.status === 'disabled' ? t('people.deactivated_marker') : undefined;
    return {
      value: u.id,
      name: u.display_name,
      'aria-label': spoken(u.display_name, u.email, extra),
      label: <PersonOption name={u.display_name} email={u.email} extra={extra} />,
    };
  });
  if (current != null && !options.some((o) => o.value === current.id)) {
    options.unshift({
      value: current.id,
      name: current.name,
      'aria-label': spoken(current.name, current.email),
      label: <PersonOption name={current.name} email={current.email} />,
    });
  }
  return (
    <Select
      id={id}
      showSearch
      allowClear
      filterOption={false}
      value={value}
      disabled={disabled}
      aria-label={ariaLabel}
      placeholder={t('incidents.pick_person')}
      onSearch={setSearch}
      onChange={(next: string | undefined) => {
        onChange(next ?? null);
      }}
      options={options}
      optionLabelProp="name"
      loading={users.isFetching}
      notFoundContent={t('incidents.nobody_found')}
      data-testid={testId}
      style={{ width: '100%' }}
    />
  );
}

export function GroupPicker({
  id,
  value,
  onChange,
  disabled,
  testId,
  ariaLabel,
}: Omit<PickerProps, 'current'>) {
  const t = useLabel();
  const groups = useUnits('groups');
  return (
    <Select
      id={id}
      allowClear
      showSearch
      optionFilterProp="label"
      value={value}
      disabled={disabled}
      aria-label={ariaLabel}
      placeholder={t('incidents.no_group')}
      onChange={(next: string | undefined) => {
        onChange(next ?? null);
      }}
      options={(groups.data ?? []).map((g) => ({
        value: g.id,
        label: g.name,
        'aria-label': g.name,
      }))}
      data-testid={testId}
      style={{ width: '100%' }}
    />
  );
}

export function SitePicker({
  id,
  value,
  onChange,
  disabled,
  testId,
  ariaLabel,
}: Omit<PickerProps, 'current'>) {
  const t = useLabel();
  const sites = useUnits('sites');
  return (
    <Select
      id={id}
      allowClear
      showSearch
      optionFilterProp="label"
      value={value}
      disabled={disabled}
      aria-label={ariaLabel}
      placeholder={t('incidents.no_site')}
      onChange={(next: string | undefined) => {
        onChange(next ?? null);
      }}
      options={(sites.data ?? []).map((s) => ({
        value: s.id,
        label: s.name,
        'aria-label': s.name,
      }))}
      data-testid={testId}
      style={{ width: '100%' }}
    />
  );
}

/** Departments (WP-021): inactive ones are offered only when already chosen. */
export function DepartmentPicker({
  id,
  value,
  onChange,
  disabled,
  testId,
  ariaLabel,
}: Omit<PickerProps, 'current'>) {
  const t = useLabel();
  const departments = useStructure('departments');
  return (
    <Select
      id={id}
      allowClear
      showSearch
      optionFilterProp="label"
      value={value}
      disabled={disabled}
      aria-label={ariaLabel}
      placeholder={t('incidents.no_department')}
      onChange={(next: string | undefined) => {
        onChange(next ?? null);
      }}
      options={(departments.data ?? [])
        .filter((d) => !d.disabled || d.id === value)
        .map((d) => ({ value: d.id, label: d.name, 'aria-label': d.name }))}
      data-testid={testId}
      style={{ width: '100%' }}
    />
  );
}

/**
 * Technicians of the chosen group only (REQ-INC-053), with email and open load as the second line;
 * the same name twice is always told apart by the email.
 */
export function TechnicianPicker({
  id,
  groupId,
  value,
  onChange,
  current,
  disabled,
  testId,
  ariaLabel,
}: PickerProps & { groupId: string | null }) {
  const t = useLabel();
  const spoken = useSpoken();
  const [search, setSearch] = useState('');
  const found = useIncidentAssignees(groupId, search, disabled !== true);
  const rows = found.data ?? [];
  const twice = duplicateNames(rows.map((r) => r.display_name));
  const options = rows.map((r) => ({
    value: r.id,
    name: twice.has(r.display_name.trim().toLocaleLowerCase())
      ? `${r.display_name} (${r.email})`
      : r.display_name,
    'aria-label': spoken(r.display_name, r.email),
    label: (
      <PersonOption
        name={r.display_name}
        email={r.email}
        extra={t('incidents.open_load', { count: r.open_count })}
      />
    ),
  }));
  if (current != null && !options.some((o) => o.value === current.id)) {
    options.unshift({
      value: current.id,
      name: current.name,
      'aria-label': spoken(current.name, current.email),
      label: <PersonOption name={current.name} email={current.email} />,
    });
  }
  return (
    <Select
      id={id}
      showSearch
      allowClear
      filterOption={false}
      value={value}
      disabled={disabled}
      aria-label={ariaLabel}
      placeholder={t('incidents.no_technician')}
      onSearch={setSearch}
      onChange={(next: string | undefined) => {
        onChange(next ?? null);
      }}
      options={options}
      optionLabelProp="name"
      loading={found.isFetching}
      notFoundContent={t('incidents.nobody_found')}
      data-testid={testId}
      style={{ width: '100%' }}
    />
  );
}

/** Category › subcategory › item; disabled nodes stay visible but cannot be chosen. */
export function CategoryPicker({
  id,
  value,
  onChange,
  disabled,
  testId,
  ariaLabel,
}: Omit<PickerProps, 'current'>) {
  const t = useLabel();
  const { locale } = useAppearance();
  const categories = useIncidentCategories();
  const tree = useMemo(() => {
    const nodes = categories.data ?? [];
    interface Node {
      value: string;
      title: string;
      disabled: boolean;
      children: Node[];
    }
    const byParent = new Map<string | null, Node[]>();
    for (const n of nodes) {
      const node: Node = {
        value: n.id,
        title: categoryLabel(t, n, locale),
        disabled: n.disabled,
        children: [],
      };
      const list = byParent.get(n.parent_id) ?? [];
      list.push(node);
      byParent.set(n.parent_id, list);
    }
    const attach = (list: Node[]): Node[] =>
      list.map((node) => ({ ...node, children: attach(byParent.get(node.value) ?? []) }));
    return attach(byParent.get(null) ?? []);
  }, [categories.data, t, locale]);
  return (
    <TreeSelect
      id={id}
      allowClear
      showSearch
      treeNodeFilterProp="title"
      value={value ?? undefined}
      disabled={disabled}
      aria-label={ariaLabel}
      placeholder={t('incidents.no_category')}
      onChange={(next: string | undefined) => {
        onChange(next ?? null);
      }}
      treeData={tree}
      data-testid={testId}
      style={{ width: '100%' }}
    />
  );
}
