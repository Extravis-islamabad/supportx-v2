import { Button, Flex, Form, Input, Select, Skeleton, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  usePortalChangeTemplates,
  useRaiseChange,
  type PortalTemplate,
} from '@supportx/api-client';
import {
  FormFooter,
  lengthLimit,
  reportError,
  RichTextField,
  useAppearance,
  useLabel,
} from '@supportx/ui';

import { FormCard } from '../FormCard';
import { FORM_COLUMN } from '../formColumn';
import { ForWhom } from '../requests/ForWhom';

const SUBJECT_MAX = 250;

function templateName(
  template: PortalTemplate,
  locale: string,
  t: ReturnType<typeof useLabel>,
): string {
  return template.labels?.[locale] ?? template.labels?.en ?? t('portal.changes.form');
}

/**
 * Raise a change (WP-045d S4a, REQ-CHG-109): a change form offered to requesters, with only its
 * requester fields. The new change opens as soon as it is saved; one Idempotency-Key per form,
 * so a double tap or a retry never makes two.
 */
export function RaiseChangePage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const templates = usePortalChangeTemplates();
  const raise = useRaiseChange();
  const [templateId, setTemplateId] = useState<string>();
  const [subject, setSubject] = useState('');
  const [onBehalf, setOnBehalf] = useState<string | null>(null);
  const [description, setDescription] = useState('');
  const key = useMemo(() => crypto.randomUUID(), []);

  if (templates.isLoading) return <Skeleton active />;
  const offered = templates.data ?? [];
  const chosen = offered.find((x) => x.id === templateId) ?? offered[0];
  const fields = new Set((chosen?.fields ?? []).map((f) => f.name));
  const required = new Set((chosen?.fields ?? []).filter((f) => f.required).map((f) => f.name));
  const empty = (html: string) => html.replace(/<[^>]*>/g, '').trim() === '';
  // What is still missing, said beside the disabled Send (QA10V-08: never a silent button).
  const why =
    chosen === undefined
      ? t('portal.changes.why.no_form')
      : subject.trim() === ''
        ? t('portal.report.why.subject')
        : required.has('description') && empty(description)
          ? t('portal.report.why.description')
          : null;

  return (
    <Flex vertical gap={16} style={FORM_COLUMN}>
      <Link to="/changes">{t('portal.changes.back')}</Link>
      <Typography.Title level={1} style={{ margin: 0 }}>
        {t('portal.changes.raise')}
      </Typography.Title>
      <FormCard testId="portal-change-form">
        <Form
          layout="vertical"
          requiredMark
          onFinish={() => {
            if (why !== null || chosen === undefined) return;
            raise.mutate(
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
                  void navigate(`/changes/${made.id}`, { replace: true });
                },
                onError: reportError,
              },
            );
          }}
        >
          {offered.length > 1 && (
            <Form.Item label={t('portal.changes.form')} htmlFor="portal-change-template">
              <Select
                id="portal-change-template"
                value={chosen?.id}
                onChange={(value: string) => {
                  setTemplateId(value);
                }}
                options={offered.map((x) => ({ value: x.id, label: templateName(x, locale, t) }))}
                data-testid="portal-change-template"
              />
            </Form.Item>
          )}
          <Form.Item label={t('portal.report.for_whom')}>
            <ForWhom value={onBehalf} onChange={setOnBehalf} />
          </Form.Item>
          <Form.Item label={t('portal.report.subject')} htmlFor="portal-change-subject" required>
            <Input
              id="portal-change-subject"
              size="large"
              value={subject}
              count={lengthLimit(SUBJECT_MAX)}
              onChange={(event) => {
                setSubject(event.target.value);
              }}
              data-testid="portal-change-subject"
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
                placeholder={t('portal.changes.description_hint')}
                testId="portal-change-description"
              />
            </Form.Item>
          )}
          <FormFooter
            testId="portal-change-footer"
            notice={
              why === null ? undefined : (
                <Typography.Text
                  type="secondary"
                  id="portal-change-why"
                  data-testid="portal-change-why"
                >
                  {why}
                </Typography.Text>
              )
            }
            cancel={
              <Button
                size="large"
                onClick={() => void navigate('/changes')}
                data-testid="portal-change-cancel"
              >
                {t('actions.cancel')}
              </Button>
            }
            primary={
              <Button
                type="primary"
                size="large"
                htmlType="submit"
                disabled={why !== null}
                loading={raise.isPending}
                aria-describedby={why === null ? undefined : 'portal-change-why'}
                data-testid="portal-change-send"
              >
                {t('portal.changes.send')}
              </Button>
            }
          />
        </Form>
      </FormCard>
    </Flex>
  );
}
