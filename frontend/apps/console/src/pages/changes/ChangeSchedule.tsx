import { NotificationOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Flex,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Select,
  Space,
  Typography,
} from 'antd';
import { useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router';

import {
  ApiError,
  changeKeys,
  useChangeConflicts,
  useFreezeOverride,
  useReapprovalPreview,
  useRemoveStagedDowntime,
  useSaveStagedDowntime,
  useStagedDowntimes,
  useStagedSchedule,
  useStagedSettings,
  useUpdateStagedSchedule,
  type Change,
  type ChangeConflict,
  type Downtime,
  type StageChanges,
} from '@supportx/api-client';
import { useListChannel, useTenantChannel } from '@supportx/realtime';
import {
  DateTimeField,
  EmptyText,
  FormProblem,
  TimeZoneNote,
  ToneTag,
  WriteButton,
  lengthLimit,
  useAccess,
  useAppearance,
  useDateTime,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

import { labelled } from '../incidents/labels';
import type { AnnouncementPrefill } from '../announcements/NewAnnouncementPage';
import { listValueName, stageName } from '../staged/labels';

const IMPLEMENTATION = 'implementation';
const BLOCKED = 'change_window_blocked';

/** The freezes a refused save names, when it was refused by one (ADR-042). */
function blockedBy(error: unknown): string[] | null {
  if (!(error instanceof ApiError) || error.code !== BLOCKED) return null;
  const ids = error.params.window_ids;
  return typeof ids === 'string' && ids !== '' ? ids.split(',') : [];
}

/**
 * Go ahead in a freeze (ADR-042; D-144's pattern): for those holding `changes.override_freeze`
 * at the change's scope, only the freezes the refused save named, with a reason. The server
 * decides and audits it; the save is then tried again.
 */
function FreezeOverrideDialog({
  change,
  windowIds,
  onDone,
  onClose,
}: {
  change: Change;
  windowIds: string[];
  onDone: () => void;
  onClose: () => void;
}) {
  const t = useLabel();
  const override = useFreezeOverride();
  const problem = useFormProblem();
  const [reason, setReason] = useState('');
  return (
    <Modal
      open
      title={t('changes.freeze.override_title')}
      okText={t('changes.freeze.override_confirm')}
      okButtonProps={{
        danger: true,
        disabled: reason.trim() === '',
        loading: override.isPending,
        'data-testid': 'freeze-override-ok',
      }}
      onOk={() => {
        override.mutate(
          { id: change.id, version: change.version, reason: reason.trim(), windowIds },
          {
            onSuccess: onDone,
            onError: (error) => {
              problem.show(error);
            },
          },
        );
      }}
      onCancel={onClose}
      destroyOnHidden
    >
      <Form layout="vertical" data-testid="freeze-override-dialog">
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('changes.freeze.override_warning', { count: windowIds.length })}
        />
        <Form.Item label={t('changes.freeze.override_reason')} required htmlFor="freeze-reason">
          <Input.TextArea
            id="freeze-reason"
            rows={3}
            count={lengthLimit(500)}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
            }}
            data-testid="freeze-override-reason"
          />
        </Form.Item>
        <FormProblem problem={problem} />
      </Form>
    </Modal>
  );
}

/**
 * A refused save in a freeze: say so, and offer the override to those who may (the server checks
 * the scope). The save that was refused runs again once the override is given.
 */
function useFreezeGuard(change: Change) {
  const t = useLabel();
  const { can } = useAccess();
  const [blocked, setBlocked] = useState<{ ids: string[]; retry: () => void } | null>(null);
  const handle = (error: unknown, retry: () => void): boolean => {
    const ids = blockedBy(error);
    if (ids === null) return false;
    setBlocked({ ids, retry });
    return true;
  };
  const view =
    blocked === null ? null : (
      <Alert
        type="error"
        showIcon
        data-testid="freeze-blocked"
        message={t('errors.change_window_blocked')}
        action={
          can('changes.override_freeze') && blocked.ids.length > 0 ? (
            <OverrideButton
              change={change}
              windowIds={blocked.ids}
              onDone={() => {
                const again = blocked.retry;
                setBlocked(null);
                again();
              }}
            />
          ) : undefined
        }
        closable
        onClose={() => {
          setBlocked(null);
        }}
      />
    );
  return { handle, view };
}

