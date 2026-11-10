import { DeleteOutlined } from '@ant-design/icons';
import {
  Button,
  Card,
  Checkbox,
  Flex,
  Form,
  Modal,
  Popconfirm,
  Select,
  Table,
  Tag,
  Typography,
} from 'antd';
import { useState } from 'react';

import type { AssetLifeCycle, AssetMove, AssetState } from '@supportx/api-client';
import { EmptyText, useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { LabelsFields, Problems } from '../incidents/shared';
import { codeFrom, nameOf, useCatalogueSave, type Names } from './shared';

interface Draft {
  names: Names;
  isDefault: boolean;
  moves: AssetMove[];
}

/**
 * Life cycles: which state an asset may move to from which, and whether the move asks for a
 * reason. A move that needs a permission (Appendix A: back to stock from retired) keeps it; the
 * screen shows it. One life cycle is the default, used by product types that name none.
 */
export function LifeCyclesTab({
  lifeCycles,
  states,
}: {
  lifeCycles: AssetLifeCycle[];
  states: AssetState[];
}) {
  const t = useLabel();
  const { locale, direction } = useAppearance();
  const { run, problems, clear, pending } = useCatalogueSave();
  const [editing, setEditing] = useState<AssetLifeCycle | 'new' | null>(null);
  const [draft, setDraft] = useState<Draft>();
  const [key, setKey] = useState(() => crypto.randomUUID());
  const stateName = (id: string) => {
    const state = states.find((s) => s.id === id);
    return state === undefined ? t('assets.admin.removed_state') : nameOf(state.names, locale);
  };
  const stateOptions = states.map((s) => ({ value: s.id, label: nameOf(s.names, locale) }));
  const open = (cycle: AssetLifeCycle | 'new') => {
    clear();
    setKey(crypto.randomUUID());
    setEditing(cycle);
    // A new life cycle starts from the default one's moves: easier to trim than to build.
    const start = lifeCycles.find((c) => c.is_default);
    setDraft(
      cycle === 'new'
        ? { names: {}, isDefault: false, moves: start?.moves ?? [] }
        : { names: cycle.names, isDefault: cycle.is_default, moves: cycle.moves },
    );
  };
  const close = () => {
    clear();
    setEditing(null);
  };
  const save = () => {
    if (draft === undefined || editing === null) return;
    if (editing === 'new') {
      run(
        {
          kind: 'create_life_cycle',
          key,
          body: {
            code: codeFrom(
              draft.names.en ?? '',
              new Set(lifeCycles.map((c) => c.code)),
              'life_cycle',
            ),
            names: draft.names,
            moves: draft.moves,
          },
        },
        close,
      );
      return;
    }
    run(
      {
        kind: 'life_cycle',
        id: editing.id,
        version: editing.version,
        body: {
          names: draft.names,
          moves: draft.moves,
          ...(draft.isDefault && !editing.is_default && { is_default: true }),
        },
      },
      close,
      close,
    );
  };
  const setMove = (index: number, next: Partial<AssetMove>) => {
    if (draft === undefined) return;
    setDraft({
      ...draft,
      moves: draft.moves.map((move, i) => (i === index ? { ...move, ...next } : move)),
    });
  };
  return (
    <Flex vertical gap={16} data-testid="asset-life-cycles">
      <Flex justify="space-between" align="center" gap={8} wrap>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t('assets.admin.life_cycles_help')}
        </Typography.Paragraph>
        <WriteButton
          onClick={() => {
            open('new');
          }}
          data-testid="asset-life-cycle-add"
        >
          {t('assets.admin.add_life_cycle')}
        </WriteButton>
      </Flex>
      {editing === null && <Problems problems={problems} testId="asset-life-cycles-problems" />}
      {lifeCycles.map((cycle) => (
        <Card
          key={cycle.id}
          title={
            <Flex gap={8} align="center">
              <bdi dir="auto">{nameOf(cycle.names, locale)}</bdi>
              {cycle.is_default && <Tag>{t('assets.admin.default')}</Tag>}
            </Flex>
          }
          extra={
            <Flex gap={4}>
              <Button
                type="link"
                onClick={() => {
                  open(cycle);
                }}
                data-testid={`asset-life-cycle-edit-${cycle.code}`}
              >
                {t('actions.edit')}
              </Button>
              {!cycle.is_default && (
                <Popconfirm
                  title={t('assets.admin.delete_confirm', { name: nameOf(cycle.names, locale) })}
                  okText={t('actions.delete')}
                  cancelText={t('actions.cancel')}
                  onConfirm={() => {
                    run({ kind: 'delete_life_cycle', id: cycle.id, version: cycle.version });
                  }}
                >
                  <Button type="link" danger data-testid={`asset-life-cycle-delete-${cycle.code}`}>
                    {t('actions.delete')}
                  </Button>
                </Popconfirm>
              )}
            </Flex>
          }
          data-testid={`asset-life-cycle-${cycle.code}`}
        >
          <Table
            size="small"
            rowKey={(move) => `${move.from_state_id}-${move.to_state_id}`}
            pagination={false}
            dataSource={cycle.moves}
            locale={{ emptyText: <EmptyText>{t('assets.admin.no_moves')}</EmptyText> }}
            columns={[
              {
                key: 'from',
                title: t('assets.admin.from_state'),
                render: (_: unknown, move: AssetMove) => (
                  <bdi dir="auto">{stateName(move.from_state_id)}</bdi>
                ),
              },
              {
                key: 'to',
                title: t('assets.admin.to_state'),
                render: (_: unknown, move: AssetMove) => (
                  <bdi dir="auto">{stateName(move.to_state_id)}</bdi>
                ),
              },
              {
                key: 'rules',
                title: t('assets.admin.move_rules'),
                render: (_: unknown, move: AssetMove) => (
                  <Flex gap={4} wrap>
                    {move.reason_required && <Tag>{t('assets.admin.asks_reason')}</Tag>}
                    {move.permission != null && <Tag>{t('assets.admin.needs_permission')}</Tag>}
                  </Flex>
                ),
              },
            ]}
          />
        </Card>
      ))}
      <Modal
        open={editing !== null}
        width={720}
        title={
          editing === 'new' ? t('assets.admin.add_life_cycle') : t('assets.admin.edit_life_cycle')
        }
        okText={t('actions.save')}
        cancelText={t('actions.cancel')}
        onOk={save}
        onCancel={close}
        confirmLoading={pending}
        destroyOnHidden
        data-testid="asset-life-cycle-dialog"
      >
        {draft !== undefined && editing !== null && (
          <Form layout="vertical">
            <Problems problems={problems} testId="asset-life-cycle-problems" />
            <LabelsFields
              value={draft.names}
              onChange={(names) => {
                setDraft({ ...draft, names });
              }}
              testId="asset-life-cycle-name"
            />
            {editing !== 'new' && !editing.is_default && (
              <Form.Item>
                <Checkbox
                  checked={draft.isDefault}
                  onChange={(event) => {
                    setDraft({ ...draft, isDefault: event.target.checked });
                  }}
                  data-testid="asset-life-cycle-default"
                >
                  {t('assets.admin.make_default')}
                </Checkbox>
              </Form.Item>
            )}
            <Typography.Title level={5}>{t('assets.admin.moves')}</Typography.Title>
            <Flex vertical gap={8}>
              {draft.moves.map((move, index) => (
                <Flex
                  key={index}
                  gap={8}
                  align="center"
                  wrap
                  data-testid={`asset-move-${String(index)}`}
                >
                  <Select
                    aria-label={t('assets.admin.from_state')}
                    value={move.from_state_id}
                    options={stateOptions}
                    onChange={(id: string) => {
                      setMove(index, { from_state_id: id });
                    }}
                    style={{ minWidth: 160 }}
                  />
                  <span aria-hidden>{direction === 'rtl' ? '←' : '→'}</span>
                  <Select
                    aria-label={t('assets.admin.to_state')}
                    value={move.to_state_id}
                    options={stateOptions}
                    onChange={(id: string) => {
                      setMove(index, { to_state_id: id });
                    }}
                    style={{ minWidth: 160 }}
                  />
                  <Checkbox
                    checked={move.reason_required}
                    onChange={(event) => {
                      setMove(index, { reason_required: event.target.checked });
                    }}
                  >
                    {t('assets.admin.asks_reason')}
                  </Checkbox>
                  {move.permission != null && <Tag>{t('assets.admin.needs_permission')}</Tag>}
                  <Button
                    type="text"
                    icon={<DeleteOutlined />}
                    aria-label={t('assets.admin.remove_move')}
                    onClick={() => {
                      setDraft({ ...draft, moves: draft.moves.filter((_, i) => i !== index) });
                    }}
                  />
                </Flex>
              ))}
              <Button
                onClick={() => {
                  const first = states[0]?.id;
                  if (first === undefined) return;
                  setDraft({
                    ...draft,
                    moves: [
                      ...draft.moves,
                      { from_state_id: first, to_state_id: first, reason_required: false },
                    ],
                  });
                }}
                style={{ alignSelf: 'start' }}
                data-testid="asset-move-add"
              >
                {t('assets.admin.add_move')}
              </Button>
            </Flex>
          </Form>
        )}
      </Modal>
    </Flex>
  );
}
