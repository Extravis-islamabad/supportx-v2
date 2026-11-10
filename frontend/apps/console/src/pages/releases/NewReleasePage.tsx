import { Button, Form, Input, Select, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';

import { useCreateRelease, useReleaseTemplates, useSession } from '@supportx/api-client';
import {
  FormPage,
  FormProblem,
  FormSection,
  usePageCrumbs,
  WriteButton,
  useAppearance,
  useFormProblem,
  useLabel,
  lengthLimit,
} from '@supportx/ui';

import { UserPicker } from '../incidents/pickers';
import { stageName, templateName } from './labels';

/**
 * A new release (REQ-REL-007): the template first, the default preselected; its path is shown,
 * read-only (there is no separate workflow picker). Only the title is required (REQ-REL-002
 * AC1). One Idempotency-Key per form, so saving twice quickly makes one release.
 */
export function NewReleasePage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const me = useSession().data?.user.id ?? null;
  const templates = useReleaseTemplates();
  const create = useCreateRelease();
  const problem = useFormProblem();
  const key = useMemo(() => crypto.randomUUID(), []);
  const offered = (templates.data ?? []).filter((x) => !x.disabled);
  const fallback = offered.find((x) => x.is_default)?.id;
  const [templateId, setTemplateId] = useState<string>();
  const chosen = offered.find((x) => x.id === (templateId ?? fallback));
  const [subject, setSubject] = useState('');
  const [requester, setRequester] = useState<string | null>(null);
  const submit = () => {
    create.mutate(
      {
        key,
        body: {
          subject: subject.trim(),
          requester_id: requester ?? me ?? '',
          template_id: chosen?.id ?? null,
          confirm_lose_access: false,
        },
      },
      {
        onSuccess: (made) => void navigate(`/releases/${made.id}`),
        onError: (error) => {
          problem.show(error);
        },
      },
    );
  };
  // The path in the top bar and the tab's title (QA6-REL-04).
  usePageCrumbs([{ label: t('nav.releases'), path: '/releases' }, { label: t('releases.new') }]);
  // Template B (D-147): the form in a section card, Cancel before Create in the sticky footer.
  return (
    <FormPage
      testId="new-release"
      title={t('releases.new')}
      description={t('releases.new_help')}
      back={{ label: t('nav.releases'), onClick: () => void navigate('/releases') }}
      notice={
        <Typography.Text type="secondary">
          {t('releases.starts_in', { stage: stageName(t, 'submission') })}
        </Typography.Text>
      }
      cancel={
        <Button onClick={() => void navigate('/releases')} data-testid="release-cancel">
          {t('actions.cancel')}
        </Button>
      }
      primary={
        <WriteButton
          type="primary"
          disabled={subject.trim() === '' || chosen === undefined}
          loading={create.isPending}
          onClick={submit}
          data-testid="release-save"
        >
          {t('releases.create')}
        </WriteButton>
      }
    >
      <FormSection title={t('releases.section.release')} testId="release-section">
        <Form layout="vertical" data-testid="release-form" component="div">
          <Form.Item label={t('releases.template')} required htmlFor="release-template">
            <Select
              id="release-template"
              value={chosen?.id}
              onChange={setTemplateId}
              loading={templates.isPending}
              data-testid="release-template"
              options={offered.map((x) => ({ value: x.id, label: templateName(t, locale, x) }))}
            />
          </Form.Item>
          {chosen?.stage_path && (
            <Typography.Paragraph type="secondary" data-testid="release-path">
              {t('releases.path_of_template', { path: t(`stage_path.${chosen.stage_path}`) })}
            </Typography.Paragraph>
          )}
          <Form.Item label={t('work_item.field.subject')} required htmlFor="release-subject">
            <Input
              id="release-subject"
              value={subject}
              count={lengthLimit(250)}
              onChange={(e) => {
                setSubject(e.target.value);
              }}
              data-testid="release-subject"
            />
          </Form.Item>
          <Form.Item label={t('work_item.field.requester_id')} htmlFor="release-requester">
            <UserPicker
              id="release-requester"
              value={requester ?? me}
              onChange={setRequester}
              testId="release-requester"
              ariaLabel={t('work_item.field.requester_id')}
            />
          </Form.Item>
          <FormProblem problem={problem} />
        </Form>
      </FormSection>
    </FormPage>
  );
}
