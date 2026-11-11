import { Button, Form, Input, Tag, Typography } from 'antd';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import {
  useCatalogCategories,
  useCatalogItem,
  useCatalogItems,
  useRaiseServiceRequest,
  useSession,
} from '@supportx/api-client';
import {
  EmptyText,
  FormPage,
  FormSection,
  lengthLimit,
  LibraryPage,
  PageHeader,
  QuestionField,
  reportError,
  requesterQuestions,
  RichTextView,
  sentAnswers,
  startingAnswers,
  textIn,
  useAppearance,
  useLabel,
  type LibraryGroup,
  type LibraryItem,
  type QuestionValue,
  useLicence,
} from '@supportx/ui';

import { useFormKey } from '../formKey';
import { UserPicker } from '../incidents/pickers';
import { AssetPickerField } from '../incidents/RecordAssets';
import { plainText } from '../incidents/writingText';
import { deliveryText, itemName } from './items';

const SUBJECT_MAX = 250;

/**
 * Raise a service request from the catalog (WP-030, REQ-SR-010): search the items the technician
 * may raise (technician-only items included), then the item's form with the requester picked.
 * The item decides the status, priority and group on the server; one Idempotency-Key per form.
 */
export function NewRequestPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const itemId = params.get('item') ?? undefined;
  const items = useCatalogItems();
  const categories = useCatalogCategories();
  const item = useCatalogItem(itemId);
  const me = useSession().data?.user.id ?? null;
  const raise = useRaiseServiceRequest();
  const { key, done } = useFormKey('new-request'); // QA-2026-11-11 F-01: kept across a remount
  const [search, setSearch] = useState('');
  const [subject, setSubject] = useState('');
  const [assetIds, setAssetIds] = useState<string[]>([]);
  const hasAssets = useLicence().has('assets');
  const [requester, setRequester] = useState<string | null>(me);
  const [answers, setAnswers] = useState<Record<string, QuestionValue> | null>(null);

  if (itemId === undefined || item.data === undefined) {
    // The library template (D-147 template D, QA10-P1-11): a search, then a tab per category
    // with each item's description; only what can be raised now (published service items).
    const raisable = (items.data ?? []).filter(
      (i) => i.status === 'published' && i.kind === 'service',
    );
    const row = (i: (typeof raisable)[number]): LibraryItem => ({
      key: i.id,
      testId: `sr-row-${i.id}`,
      title: (
        <Button
          type="link"
          style={{ padding: 0 }}
          onClick={() => {
            setParams({ item: i.id });
          }}
          data-testid={`sr-item-${i.id}`}
        >
          {itemName(i, locale)}
        </Button>
      ),
      // The description is rich text: a list shows its words, never its markup (QA10V-01).
      searchText: `${itemName(i, locale)} ${plainText(textIn(i.descriptions, locale))}`,
      description: plainText(textIn(i.descriptions, locale)) || undefined,
      tags:
        i.audience === 'technicians' ? (
          <Tag>{t('catalog_item_audience.technicians')}</Tag>
        ) : undefined,
    });
    const tops = (categories.data ?? []).filter((c) => c.parent_id === null && c.enabled);
    const under = (top: string): Set<string> => {
      const ids = new Set([top]);
      for (let grew = true; grew;) {
        grew = false;
        for (const c of categories.data ?? []) {
          if (c.parent_id !== null && ids.has(c.parent_id) && !ids.has(c.id)) {
            ids.add(c.id);
            grew = true;
          }
        }
      }
      return ids;
    };
    // Each item in one tab only, its own category's first (lane C's #315 review): "All" then
    // lists it once.
    const home = new Map<string, string>();
    for (const i of raisable) {
      const top = [i.category_id, ...i.extra_category_ids]
        .map((id) => tops.find((c) => id !== null && under(c.id).has(id)))
        .find((c) => c !== undefined);
      if (top !== undefined) home.set(i.id, top.id);
    }
    const groups: LibraryGroup[] = tops.map((c) => ({
      key: c.id,
      label: textIn(c.names, locale),
      items: raisable.filter((i) => home.get(i.id) === c.id).map(row),
      empty: <EmptyText>{t('requests.catalog_empty_category')}</EmptyText>,
    }));
    const placed = new Set(groups.flatMap((g) => g.items.map((i) => i.key)));
    const others = raisable.filter((i) => !placed.has(i.id)).map(row);
    if (others.length > 0 || groups.length === 0) {
      groups.push({ key: 'other', label: t('requests.catalog_other'), items: others });
    }
    return (
      <LibraryPage
        testId="sr-catalog"
        header={
          <PageHeader
            title={t('requests.new')}
            back={{ label: t('nav.requests'), onClick: () => void navigate('/requests') }}
          />
        }
        groups={groups}
        search={search}
        onSearch={setSearch}
        searchLabel={t('requests.search_catalog')}
        loading={items.isLoading || categories.isLoading}
      />
    );
  }

  const chosen = item.data;
  // The questions the requester answers (a technician raises it as them, WP-031 plan D6).
  const questions = requesterQuestions(chosen.questions);
  const shown = answers ?? startingAnswers(questions);
  const missing = questions.some((q) => {
    const value = shown[q.key];
    return (
      q.required && (value == null || value === '' || (Array.isArray(value) && value.length === 0))
    );
  });
  const ready = subject.trim() !== '' && requester !== null && !missing;
  // What is still missing, said beside the disabled Raise (Haider, 2026-11-10).
  const why =
    subject.trim() === ''
      ? t('requests.why.subject')
      : requester === null
        ? t('requests.why.requester')
        : missing
          ? t('requests.why.answers')
          : null;
  const description = textIn(chosen.descriptions, locale);
  // What is included: the fulfilment steps a requester may see (internal ones stay inside).
  const included = chosen.plan
    .filter((step) => !step.internal)
    .map((step) => textIn(step.title, locale))
    .filter((title) => title !== '');
  const approval =
    chosen.approval === null || chosen.approval.approvers.length === 0
      ? null
      : chosen.approval.approvers.some((a) => a.kind === 'requested_for_manager')
        ? t('requests.context.manager_approves')
        : t('requests.context.someone_approves');
  const delivery = deliveryText(t, chosen.expected_delivery);
  const onBehalf = requester !== null && requester !== me;
  const send = () => {
    if (!ready) return;
    raise
      .mutateAsync({
        key,
        body: {
          subject: subject.trim(),
          requester_id: requester,
          catalog_item_id: chosen.id,
          answers: sentAnswers(shown),
          confirm_lose_access: false,
          ...(assetIds.length > 0 ? { asset_ids: assetIds } : {}),
        },
      })
      .then((made) => {
        done(`/requests/${made.id}`, { replace: true });
      }, reportError);
  };
  return (
    // Template B (D-147, Haider 2026-11-10): the item's context, the request, its questions;
    // one footer bar with Cancel before Raise, at the bottom of the window.
    <Form layout="vertical" component="div" requiredMark>
      <FormPage
        testId="sr-new"
        title={itemName(chosen, locale)}
        back={{
          label: t('requests.back_to_catalog'),
          onClick: () => {
            setParams({});
          },
        }}
        description={textIn(chosen.summaries, locale) || undefined}
        notice={
          why === null ? undefined : (
            <Typography.Text type="secondary" id="sr-send-why" data-testid="sr-send-why">
              {why}
            </Typography.Text>
          )
        }
        cancel={
          <Button onClick={() => void navigate('/requests')} data-testid="sr-cancel">
            {t('actions.cancel')}
          </Button>
        }
        primary={
          <Button
            type="primary"
            disabled={!ready}
            loading={raise.isPending}
            onClick={send}
            aria-describedby={why === null ? undefined : 'sr-send-why'}
            data-testid="sr-send"
          >
            {t('requests.send')}
          </Button>
        }
      >
        {(description !== '' || included.length > 0 || approval !== null || delivery !== null) && (
          <FormSection title={t('requests.context.title')} testId="sr-context">
            {description !== '' && (
              <div data-testid="sr-context-description">
                <RichTextView html={description} />
              </div>
            )}
            {included.length > 0 && (
              <div data-testid="sr-context-included">
                <Typography.Text strong>{t('requests.context.included')}</Typography.Text>
                <ul style={{ marginTop: 4 }}>
                  {included.map((title) => (
                    <li key={title}>
                      <bdi dir="auto">{title}</bdi>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {approval !== null && (
              <Typography.Paragraph data-testid="sr-context-approval">
                {approval}
              </Typography.Paragraph>
            )}
            {delivery !== null && (
              <Typography.Paragraph data-testid="sr-context-delivery">
                {delivery}
              </Typography.Paragraph>
            )}
          </FormSection>
        )}
        <FormSection title={t('requests.section.request')} testId="sr-section-request">
          <Form.Item label={t('work_item.field.subject')} htmlFor="sr-subject" required>
            <Input
              id="sr-subject"
              value={subject}
              count={lengthLimit(SUBJECT_MAX)}
              onChange={(e) => {
                setSubject(e.target.value);
              }}
              data-testid="sr-subject"
            />
          </Form.Item>
          <Form.Item
            label={t('requests.requested_for')}
            htmlFor="sr-requester"
            required
            extra={onBehalf ? t('requests.on_behalf_note') : t('requests.for_yourself_note')}
            style={{ maxWidth: 420 }}
          >
            <UserPicker
              id="sr-requester"
              value={requester}
              onChange={setRequester}
              testId="sr-requester"
              ariaLabel={t('requests.requested_for')}
            />
          </Form.Item>
          {/* REQ-AST-025: the assets it is about, the person's own first. */}
          {hasAssets && (
            <Form.Item label={t('work_item.field.asset_ids')} htmlFor="sr-assets">
              <AssetPickerField
                id="sr-assets"
                value={assetIds}
                onChange={setAssetIds}
                forUser={requester}
                testId="sr-assets"
              />
            </Form.Item>
          )}
        </FormSection>
        {questions.length > 0 && (
          <FormSection title={t('requests.section.details')} testId="sr-section-details">
            {questions.map((q) => (
              <Form.Item
                key={q.key}
                label={textIn(q.label, locale) || q.key}
                extra={textIn(q.help, locale) || undefined}
                htmlFor={`sr-q-${q.key}`}
                required={q.required}
                style={{ maxWidth: 560 }}
              >
                <QuestionField
                  question={q}
                  value={shown[q.key] ?? null}
                  onChange={(value) => {
                    setAnswers({ ...shown, [q.key]: value });
                  }}
                  locale={locale}
                  renderPerson={({ id, value, onChange, disabled }) => (
                    <UserPicker
                      id={id}
                      value={value}
                      onChange={onChange}
                      disabled={disabled}
                      testId={id}
                      ariaLabel={textIn(q.label, locale) || q.key}
                    />
                  )}
                />
              </Form.Item>
            ))}
          </FormSection>
        )}
      </FormPage>
    </Form>
  );
}
