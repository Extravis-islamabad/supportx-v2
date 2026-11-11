import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Card, Flex, Input, InputNumber, Select, Space, Switch, Typography } from 'antd';

import { useUnits, type SlaLevel } from '@supportx/api-client';
import { lengthLimit, useLabel } from '@supportx/ui';

import { UserPicker } from '../../incidents/pickers';
import { levelWhen } from './levels';

type Kind = SlaLevel['kind'];
type Recipient = NonNullable<SlaLevel['recipients']>[number];
type Action = NonNullable<SlaLevel['actions']>[number];

const KINDS: Kind[] = ['first_response', 'resolution'];
const MAX_LEVELS = 8; // per target (domain/escalation.py)
const NOTE_MAX = 2000;
const RELATIVES: Recipient['kind'][] = [
  'assignee',
  'group_head',
  'assignee_manager',
  'requester_manager',
  'department_head',
];

/** Recipients as select values: a relative's kind, or "group:<id>" for a support group. */
function toValues(who: Recipient[] | undefined): string[] {
  return (who ?? []).map((r) => (r.kind === 'group' ? `group:${r.id ?? ''}` : r.kind));
}

function fromValues(values: string[]): Recipient[] {
  return values.map((v) =>
    v.startsWith('group:')
      ? { kind: 'group', id: v.slice('group:'.length) }
      : { kind: v as Recipient['kind'], id: null },
  );
}

/**
 * A policy's escalation levels (REQ-SLA-022..024): per target, when each runs (business time
 * before or after the due time or the warning point), whom it tells (relatives of the record or
 * support groups, with a fallback when a relative is not set), and what it does.
 */