function OverrideButton({
  change,
  windowIds,
  onDone,
}: {
  change: Change;
  windowIds: string[];
  onDone: () => void;
}) {
  const t = useLabel();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        size="small"
        danger
        onClick={() => {
          setOpen(true);
        }}
        data-testid="freeze-override"
      >
        {t('changes.freeze.override')}
      </Button>
      {open && (
        <FreezeOverrideDialog
          change={change}
          windowIds={windowIds}
          onDone={() => {
            setOpen(false);
            onDone();
          }}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </>
  );
}

/**
 * The change's conflicts now (ADR-042): each says what and why, in the reader's language, and
 * whether it blocks. Live: a save, a window an admin changes, or another change moving.
 */
export function ConflictsPanel({ id }: { id: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { format } = useDateTime();
  const queryClient = useQueryClient();
  const conflicts = useChangeConflicts(id);
  useTenantChannel((m) => {
    if (m.type === 'work_items.change_windows_changed') {
      void queryClient.invalidateQueries({ queryKey: changeKeys.part(id, 'conflicts') });
    }
  });
  // Another change moving into (or out of) this one's time is an overlap gained or gone: the
  // changes' list channel says some change moved (lane C's review of #377).
  useListChannel('changes', () => {
    void queryClient.invalidateQueries({ queryKey: changeKeys.part(id, 'conflicts') });
  });
  const items = conflicts.data?.items ?? [];
  if (items.length === 0) return null;
  const what = (c: ChangeConflict) =>
    c.window_name !== null && c.window_name !== undefined
      ? labelled(c.window_labels, locale, () => c.window_name ?? '')
      : c.record_id
        ? t('changes.conflicts.another_change')
        : '';
  return (
    <Alert
      type={items.some((c) => c.blocks) ? 'error' : 'warning'}
      showIcon
      data-testid="change-conflicts"
      message={t('changes.conflicts.title', { count: items.length })}
      description={
        <List
          size="small"
          dataSource={items}
          renderItem={(c, index) => (
            <List.Item key={index} data-testid={`conflict-${c.kind}`}>
              <Space wrap>
                <ToneTag tone={c.blocks ? 'error' : 'warning'}>
                  {t(`change_conflict.${c.kind}`)}
                </ToneTag>
                {what(c) !== '' && <span>{what(c)}</span>}
                <span>{`${format(c.starts_at)} – ${format(c.ends_at)}`}</span>
                {c.blocks && (
                  <Typography.Text type="danger">{t('changes.conflicts.blocks')}</Typography.Text>
                )}
              </Space>
            </List.Item>
          )}
        />
      }
    />
  );
}

/**
 * The implementation window (REQ-CHG-017): planned start and end, with the stage row's own
 * If-Match. A window that sends approved stages back says so first (REQ-CHG-053); one in a
 * blocking freeze is refused and, for those who may, offers the override.
 */
function ImplementationWindow({ change }: { change: Change }) {
  const t = useLabel();
  const schedule = useStagedSchedule('changes', change.id);
  const update = useUpdateStagedSchedule('changes');
  const preview = useReapprovalPreview();
  const problem = useFormProblem();
  const row = (schedule.data ?? []).find((r) => r.stage === IMPLEMENTATION);
  const [start, setStart] = useState<string | null | undefined>(undefined);
  const [end, setEnd] = useState<string | null | undefined>(undefined);
  const [restarts, setRestarts] = useState<StageChanges[]>();
  const shownStart = start === undefined ? (row?.scheduled_start ?? null) : start;
  const shownEnd = end === undefined ? (row?.scheduled_end ?? null) : end;
  const dirty = start !== undefined || end !== undefined;
  const guard = useFreezeGuard(change);
  const write = () => {
    setRestarts(undefined);
    update.mutate(
      {
        id: change.id,
        stage: IMPLEMENTATION,
        version: row?.version ?? 0,
        body: { scheduled_start: shownStart, scheduled_end: shownEnd },
      },
      {
        onSuccess: () => {
          setStart(undefined);
          setEnd(undefined);
          problem.clear();
        },
        onError: (error) => {
          if (!guard.handle(error, write)) problem.show(error);
        },
      },
    );
  };
  const submit = () => {
    preview.mutate(
      { id: change.id, body: { window_start: shownStart, window_end: shownEnd } },
      {
        onSuccess: (found) => {
          const back = found.filter((s) => s.changes.some((c) => c.effect === 'restart'));
          if (back.length === 0) write();
          else setRestarts(back);
        },
        onError: (error) => {
          problem.show(error);
        },
      },
    );
  };
  const missing = shownStart === null || shownEnd === null;
  return (
    <Form layout="vertical" component="div" data-testid="change-window">
      <Typography.Title level={5}>{t('changes.window.title')}</Typography.Title>
      <Flex gap={16} wrap align="flex-start">
        <Form.Item label={t('work_item.field.scheduled_start')} htmlFor="window-start">
          <DateTimeField
            id="window-start"
            value={shownStart}
            onChange={setStart}
            testId="window-start"
            hideZone
          />
        </Form.Item>
        <Form.Item label={t('work_item.field.scheduled_end')} htmlFor="window-end">
          <DateTimeField
            id="window-end"
            value={shownEnd}
            onChange={setEnd}
            testId="window-end"
            hideZone
          />
        </Form.Item>
        {dirty && (
          <Form.Item label={<span aria-hidden>&nbsp;</span>}>
            <Space>
              <WriteButton
                type="primary"
                disabled={missing}
                whyDisabled={t('changes.window.need_both')}
                loading={update.isPending || preview.isPending}
                onClick={submit}
                data-testid="window-save"
              >
                {t('actions.save')}
              </WriteButton>
              <Button
                onClick={() => {
                  setStart(undefined);
                  setEnd(undefined);
                  problem.clear();
                }}
              >
                {t('actions.cancel')}
              </Button>
            </Space>
          </Form.Item>
        )}
      </Flex>
      <TimeZoneNote />
      {guard.view}
      <FormProblem problem={problem} />
      {restarts && (
        <Modal
          open
          title={t('changes.reapproval.title')}
          okText={t('changes.reapproval.confirm')}
          okButtonProps={{ loading: update.isPending, 'data-testid': 'reapproval-ok' }}
          onOk={write}
          onCancel={() => {
            setRestarts(undefined);
          }}
          destroyOnHidden
        >
          <Flex vertical gap={8} data-testid="reapproval-warning">
            <Typography.Text>{t('changes.window.reapproval_warning')}</Typography.Text>
            {restarts.map((s) => (
              <Typography.Text key={s.stage} strong>
                {stageName(t, s.stage)}
              </Typography.Text>
            ))}
          </Flex>
        </Modal>
      )}
    </Form>
  );
}

/**
 * Planned and actual downtime (REQ-CHG-018, -063): add and remove, a planned one checked against
 * the freezes as the window is; a planned one can be announced (an announcement draft, through
 * the announcements screen: nothing is sent until someone publishes it).
 */
function Downtimes({ change }: { change: Change }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { format } = useDateTime();
  const { can } = useAccess();
  const navigate = useNavigate();
  const settings = useStagedSettings('changes');
  const downtimes = useStagedDowntimes('changes', change.id);
  const save = useSaveStagedDowntime('changes');
  const remove = useRemoveStagedDowntime('changes');
  const problem = useFormProblem();
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [phase, setPhase] = useState<'planned' | 'actual'>('planned');
  const [kind, setKind] = useState<string>();
  const [startsAt, setStartsAt] = useState<string | null>(null);
  const [endsAt, setEndsAt] = useState<string | null>(null);
  const kinds = (settings.data?.own_lists?.downtime_kind ?? []).filter((k) => !k.disabled);
  const kindName = (code: string | null | undefined) =>
    listValueName(
      t,
      locale,
      'downtime_kind',
      kinds.find((k) => k.code === code),
      code,
    );
  const guard = useFreezeGuard(change);
  const add = () => {
    save.mutate(
      {
        id: change.id,
        key,
        body: { phase, kind: kind ?? null, starts_at: startsAt, ends_at: endsAt },
      },
      {
        onSuccess: () => {
          setKind(undefined);
          setStartsAt(null);
          setEndsAt(null);
          setKey(crypto.randomUUID());
          problem.clear();
        },
        onError: (error) => {
          if (!guard.handle(error, add)) problem.show(error);
        },
      },
    );
  };
  const announce = (d: Downtime) => {
    const prefill: AnnouncementPrefill = {
      title: t('changes.downtime.announce_title', { id: change.display_id }),
      body: `<p>${t('changes.downtime.announce_body', {
        start: format(d.starts_at),
        end: format(d.ends_at),
      })}</p>`,
      severity: 'warning',
      publish_until: d.ends_at,
    };
    void navigate('/announcements/new', { state: { prefill } });
  };
  const rows = downtimes.data ?? [];
  const missing =
    startsAt === null || endsAt === null ? t('releases.downtime.need_both') : undefined;
  return (
    <Flex vertical gap={12} data-testid="change-downtimes">
      <Typography.Title level={5}>{t('releases.tab.downtime')}</Typography.Title>
      {rows.length === 0 && !downtimes.isPending ? (
        <EmptyText>{t('releases.downtime.none')}</EmptyText>
      ) : (
        <List<Downtime>
          dataSource={rows}
          renderItem={(d) => (
            <List.Item
              key={d.id}
              data-testid={`downtime-${d.id}`}
              actions={[
                ...(d.phase === 'planned' && can('announcements.manage')
                  ? [
                      <Button
                        key="announce"
                        size="small"
                        icon={<NotificationOutlined aria-hidden />}
                        onClick={() => {
                          announce(d);
                        }}
                        data-testid={`downtime-${d.id}-announce`}
                      >
                        {t('changes.downtime.announce')}
                      </Button>,
                    ]
                  : []),
                <Popconfirm
                  key="remove"
                  title={t('changes.downtime.delete_confirm')}
                  okText={t('actions.delete')}
                  okButtonProps={{ danger: true, 'data-testid': `downtime-${d.id}-remove-ok` }}
                  cancelText={t('actions.cancel')}
                  onConfirm={() => {
                    remove.mutate({ id: change.id, downtimeId: d.id, version: d.version });
                  }}
                >
                  <WriteButton size="small" danger data-testid={`downtime-${d.id}-remove`}>
                    {t('actions.delete')}
                  </WriteButton>
                </Popconfirm>,
              ]}
            >
              <Space wrap>
                <ToneTag tone={d.phase === 'actual' ? 'warning' : 'info'}>
                  {t(`downtime_phase.${d.phase}`)}
                </ToneTag>
                {kindName(d.kind) !== '' && <span>{kindName(d.kind)}</span>}
                <span>{`${format(d.starts_at)} – ${format(d.ends_at)}`}</span>
              </Space>
            </List.Item>
          )}
        />
      )}
      <Form layout="vertical" component="div">
        <Flex gap={16} wrap align="flex-start">
          <Form.Item label={t('changes.downtime.phase')} htmlFor="downtime-phase">
            <Select<'planned' | 'actual'>
              id="downtime-phase"
              style={{ minWidth: 140 }}
              value={phase}
              onChange={setPhase}
              data-testid="downtime-phase"
              options={(['planned', 'actual'] as const).map((p) => ({
                value: p,
                label: t(`downtime_phase.${p}`),
              }))}
            />
          </Form.Item>
          <Form.Item
            label={t('releases.downtime.kind')}
            style={{ minWidth: 200 }}
            htmlFor="downtime-kind"
          >
            <Select
              id="downtime-kind"
              allowClear
              value={kind}
              onChange={setKind}
              data-testid="downtime-kind"
              options={kinds.map((k) => ({
                value: k.code,
                label: listValueName(t, locale, 'downtime_kind', k, k.code),
              }))}
            />
          </Form.Item>
          <Form.Item label={t('releases.downtime.starts')} required htmlFor="downtime-starts">
            <DateTimeField
              id="downtime-starts"
              value={startsAt}
              onChange={setStartsAt}
              testId="downtime-starts"
              hideZone
            />
          </Form.Item>
          <Form.Item label={t('releases.downtime.ends')} required htmlFor="downtime-ends">
            <DateTimeField
              id="downtime-ends"
              value={endsAt}
              onChange={setEndsAt}
              testId="downtime-ends"
              hideZone
            />
          </Form.Item>
          <Form.Item label={<span aria-hidden>&nbsp;</span>}>
            <WriteButton
              disabled={missing !== undefined}
              whyDisabled={missing}
              loading={save.isPending}
              data-testid="downtime-add"
              onClick={add}
            >
              {t('releases.downtime.add')}
            </WriteButton>
          </Form.Item>
        </Flex>
        <TimeZoneNote />
        {guard.view}
        <FormProblem problem={problem} />
      </Form>
    </Flex>
  );
}

/** The Schedule tab: conflicts first, then the window, the downtimes and each stage's dates. */
export function ChangeScheduleTab({ change, stages }: { change: Change; stages: ReactNode }) {
  return (
    <Flex vertical gap={24} data-testid="change-schedule-tab">
      <ConflictsPanel id={change.id} />
      <ImplementationWindow change={change} />
      <Downtimes change={change} />
      {stages}
    </Flex>
  );
}
