import { Button, Flex, Form, Input, Select, Skeleton, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';

import { usePortalTemplates, useReportIssue, type PortalTemplate } from '@supportx/api-client';
import {
  FormFooter,
  lengthLimit,
  reportError,
  RichTextField,
  useAppearance,
  useLabel,
} from '@supportx/ui';

import { AttachFiles } from './attachFiles';
import { ForWhom } from './ForWhom';
import { useFilesToAttach } from './useFilesToAttach';
import { FormCard } from '../FormCard';
import { FORM_COLUMN } from '../formColumn';

const SUBJECT_MAX = 250;

function templateName(
  template: PortalTemplate,
  locale: string,
  t: ReturnType<typeof useLabel>,
): string {
  const own = template.labels?.[locale] ?? template.labels?.en;
  if (own) return own;
  return template.code ? t(`incident_template.${template.code}`) : t('portal.report.form');
}

/**
 * Report an issue (REQ-INC-028): the form of a template offered to requesters, with only the
 * fields they may fill in. The new ID shows at once: the record opens as soon as it is saved.
 * One Idempotency-Key per form, so a double tap or a retry never makes two incidents.
 */
export function ReportPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const templates = usePortalTemplates();
  const report = useReportIssue();
  // A catalog "report a problem" entry opens this form with its template (WP-031 plan D10).
  const [params] = useSearchParams();
  const [templateId, setTemplateId] = useState<string | undefined>(
    params.get('template') ?? undefined,
  );
  const [subject, setSubject] = useState(params.get('subject') ?? ''); // from search (WP-032 D2)
  const [onBehalf, setOnBehalf] = useState<string | null>(null);
  const [description, setDescription] = useState('');
  const key = useMemo(() => crypto.randomUUID(), []);
  const files = useFilesToAttach();

  if (templates.isLoading) return <Skeleton active />;
  const offered = templates.data ?? [];
  const chosen = offered.find((x) => x.id === templateId) ?? offered[0];
  const fields = new Set((chosen?.fields ?? []).map((f) => f.name));
  const required = new Set((chosen?.fields ?? []).filter((f) => f.required).map((f) => f.name));
  const empty = (html: string) => html.replace(/<[^>]*>/g, '').trim() === '';
  const ready =
    chosen !== undefined &&
    subject.trim() !== '' &&
    !(required.has('description') && empty(description));
  // What is still missing, said beside the disabled Send (QA10V-08: never a silent button).
  const why =
    subject.trim() === ''
      ? t('portal.report.why.subject')
      : required.has('description') && empty(description)
        ? t('portal.report.why.description')
        : null;

  return (
    <Flex vertical gap={16} style={FORM_COLUMN}>
      <Link to="/requests">{t('portal.request.back')}</Link>
      <Typography.Title level={1} style={{ margin: 0 }}>
        {t('portal.report.title')}
      </Typography.Title>
      <FormCard testId="portal-report-form">
        <Form
          layout="vertical"
          requiredMark
          onFinish={() => {
            if (!ready) return;
            report.mutate(
              {
                key,
                body: {
                  template_id: chosen.id,
                  subject: subject.trim(),
                  ...(fields.has('description') && !empty(description) ? { description } : {}),
                  ...(onBehalf !== null ? { on_behalf_of_id: onBehalf } : {}),
                },
              },
              {
                onSuccess: (made) => {
                  void files
                    .attach(made.id)
                    .then(() => navigate(`/requests/${made.id}`, { replace: true }));
                },
                onError: reportError,
              },
            );
          }}
        >
          {offered.length > 1 && (
            <Form.Item label={t('portal.report.form')} htmlFor="portal-report-template">
              <Select
                id="portal-report-template"
                value={chosen?.id}
                onChange={(value: string) => {
                  setTemplateId(value);
                }}
                options={offered.map((x) => ({ value: x.id, label: templateName(x, locale, t) }))}
                data-testid="portal-report-template"
              />
            </Form.Item>
          )}
          <Form.Item label={t('portal.report.for_whom')}>
            <ForWhom value={onBehalf} onChange={setOnBehalf} />
          </Form.Item>
          <Form.Item label={t('portal.report.subject')} htmlFor="portal-report-subject" required>
            <Input
              id="portal-report-subject"
              size="large"
              value={subject}
              count={lengthLimit(SUBJECT_MAX)}
              onChange={(event) => {
                setSubject(event.target.value);
              }}
              data-testid="portal-report-subject"
            />
          </Form.Item>
          {fields.has('description') && (
            <Form.Item
              label={t('portal.report.description')}
              required={required.has('description')}
            >
              <RichTextField
                value={description}
                onChange={setDescription}
                label={t('portal.report.description')}
                placeholder={t('portal.report.description_hint')}
                testId="portal-report-description"
              />
            </Form.Item>
          )}
          <Form.Item label={t('portal.report.files')}>
            <AttachFiles
              files={files.files}
              keep={files.keep}
              remove={files.remove}
              testId="portal-report"
            />
          </Form.Item>
          {/* Template B's footer (D-147; QA10V-08): Cancel, then Send, with why it waits. */}
          <FormFooter
            testId="portal-report-footer"
            notice={
              why === null ? undefined : (
                <Typography.Text
                  type="secondary"
                  id="portal-report-why"
                  data-testid="portal-report-why"
                >
                  {why}
                </Typography.Text>
              )
            }
            cancel={
              <Button
                size="large"
                onClick={() => void navigate('/requests')}
                data-testid="portal-report-cancel"
              >
                {t('actions.cancel')}
              </Button>
            }
            primary={
              <Button
                type="primary"
                size="large"
                htmlType="submit"
                disabled={!ready}
                loading={report.isPending || files.sending}
                aria-describedby={why === null ? undefined : 'portal-report-why'}
                data-testid="portal-report-send"
              >
                {t('portal.report.send')}
              </Button>
            }
          />
        </Form>
      </FormCard>
    </Flex>
  );
}
