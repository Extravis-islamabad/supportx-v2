import { Alert, Form, Input, Modal, Select } from 'antd';
import { useState, type ReactNode } from 'react';

import {
  useCustomFields,
  useStagedMove,
  useStagedRoleCandidates,
  useStagedSettings,
  type CustomField,
  type StageMove,
  type StagedPath,
} from '@supportx/api-client';
import {
  DateTimeField,
  FormProblem,
  RichTextField,
  lengthLimit,
  useAppearance,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

import { CustomFieldControl } from '../customFields/fields';
import { fieldName } from '../customFields/values';
import { labelled } from '../incidents/labels';
import { listValueName, statusName } from '../staged/labels';

const CUSTOM = 'custom.';
// A plan section a stage needs (`plan.backout`): written on the Plan tab, with its own version
// and history, never in the move's request. The dialog says so and waits for it.
const PLAN = 'plan.';
const isDate = (field: string) => /_(start|end)$/.test(field);
const filled = (v: unknown) =>
  v !== undefined && v !== null && v !== '' && !(Array.isArray(v) && v.length === 0);

/** What differs between staged types in the dialog: their fields, lists and people. */
interface StagedKind {
  entity: 'release' | 'change';
  /** People fields held through a role: the picker offers only those the role allows. */
  people: Record<string, string>;
  lists: ReadonlySet<string>;
  risks: readonly string[];
  riskLabel: string;
  rich: ReadonlySet<string>;
  limits: Record<string, number>;
}

const KINDS: Record<StagedPath, StagedKind> = {
  releases: {
    entity: 'release',
    people: { release_manager_id: 'release_manager', release_engineer_id: 'release_engineer' },
    lists: new Set(['release_type', 'release_reason']),
    risks: ['low', 'medium', 'high'],
    riskLabel: 'release_risk',
    rich: new Set(['release_notes']),
    limits: { build_ref: 200 },
  },
  changes: {
    entity: 'change',
    people: {},
    lists: new Set(['change_type', 'change_reason']),
    risks: ['low', 'medium', 'high', 'very_high'],
    riskLabel: 'risk_level',
    rich: new Set(),
    limits: {},
  },
};

/** Someone the role allows, searched as the role's picker does. */
function PersonField({
  path,
  role,
  value,
  onChange,
  testId,
  label,
}: {
  path: StagedPath;
  role: string;
  value: string | null;
  onChange: (v: string | null) => void;
  testId: string;
  label: string;
}) {
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(false);
  const candidates = useStagedRoleCandidates(path, role, search, open);
  return (
    <Select
      id={testId}
      showSearch
      allowClear
      filterOption={false}
      aria-label={label}
      value={value ?? undefined}
      onOpenChange={setOpen}
      onSearch={setSearch}
      loading={candidates.isFetching}
      data-testid={testId}
      options={(candidates.data ?? []).map((p) => ({ value: p.id, label: p.name }))}
      onChange={(v: string | undefined) => {
        onChange(v ?? null);
      }}
    />
  );
}

/** The control for one field a move still needs, as the record's own tabs edit it. */
function MoveField({
  path,
  field,
  label,
  custom,
  value,
  onChange,
}: {
  path: StagedPath;
  field: string;
  label: string;
  custom: CustomField | undefined;
  value: unknown;
  onChange: (v: unknown) => void;
}): ReactNode {
  const t = useLabel();
  const { locale } = useAppearance();
  const settings = useStagedSettings(path);
  const kind = KINDS[path];
  const testId = `move-field-${field}`;
  if (custom !== undefined) {
    return (
      <CustomFieldControl
        id={testId}
        field={custom}
        value={value}
        onChange={onChange}
        testId={testId}
        ariaLabel={label}
      />
    );
  }
  const text = typeof value === 'string' ? value : null;
  if (isDate(field)) {
    return <DateTimeField id={testId} value={text} onChange={onChange} testId={testId} />;
  }
  const role = kind.people[field];
  if (role !== undefined) {
    return (
      <PersonField
        path={path}
        role={role}
        value={text}
        onChange={onChange}
        testId={testId}
        label={label}
      />
    );
  }
  if (kind.lists.has(field) || field === 'risk') {
    const values = (settings.data?.own_lists?.[field] ?? []).filter((v) => !v.disabled);
    const options =
      field === 'risk'
        ? kind.risks.map((r) => ({ value: r, label: t(`${kind.riskLabel}.${r}`) }))
        : values.map((v) => ({
            value: v.code,
            label: listValueName(t, locale, field, v, v.code),
          }));
    return (
      <Select
        id={testId}
        aria-label={label}
        value={text ?? undefined}
        onChange={(v: string) => {
          onChange(v);
        }}
        data-testid={testId}
        options={options}
      />
    );
  }
  if (kind.rich.has(field)) {
    return <RichTextField label={label} value={text} onChange={onChange} testId={testId} />;
  }
  return (
    <Input
      id={testId}
      value={text ?? ''}
      count={lengthLimit(kind.limits[field] ?? 60)}
      onChange={(e) => {
        onChange(e.target.value);
      }}
      data-testid={testId}
    />
  );
}

/**
 * One move's dialog for any staged type (REQ-REL-016, -018; REQ-CHG-013): the reason when the
 * move asks for one, and only the fields it still needs (`missing`), saved in the same request.
 * A move into the closed status asks for the closure code, as the closing rules do. A plan
 * section it needs is written on the Plan tab first; the dialog names it and waits.
 */
export function StagedMoveDialog({
  path,
  recordId,
  version,
  move,
  onClose,
  notice,
}: {
  path: StagedPath;
  recordId: string;
  version: number;
  move: StageMove;
  onClose: () => void;
  /** What the type says before this move, e.g. who would approve a change's stage. */
  notice?: ReactNode;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const settings = useStagedSettings(path);
  const moving = useStagedMove(path);
  const problem = useFormProblem();
  const [reason, setReason] = useState('');
  const [fields, setFields] = useState<Record<string, unknown>>({});
  const [closureCode, setClosureCode] = useState<string>();
  const closing = move.to_status === 'closure_closed';
  const all = move.missing ?? [];
  const plans = all.filter((m) => m.field.startsWith(PLAN));
  const missing = all.filter((m) => !m.field.startsWith(PLAN));
  const wantsCustom = missing.some((m) => m.field.startsWith(CUSTOM));
  const customFields = useCustomFields(KINDS[path].entity, false, wantsCustom);
  const customByName = new Map<string, CustomField>(
    (customFields.data ?? []).map((f) => [`${CUSTOM}${f.key}`, f]),
  );
  const fieldLabel = (field: string) => {
    const found = customByName.get(field);
    if (found !== undefined) return fieldName(found, locale);
    // A custom field not loaded (yet, or removed) reads as unknown, never as its key (rule d).
    if (field.startsWith(CUSTOM)) {
      return customFields.isPending ? '' : t('custom_fields.unknown_field');
    }
    return t(`work_item.field.${field}`);
  };
  const needsReason = move.reason_mode === 'required';
  const ready =
    plans.length === 0 &&
    (!needsReason || reason.trim() !== '') &&
    missing.every((m) => filled(fields[m.field])) &&
    (!closing || closureCode !== undefined);
  const submit = () => {
    moving.mutate(
      {
        id: recordId,
        version,
        body: {
          to_status: move.to_status,
          reason_text: reason.trim() === '' ? null : reason.trim(),
          fields: missing.length > 0 ? fields : null,
          confirm_open_work: false,
          closure_code: closing ? (closureCode ?? null) : null,
        },
      },
      {
        onSuccess: onClose,
        onError: (error) => {
          problem.show(error);
        },
      },
    );
  };
  return (
    <Modal
      open
      title={t('staged.move.title', { status: statusName(t, move.to_status) })}
      okText={t('staged.move.confirm')}
      okButtonProps={{ disabled: !ready, loading: moving.isPending, 'data-testid': 'move-ok' }}
      onOk={submit}
      onCancel={onClose}
      destroyOnHidden
    >
      <Form layout="vertical" data-testid="move-dialog">
        {notice}
        {plans.map((m) => (
          <Alert
            key={m.field}
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            data-testid={`move-plan-${m.field.slice(PLAN.length)}`}
            message={t('staged.move.plan_needed', {
              section: t(`plan_section.${m.field.slice(PLAN.length)}`),
            })}
          />
        ))}
        {missing.map((m) => (
          <Form.Item
            key={m.field}
            label={fieldLabel(m.field)}
            htmlFor={`move-field-${m.field}`}
            help={t(`errors.field.${m.code}`)}
            required
          >
            <MoveField
              path={path}
              field={m.field}
              label={fieldLabel(m.field)}
              custom={customByName.get(m.field)}
              value={fields[m.field] ?? null}
              onChange={(value) => {
                setFields((now) => ({ ...now, [m.field]: value }));
              }}
            />
          </Form.Item>
        ))}
        {closing && (
          <Form.Item label={t('work_item.field.closure_code')} required htmlFor="move-closure-code">
            <Select
              id="move-closure-code"
              value={closureCode}
              onChange={setClosureCode}
              data-testid="move-closure-code"
              options={(settings.data?.closure_codes ?? [])
                .filter((c) => !c.disabled)
                .map((c) => ({
                  value: c.code,
                  label: labelled(c.labels, locale, () => t(`closure_code.${c.code}`)),
                }))}
            />
          </Form.Item>
        )}
        {move.reason_mode !== 'none' && (
          <Form.Item label={t('staged.move.reason')} required={needsReason} htmlFor="move-reason">
            <Input.TextArea
              id="move-reason"
              rows={3}
              count={lengthLimit(500)}
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
              }}
              data-testid="move-reason"
            />
          </Form.Item>
        )}
        <FormProblem problem={problem} />
      </Form>
    </Modal>
  );
}
