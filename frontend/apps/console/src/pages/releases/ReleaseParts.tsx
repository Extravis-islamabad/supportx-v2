import { PlusOutlined } from '@ant-design/icons';
import { Button, Flex, Form, Input, List, Select, Space, Table, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';

import {
  ApiError,
  useDecideReleaseApproval,
  useDowntimes,
  usePlanSections,
  useReleaseApprovals,
  useReleaseDetails,
  useReleaseRoles,
  useRemoveDowntime,
  useRoleCandidates,
  useSaveDowntime,
  useSetReleaseRole,
  useStageSchedules,
  useSubReleases,
  useUpdateReleaseDetails,
  useUpdateStageSchedule,
  useWritePlanSection,
  type ReleaseApproval,
  type ReleaseDetailsInput,
  type StageSchedule,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import {
  DateTimeField,
  EmptyText,
  FormProblem,
  RichTextField,
  RichTextView,
  ToneTag,
  WriteButton,
  useAppearance,
  useDateTime,
  useFormProblem,
  useLabel,
  lengthLimit,
  FormFooter,
  TimeZoneNote,
} from '@supportx/ui';

import { labelled } from '../incidents/labels';
import { RISKS, useOwnList } from './lists';
import { DecisionDialog } from '../requests/DecisionDialog';
import { listValueName, stageName, statusName } from './labels';

const REVIEW_OUTCOMES = ['successful', 'successful_with_issues', 'failed'] as const;
const WORK_OUTCOMES = ['passed', 'failed', 'partly_done'] as const;

const EMPTY_HTML = new Set(['', '<p></p>']);
const same = (a: unknown, b: unknown) => {
  const empty = (v: unknown) =>
    v === null || v === undefined || (typeof v === 'string' && EMPTY_HTML.has(v));
  return (empty(a) && empty(b)) || a === b;
};

/** The release's own fields (REQ-REL-002..005), with the release's version for If-Match. */
export function DetailsPart({ id }: { id: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const details = useReleaseDetails(id);
  const save = useUpdateReleaseDetails();
  const problem = useFormProblem();
  const types = useOwnList('release_type');
  const reasons = useOwnList('release_reason');
  const [draft, setDraft] = useState<ReleaseDetailsInput>({});
  const [riskReason, setRiskReason] = useState('');
  const d = details.data;
  if (d === undefined) return null;
  const value = <K extends keyof ReleaseDetailsInput>(k: K) =>
    (k in draft ? draft[k] : (d as unknown as ReleaseDetailsInput)[k]) ?? null;
  const set = (k: keyof ReleaseDetailsInput, v: unknown) => {
    setDraft((now) => ({ ...now, [k]: v }));
  };
  const riskChanged = 'risk' in draft && draft.risk !== d.risk;
  // The editor reports its empty document on mount: only a value that differs is a change.
  const dirty = Object.entries(draft).some(
    ([k, v]) => !same(v, (d as unknown as Record<string, unknown>)[k]),
  );
  const submit = () => {
    save.mutate(
      {
        id,
        version: d.version,
        body: { ...draft, risk_reason: riskChanged ? riskReason : undefined },
      },
      {
        onSuccess: () => {
          setDraft({});
          setRiskReason('');
        },
        onError: (error) => {
          problem.show(error);
        },
      },
    );
  };
  return (
    <Form layout="vertical" data-testid="release-details" style={{ maxWidth: 720 }}>
      <Flex gap={16} wrap>
        <Form.Item
          label={t('work_item.field.release_type')}
          style={{ minWidth: 220 }}
          htmlFor="release-type"
        >
          <Select
            id="release-type"
            allowClear
            value={value('release_type')}
            onChange={(v: string | undefined) => {
              set('release_type', v ?? null);
            }}
            placeholder={t('form.choose')}
            data-testid="release-type"
            options={types.map((v) => ({
              value: v.code,
              label: listValueName(t, locale, 'release_type', v, v.code),
            }))}
          />
        </Form.Item>
        <Form.Item
          label={t('work_item.field.risk')}
          style={{ minWidth: 180 }}
          htmlFor="release-risk"
        >
          <Select
            id="release-risk"
            allowClear
            value={value('risk')}
            onChange={(v: string | undefined) => {
              set('risk', v ?? null);
            }}
            placeholder={t('form.choose')}
            data-testid="release-risk"
            options={RISKS.map((r) => ({ value: r, label: t(`release_risk.${r}`) }))}
          />
        </Form.Item>
      </Flex>
      {riskChanged && (
        <Form.Item label={t('releases.risk_reason')} required htmlFor="release-risk-reason">
          <Input
            id="release-risk-reason"
            value={riskReason}
            onChange={(e) => {
              setRiskReason(e.target.value);
            }}
            data-testid="release-risk-reason"
          />
        </Form.Item>
      )}
      <Flex gap={16} wrap>
        <Form.Item label={t('work_item.field.release_version')} htmlFor="release-version">
          <Input
            id="release-version"
            value={value('release_version') ?? ''}
            count={lengthLimit(60)}
            onChange={(e) => {
              set('release_version', e.target.value);
            }}
            data-testid="release-version"
          />
        </Form.Item>
        <Form.Item label={t('work_item.field.build_ref')} htmlFor="release-build">
          <Input
            id="release-build"
            value={value('build_ref') ?? ''}
            count={lengthLimit(200)}
            onChange={(e) => {
              set('build_ref', e.target.value);
            }}
            data-testid="release-build"
          />
        </Form.Item>
        <Form.Item
          label={t('work_item.field.release_reason')}
          style={{ minWidth: 220 }}
          htmlFor="release-reason"
        >
          <Select
            id="release-reason"
            allowClear
            value={value('release_reason')}
            onChange={(v: string | undefined) => {
              set('release_reason', v ?? null);
            }}
            placeholder={t('form.choose')}
            data-testid="release-reason"
            options={reasons.map((v) => ({
              value: v.code,
              label: listValueName(t, locale, 'release_reason', v, v.code),
            }))}
          />
        </Form.Item>
      </Flex>
      <Flex gap={16} wrap>
        {(['scheduled_start', 'scheduled_end'] as const).map((k) => (
          <Form.Item key={k} label={t(`work_item.field.${k}`)} htmlFor={`release-${k}`}>
            <DateTimeField
              id={`release-${k}`}
              value={value(k)}
              onChange={(v) => {
                set(k, v);
              }}
              testId={`release-${k}`}
              hideZone
            />
          </Form.Item>
        ))}
      </Flex>
      {/* Once for the pair (D-155), not under each field. */}
      <div style={{ marginTop: -12, marginBottom: 16 }}>
        <TimeZoneNote />
      </div>
      <Form.Item label={t('work_item.field.release_notes')}>
        <RichTextField
          label={t('work_item.field.release_notes')}
          value={value('release_notes')}
          onChange={(html) => {
            set('release_notes', html);
          }}
          testId="release-notes"
        />
      </Form.Item>
      <FormProblem problem={problem} />
      {/* Template B (D-147, D-155): once something changed, a sticky footer with Cancel then
          Save, and Save says what is missing; nothing to save, no footer and no dead button. */}
      {dirty && (
        <FormFooter
          testId="release-details-footer"
          cancel={
            <Button
              onClick={() => {
                setDraft({});
                setRiskReason('');
                problem.clear();
              }}
              data-testid="release-details-cancel"
            >
              {t('actions.cancel')}
            </Button>
          }
          primary={
            <WriteButton
              type="primary"
              disabled={riskChanged && riskReason.trim() === ''}
              whyDisabled={t('releases.risk_reason_needed')}
              loading={save.isPending}
              onClick={submit}
              data-testid="release-details-save"
            >
              {t('actions.save')}
            </WriteButton>
          }
        />
      )}
    </Form>
  );
}

function RolePicker({
  id,
  role,
  label,
  version,
  current,
}: {
  id: string;
  role: string;
  label: string;
  version: number;
  current: string | undefined;
}) {
  const t = useLabel();
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(false);
  const candidates = useRoleCandidates(role, search, open);
  const setRole = useSetReleaseRole();
  const problem = useFormProblem();
  return (
    <Space direction="vertical">
      <Select
        showSearch
        allowClear
        filterOption={false}
        style={{ minWidth: 260 }}
        aria-label={label}
        value={current}
        placeholder={t('releases.roles.nobody')}
        onOpenChange={setOpen}
        onSearch={setSearch}
        loading={candidates.isFetching}
        data-testid={`role-${role}`}
        options={(candidates.data ?? []).map((p) => ({ value: p.id, label: p.name }))}
        onChange={(user: string | undefined) => {
          setRole.mutate(
            { id, role, version, userIds: user === undefined ? [] : [user] },
            {
              onError: (error) => {
                problem.show(error);
              },
            },
          );
        }}
      />
      <FormProblem problem={problem} />
    </Space>
  );
}

/** The roles tab (REQ-REL-023, -024): each role and its holder; pickers offer only the eligible. */
export function RolesPart({ id }: { id: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const roles = useReleaseRoles(id);
  const list = useListFormat();
  const view = roles.data;
  if (view === undefined) return null;
  return (
    <List
      data-testid="release-roles"
      locale={{ emptyText: <EmptyText>{t('releases.roles.none')}</EmptyText> }}
      dataSource={view.roles.filter((r) => !r.disabled || r.user_ids.length > 0)}
      renderItem={(r) => (
        <List.Item key={r.code} data-testid={`release-role-${r.code}`}>
          <List.Item.Meta
            title={labelled(r.labels, locale, () => t(`work_item_role.${r.code}`))}
            description={
              r.group_ids.length > 0
                ? t('releases.roles.groups', { count: r.group_ids.length })
                : undefined
            }
          />
          {r.single ? (
            <RolePicker
              id={id}
              role={r.code}
              label={labelled(r.labels, locale, () => t(`work_item_role.${r.code}`))}
              version={view.version}
              current={r.user_ids[0]}
            />
          ) : (
            <Typography.Text>
              {r.user_ids.length > 0
                ? list(
                    r.user_ids.map((u) => view.people[u] ?? ''),
                    'conjunction',
                  )
                : t('releases.roles.nobody')}
            </Typography.Text>
          )}
        </List.Item>
      )}
    />
  );
}

function PlanSectionEditor({
  id,
  section,
  content,
  version,
  startEditing = false,
  onClose,
}: {
  id: string;
  section: string;
  content: string | null;
  version: number;
  startEditing?: boolean;
  onClose?: () => void;
}) {
  const t = useLabel();
  const write = useWritePlanSection();
  const problem = useFormProblem();
  const [draft, setDraft] = useState<string | null>(null);
  const [editing, setEditing] = useState(startEditing);
  const label = t(`plan_section.${section}`);
  if (!editing) {
    return (
      <Space direction="vertical" style={{ width: '100%' }} data-testid={`plan-${section}`}>
        <Typography.Title level={5}>{label}</Typography.Title>
        {content ? (
          <RichTextView html={content} />
        ) : (
          <Typography.Text type="secondary">{t('releases.plan.empty')}</Typography.Text>
        )}
        <Button
          size="small"
          onClick={() => {
            setEditing(true);
          }}
          data-testid={`plan-${section}-edit`}
        >
          {t('actions.edit')}
        </Button>
      </Space>
    );
  }
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Typography.Title level={5}>{label}</Typography.Title>
      <RichTextField
        label={label}
        value={draft ?? content}
        onChange={setDraft}
        testId={`plan-${section}-editor`}
      />
      <FormProblem problem={problem} />
      <Space>
        <WriteButton
          size="small"
          loading={write.isPending}
          onClick={() => {
            write.mutate(
              { id, section, version, content: draft ?? content },
              {
                onSuccess: () => {
                  setEditing(false);
                  setDraft(null);
                  onClose?.();
                },
                onError: (error) => {
                  problem.show(error);
                },
              },
            );
          }}
          data-testid={`plan-${section}-save`}
        >
          {t('actions.save')}
        </WriteButton>
        <Button
          size="small"
          onClick={() => {
            setEditing(false);
            setDraft(null);
            onClose?.();
          }}
        >
          {t('actions.cancel')}
        </Button>
      </Space>
    </Space>
  );
}

// The review's sections are written from the Review stage on (D-155); the plan's from the start.
const REVIEW_SECTIONS = new Set(['review_findings', 'review_went_well', 'review_went_badly']);
const REVIEW_FROM = 'review';
const STAGE_ORDER = [
  'submission',
  'planning',
  'build',
  'testing',
  'acceptance_testing',
  'deployment',
  'training',
  'review',
  'closure',
];

/**
 * The plan's sections (REQ-REL-025, -030): each with its own version, so editors never clash.
 * Only the sections that fit the release's stage; a written one reads with its Edit, the empty
 * ones are one compact "Add …" list rather than blocks of "Nothing written yet" (D-155).
 */
export function PlanPart({ id, stage }: { id: string; stage: string }) {
  const t = useLabel();
  const sections = usePlanSections(id);
  const [adding, setAdding] = useState<string | null>(null);
  const reviewing = STAGE_ORDER.indexOf(stage) >= STAGE_ORDER.indexOf(REVIEW_FROM);
  const fitting = (sections.data ?? []).filter((s) => reviewing || !REVIEW_SECTIONS.has(s.section));
  const written = fitting.filter((s) => Boolean(s.content) || s.section === adding);
  const empty = fitting.filter((s) => !s.content && s.section !== adding);
  return (
    <Flex vertical gap={24} data-testid="release-plan">
      {written.map((s) => (
        <PlanSectionEditor
          key={s.section}
          id={id}
          section={s.section}
          content={s.content}
          version={s.version}
          startEditing={s.section === adding}
          onClose={() => {
            setAdding(null);
          }}
        />
      ))}
      {empty.length > 0 && (
        <Flex vertical gap={4} align="flex-start" data-testid="release-plan-add">
          {written.length === 0 && (
            <Typography.Text type="secondary">{t('releases.plan.none_yet')}</Typography.Text>
          )}
          {empty.map((s) => (
            <WriteButton
              key={s.section}
              type="link"
              icon={<PlusOutlined aria-hidden />}
              style={{ paddingInline: 0 }}
              onClick={() => {
                setAdding(s.section);
              }}
              data-testid={`plan-${s.section}-add`}
            >
              {t(`plan_section_add.${s.section}`)}
            </WriteButton>
          ))}
        </Flex>
      )}
    </Flex>
  );
}

function OutcomeSelect({ id, row }: { id: string; row: StageSchedule }) {
  const t = useLabel();
  const update = useUpdateStageSchedule();
  const problem = useFormProblem();
  const codes = row.stage === 'review' ? REVIEW_OUTCOMES : WORK_OUTCOMES;
  return (
    <Space direction="vertical">
      <Select
        allowClear
        style={{ minWidth: 200 }}
        aria-label={t('releases.schedule.outcome_of', { stage: stageName(t, row.stage) })}
        value={row.outcome}
        data-testid={`outcome-${row.stage}`}
        options={codes.map((c) => ({ value: c, label: t(`stage_outcome.${c}`) }))}
        onChange={(outcome: string | undefined) => {
          update.mutate(
            {
              id,
              stage: row.stage,
              version: row.version,
              body: { outcome: (outcome ?? null) as StageSchedule['outcome'] },
            },
            {
              onError: (error) => {
                problem.show(error);
              },
            },
          );
        }}
      />
      <FormProblem problem={problem} />
    </Space>
  );
}

const OUTCOME_STAGES = new Set([
  'build',
  'testing',
  'acceptance_testing',
  'deployment',
  'training',
  'review',
]);

/** Each stage's dates and outcome (REQ-REL-026, -028); the engine sets the actual dates. */
export function SchedulePart({ id }: { id: string }) {
  const t = useLabel();
  const { format } = useDateTime();
  const schedule = useStageSchedules(id);
  const when = (value: string | null | undefined) => (value ? format(value) : '');
  return (
    <div
      role="region"
      aria-label={t('releases.tab.schedule')}
      tabIndex={0}
      style={{ overflowX: 'auto' }}
    >
      <Table<StageSchedule>
        rowKey="stage"
        size="small"
        pagination={false}
        data-testid="release-schedule"
        dataSource={schedule.data ?? []}
        columns={[
          {
            key: 'stage',
            title: t('work_item.field.stage'),
            render: (_, r) => stageName(t, r.stage),
          },
          {
            key: 'planned',
            title: t('releases.schedule.planned'),
            render: (_, r) =>
              [when(r.scheduled_start), when(r.scheduled_end)].filter(Boolean).join(' – '),
          },
          {
            key: 'actual',
            title: t('releases.schedule.actual'),
            render: (_, r) =>
              [when(r.actual_start), when(r.actual_end)].filter(Boolean).join(' – '),
          },
          {
            key: 'outcome',
            title: t('releases.schedule.outcome'),
            render: (_, r) =>
              OUTCOME_STAGES.has(r.stage) ? <OutcomeSelect id={id} row={r} /> : null,
          },
        ]}
      />
    </div>
  );
}

/** Planned and actual downtime windows (REQ-REL-027). */
export function DowntimePart({ id }: { id: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { format } = useDateTime();
  const downtimes = useDowntimes(id);
  const save = useSaveDowntime();
  const remove = useRemoveDowntime();
  const problem = useFormProblem();
  const kinds = useOwnList('downtime_kind');
  const key = useMemo(() => crypto.randomUUID(), []);
  const [kind, setKind] = useState<string>();
  const [startsAt, setStartsAt] = useState<string | null>(null);
  const [endsAt, setEndsAt] = useState<string | null>(null);
  const kindName = (code: string | null) =>
    listValueName(
      t,
      locale,
      'downtime_kind',
      kinds.find((k) => k.code === code),
      code,
    );
  const rows = downtimes.data ?? [];
  // D-155: what is missing, said on the disabled button.
  const missing =
    startsAt === null && endsAt === null
      ? t('releases.downtime.need_both')
      : startsAt === null
        ? t('releases.downtime.need_start')
        : endsAt === null
          ? t('releases.downtime.need_end')
          : undefined;
  return (
    <Flex vertical gap={12} data-testid="release-downtimes">
      {/* D-155: a compact line when there is none yet, above the form; the list once there is. */}
      {rows.length === 0 && !downtimes.isPending ? (
        <EmptyText>{t('releases.downtime.none')}</EmptyText>
      ) : (
        <List
          dataSource={rows}
          renderItem={(d) => (
            <List.Item
              key={d.id}
              data-testid={`downtime-${d.id}`}
              actions={[
                <WriteButton
                  key="remove"
                  size="small"
                  danger
                  onClick={() => {
                    remove.mutate({ id, downtimeId: d.id, version: d.version });
                  }}
                >
                  {t('actions.delete')}
                </WriteButton>,
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
      {/* Template B (D-147, D-155): kind, start and end on one baseline, the zone said once. */}
      <Form layout="vertical" component="div">
        <Flex gap={16} wrap align="flex-start">
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
          {/* Its label's height, so the button sits on the fields' baseline. */}
          <Form.Item label={<span aria-hidden>&nbsp;</span>}>
            <WriteButton
              disabled={missing !== undefined}
              whyDisabled={missing}
              loading={save.isPending}
              data-testid="downtime-add"
              onClick={() => {
                save.mutate(
                  { id, key, body: { kind: kind ?? null, starts_at: startsAt, ends_at: endsAt } },
                  {
                    onSuccess: () => {
                      setKind(undefined);
                      setStartsAt(null);
                      setEndsAt(null);
                    },
                    onError: (error) => {
                      problem.show(error);
                    },
                  },
                );
              }}
            >
              {t('releases.downtime.add')}
            </WriteButton>
          </Form.Item>
        </Flex>
        <TimeZoneNote />
        <FormProblem problem={problem} />
      </Form>
    </Flex>
  );
}

/** Stage approvals (REQ-REL-031): who is pending and each decision, live; approve or reject.
 * Both go through the requests' decision dialog: every rejection gives its own reason, and an
 * approval asks for a comment when the level requires one (lane B's review of #219). */
export function ApprovalsPart({ id }: { id: string }) {
  const t = useLabel();
  const { format } = useDateTime();
  const approvals = useReleaseApprovals(id);
  const decide = useDecideReleaseApproval();
  const problem = useFormProblem();
  const [deciding, setDeciding] = useState<{
    approval: ReleaseApproval;
    decision: 'approve' | 'reject';
  }>();
  const [fieldProblems, setFieldProblems] = useState<string[]>([]);
  const rows = approvals.data?.items ?? [];
  const routed = (reason: string | null | undefined) =>
    reason ? t(`approval_route_reason.${reason}`) : '';
  const start = (approval: ReleaseApproval, decision: 'approve' | 'reject') => {
    setFieldProblems([]);
    setDeciding({ approval, decision });
  };
  const close = () => {
    setDeciding(undefined);
    setFieldProblems([]);
  };
  return (
    <Flex vertical gap={8} data-testid="release-approvals">
      <List
        dataSource={rows}
        locale={{ emptyText: <EmptyText>{t('releases.approvals.none')}</EmptyText> }}
        renderItem={(a) => (
          <List.Item
            key={a.id}
            data-testid={`approval-${a.id}`}
            actions={
              a.can_decide
                ? [
                    <WriteButton
                      key="approve"
                      size="small"
                      disabled={decide.isPending}
                      onClick={() => {
                        start(a, 'approve');
                      }}
                      data-testid={`approval-${a.id}-approve`}
                    >
                      {t('requests.approve')}
                    </WriteButton>,
                    <WriteButton
                      key="reject"
                      size="small"
                      danger
                      disabled={decide.isPending}
                      onClick={() => {
                        start(a, 'reject');
                      }}
                      data-testid={`approval-${a.id}-reject`}
                    >
                      {t('requests.reject')}
                    </WriteButton>,
                  ]
                : []
            }
          >
            <List.Item.Meta
              title={
                <Space wrap>
                  <span>{stageName(t, a.record_stage)}</span>
                  <span>{t('releases.approvals.level', { level: a.stage })}</span>
                  {a.rule && <ToneTag tone="info">{t(`approval_rule.${a.rule}`)}</ToneTag>}
                </Space>
              }
              description={
                <Space wrap>
                  <ToneTag
                    tone={
                      a.state === 'approved'
                        ? 'success'
                        : a.state === 'rejected'
                          ? 'error'
                          : 'default'
                    }
                  >
                    {t(`approval_state.${a.state}`)}
                  </ToneTag>
                  {routed(a.route_reason) !== '' && <span>{routed(a.route_reason)}</span>}
                  {a.decided_at && <span>{format(a.decided_at)}</span>}
                </Space>
              }
            />
          </List.Item>
        )}
      />
      {deciding && (
        <DecisionDialog
          decision={deciding.decision}
          commentsRequired={deciding.approval.comments_required}
          pending={decide.isPending}
          problems={fieldProblems}
          onClose={close}
          onSend={(comment, isPrivate) => {
            decide.mutate(
              {
                id,
                approvalId: deciding.approval.id,
                version: deciding.approval.version,
                decision: deciding.decision,
                comment,
                isPrivate,
              },
              {
                onSuccess: close,
                onError: (error) => {
                  if (error instanceof ApiError && error.status === 422) {
                    setFieldProblems(
                      error.fieldErrors.map((f) => t(f.message_key, f.params ?? {})),
                    );
                    return;
                  }
                  close();
                  problem.show(error);
                },
              },
            );
          }}
        />
      )}
      <FormProblem problem={problem} />
    </Flex>
  );
}

/** The release's sub-releases with their stage and status, live (REQ-REL-037 AC3). */
export function SubReleasesPart({ id }: { id: string }) {
  const t = useLabel();
  const subs = useSubReleases(id);
  return (
    <List
      data-testid="release-sub-releases"
      dataSource={subs.data ?? []}
      locale={{ emptyText: <EmptyText>{t('releases.sub.none')}</EmptyText> }}
      renderItem={(s) => (
        <List.Item key={s.id} data-testid={`sub-release-${s.id}`}>
          {s.visible ? (
            <Space wrap>
              <Link to={`/releases/${s.id}`}>
                <bdi>{s.display_id}</bdi>
              </Link>
              <bdi>{s.subject}</bdi>
              <span>{stageName(t, s.stage)}</span>
              <span>{statusName(t, s.status)}</span>
            </Space>
          ) : (
            <Typography.Text type="secondary">{t('releases.sub.hidden')}</Typography.Text>
          )}
        </List.Item>
      )}
    />
  );
}
