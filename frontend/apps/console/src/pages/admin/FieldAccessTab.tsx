import { TeamOutlined } from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Flex,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Table,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';

import {
  ApiError,
  FIELD_RULE_MODES,
  fieldAccessKeys,
  useEffectiveFieldAccess,
  useFieldCatalogue,
  useFieldRules,
  useSetFieldRule,
  type FieldAccessRule,
  type FieldMode,
  type RuleableField,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { refreshList, useListChannel } from '@supportx/realtime';
import {
  CellText,
  FormProblem,
  loadedEmpty,
  useAccess,
  useAppearance,
  useFormProblem,
  useLabel,
  useLicence,
  useMinWidth,
} from '@supportx/ui';
import { useQueryClient } from '@tanstack/react-query';

import { fieldName } from '../customFields/values';

// ADR-047 slice c: who in a role sees which field how. Each row saves at once (no footer Save on
// this tab: lane C's review), a stale row reloads with a notice, the server decides everything.

const NONE = '';
/** The effective view's groups, from the clearest. */
const EFFECTIVE_ORDER = ['clear', 'read_only', 'masked', 'hidden'] as const;

export function FieldAccessTab({ roleId }: { roleId: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const { can } = useAccess();
  const licence = useLicence();
  const queryClient = useQueryClient();
  const catalogue = useFieldCatalogue();
  const rules = useFieldRules(roleId);
  const setRule = useSetFieldRule(roleId);
  const problem = useFormProblem();
  const [recordType, setRecordType] = useState<string>();
  const [search, setSearch] = useState('');
  const [saving, setSaving] = useState<string | null>(null);
  const [stale, setStale] = useState<string | null>(null);
  const [whoSees, setWhoSees] = useState<RuleableField>();
  // Live: a rule set elsewhere (another admin, another tab) shows here at once.
  useListChannel('field_access', () => {
    refreshList(queryClient, fieldAccessKeys.all);
  });

  const types = catalogue.data ?? [];
  const current = recordType ?? types[0]?.record_type;
  const fields = types.find((c) => c.record_type === current)?.fields ?? [];
  const label = (f: RuleableField) =>
    f.custom ? fieldName({ labels: f.labels }, locale) : t(f.label_key ?? f.key);
  const query = search.trim().toLocaleLowerCase();
  const shown = fields.filter((f) => query === '' || label(f).toLocaleLowerCase().includes(query));
  const byField = useMemo(
    () =>
      new Map(
        (rules.data ?? [])
          .filter((r) => r.record_type === current)
          .map((r): [string, FieldAccessRule] => [r.field, r]),
      ),
    [rules.data, current],
  );
  const manage = can('roles.manage');
  const wide = useMinWidth(768);
  // A lapsed plan keeps every rule applied; rules can only be viewed and removed (ADR-047 §13).
  // A reflection of the plan: the server refuses anything else anyway.
  const licensed = licence.has('field_access');

  const change = (field: RuleableField, value: string) => {
    if (current === undefined) return;
    problem.clear();
    setStale(null);
    setSaving(field.key);
    setRule.mutate(
      {
        recordType: current,
        field: field.key,
        mode: value === NONE ? null : (value as FieldMode),
        current: byField.get(field.key),
        key: crypto.randomUUID(),
      },
      {
        onSuccess: () => {
          void message.success(t('field_access.saved'));
        },
        onError: (error) => {
          if (error instanceof ApiError && error.isConflict) setStale(field.key);
          else problem.show(error);
        },
        onSettled: () => {
          setSaving(null);
        },
      },
    );
  };

  if (catalogue.isPending || rules.isPending) return <Spin />;
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Typography.Text type="secondary" data-testid="field-access-help">
        {t('field_access.help')}
      </Typography.Text>
      <Typography.Text type="secondary">{t('field_access.clearest_wins')}</Typography.Text>
      {!licensed && (
        <Alert type="info" showIcon message={t('field_access.unlicensed')} role="status" />
      )}
      <Flex gap={12} wrap align="center">
        <Select
          aria-label={t('field_access.record_type')}
          value={current}
          onChange={(value: string) => {
            setRecordType(value);
            setStale(null);
          }}
          options={types.map((c) => ({
            value: c.record_type,
            label: t(`work_item_type.${c.record_type}`),
          }))}
          style={{ minWidth: 180 }}
          data-testid="field-access-type"
        />
        <Input.Search
          allowClear
          aria-label={t('field_access.search')}
          placeholder={t('field_access.search')}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
          style={{ maxWidth: 280 }}
          data-testid="field-access-search"
        />
      </Flex>
      {stale !== null && (
        <Alert
          type="warning"
          showIcon
          role="status"
          message={t('field_access.stale')}
          data-testid="field-access-stale"
        />
      )}
      <FormProblem problem={problem} />
      <Table<RuleableField>
        size="small"
        rowKey="key"
        pagination={false}
        dataSource={shown}
        tableLayout="fixed"
        locale={{
          emptyText: loadedEmpty(
            false,
            query === '' ? t('field_access.empty') : t('field_access.no_match'),
          ),
        }}
        data-testid="field-access-table"
        columns={[
          {
            key: 'field',
            title: t('field_access.column.field'),
            render: (_, f) => <CellText>{label(f)}</CellText>,
          },
          {
            key: 'mode',
            title: t('field_access.column.mode'),
            width: 170,
            render: (_, f) => {
              const rule = byField.get(f.key);
              const mode = rule?.mode ?? NONE;
              // Without the plan, only "No rule" may be chosen (removing stays allowed).
              const options = [
                { value: NONE, label: t('field_access.no_rule') },
                ...FIELD_RULE_MODES.map((m) => ({
                  value: m,
                  label: t(`field_mode.${m}`),
                  disabled: !licensed && m !== mode,
                })),
              ];
              return (
                <Select
                  aria-label={t('field_access.mode_for', { field: label(f) })}
                  value={mode}
                  options={options}
                  disabled={!manage || saving !== null || (!licensed && mode === NONE)}
                  loading={saving === f.key}
                  status={stale === f.key ? 'warning' : undefined}
                  onChange={(value: string) => {
                    change(f, value);
                  }}
                  style={{ width: 150 }}
                  data-testid={`field-access-mode-${f.key}`}
                />
              );
            },
          },
          {
            key: 'who',
            title: <span className="sx-visually-hidden">{t('field_access.who')}</span>,
            // Below md an icon (its name says which field), so the field's name keeps the room.
            width: wide ? 130 : 44,
            render: (_, f) => (
              <Button
                type="link"
                size="small"
                style={{ paddingInline: 0 }}
                icon={wide ? undefined : <TeamOutlined aria-hidden />}
                aria-label={wide ? undefined : t('field_access.who_for', { field: label(f) })}
                onClick={() => {
                  setWhoSees(f);
                }}
                data-testid={`field-access-who-${f.key}`}
              >
                {wide ? t('field_access.who') : null}
              </Button>
            ),
          },
        ]}
      />
      {current !== undefined && (
        <WhoSees
          recordType={current}
          field={whoSees}
          label={whoSees === undefined ? '' : label(whoSees)}
          onClose={() => {
            setWhoSees(undefined);
          }}
        />
      )}
    </Space>
  );
}

/** Who sees one field how, across every role (a Modal: never a drawer on the drawer). */
function WhoSees({
  recordType,
  field,
  label,
  onClose,
}: {
  recordType: string;
  field: RuleableField | undefined;
  label: string;
  onClose: () => void;
}) {
  const t = useLabel();
  const listFormat = useListFormat();
  const effective = useEffectiveFieldAccess(recordType, field?.key);
  const data = effective.data;
  return (
    <Modal
      open={field !== undefined}
      onCancel={onClose}
      footer={null}
      width={560}
      destroyOnHidden
      title={t('field_access.who_title', { field: label })}
    >
      {data === undefined ? (
        <Spin />
      ) : (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Typography.Text type="secondary">{t('field_access.clearest_wins')}</Typography.Text>
          {EFFECTIVE_ORDER.map((mode) => {
            const people = data.people[mode] ?? [];
            const count = data.counts[mode] ?? 0;
            return (
              <div key={mode} data-testid={`field-access-effective-${mode}`}>
                <Typography.Text strong>
                  {t(`field_access.effective.${mode}`, { n: count })}
                </Typography.Text>
                <div>
                  {count === 0 ? (
                    <Typography.Text type="secondary">{t('field_access.nobody')}</Typography.Text>
                  ) : (
                    <Typography.Text>
                      {/* Each name isolated in its own direction; the joiners follow the page. */}
                      {listFormat(
                        [
                          ...people.map((p) => p.name),
                          ...(count > people.length
                            ? [t('field_access.more', { n: count - people.length })]
                            : []),
                        ],
                        // "A, B and 3 more": the language's own "and" (ur's unit style mixes
                        // in a Latin comma); formatList isolates each name itself.
                        'conjunction',
                      )}
                    </Typography.Text>
                  )}
                </div>
              </div>
            );
          })}
        </Space>
      )}
    </Modal>
  );
}