export function LevelsEditor({
  levels,
  onChange,
  disabled,
}: {
  levels: SlaLevel[];
  onChange: (levels: SlaLevel[]) => void;
  disabled?: boolean;
}) {
  const t = useLabel();
  const groups = useUnits('groups');
  // The support groups a person is in (D-154 rules: the record moves there with them).
  const groupsOf = (person: string): string[] =>
    (groups.data ?? []).filter((g) => g.member_ids.includes(person)).map((g) => g.id);
  const groupName = (id: string) => (groups.data ?? []).find((g) => g.id === id)?.name ?? '';
  const groupOptions = (groups.data ?? []).map((g) => ({ value: `group:${g.id}`, label: g.name }));
  const whoOptions = [
    ...RELATIVES.map((kind) => ({ value: kind, label: t(`sla_recipient_kind.${kind}`) })),
    ...groupOptions,
  ];

  const change = (index: number, patch: Partial<SlaLevel>) => {
    onChange(levels.map((level, at) => (at === index ? { ...level, ...patch } : level)));
  };
  const action = (level: SlaLevel, kind: Action['kind']) =>
    (level.actions ?? []).find((a) => a.kind === kind);
  const setAction = (index: number, kind: Action['kind'], value: Action | null) => {
    const level = levels[index];
    if (level === undefined) return;
    const others = (level.actions ?? []).filter((a) => a.kind !== kind);
    change(index, { actions: value === null ? others : [...others, value] });
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} data-testid="sla-levels">
      <Typography.Text type="secondary">{t('sla.levels.explain')}</Typography.Text>
      {KINDS.map((kind) => {
        const mine = levels
          .map((level, index) => ({ level, index }))
          .filter((x) => x.level.kind === kind);
        return (
          <Space key={kind} direction="vertical" style={{ width: '100%' }}>
            <Typography.Text strong>{t(`sla_target_kind.${kind}`)}</Typography.Text>
            {mine.map(({ level, index }, position) => {
              const minutes = Math.round(Math.abs(level.offset_seconds) / 60);
              const before = level.offset_seconds < 0;
              const reassign = action(level, 'reassign_group');
              const person = action(level, 'reassign_person');
              const theirs = person?.target_id ? groupsOf(person.target_id) : [];
              const note = action(level, 'add_note');
              return (
                <Card
                  key={index}
                  size="small"
                  data-testid={`sla-level-${kind}-${String(position + 1)}`}
                  title={`${t('incidents.sla.level', { position: position + 1 })} · ${levelWhen(t, {
                    anchor: level.anchor,
                    offset_seconds: level.offset_seconds,
                  })}`}
                  extra={
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      disabled={disabled}
                      aria-label={t('sla.levels.remove')}
                      onClick={() => {
                        onChange(levels.filter((_, at) => at !== index));
                      }}
                      data-testid={`sla-level-remove-${kind}-${String(position + 1)}`}
                    />
                  }
                >
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Flex gap={8} wrap align="center">
                      <InputNumber
                        min={0}
                        max={30 * 24 * 60}
                        value={minutes}
                        disabled={disabled}
                        suffix={t('sla.levels.minutes')}
                        aria-label={t('sla.levels.offset')}
                        onChange={(value) => {
                          const amount = (value ?? 0) * 60;
                          change(index, { offset_seconds: before ? -amount : amount });
                        }}
                        data-testid={`sla-level-offset-${kind}-${String(position + 1)}`}
                      />
                      <Select
                        value={before ? 'before' : 'after'}
                        disabled={disabled}
                        aria-label={t('sla.levels.direction')}
                        style={{ minWidth: 120 }}
                        options={[
                          { value: 'before', label: t('sla.levels.before') },
                          { value: 'after', label: t('sla.levels.after') },
                        ]}
                        onChange={(value) => {
                          change(index, {
                            offset_seconds: (value === 'before' ? -1 : 1) * minutes * 60,
                          });
                        }}
                      />
                      <Select
                        value={level.anchor}
                        disabled={disabled}
                        aria-label={t('sla.levels.anchor')}
                        style={{ minWidth: 160 }}
                        options={(['due', 'warning'] as const).map((a) => ({
                          value: a,
                          label: t(`sla_level_anchor.${a}`),
                        }))}
                        onChange={(value) => {
                          change(index, { anchor: value });
                        }}
                      />
                    </Flex>
                    <Flex gap={8} align="center">
                      <Switch
                        checked={level.notify}
                        disabled={disabled}
                        onChange={(checked) => {
                          change(index, { notify: checked });
                        }}
                        aria-label={t('sla.levels.notify')}
                      />
                      <Typography.Text>{t('sla.levels.notify')}</Typography.Text>
                    </Flex>
                    {level.notify && (
                      <>
                        <Select
                          mode="multiple"
                          value={toValues(level.recipients)}
                          disabled={disabled}
                          placeholder={t('sla.levels.recipients')}
                          aria-label={t('sla.levels.recipients')}
                          options={whoOptions}
                          onChange={(values) => {
                            change(index, { recipients: fromValues(values) });
                          }}
                          data-testid={`sla-level-recipients-${kind}-${String(position + 1)}`}
                        />
                        <Select
                          mode="multiple"
                          value={toValues(level.fallback)}
                          disabled={disabled}
                          placeholder={t('sla.levels.fallback')}
                          aria-label={t('sla.levels.fallback')}
                          options={whoOptions}
                          onChange={(values) => {
                            change(index, { fallback: fromValues(values) });
                          }}
                        />
                      </>
                    )}
                    <Select
                      allowClear
                      value={reassign?.target_id ?? undefined}
                      disabled={disabled}
                      placeholder={t('sla_action_kind.reassign_group')}
                      aria-label={t('sla_action_kind.reassign_group')}
                      options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))}
                      onChange={(value: string | undefined) => {
                        setAction(
                          index,
                          'reassign_group',
                          value ? { kind: 'reassign_group', target_id: value } : null,
                        );
                      }}
                    />
                    {/* D-154 rules: a person comes with the group the record moves to with them,
                        chosen here when they are in several, filled in when in one. */}
                    <UserPicker
                      value={person?.target_id ?? null}
                      disabled={disabled}
                      ariaLabel={t('sla_action_kind.reassign_person')}
                      testId={`sla-level-person-${String(index)}`}
                      onChange={(value) => {
                        const groupsOfThem = value === null ? [] : groupsOf(value);
                        setAction(
                          index,
                          'reassign_person',
                          value === null
                            ? null
                            : {
                                kind: 'reassign_person',
                                target_id: value,
                                group_id: groupsOfThem.length === 1 ? groupsOfThem[0] : null,
                              },
                        );
                      }}
                    />
                    {person?.target_id && theirs.length > 1 && (
                      <Select
                        value={person.group_id ?? undefined}
                        disabled={disabled}
                        status={person.group_id ? undefined : 'error'}
                        placeholder={t('sla.levels.person_group')}
                        aria-label={t('sla.levels.person_group')}
                        options={theirs.map((id) => ({
                          value: id,
                          label: groupName(id),
                        }))}
                        onChange={(value: string) => {
                          setAction(index, 'reassign_person', { ...person, group_id: value });
                        }}
                        data-testid={`sla-level-person-group-${String(index)}`}
                      />
                    )}
                    {person?.target_id && theirs.length > 1 && !person.group_id && (
                      <Typography.Text type="danger" role="alert">
                        {t('errors.field.reassign_group_required')}
                      </Typography.Text>
                    )}
                    {person?.target_id && theirs.length === 0 && groups.data !== undefined && (
                      <Typography.Text type="danger" role="alert">
                        {t('errors.field.person_in_no_group')}
                      </Typography.Text>
                    )}
                    <Flex gap={8} align="center">
                      <Switch
                        checked={action(level, 'raise_priority') !== undefined}
                        disabled={disabled}
                        aria-label={t('sla_action_kind.raise_priority')}
                        onChange={(checked) => {
                          setAction(
                            index,
                            'raise_priority',
                            checked ? { kind: 'raise_priority' } : null,
                          );
                        }}
                      />
                      <Typography.Text>{t('sla_action_kind.raise_priority')}</Typography.Text>
                    </Flex>
                    <Input.TextArea
                      value={note?.text ?? ''}
                      disabled={disabled}
                      placeholder={t('sla_action_kind.add_note')}
                      aria-label={t('sla_action_kind.add_note')}
                      count={lengthLimit(NOTE_MAX)}
                      autoSize={{ minRows: 1 }}
                      onChange={(event) => {
                        const text = event.target.value;
                        setAction(index, 'add_note', text ? { kind: 'add_note', text } : null);
                      }}
                    />
                  </Space>
                </Card>
              );
            })}
            <Button
              icon={<PlusOutlined />}
              disabled={(disabled ?? false) || mine.length >= MAX_LEVELS}
              onClick={() => {
                onChange([
                  ...levels,
                  {
                    kind,
                    anchor: 'due',
                    offset_seconds: 0,
                    recipients: [{ kind: 'assignee', id: null }],
                    fallback: [],
                    actions: [],
                    notify: true,
                  },
                ]);
              }}
              data-testid={`sla-level-add-${kind}`}
            >
              {t('sla.levels.add')}
            </Button>
          </Space>
        );
      })}
    </Space>
  );
}
