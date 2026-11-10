import { Button, Flex, Form, Input, Tag } from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';

import {
  useCatalogCategories,
  useCatalogItem,
  useCatalogItems,
  useRaiseServiceRequest,
  useSession,
} from '@supportx/api-client';
import {
  lengthLimit,
  LibraryPage,
  PageHeader,
  QuestionField,
  reportError,
  requesterQuestions,
  sentAnswers,
  startingAnswers,
  textIn,
  useAppearance,
  useLabel,
  type LibraryGroup,
  type LibraryItem,
  type QuestionValue,
} from '@supportx/ui';

import { UserPicker } from '../incidents/pickers';
import { itemName } from './items';

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
  const key = useMemo(() => crypto.randomUUID(), []);
  const [search, setSearch] = useState('');
  const [subject, setSubject] = useState('');
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
      searchText: `${itemName(i, locale)} ${textIn(i.descriptions, locale)}`,
      description: textIn(i.descriptions, locale) || undefined,
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
    const groups: LibraryGroup[] = tops.map((c) => {
      const ids = under(c.id);
      return {
        key: c.id,
        label: textIn(c.names, locale),
        items: raisable
          .filter((i) =>
            [i.category_id, ...i.extra_category_ids].some((id) => id !== null && ids.has(id)),
          )
          .map(row),
      };
    });
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
  return (
    <Flex vertical gap={16} style={{ maxWidth: 760 }}>
      <PageHeader
        title={itemName(chosen, locale)}
        back={{
          label: t('requests.back_to_catalog'),
          onClick: () => {
            setParams({});
          },
        }}
      />
      <Form
        layout="vertical"
        onFinish={() => {
          if (!ready) return;
          raise.mutate(
            {
              key,
              body: {
                subject: subject.trim(),
                requester_id: requester,
                catalog_item_id: chosen.id,
                answers: sentAnswers(shown),
                confirm_lose_access: false,
              },
            },
            {
              onSuccess: (made) => void navigate(`/requests/${made.id}`, { replace: true }),
              onError: reportError,
            },
          );
        }}
      >
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
        <Form.Item label={t('requests.requested_for')} htmlFor="sr-requester" required>
          <UserPicker
            id="sr-requester"
            value={requester}
            onChange={setRequester}
            testId="sr-requester"
            ariaLabel={t('requests.requested_for')}
          />
        </Form.Item>
        {questions.map((q) => (
          <Form.Item
            key={q.key}
            label={textIn(q.label, locale) || q.key}
            extra={textIn(q.help, locale) || undefined}
            htmlFor={`sr-q-${q.key}`}
            required={q.required}
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
        <Button
          type="primary"
          htmlType="submit"
          disabled={!ready}
          loading={raise.isPending}
          data-testid="sr-send"
        >
          {t('requests.send')}
        </Button>
        <Link to="/requests" style={{ marginInlineStart: 12 }}>
          {t('actions.cancel')}
        </Link>
      </Form>
    </Flex>
  );
}
