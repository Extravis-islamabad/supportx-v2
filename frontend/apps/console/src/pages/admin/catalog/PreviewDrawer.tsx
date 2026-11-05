import { Alert, Drawer, Form, Typography } from 'antd';
import { useState } from 'react';

import type { CatalogItemInput } from '@supportx/api-client';
import {
  QuestionField,
  RichTextView,
  requesterQuestions,
  startingAnswers,
  textIn,
  useAppearance,
  useLabel,
  type QuestionValue,
} from '@supportx/ui';

/**
 * The item as a requester sees it (WP-031 plan, REQ-CAT-024 AC1): the summary, the description
 * first, then the form with only the questions shown to requesters, in the admin's language.
 * Read-only: nothing here can be submitted. The unsaved draft is what is shown.
 */
export function PreviewDrawer({
  draft,
  onClose,
}: {
  draft: CatalogItemInput;
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const questions = requesterQuestions(draft.questions ?? []);
  const [answers] = useState<Record<string, QuestionValue>>(() => startingAnswers(questions));
  const description = textIn(draft.descriptions ?? undefined, locale);
  return (
    <Drawer
      open
      width={560}
      title={t('catalog_admin.preview_title', { name: textIn(draft.names ?? undefined, locale) })}
      onClose={onClose}
      data-testid="cat-preview-drawer"
    >
      <Alert
        type="info"
        showIcon
        message={t('catalog_admin.preview_note')}
        style={{ marginBottom: 16 }}
      />
      <Typography.Paragraph>{textIn(draft.summaries ?? undefined, locale)}</Typography.Paragraph>
      {description !== '' && <RichTextView html={description} testId="cat-preview-description" />}
      <Form layout="vertical" disabled component="div" style={{ marginTop: 16 }}>
        {questions.map((q) => (
          <Form.Item
            key={q.key}
            label={textIn(q.label, locale) || q.key}
            required={q.required}
            extra={textIn(q.help, locale) || undefined}
            htmlFor={`sr-q-${q.key}`}
          >
            <QuestionField
              question={q}
              value={answers[q.key] ?? null}
              onChange={() => undefined}
              locale={locale}
              disabled
            />
          </Form.Item>
        ))}
      </Form>
    </Drawer>
  );
}
