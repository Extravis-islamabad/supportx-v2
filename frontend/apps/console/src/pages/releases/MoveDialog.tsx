import { Form, Input, Modal, Select } from 'antd';
import { useState, type ReactNode } from 'react';

import {
  useCustomFields,
  useMoveRelease,
  useReleaseSettings,
  useRoleCandidates,
  type CustomField,
  type StageMove,
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
import { listValueName, statusName } from './labels';
import { RISKS, useOwnList } from './lists';

const CUSTOM = 'custom.';
const isDate = (field: string) => /_(start|end)$/.test(field);
// The release's people fields are its roles' holders: the picker offers only those the role
// allows (REQ-REL-024), never a UUID typed by hand.
const PEOPLE: Record<string, string> = {
  release_manager_id: 'release_manager',
  release_engineer_id: 'release_engineer',
};
const LISTS = new Set(['release_type', 'release_reason']);
const filled = (v: unknown) =>
  v !== undefined && v !== null && v !== '' && !(Array.isArray(v) && v.length === 0);

/** Someone the role allows, searched as the role's picker does. */
function PersonField({
  role,
  value,
  onChange,
  testId,
  label,
}: {
  role: string;
  value: string | null;
  onChange: (v: string | null) => void;
  testId: string;
  label: string;
}) {
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(false);
  const candidates = useRoleCandidates(role, search, open);
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

/** The control for one field a move still needs, as the release's own tabs edit it. */
function MoveField({
  field,
  label,
  custom,
  value,
  onChange,
}: {
  field: string;
  label: string;
  custom: CustomField | undefined;
  value: unknown;
  onChange: (v: unknown) => void;
}): ReactNode {
  const t = useLabel();
  const { locale } = useAppearance();
  const types = useOwnList('release_type');
  const reasons = useOwnList('release_reason');
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
  const role = PEOPLE[field];
  if (role !== undefined) {
    return (
      <PersonField role={role} value={text} onChange={onChange} testId={testId} label={label} />
    );
  }
  if (LISTS.has(field) || field === 'risk') {
    const options =
      field === 'risk'
        ? RISKS.map((r) => ({ value: r, label: t(`release_risk.${r}`) }))
        : (field === 'release_type' ? types : reasons).map((v) => ({
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
  if (field === 'release_notes') {
    return <RichTextField label={label} value={text} onChange={onChange} testId={testId} />;
  }
  return (
    <Input
      id={testId}
      value={text ?? ''}
      count={lengthLimit(field === 'build_ref' ? 200 : 60)}
      onChange={(e) => {
        onChange(e.target.value);
      }}
      data-testid={testId}
    />
  );
}

/**
 * One move's dialog (REQ-REL-016, -018): the reason when the move asks for one, and only the
 * fields it still needs (`missing`), saved in the same request. A move into the closed status
 * asks for the closure code, as the closing rules do (lane A's review of ADR-041).
 */
export function MoveDialog({
  releaseId,
  version,
  move,
  onClose,
}: {
  releaseId: string;
  version: number;
  move: StageMove;
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const settings = useReleaseSettings();
  const moving = useMoveRelease();
  const problem = useFormProblem();
  const [reason, setReason] = useState('');
  const [fields, setFields] = useState<Record<string, unknown>>({});
  const [closureCode, setClosureCode] = useState<string>();
  const closing = move.to_status === 'closure_closed';
  const missing = move.missing ?? [];
  const wantsCustom = missing.some((m) => m.field.startsWith(CUSTOM));
  const customFields = useCustomFields('release', false, wantsCustom);
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
    (!needsReason || reason.trim() !== '') &&
    missing.every((m) => filled(fields[m.field])) &&
    (!closing || closureCode !== undefined);
  const submit = () => {
    moving.mutate(
      {
        id: releaseId,
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
      title={t('releases.move.title', { status: statusName(t, move.to_status) })}
      okText={t('releases.move.confirm')}
      okButtonProps={{ disabled: !ready, loading: moving.isPending, 'data-testid': 'move-ok' }}
      onOk={submit}
      onCancel={onClose}
      destroyOnHidden
    >
      <Form layout="vertical" data-testid="move-dialog">
        {missing.map((m) => (
          <Form.Item
            key={m.field}
            label={fieldLabel(m.field)}
            htmlFor={`move-field-${m.field}`}
            help={t(`errors.field.${m.code}`)}
            required
          >
            <MoveField
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
          <Form.Item label={t('releases.move.reason')} required={needsReason} htmlFor="move-reason">
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
