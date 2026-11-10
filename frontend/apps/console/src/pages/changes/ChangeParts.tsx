import { PlusOutlined } from '@ant-design/icons';
import {
  Button,
  Col,
  Flex,
  Form,
  Input,
  List,
  Radio,
  Row,
  Select,
  Space,
  Table,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  useAssessChangeRisk,
  useChangeDetails,
  useChangeRiskQuestionnaire,
  useSetStagedRole,
  useStagedDowntimes,
  useStagedPlan,
  useStagedRoleCandidates,
  useStagedRoles,
  useStagedSchedule,
  useStagedSettings,
  useUpdateChangeDetails,
  useWriteStagedPlan,
  type ChangeDetailsInput,
  type Downtime,
  type StageSchedule,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import {
  EmptyText,
  FormFooter,
  FormProblem,
  RichTextField,
  RichTextView,
  ToneTag,
  WriteButton,
  useAppearance,
  useDateTime,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

import { labelled } from '../incidents/labels';
import { listValueName, stageName } from '../releases/labels';
import { RISKS, riskTone } from './labels';

/**
 * The change's own fields (REQ-CHG-005, -011) and its risk (REQ-CHG-056..060): the type and the
 * reason for change from the type's own lists; the risk as the questionnaire scored it, and a
 * person's override, which always says why. Saved with the details' own version (If-Match).
 */
export function DetailsPart({ id }: { id: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const details = useChangeDetails(id);
  const settings = useStagedSettings('changes');
  const save = useUpdateChangeDetails();
  const problem = useFormProblem();
  const [draft, setDraft] = useState<ChangeDetailsInput>({});
  const d = details.data;
  if (d === undefined) return null;
  const own = (list: string) => (settings.data?.own_lists?.[list] ?? []).filter((v) => !v.disabled);
  const value = <K extends keyof ChangeDetailsInput>(k: K) =>
    (k in draft ? draft[k] : (d as unknown as ChangeDetailsInput)[k]) ?? null;
  const set = (k: keyof ChangeDetailsInput, v: unknown) => {
    setDraft((now) => ({ ...now, [k]: v }));
  };
  const overriding = 'risk_chosen' in draft && draft.risk_chosen !== d.risk_chosen;
  const reason = typeof draft.risk_reason === 'string' ? draft.risk_reason : '';
  const dirty = Object.entries(draft).some(
    ([k, v]) => v !== (d as unknown as Record<string, unknown>)[k],
  );
  const submit = () => {
    save.mutate(
      { id, version: d.version, body: draft },
      {
        onSuccess: () => {
          setDraft({});
        },
        onError: (error) => {
          problem.show(error);
        },
      },
    );
  };
  return (
    <Form layout="vertical" data-testid="change-details">
      <Row gutter={16}>
        {(['change_type', 'change_reason'] as const).map((list) => (
          <Col key={list} xs={24} md={12}>
            <Form.Item label={t(`work_item.field.${list}`)} htmlFor={`change-${list}`}>
              <Select
                id={`change-${list}`}
                allowClear
                value={value(list) ?? undefined}
                onChange={(v: string | undefined) => {
                  set(list, v ?? null);
                }}
                placeholder={t('form.choose')}
                data-testid={`change-${list}`}
                options={own(list).map((v) => ({
                  value: v.code,
                  label: listValueName(t, locale, list, v, v.code),
                }))}
              />
            </Form.Item>
          </Col>
        ))}
      </Row>
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item
            label={t('changes.risk.override')}
            htmlFor="change-risk-chosen"
            extra={
              d.risk_score === null || d.risk_score === undefined
                ? t('changes.risk.not_assessed')
                : t('changes.risk.scored', {
                    score: d.risk_score,
                    risk: d.risk ? t(`risk_level.${d.risk}`) : '',
                  })
            }
          >
            <Select
              id="change-risk-chosen"
              allowClear
              value={value('risk_chosen') ?? undefined}
              onChange={(v: string | undefined) => {
                set('risk_chosen', v ?? null);
              }}
              placeholder={t('changes.risk.as_assessed')}
              data-testid="change-risk-chosen"
              options={RISKS.map((r) => ({ value: r, label: t(`risk_level.${r}`) }))}
            />
          </Form.Item>
        </Col>
        {overriding && (
          <Col xs={24} md={12}>
            <Form.Item label={t('releases.risk_reason')} required htmlFor="change-risk-reason">
              <Input
                id="change-risk-reason"
                value={reason}
                onChange={(e) => {
                  set('risk_reason', e.target.value);
                }}
                data-testid="change-risk-reason"
              />
            </Form.Item>
          </Col>
        )}
      </Row>
      {Boolean(d.risk_chosen) && Boolean(d.risk_reason) && (
        <Typography.Paragraph type="secondary" data-testid="change-risk-why">
          {t('changes.risk.overridden_because', { reason: d.risk_reason })}
        </Typography.Paragraph>
      )}
      <FormProblem problem={problem} />
      {dirty && (
        <FormFooter
          testId="change-details-footer"
          cancel={
            <Button
              onClick={() => {
                setDraft({});
                problem.clear();
              }}
              data-testid="change-details-cancel"
            >
              {t('actions.cancel')}
            </Button>
          }
          primary={
            <WriteButton
              type="primary"
              disabled={overriding && reason.trim() === ''}
              whyDisabled={t('releases.risk_reason_needed')}
              loading={save.isPending}
              onClick={submit}
              data-testid="change-details-save"
            >
              {t('actions.save')}
            </WriteButton>
          }
        />
      )}
    </Form>
  );
}

/**
 * The risk questionnaire (REQ-CHG-057): one answer per question, the score and its level shown
 * as you answer; the server scores it again and keeps the questionnaire's version. Questions and
 * answers by code (labels `change_risk_question.*`, `change_risk_answer.<question>.<answer>`).
 */
export function RiskPart({ id }: { id: string }) {
  const t = useLabel();
  const questionnaire = useChangeRiskQuestionnaire(id);
  const details = useChangeDetails(id);
  const assess = useAssessChangeRisk();
  const problem = useFormProblem();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const q = questionnaire.data;
  const d = details.data;
  if (q === undefined || d === undefined) return null;
  const given = { ...((d.risk_answers ?? {}) as Record<string, string>), ...answers };
  const score = q.questions.reduce(
    (sum, question) =>
      sum + (question.answers.find((a) => a.code === given[question.code])?.score ?? 0),
    0,
  );
  const complete = q.questions.every((question) => given[question.code] !== undefined);
  const band = [...q.bands].sort((a, b) => b.low - a.low).find((b) => score >= b.low);
  const changed = Object.keys(answers).length > 0;
  return (
    <Flex vertical gap={16} data-testid="change-risk">
      <Flex gap={8} align="center" wrap>
        <Typography.Text>{t('changes.risk.score', { score })}</Typography.Text>
        {complete && band && (
          <ToneTag tone={riskTone(band.level)} testId="change-risk-level">
            {t('releases.risk_chip', { risk: t(`risk_level.${band.level}`) })}
          </ToneTag>
        )}
      </Flex>
      {q.questions.map((question) => (
        <Form.Item
          key={question.code}
          label={t(`change_risk_question.${question.code}`)}
          style={{ marginBottom: 0 }}
        >
          <Radio.Group
            value={given[question.code]}
            onChange={(e) => {
              setAnswers((now) => ({ ...now, [question.code]: String(e.target.value) }));
            }}
            data-testid={`risk-${question.code}`}
            options={question.answers.map((a) => ({
              value: a.code,
              label: t(`change_risk_answer.${question.code}.${a.code}`),
            }))}
          />
        </Form.Item>
      ))}
      <FormProblem problem={problem} />
      <div>
        <WriteButton
          type="primary"
          disabled={!complete || !changed}
          whyDisabled={t(complete ? 'changes.risk.why_unchanged' : 'changes.risk.why_incomplete')}
          loading={assess.isPending}
          onClick={() => {
            assess.mutate(
              { id, version: d.version, answers: given },
              {
                onSuccess: () => {
                  setAnswers({});
                },
                onError: (error) => {
                  problem.show(error);
                },
              },
            );
          }}
          data-testid="change-risk-save"
        >
          {t('changes.risk.save')}
        </WriteButton>
      </div>
    </Flex>
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
  const candidates = useStagedRoleCandidates('changes', role, search, open);
  const setRole = useSetStagedRole('changes');
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

/** The change's roles (REQ-CHG-034): each role and its holders; pickers offer only the eligible. */
export function RolesPart({ id }: { id: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const roles = useStagedRoles('changes', id);
  const list = useListFormat();
  const view = roles.data;
  if (view === undefined) return null;
  return (
    <List
      data-testid="change-roles"
      locale={{ emptyText: <EmptyText>{t('releases.roles.none')}</EmptyText> }}
      dataSource={view.roles.filter((r) => !r.disabled || r.user_ids.length > 0)}
      renderItem={(r) => {
        const name = labelled(r.labels, locale, () => t(`work_item_role.${r.code}`));
        return (
          <List.Item key={r.code} data-testid={`change-role-${r.code}`}>
            <List.Item.Meta
              title={name}
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
                label={name}
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
        );
      }}
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
  const write = useWriteStagedPlan('changes');
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
  const close = () => {
    setEditing(false);
    setDraft(null);
    onClose?.();
  };
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
                onSuccess: close,
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
        <Button size="small" onClick={close}>
          {t('actions.cancel')}
        </Button>
      </Space>
    </Space>
  );
}

/**
 * The plans (REQ-CHG-013, -016, -017): impact, roll-out, backout and test, each with its own
 * version so editors never clash. A written one reads with its Edit; the empty ones are one
 * compact "Add …" list (D-155). The backout plan is needed before the plan goes for approval.
 */
export function PlanPart({ id }: { id: string }) {
  const t = useLabel();
  const sections = useStagedPlan('changes', id);
  const [adding, setAdding] = useState<string | null>(null);
  const all = sections.data ?? [];
  const written = all.filter((s) => Boolean(s.content) || s.section === adding);
  const empty = all.filter((s) => !s.content && s.section !== adding);
  return (
    <Flex vertical gap={24} data-testid="change-plan">
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
        <Flex vertical gap={4} align="flex-start" data-testid="change-plan-add">
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

/**
 * Each stage's planned and actual dates and its outcome (REQ-CHG-017, -031), read here; the
 * engine sets the actual dates. Planning the windows and the calendar come with WP-045c.
 */
export function SchedulePart({ id }: { id: string }) {
  const t = useLabel();
  const { format } = useDateTime();
  const schedule = useStagedSchedule('changes', id);
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
        data-testid="change-schedule"
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
            render: (_, r) => (r.outcome ? t(`stage_outcome.${r.outcome}`) : ''),
          },
        ]}
      />
    </div>
  );
}

/** Planned and actual downtime windows (REQ-CHG-018), read here; WP-045c edits them. */
export function DowntimePart({ id }: { id: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { format } = useDateTime();
  const settings = useStagedSettings('changes');
  const downtimes = useStagedDowntimes('changes', id);
  const kinds = settings.data?.own_lists?.downtime_kind ?? [];
  const kindName = (code: string | null | undefined) =>
    listValueName(
      t,
      locale,
      'downtime_kind',
      kinds.find((k) => k.code === code),
      code,
    );
  return (
    <List<Downtime>
      data-testid="change-downtimes"
      locale={{ emptyText: <EmptyText>{t('releases.downtime.none')}</EmptyText> }}
      dataSource={downtimes.data ?? []}
      renderItem={(d) => (
        <List.Item key={d.id} data-testid={`downtime-${d.id}`}>
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
  );
}
