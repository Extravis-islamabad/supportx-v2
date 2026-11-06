import {
  Alert,
  Button,
  Checkbox,
  Flex,
  Form,
  Input,
  List,
  Select,
  Skeleton,
  Space,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';

import {
  useCreateProblem,
  useCreateProblemFromIncidents,
  useFromIncidentsPreview,
  useLinkIncident,
  useProblemCatalogue,
  useProblemPrefill,
  useProblemTemplates,
  useSession,
  useSimilarProblems,
  type ProblemInput,
  type ProblemPrefill,
  type ProblemTemplate,
  type SimilarProblem,
} from '@supportx/api-client';
import {
  PageHeader,
  RichTextField,
  lengthLimit,
  reportError,
  useAppearance,
  useLabel,
} from '@supportx/ui';

import { labelled, scaleLabel } from '../incidents/labels';
import { GroupPicker } from '../incidents/pickers';
import { StatusTag } from '../incidents/tags';
import { useDebounced } from '../../useDebounced';

/** The incidents a problem is created from: `?incident=<id>` or `?incidents=<id>,<id>…`. */
function useSourceIncidents(): string[] {
  const [params] = useSearchParams();
  return useMemo(() => {
    const many = (params.get('incidents') ?? '').split(',').filter((id) => id !== '');
    const one = params.get('incident');
    return many.length > 0 ? many : one ? [one] : [];
  }, [params]);
}

/** One similar open problem, and "link the incidents to it instead" when there are some. */
function SimilarRow({ found, incidents }: { found: SimilarProblem; incidents: string[] }) {
  const t = useLabel();
  const navigate = useNavigate();
  const link = useLinkIncident(found.id);
  const [busy, setBusy] = useState(false);
  const linkAll = async () => {
    setBusy(true);
    try {
      for (const incidentId of incidents) {
        await link.mutateAsync({ incidentId, move: false });
      }
      void navigate(`/problems/${found.id}`);
    } catch (error) {
      reportError(error);
    } finally {
      setBusy(false);
    }
  };
  return (
    <List.Item
      data-testid={`prb-similar-${found.display_id}`}
      actions={
        incidents.length > 0
          ? [
              <Button
                key="link"
                size="small"
                loading={busy}
                onClick={() => void linkAll()}
                data-testid={`prb-similar-link-${found.display_id}`}
              >
                {t('problems.similar.link_instead')}
              </Button>,
            ]
          : []
      }
    >
      <Space>
        <Link to={`/problems/${found.id}`}>
          <strong dir="ltr">{found.display_id}</strong>
        </Link>
        <bdi dir="auto">{found.subject}</bdi>
        <StatusTag status={found.status} catalogue={undefined} />
      </Space>
    </List.Item>
  );
}

/**
 * Create a problem (WP-044a s5; REQ-PRB-010..014): the template first, reported by you; from an
 * incident the form starts filled from it, from many the ones already caused by another problem
 * are listed to move or leave. Open problems with a similar title show while you type, with
 * "link the incidents to it instead". Nothing is saved until you press Create.
 */
export function NewProblemPage() {
  const incidents = useSourceIncidents();
  const prefill = useProblemPrefill(incidents[0]);
  const templates = useProblemTemplates();
  const waiting = templates.isLoading || (incidents.length > 0 && prefill.isLoading);
  if (waiting) return <Skeleton active />;
  const offered = (templates.data ?? []).filter((x) => !x.disabled);
  return (
    <ProblemForm
      incidents={incidents}
      filled={prefill.data}
      templates={offered}
      firstTemplate={(offered.find((x) => x.is_default) ?? offered[0])?.id}
    />
  );
}

function ProblemForm({
  incidents,
  filled,
  templates,
  firstTemplate,
}: {
  incidents: string[];
  filled: ProblemPrefill | undefined;
  templates: ProblemTemplate[];
  firstTemplate: string | undefined;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const me = useSession().data?.user.id ?? '';
  const main = incidents[0];
  const preview = useFromIncidentsPreview(incidents.length > 1 ? incidents : []);
  const catalogue = useProblemCatalogue();
  const create = useCreateProblem();
  const fromIncidents = useCreateProblemFromIncidents();
  const [key] = useState(() => crypto.randomUUID());
  // The incident's values start the form; the person changes them before saving (AC1).
  const [templateId, setTemplateId] = useState<string | undefined>(firstTemplate);
  const [subject, setSubject] = useState(filled?.subject ?? '');
  const [description, setDescription] = useState(filled?.description ?? '');
  const [impact, setImpact] = useState<string | null>(filled?.impact ?? null);
  const [urgency, setUrgency] = useState<string | null>(filled?.urgency ?? null);
  const [groupId, setGroupId] = useState<string | null>(null);
  const [problemType, setProblemType] = useState<string | null>(filled?.problem_type ?? null);
  const [move, setMove] = useState<string[]>([]);
  const similar = useSimilarProblems(useDebounced(subject, 300));
  const offered = templates;

  const scaleOptions = (scale: 'impact' | 'urgency') =>
    (catalogue.data?.scales ?? [])
      .filter((v) => v.scale === scale)
      .map((v) => ({ value: v.code, label: scaleLabel(t, catalogue.data, scale, v.code, locale) }));
  const caused = preview.data?.already_caused ?? [];
  const saving = create.isPending || fromIncidents.isPending;

  const submit = () => {
    const body: ProblemInput = {
      subject,
      requester_id: filled?.requester_id ?? me,
      confirm_lose_access: false,
      ...(description.trim() === '' ? {} : { description }),
      ...(templateId === undefined ? {} : { template_id: templateId }),
      ...(impact === null ? {} : { impact: impact as ProblemInput['impact'] }),
      ...(urgency === null ? {} : { urgency: urgency as ProblemInput['urgency'] }),
      ...(groupId === null ? {} : { group_id: groupId }),
      ...(problemType === null ? {} : { problem_type: problemType }),
      ...(filled?.category_id ? { category_id: filled.category_id } : {}),
      ...(filled?.site_id ? { site_id: filled.site_id } : {}),
    };
    if (main === undefined) {
      create.mutate(
        { body, key },
        {
          onSuccess: (made) => void navigate(`/problems/${made.id}`),
          onError: reportError,
        },
      );
      return;
    }
    fromIncidents.mutate(
      { body, key, mainIncidentId: main, incidentIds: incidents, moveIncidentIds: move },
      {
        onSuccess: (made) => void navigate(`/problems/${made.problem.id}`),
        onError: reportError,
      },
    );
  };

  return (
    <Flex vertical gap={16} style={{ width: '100%', maxWidth: 880 }}>
      <PageHeader
        title={t('problems.new')}
        back={{ label: t('nav.problems'), onClick: () => void navigate('/problems') }}
      />
      {incidents.length > 0 && (
        <Alert
          type="info"
          showIcon
          data-testid="prb-from-incidents"
          message={t('problems.from_incidents', { count: incidents.length })}
        />
      )}
      {caused.length > 0 && (
        <Alert
          type="warning"
          showIcon
          data-testid="prb-already-caused"
          message={t('problems.already_caused.title', { count: caused.length })}
          description={
            <Checkbox.Group
              value={move}
              onChange={(values) => {
                setMove(values);
              }}
              options={caused.map((c) => ({
                value: c.incident_id,
                label: t('problems.already_caused.move', { problem: c.problem_display_id }),
              }))}
            />
          }
        />
      )}
      <Form layout="vertical" component="div" requiredMark>
        <Form.Item label={t('templates.field')} htmlFor="prb-template">
          <Select
            id="prb-template"
            value={templateId}
            onChange={setTemplateId}
            data-testid="prb-template"
            options={offered.map((x) => ({
              value: x.id,
              label: labelled(x.labels, locale, () => t(`problem_template.${x.code ?? ''}`)),
            }))}
          />
        </Form.Item>
        <Form.Item label={t('work_item.field.subject')} htmlFor="prb-subject" required>
          <Input
            id="prb-subject"
            dir="auto"
            value={subject}
            onChange={(event) => {
              setSubject(event.target.value);
            }}
            count={lengthLimit(250)}
            data-testid="prb-subject"
          />
        </Form.Item>
        {(similar.data ?? []).length > 0 && (
          <Flex vertical gap={4} style={{ marginBottom: 16 }} data-testid="prb-similar">
            <Typography.Text type="secondary">{t('problems.similar.title')}</Typography.Text>
            <List
              size="small"
              bordered
              dataSource={similar.data ?? []}
              renderItem={(found) => <SimilarRow found={found} incidents={incidents} />}
            />
          </Flex>
        )}
        <Form.Item label={t('work_item.field.description')}>
          <RichTextField
            label={t('work_item.field.description')}
            value={description}
            onChange={setDescription}
            testId="prb-description"
            imageOwnerId={me}
          />
        </Form.Item>
        <Flex gap={16} wrap>
          <Form.Item label={t('work_item.field.impact')} htmlFor="prb-impact">
            <Select
              id="prb-impact"
              allowClear
              style={{ minWidth: 200 }}
              value={impact}
              onChange={(value: string | undefined) => {
                setImpact(value ?? null);
              }}
              options={scaleOptions('impact')}
              data-testid="prb-impact"
            />
          </Form.Item>
          <Form.Item label={t('work_item.field.urgency')} htmlFor="prb-urgency">
            <Select
              id="prb-urgency"
              allowClear
              style={{ minWidth: 200 }}
              value={urgency}
              onChange={(value: string | undefined) => {
                setUrgency(value ?? null);
              }}
              options={scaleOptions('urgency')}
              data-testid="prb-urgency"
            />
          </Form.Item>
          <Form.Item label={t('work_item.field.problem_type')} htmlFor="prb-type">
            <Select
              id="prb-type"
              allowClear
              style={{ minWidth: 200 }}
              value={problemType}
              onChange={(value: string | undefined) => {
                setProblemType(value ?? null);
              }}
              options={(catalogue.data?.problem_types ?? [])
                .filter((v) => !v.disabled)
                .map((v) => ({
                  value: v.code,
                  label: labelled(v.labels, locale, () => t(`problem_type.${v.code}`)),
                }))}
              data-testid="prb-type"
            />
          </Form.Item>
          <Form.Item label={t('work_item.field.group_id')} htmlFor="prb-group">
            <GroupPicker
              id="prb-group"
              value={groupId}
              onChange={setGroupId}
              testId="prb-group"
              ariaLabel={t('work_item.field.group_id')}
            />
          </Form.Item>
        </Flex>
        <Space>
          <Button
            type="primary"
            onClick={submit}
            loading={saving}
            disabled={subject.trim() === '' || me === ''}
            data-testid="prb-create"
          >
            {t('problems.create')}
          </Button>
          <Button onClick={() => void navigate('/problems')}>{t('actions.cancel')}</Button>
        </Space>
      </Form>
    </Flex>
  );
}
