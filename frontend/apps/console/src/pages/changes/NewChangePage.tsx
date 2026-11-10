import { Button, Col, Form, Input, Row, Select, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import {
  useChangePrefill,
  useChangeTemplates,
  useCreateChange,
  useSession,
  useStagedSettings,
  type ChangeInput,
} from '@supportx/api-client';
import {
  FormPage,
  FormProblem,
  FormSection,
  RichTextField,
  usePageCrumbs,
  WriteButton,
  useAppearance,
  useFormProblem,
  useLabel,
  lengthLimit,
} from '@supportx/ui';

import { UserPicker } from '../incidents/pickers';
import { listValueName, stageName } from '../releases/labels';
import { templateName } from './labels';

/**
 * A new change on template B (D-147; REQ-CHG-001, -002, -005, -011): the template first (it binds
 * the type and the path, shown read-only), then the title, the description, the requester and
 * the reason for change. Raised from another record (`?from=`), its values come prefilled and the
 * two are linked. On create the change opens on its risk questionnaire (REQ-CHG-057), which is
 * the template's and so needs the change to exist. One Idempotency-Key per form.
 */
export function NewChangePage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const from = params.get('from');
  const me = useSession().data?.user.id ?? null;
  const templates = useChangeTemplates();
  const settings = useStagedSettings('changes');
  const prefill = useChangePrefill(from);
  const create = useCreateChange();
  const problem = useFormProblem();
  const key = useMemo(() => crypto.randomUUID(), []);
  const offered = (templates.data ?? []).filter((x) => !x.disabled);
  const fallback = offered.find((x) => x.is_default)?.id;
  const [templateId, setTemplateId] = useState<string>();
  const chosen = offered.find((x) => x.id === (templateId ?? fallback));
  // Null: not touched, so the prefill (once it arrives) shows; typing takes over from it.
  const [typedSubject, setSubject] = useState<string | null>(null);
  const [typedDescription, setDescription] = useState<string | null>(null);
  const [pickedRequester, setRequester] = useState<string | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const reasons = (settings.data?.own_lists?.change_reason ?? []).filter((v) => !v.disabled);
  const filledFrom = prefill.data;
  const subject = typedSubject ?? filledFrom?.subject ?? '';
  const description = typedDescription ?? filledFrom?.description ?? null;
  const requester = pickedRequester ?? filledFrom?.requester_id ?? null;
  const submit = () => {
    create.mutate(
      {
        key,
        body: {
          subject: subject.trim(),
          description,
          requester_id: requester ?? me ?? '',
          template_id: chosen?.id ?? null,
          change_reason: reason,
          from_record_id: filledFrom?.from_record_id ?? null,
          // The prefill's codes come from the record it is raised from, of the same lists.
          impact: (filledFrom?.impact ?? null) as ChangeInput['impact'],
          urgency: (filledFrom?.urgency ?? null) as ChangeInput['urgency'],
          site_id: filledFrom?.site_id ?? null,
          confirm_lose_access: false,
        },
      },
      {
        onSuccess: (made) => void navigate(`/changes/${made.id}?tab=risk`),
        onError: (error) => {
          problem.show(error);
        },
      },
    );
  };
  usePageCrumbs([{ label: t('nav.changes'), path: '/changes' }, { label: t('changes.new') }]);
  return (
    <FormPage
      testId="new-change"
      title={t('changes.new')}
      description={t('changes.new_help')}
      back={{ label: t('nav.changes'), onClick: () => void navigate('/changes') }}
      notice={
        <Typography.Text type="secondary">
          {t('changes.starts_in', { stage: stageName(t, 'submission') })}
        </Typography.Text>
      }
      cancel={
        <Button onClick={() => void navigate('/changes')} data-testid="change-cancel">
          {t('actions.cancel')}
        </Button>
      }
      primary={
        <WriteButton
          type="primary"
          disabled={subject.trim() === '' || chosen === undefined}
          whyDisabled={t(chosen === undefined ? 'changes.why.template' : 'changes.why.subject')}
          loading={create.isPending}
          onClick={submit}
          data-testid="change-save"
        >
          {t('changes.create')}
        </WriteButton>
      }
    >
      <FormSection title={t('changes.section.change')} testId="change-section">
        <Form layout="vertical" data-testid="change-form" component="div">
          {filledFrom !== undefined && (
            <Typography.Paragraph type="secondary" data-testid="change-from">
              {t('changes.raised_from')}
            </Typography.Paragraph>
          )}
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item label={t('changes.template')} required htmlFor="change-template">
                <Select
                  id="change-template"
                  value={chosen?.id}
                  onChange={setTemplateId}
                  loading={templates.isPending}
                  placeholder={templates.isPending ? t('shell.loading') : undefined}
                  data-testid="change-template"
                  options={offered.map((x) => ({
                    value: x.id,
                    label: templateName(t, locale, x),
                  }))}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t('work_item.field.change_reason')} htmlFor="change-reason">
                <Select
                  id="change-reason"
                  allowClear
                  value={reason ?? undefined}
                  onChange={(v: string | undefined) => {
                    setReason(v ?? null);
                  }}
                  placeholder={t('form.choose')}
                  data-testid="change-reason"
                  options={reasons.map((v) => ({
                    value: v.code,
                    label: listValueName(t, locale, 'change_reason', v, v.code),
                  }))}
                />
              </Form.Item>
            </Col>
          </Row>
          {chosen !== undefined && (
            <Typography.Paragraph type="secondary" data-testid="change-path">
              {t('releases.path_of_template', {
                path: t(`stage_path.${chosen.stage_path ?? 'default'}`),
              })}
            </Typography.Paragraph>
          )}
          <Form.Item label={t('work_item.field.subject')} required htmlFor="change-subject">
            <Input
              id="change-subject"
              value={subject}
              count={lengthLimit(250)}
              onChange={(e) => {
                setSubject(e.target.value);
              }}
              data-testid="change-subject"
            />
          </Form.Item>
          <Form.Item label={t('work_item.field.description')}>
            <RichTextField
              label={t('work_item.field.description')}
              value={description}
              onChange={setDescription}
              testId="change-description"
            />
          </Form.Item>
          <Form.Item label={t('work_item.field.requester_id')} htmlFor="change-requester">
            <UserPicker
              id="change-requester"
              value={requester ?? me}
              onChange={setRequester}
              testId="change-requester"
              ariaLabel={t('work_item.field.requester_id')}
            />
          </Form.Item>
          <FormProblem problem={problem} />
        </Form>
      </FormSection>
    </FormPage>
  );
}
