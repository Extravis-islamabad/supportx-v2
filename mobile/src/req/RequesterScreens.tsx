import { useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import {
  isApiError,
  useAnnouncementFeed,
  useCatalogItem,
  useCatalogItems,
  useKbSuggestions,
  usePortalIncidents,
  usePortalRequests,
  useRaiseServiceRequest,
  useReportIssue,
  type components,
} from '@supportx/api-client';
import { useLabels, type Locale } from '@supportx/labels';
import { usePersonalChannel } from '@supportx/realtime';

import { Button } from '../components/Button';
import { Screen } from '../components/Screen';
import { useMe } from '../session';
import { useSettings } from '../settings';
import { SPACE, usePalette } from '../theme';
import { portalStatusTone, TONES } from '../tones';
import { Card, Chip, Field, Heading, Muted, Row, useToast } from '../ui';

type Question = components['schemas']['QuestionIO'];
type Urgency = components['schemas']['Urgency'];

function newKey(): string {
  return crypto.randomUUID();
}

/** A text the tenant wrote per language: the user's, else English, else any. */
export function localised(texts: Record<string, string> | undefined, locale: Locale): string {
  if (texts === undefined) return '';
  return texts[locale] ?? texts.en ?? Object.values(texts)[0] ?? '';
}

function useFail() {
  const t = useLabels();
  const show = useToast((state) => state.show);
  return (error: unknown) => {
    show(t(isApiError(error) ? error.messageKey : 'errors.internal_error'));
  };
}

/** One of my records in a list: incident or service request, with its portal status. */
function RecordRow({
  kind,
  id,
  displayId,
  subject,
  status,
}: {
  kind: 'incident' | 'request';
  id: string;
  displayId: string;
  subject: string;
  status: string;
}) {
  const t = useLabels();
  const palette = usePalette();
  return (
    <Card
      testID={`record-${displayId}`}
      label={`${displayId} ${subject}`}
      onPress={() => {
        router.push(`/r/requests/${kind}/${id}`);
      }}
    >
      <Row>
        <Text style={[styles.id, { color: palette.textSecondary }]}>{displayId}</Text>
        <Chip text={t(`portal_status.${status}`)} tone={portalStatusTone(status)} />
      </Row>
      <Text style={[styles.subject, { color: palette.text }]}>{subject}</Text>
    </Card>
  );
}

/** Requester home: report or request, announcements, and what is open for me. */
export function RequesterHome() {
  const t = useLabels();
  const me = useMe();
  const feed = useAnnouncementFeed();
  const incidents = usePortalIncidents({ state: 'open' });
  const requests = usePortalRequests('open');
  usePersonalChannel(() => {
    void incidents.refetch();
    void requests.refetch();
  });
  const announcements = feed.data?.items ?? [];
  const open = [
    ...(incidents.data?.pages.flatMap((page) => page.items) ?? []).map((item) => ({
      kind: 'incident' as const,
      item,
    })),
    ...(requests.data?.items ?? []).map((item) => ({ kind: 'request' as const, item })),
  ].sort((a, b) => b.item.updated_at.localeCompare(a.item.updated_at));

  return (
    <Screen
      title={t('mobile.home.greeting', { name: me.data?.user.display_name ?? '' })}
      subtitle={me.data?.tenant.name}
      refreshing={incidents.isRefetching}
      onRefresh={() => {
        void incidents.refetch();
        void requests.refetch();
        void feed.refetch();
      }}
    >
      {announcements.map((item) => (
        <Card
          key={item.id}
          testID={`announcement-${item.display_id}`}
          style={{ backgroundColor: TONES.warning.bg, borderColor: '#FEDF89' }}
        >
          <Text style={{ color: TONES.warning.fg, fontWeight: '700' }}>{item.title}</Text>
          <Text style={{ color: '#1B1530' }}>{item.body.replace(/<[^>]+>/g, ' ').trim()}</Text>
        </Card>
      ))}
      <View style={styles.actions}>
        <View style={styles.flex}>
          <Button
            testID="go-report"
            title={t('mobile.req.report')}
            onPress={() => {
              router.replace('/r/report');
            }}
          />
        </View>
        <View style={styles.flex}>
          <Button
            testID="go-catalog"
            variant="plain"
            title={t('mobile.req.request')}
            onPress={() => {
              router.push('/r/catalog');
            }}
          />
        </View>
      </View>
      <Heading text={t('mobile.req.open_now')} />
      {open.length === 0 && !incidents.isPending ? (
        <Muted testID="open-empty" text={t('mobile.req.nothing_open')} />
      ) : null}
      {open.map(({ kind, item }) => (
        <RecordRow
          key={item.id}
          kind={kind}
          id={item.id}
          displayId={item.display_id}
          subject={item.subject}
          status={item.portal_status}
        />
      ))}
    </Screen>
  );
}

const URGENCIES: Urgency[] = ['low', 'medium', 'high'];

/** Report a problem: knowledge suggestions while typing; urgency; one key per form. */
export function ReportProblem() {
  const t = useLabels();
  const palette = usePalette();
  const locale = useSettings((state) => state.locale);
  const show = useToast((state) => state.show);
  const fail = useFail();
  const report = useReportIssue();
  const [subject, setSubject] = useState('');
  const [details, setDetails] = useState('');
  const [urgency, setUrgency] = useState<Urgency>('medium');
  const [subjectError, setSubjectError] = useState(false);
  const [key, setKey] = useState(newKey);
  const suggestions = useKbSuggestions(`${subject} ${details}`, locale === 'ar' ? 'ar' : 'en');

  const send = () => {
    if (subject.trim() === '') {
      setSubjectError(true);
      return;
    }
    report.mutate(
      {
        body: {
          subject: subject.trim(),
          description: details.trim() === '' ? null : details.trim(),
          urgency,
        },
        key,
      },
      {
        onSuccess: (made) => {
          show(t('mobile.toast.reported', { id: made.display_id }));
          setSubject('');
          setDetails('');
          setKey(newKey());
          router.push(`/r/requests/incident/${made.id}`);
        },
        onError: fail,
      },
    );
  };

  return (
    <Screen title={t('mobile.req.report')}>
      <Field
        testID="report-subject"
        label={`${t('mobile.req.subject')} *`}
        value={subject}
        onChange={(text) => {
          setSubject(text);
          setSubjectError(false);
        }}
        lines={1}
        placeholder={t('mobile.req.subject_placeholder')}
        error={subjectError ? t('mobile.req.subject_required') : null}
      />
      {(suggestions.data ?? []).length > 0 ? (
        <Card testID="suggestions">
          <Text style={[styles.strong, { color: palette.text }]}>
            {t('mobile.req.suggestions')}
          </Text>
          {(suggestions.data ?? []).map((article) => (
            <View key={article.id} style={styles.article}>
              <Text style={{ color: palette.link, fontWeight: '600' }}>{article.title}</Text>
              <Muted text={(article.snippet ?? []).map((part) => part.text).join('')} />
            </View>
          ))}
        </Card>
      ) : null}
      <Field
        testID="report-details"
        label={t('mobile.req.details')}
        value={details}
        onChange={setDetails}
        lines={4}
      />
      <Text style={[styles.strong, { color: palette.text }]}>{t('mobile.req.urgency')}</Text>
      <View style={styles.chips}>
        {URGENCIES.map((value) => {
          const on = value === urgency;
          return (
            <Pressable
              key={value}
              testID={`urgency-${value}`}
              accessibilityRole="radio"
              accessibilityState={{ selected: on }}
              onPress={() => {
                setUrgency(value);
              }}
              style={[
                styles.choice,
                {
                  backgroundColor: on ? palette.primary : palette.background,
                  borderColor: on ? palette.primary : palette.strongBorder,
                },
              ]}
            >
              <Text style={{ color: on ? palette.onPrimary : palette.text, fontWeight: '600' }}>
                {t(`urgency.${value}`)}
              </Text>
            </Pressable>
          );
        })}
      </View>
      <Button
        testID="report-send"
        title={t('mobile.req.send')}
        busy={report.isPending}
        onPress={send}
      />
    </Screen>
  );
}

/** The catalog: what can be requested, and whether a manager approves it first. */
export function Catalog() {
  const t = useLabels();
  const palette = usePalette();
  const locale = useSettings((state) => state.locale);
  const items = useCatalogItems();
  const available = (items.data ?? []).filter((item) => item.enabled);
  return (
    <Screen title={t('mobile.req.request')}>
      {items.isPending ? <ActivityIndicator color={palette.primary} /> : null}
      {!items.isPending && available.length === 0 ? (
        <Muted testID="catalog-empty" text={t('mobile.req.catalog_empty')} />
      ) : null}
      {available.map((item) => (
        <Card
          key={item.id}
          testID={`catalog-${item.id}`}
          label={localised(item.names, locale)}
          onPress={() => {
            router.push(`/r/catalog/${item.id}`);
          }}
        >
          <Text style={[styles.subject, { color: palette.text }]}>
            {localised(item.names, locale)}
          </Text>
          <Muted
            text={t(
              item.approval === null ? 'mobile.req.no_approval' : 'mobile.req.needs_approval',
            )}
          />
        </Card>
      ))}
    </Screen>
  );
}

function QuestionField({
  question,
  value,
  onChange,
  locale,
}: {
  question: Question;
  value: string;
  onChange: (value: string) => void;
  locale: Locale;
}) {
  const palette = usePalette();
  const label = `${localised(question.label, locale)}${question.required ? ' *' : ''}`;
  if (question.kind === 'choice') {
    return (
      <View style={styles.question}>
        <Text style={[styles.strong, { color: palette.text }]}>{label}</Text>
        <View style={styles.chips}>
          {(question.options ?? []).map((option) => {
            const on = option === value;
            return (
              <Pressable
                key={option}
                accessibilityRole="radio"
                accessibilityState={{ selected: on }}
                onPress={() => {
                  onChange(option);
                }}
                style={[
                  styles.choice,
                  {
                    backgroundColor: on ? palette.primary : palette.background,
                    borderColor: on ? palette.primary : palette.strongBorder,
                  },
                ]}
              >
                <Text style={{ color: on ? palette.onPrimary : palette.text }}>{option}</Text>
              </Pressable>
            );
          })}
        </View>
      </View>
    );
  }
  return (
    <Field
      testID={`question-${question.key}`}
      label={label}
      value={value}
      onChange={onChange}
      lines={question.kind === 'long_text' ? 4 : 1}
      placeholder={question.kind === 'date' ? 'YYYY-MM-DD' : undefined}
    />
  );
}

/** One catalog item: its description, its questions, and the request. */
export function CatalogItem({ id }: { id: string }) {
  const t = useLabels();
  const palette = usePalette();
  const locale = useSettings((state) => state.locale);
  const show = useToast((state) => state.show);
  const fail = useFail();
  const me = useMe();
  const item = useCatalogItem(id);
  const raise = useRaiseServiceRequest();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [missing, setMissing] = useState(false);
  const [key, setKey] = useState(newKey);
  const data = item.data;
  if (data === undefined) {
    return (
      <Screen title={t('mobile.req.request')}>
        <ActivityIndicator color={palette.primary} />
      </Screen>
    );
  }
  const name = localised(data.names, locale);
  const send = () => {
    const unanswered = data.questions.some(
      (question) => question.required && (answers[question.key] ?? '').trim() === '',
    );
    if (unanswered) {
      setMissing(true);
      return;
    }
    if (me.data === undefined) return;
    raise.mutate(
      {
        body: {
          subject: name,
          requester_id: me.data.user.id,
          catalog_item_id: data.id,
          answers: Object.fromEntries(
            data.questions.map((question) => [
              question.key,
              question.kind === 'number' && answers[question.key]
                ? Number(answers[question.key])
                : (answers[question.key] ?? null),
            ]),
          ),
          channel: 'mobile_app',
          confirm_lose_access: false,
        },
        key,
      },
      {
        onSuccess: (made) => {
          show(t('mobile.toast.requested', { id: made.display_id }));
          setKey(newKey());
          router.replace(`/r/requests/request/${made.id}`);
        },
        onError: fail,
      },
    );
  };
  return (
    <Screen
      title={name}
      aside={
        <Button
          variant="plain"
          title={t('mobile.back')}
          onPress={() => {
            router.back();
          }}
        />
      }
    >
      <Card>
        <Text style={{ color: palette.text }}>{localised(data.descriptions, locale)}</Text>
        <Muted
          text={t(data.approval === null ? 'mobile.req.no_approval' : 'mobile.req.needs_approval')}
        />
      </Card>
      {data.questions.map((question) => (
        <QuestionField
          key={question.key}
          question={question}
          locale={locale}
          value={answers[question.key] ?? ''}
          onChange={(value) => {
            setMissing(false);
            setAnswers((current) => ({ ...current, [question.key]: value }));
          }}
        />
      ))}
      {missing ? (
        <Text accessibilityLiveRegion="polite" style={{ color: palette.error, fontWeight: '600' }}>
          {t('mobile.req.answer_required')}
        </Text>
      ) : null}
      <Button
        testID="request-send"
        title={t('mobile.req.send_request')}
        busy={raise.isPending}
        onPress={send}
      />
    </Screen>
  );
}

/** Everything I raised: open first, then the rest. */
export function MyRequests() {
  const t = useLabels();
  const palette = usePalette();
  const queryClient = useQueryClient();
  const incidents = usePortalIncidents({});
  const requests = usePortalRequests(undefined);
  usePersonalChannel(() => {
    void queryClient.invalidateQueries({ queryKey: ['portal'] });
  });
  const all = [
    ...(incidents.data?.pages.flatMap((page) => page.items) ?? []).map((item) => ({
      kind: 'incident' as const,
      item,
    })),
    ...(requests.data?.items ?? []).map((item) => ({ kind: 'request' as const, item })),
  ].sort((a, b) => b.item.updated_at.localeCompare(a.item.updated_at));
  return (
    <Screen
      title={t('mobile.nav.requests')}
      refreshing={incidents.isRefetching}
      onRefresh={() => {
        void queryClient.invalidateQueries({ queryKey: ['portal'] });
      }}
    >
      {incidents.isPending ? <ActivityIndicator color={palette.primary} /> : null}
      {!incidents.isPending && all.length === 0 ? (
        <Muted testID="requests-empty" text={t('mobile.req.nothing_yet')} />
      ) : null}
      {all.map(({ kind, item }) => (
        <RecordRow
          key={item.id}
          kind={kind}
          id={item.id}
          displayId={item.display_id}
          subject={item.subject}
          status={item.portal_status}
        />
      ))}
    </Screen>
  );
}

const styles = StyleSheet.create({
  id: { fontSize: 12, fontWeight: '600' },
  subject: { fontSize: 15, fontWeight: '600' },
  strong: { fontSize: 14, fontWeight: '600' },
  actions: { flexDirection: 'row', gap: SPACE.sm },
  flex: { flex: 1 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm },
  choice: {
    minHeight: 40,
    paddingHorizontal: 14,
    borderRadius: 12,
    borderWidth: 1,
    justifyContent: 'center',
  },
  question: { gap: 6 },
  article: { gap: 2, paddingVertical: 4 },
});
