import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import {
  App,
  Button,
  Flex,
  Form,
  Input,
  List,
  Select,
  Space,
  Switch,
  Table,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';

import {
  useChangeBoards,
  useChangeTemplates,
  useCreateChangeBoard,
  useRemoveChangeBoard,
  useStagedSettings,
  useUnits,
  useUpdateChangeBoard,
  useUser,
  type ChangeBoard,
  type ChangeBoardInput,
  type RiskLevel,
} from '@supportx/api-client';
import {
  EditDrawer,
  EmptyText,
  FormProblem,
  RowActions,
  SettingsPageHeader,
  ToneTag,
  TranslatedField,
  WriteButton,
  reportError,
  useAccess,
  useAppearance,
  useFormProblem,
  useLabel,
  type TranslatedValue,
} from '@supportx/ui';

import { useTenantChannel } from '@supportx/realtime';

import { GroupPicker, UserPicker } from '../../incidents/pickers';
import { boardName, RISKS, templateName } from '../../changes/labels';
import { listValueName } from '../../staged/labels';

const RULES = ['any', 'all', 'majority', 'majority_with_chair'] as const;
type Rule = (typeof RULES)[number];
interface Member {
  user_id: string | null;
  group_id: string | null;
  optional: boolean;
}
interface Draft {
  labels: TranslatedValue;
  description: string;
  rule: Rule;
  chair_id: string | null;
  members: Member[];
  change_types: string[];
  risk_levels: string[];
  site_ids: string[];
  template_ids: string[];
}

const fromBoard = (b: ChangeBoard | undefined): Draft => ({
  // A seeded board has no labels of its own: its name starts the English one.
  labels: b?.labels ?? (b ? { en: b.name } : {}),
  description: b?.description ?? '',
  rule: b?.rule ?? 'any',
  chair_id: b?.chair_id ?? null,
  members: (b?.members ?? []).map((m) => ({ ...m, optional: m.optional })),
  change_types: b?.mapping?.change_types ?? [],
  risk_levels: b?.mapping?.risk_levels ?? [],
  site_ids: b?.mapping?.site_ids ?? [],
  template_ids: b?.mapping?.template_ids ?? [],
});

/** A person just added (not saved yet): their name from the people list, as the picker had it. */
function PersonName({ id, known }: { id: string; known: string | undefined }) {
  const t = useLabel();
  const user = useUser(known === undefined ? id : undefined);
  return <span>{known ?? user.data?.display_name ?? t('changes.boards.someone')}</span>;
}

/** One board's editor: its name, rule and chair, its members, and which changes it reviews. */
function BoardEditor({ board, onClose }: { board: ChangeBoard | undefined; onClose: () => void }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const settings = useStagedSettings('changes');
  const templates = useChangeTemplates();
  const sites = useUnits('sites');
  const groups = useUnits('groups');
  const create = useCreateChangeBoard();
  const update = useUpdateChangeBoard();
  const problem = useFormProblem();
  const key = useMemo(() => crypto.randomUUID(), []);
  const [draft, setDraft] = useState<Draft>(() => fromBoard(board));
  const [dirty, setDirty] = useState(false);
  const set = (next: Partial<Draft>) => {
    setDraft((now) => ({ ...now, ...next }));
    setDirty(true);
  };
  const people = board?.people ?? {};
  const personLabel = (id: string) => people[id]?.display_name ?? t('changes.boards.someone');
  const groupLabel = (id: string) =>
    (groups.data ?? []).find((g) => g.id === id)?.name ?? t('changes.boards.a_group');
  const name = (draft.labels.en ?? '').trim();
  const needsChair = draft.rule === 'majority_with_chair';
  const ready = name !== '' && draft.members.length > 0 && (!needsChair || draft.chair_id !== null);
  const whyNot =
    name === ''
      ? t('changes.boards.why.name')
      : draft.members.length === 0
        ? t('changes.boards.why.members')
        : t('changes.boards.why.chair');
  const body = (): ChangeBoardInput => ({
    name,
    labels: Object.keys(draft.labels).length > 0 ? draft.labels : null,
    description: draft.description.trim() === '' ? null : draft.description.trim(),
    rule: draft.rule,
    chair_id: draft.chair_id,
    members: draft.members.map((m) =>
      m.user_id
        ? { user_id: m.user_id, optional: m.optional }
        : { group_id: m.group_id, optional: m.optional },
    ),
    mapping: {
      change_types: draft.change_types,
      risk_levels: draft.risk_levels as RiskLevel[],
      site_ids: draft.site_ids,
      template_ids: draft.template_ids,
    },
  });
  const done = () => {
    void message.success(t('settings.saved'));
    onClose();
  };
  const save = () => {
    if (board === undefined) {
      create.mutate({ key, body: body() }, { onSuccess: done, onError: (e) => problem.show(e) });
    } else {
      update.mutate(
        { id: board.id, version: board.version, body: body() },
        { onSuccess: done, onError: (e) => problem.show(e) },
      );
    }
  };
  const chairOptions = draft.members
    .filter((m) => m.user_id !== null)
    .map((m) => ({ value: m.user_id ?? '', label: personLabel(m.user_id ?? '') }));
  return (
    <EditDrawer
      open
      title={board ? boardName(t, locale, board) : t('changes.boards.add')}
      okText={board ? t('actions.save') : t('changes.boards.add')}
      saving={create.isPending || update.isPending}
      okDisabled={!ready}
      okWhyNot={ready ? undefined : whyNot}
      dirty={dirty}
      onCancel={onClose}
      onOk={save}
      testId="board-editor"
    >
      <Form layout="vertical" data-testid="board-form">
        <TranslatedField
          label={t('changes.boards.name')}
          value={draft.labels}
          onChange={(labels) => {
            set({ labels });
          }}
          required={['en']}
          max={120}
          testId="board-name"
        />
        <Form.Item label={t('changes.boards.description')} htmlFor="board-description">
          <Input.TextArea
            id="board-description"
            rows={2}
            value={draft.description}
            onChange={(e) => {
              set({ description: e.target.value });
            }}
            data-testid="board-description"
          />
        </Form.Item>
        <Form.Item
          label={t('changes.boards.rule')}
          htmlFor="board-rule"
          extra={t(`changes.boards.rule_help.${draft.rule}`)}
        >
          <Select<Rule>
            id="board-rule"
            value={draft.rule}
            onChange={(rule) => {
              set({ rule });
            }}
            data-testid="board-rule"
            options={RULES.map((r) => ({ value: r, label: t(`board_rule.${r}`) }))}
          />
        </Form.Item>
        <Form.Item label={t('changes.boards.members')} required>
          <List
            size="small"
            bordered
            data-testid="board-members"
            locale={{ emptyText: <EmptyText>{t('changes.boards.no_members')}</EmptyText> }}
            dataSource={draft.members}
            renderItem={(m, index) => {
              const label = m.user_id ? personLabel(m.user_id) : groupLabel(m.group_id ?? '');
              return (
                <List.Item
                  key={m.user_id ?? m.group_id ?? index}
                  data-testid={`board-member-${String(index)}`}
                  actions={[
                    <Space key="optional" size={4}>
                      <Switch
                        size="small"
                        checked={m.optional}
                        aria-label={t('changes.boards.optional_for', { name: label })}
                        onChange={(optional) => {
                          set({
                            members: draft.members.map((x, i) =>
                              i === index ? { ...x, optional } : x,
                            ),
                          });
                        }}
                      />
                      <Typography.Text type="secondary">
                        {t('changes.boards.optional')}
                      </Typography.Text>
                    </Space>,
                    <Button
                      key="remove"
                      type="text"
                      danger
                      icon={<DeleteOutlined aria-hidden />}
                      aria-label={t('changes.boards.remove_member', { name: label })}
                      onClick={() => {
                        set({
                          members: draft.members.filter((_, i) => i !== index),
                          chair_id: draft.chair_id === m.user_id ? null : draft.chair_id,
                        });
                      }}
                    />,
                  ]}
                >
                  <Space>
                    {m.user_id ? (
                      <PersonName id={m.user_id} known={people[m.user_id]?.display_name} />
                    ) : (
                      <span>{label}</span>
                    )}
                    {m.group_id && <ToneTag tone="default">{t('changes.boards.group')}</ToneTag>}
                  </Space>
                </List.Item>
              );
            }}
          />
        </Form.Item>
        <Flex gap={8} wrap style={{ marginBottom: 24 }}>
          <div style={{ minWidth: 240, flex: 1 }}>
            <UserPicker
              id="board-add-person"
              value={null}
              onChange={(user) => {
                if (!user || draft.members.some((m) => m.user_id === user)) return;
                set({
                  members: [...draft.members, { user_id: user, group_id: null, optional: false }],
                });
              }}
              testId="board-add-person"
              ariaLabel={t('changes.boards.add_person')}
            />
          </div>
          <div style={{ minWidth: 240, flex: 1 }}>
            <GroupPicker
              id="board-add-group"
              value={null}
              onChange={(group) => {
                if (!group || draft.members.some((m) => m.group_id === group)) return;
                set({
                  members: [...draft.members, { user_id: null, group_id: group, optional: false }],
                });
              }}
              testId="board-add-group"
              ariaLabel={t('changes.boards.add_group')}
            />
          </div>
        </Flex>
        <Form.Item
          label={t('changes.boards.chair')}
          htmlFor="board-chair"
          required={needsChair}
          extra={t('changes.boards.chair_help')}
        >
          <Select
            id="board-chair"
            allowClear
            value={draft.chair_id ?? undefined}
            onChange={(chair: string | undefined) => {
              set({ chair_id: chair ?? null });
            }}
            placeholder={t('changes.boards.no_chair')}
            data-testid="board-chair"
            options={chairOptions}
          />
        </Form.Item>
        <Typography.Title level={5}>{t('changes.boards.mapping')}</Typography.Title>
        <Typography.Paragraph type="secondary">
          {t('changes.boards.mapping_help')}
        </Typography.Paragraph>
        <Form.Item label={t('work_item.field.change_type')} htmlFor="board-types">
          <Select
            id="board-types"
            mode="multiple"
            allowClear
            value={draft.change_types}
            onChange={(change_types: string[]) => {
              set({ change_types });
            }}
            placeholder={t('changes.boards.any')}
            data-testid="board-types"
            options={(settings.data?.own_lists?.change_type ?? [])
              .filter((v) => !v.disabled)
              .map((v) => ({
                value: v.code,
                label: listValueName(t, locale, 'change_type', v, v.code),
              }))}
          />
        </Form.Item>
        <Form.Item label={t('work_item.field.risk')} htmlFor="board-risks">
          <Select
            id="board-risks"
            mode="multiple"
            allowClear
            value={draft.risk_levels}
            onChange={(risk_levels: string[]) => {
              set({ risk_levels });
            }}
            placeholder={t('changes.boards.any')}
            data-testid="board-risks"
            options={RISKS.map((r) => ({ value: r, label: t(`risk_level.${r}`) }))}
          />
        </Form.Item>
        <Form.Item label={t('work_item.field.site_id')} htmlFor="board-sites">
          <Select
            id="board-sites"
            mode="multiple"
            allowClear
            optionFilterProp="label"
            value={draft.site_ids}
            onChange={(site_ids: string[]) => {
              set({ site_ids });
            }}
            placeholder={t('changes.boards.any')}
            data-testid="board-sites"
            options={(sites.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
          />
        </Form.Item>
        <Form.Item label={t('changes.template')} htmlFor="board-templates">
          <Select
            id="board-templates"
            mode="multiple"
            allowClear
            optionFilterProp="label"
            value={draft.template_ids}
            onChange={(template_ids: string[]) => {
              set({ template_ids });
            }}
            placeholder={t('changes.boards.any')}
            data-testid="board-templates"
            options={(templates.data ?? []).map((x) => ({
              value: x.id,
              label: templateName(t, locale, x),
            }))}
          />
        </Form.Item>
        <FormProblem problem={problem} />
      </Form>
    </EditDrawer>
  );
}

/**
 * Change advisory boards on template E (WP-045b S2; the coordinator, 2026-11-11): every board
 * in the order they are tried, its rule, members and what it reviews; add, edit, reorder and
 * remove (never the default board, which takes whatever no other board matches). Changing a
 * board needs `changes.manage_boards` (the change manager) or `settings.manage`; every change
 * is audited by the server. A board needs at least one member.
 */
export function ChangeBoardsPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const { message, modal } = App.useApp();
  const boards = useChangeBoards();
  const update = useUpdateChangeBoard();
  const remove = useRemoveChangeBoard();
  const [editing, setEditing] = useState<ChangeBoard | 'new'>();
  const manage = can('changes.manage_boards') || can('settings.manage');
  // Another admin's change shows at once (rule c): the boards' broadcast refetches the list.
  useTenantChannel((m) => {
    if (m.type === 'work_items.change_boards_changed') void boards.refetch();
  });
  const rows = [...(boards.data ?? [])].sort((a, b) => a.position - b.position);
  const move = (board: ChangeBoard, by: -1 | 1) => {
    const other = rows[rows.indexOf(board) + by];
    if (other === undefined) return;
    update.mutate(
      { id: board.id, version: board.version, body: { position: other.position } },
      {
        onError: (e) => {
          reportError(e);
        },
      },
    );
  };
  return (
    <Flex vertical gap={16} data-testid="change-boards">
      <SettingsPageHeader
        title={t('nav.admin_change_boards')}
        description={t('setup.page.change-boards.description')}
        testId="admin-page-header"
        primaryAction={
          manage && (
            <WriteButton
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => {
                setEditing('new');
              }}
              data-testid="board-add"
            >
              {t('changes.boards.add')}
            </WriteButton>
          )
        }
      />
      <Table<ChangeBoard>
        rowKey="id"
        loading={boards.isPending}
        pagination={false}
        dataSource={rows}
        data-testid="boards-table"
        scroll={{ x: 760 }}
        columns={[
          {
            key: 'name',
            title: t('changes.boards.name'),
            render: (_, b) => (
              <Space wrap>
                <span>{boardName(t, locale, b)}</span>
                {b.is_default && <ToneTag tone="info">{t('changes.boards.default')}</ToneTag>}
              </Space>
            ),
          },
          {
            key: 'rule',
            title: t('changes.boards.rule'),
            render: (_, b) => t(`board_rule.${b.rule}`),
          },
          {
            key: 'members',
            title: t('changes.boards.members'),
            render: (_, b) =>
              b.members.length === 0 ? (
                <ToneTag tone="warning" testId={`board-${b.id}-no-members`}>
                  {t('changes.boards.no_members_short')}
                </ToneTag>
              ) : (
                t('changes.boards.member_count', { count: b.members.length })
              ),
          },
          {
            key: 'actions',
            title: <span className="sr-only">{t('settings.actions')}</span>,
            align: 'end' as const,
            render: (_, b) =>
              manage && (
                // Template E's row actions (QA6S-SHELL-10; lane C's review of #373): Edit as the
                // link, the rest in the row's "…" menu, Delete last and red.
                <RowActions
                  rowName={boardName(t, locale, b)}
                  primary={{
                    key: 'edit',
                    label: t('actions.edit'),
                    onClick: () => {
                      setEditing(b);
                    },
                    testId: `board-${b.id}-edit`,
                  }}
                  more={[
                    {
                      key: 'up',
                      label: t('changes.boards.move_up', { name: boardName(t, locale, b) }),
                      disabled: rows.indexOf(b) === 0,
                      whyNot: t('changes.boards.why.first'),
                      onClick: () => {
                        move(b, -1);
                      },
                      testId: `board-${b.id}-up`,
                    },
                    {
                      key: 'down',
                      label: t('changes.boards.move_down', { name: boardName(t, locale, b) }),
                      disabled: rows.indexOf(b) === rows.length - 1,
                      whyNot: t('changes.boards.why.last'),
                      onClick: () => {
                        move(b, 1);
                      },
                      testId: `board-${b.id}-down`,
                    },
                    {
                      key: 'delete',
                      label: t('actions.delete'),
                      danger: true,
                      disabled: b.is_default,
                      whyNot: t('changes.boards.why.default'),
                      onClick: () => {
                        void modal.confirm({
                          title: t('changes.boards.remove_title', {
                            name: boardName(t, locale, b),
                          }),
                          okButtonProps: { danger: true },
                          okText: t('actions.delete'),
                          onOk: () =>
                            remove.mutateAsync({ id: b.id, version: b.version }).then(() => {
                              void message.success(t('changes.boards.removed'));
                            }),
                        });
                      },
                      testId: `board-${b.id}-remove`,
                    },
                  ]}
                />
              ),
          },
        ]}
      />
      {editing !== undefined && (
        <BoardEditor
          board={editing === 'new' ? undefined : editing}
          onClose={() => {
            setEditing(undefined);
          }}
        />
      )}
    </Flex>
  );
}
