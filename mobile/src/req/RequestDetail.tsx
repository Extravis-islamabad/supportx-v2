import { useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import {
  isApiError,
  useAnswerFix,
  useAnswerRequest,
  usePortalConversation,
  usePortalIncident,
  usePortalReply,
  usePortalRequest,
  usePortalRequestSteps,
} from '@supportx/api-client';
import { useLabels } from '@supportx/labels';
import { useRecordChannel } from '@supportx/realtime';

import { Button } from '../components/Button';
import { Screen } from '../components/Screen';
import { SPACE, usePalette } from '../theme';
import { portalStatusTone, TONES } from '../tones';
import { Card, Chip, Field, Heading, Muted, Row, Sheet, useToast } from '../ui';

/** The stages a requester sees, in order (the prototype's status timeline). */
const STAGES = ['received', 'in_progress', 'resolved', 'closed'] as const;

function stageIndex(status: string): number {
  if (status === 'closed') return 3;
  if (status === 'resolved') return 2;
  if (status === 'received' || status === 'awaiting_approval') return 0;
  return 1;
}

function Timeline({ steps }: { steps: { label: string; done: boolean; current: boolean }[] }) {
  const palette = usePalette();
  return (
    <Card testID="timeline">
      {steps.map((step) => (
        <View key={step.label} style={styles.step}>
          <View
            style={[
              styles.dot,
              {
                backgroundColor: step.done ? palette.primary : palette.background,
                borderColor: step.done || step.current ? palette.primary : palette.strongBorder,
              },
            ]}
          />
          <Text
            style={{
              color: step.done || step.current ? palette.text : palette.textSecondary,
              fontWeight: step.current ? '700' : '500',
            }}
          >
            {step.label}
          </Text>
        </View>
      ))}
    </Card>
  );
}

/** Confirm a fix, or say it is still broken (with the requester's words; it reopens). */
function FixQuestion({
  onConfirm,
  onBroken,
  busy,
}: {
  onConfirm: () => void;
  onBroken: (why: string) => void;
  busy: boolean;
}) {
  const t = useLabels();
  const [asking, setAsking] = useState(false);
  const [why, setWhy] = useState('');
  const [error, setError] = useState(false);
  return (
    <Card style={{ backgroundColor: TONES.success.bg, borderColor: '#ABEFC6' }}>
      <Text style={{ color: '#1B1530', fontWeight: '600' }}>{t('mobile.req.fixed_question')}</Text>
      <View style={styles.buttons}>
        <View style={styles.flex}>
          <Button
            testID="fixed-yes"
            title={t('mobile.req.fixed_yes')}
            busy={busy}
            onPress={onConfirm}
          />
        </View>
        <View style={styles.flex}>
          <Button
            testID="fixed-no"
            variant="plain"
            title={t('mobile.req.fixed_no')}
            onPress={() => {
              setWhy('');
              setError(false);
              setAsking(true);
            }}
          />
        </View>
      </View>
      <Sheet
        visible={asking}
        title={t('mobile.req.fixed_no')}
        onClose={() => {
          setAsking(false);
        }}
      >
        <Field
          testID="broken-why"
          label={`${t('mobile.req.what_is_wrong')} *`}
          value={why}
          onChange={(text) => {
            setWhy(text);
            setError(false);
          }}
          error={error ? t('mobile.approvals.reason_required') : null}
        />
        <Button
          testID="broken-send"
          title={t('mobile.req.send')}
          busy={busy}
          onPress={() => {
            if (why.trim() === '') {
              setError(true);
              return;
            }
            setAsking(false);
            onBroken(why.trim());
          }}
        />
      </Sheet>
    </Card>
  );
}

function Back() {
  const t = useLabels();
  return (
    <Button
      variant="plain"
      title={t('mobile.back')}
      onPress={() => {
        if (router.canGoBack()) router.back();
        else router.replace('/r/requests');
      }}
    />
  );
}

export function IncidentRequestDetail({ id }: { id: string }) {
  const t = useLabels();
  const palette = usePalette();
  const queryClient = useQueryClient();
  const show = useToast((state) => state.show);
  const record = usePortalIncident(id);
  const conversation = usePortalConversation(id);
  const answer = useAnswerFix(id);
  const reply = usePortalReply(id);
  const [message, setMessage] = useState('');
  useRecordChannel('wi', id, () => {
    void queryClient.invalidateQueries({ queryKey: ['portal', 'incidents'] });
  });
  const fail = (error: unknown) => {
    show(t(isApiError(error) ? error.messageKey : 'errors.internal_error'));
  };
  const item = record.data;
  if (item === undefined) {
    return (
      <Screen title={t('mobile.nav.requests')} aside={<Back />}>
        {record.isError ? (
          <Muted text={t('errors.not_found')} />
        ) : (
          <ActivityIndicator color={palette.primary} />
        )}
      </Screen>
    );
  }
  const at = stageIndex(item.portal_status);
  const steps = STAGES.map((stage, index) => ({
    label: t(`portal_status.${stage}`),
    done: index < at || (index === at && stage === 'closed'),
    current: index === at,
  }));
  return (
    <Screen title={item.display_id} aside={<Back />}>
      <Row>
        <Chip
          testID="request-status"
          text={t(`portal_status.${item.portal_status}`)}
          tone={portalStatusTone(item.portal_status)}
        />
      </Row>
      <Text style={[styles.title, { color: palette.text }]}>{item.subject}</Text>
      <Timeline steps={steps} />
      {item.portal_status === 'resolved' ? (
        <FixQuestion
          busy={answer.isPending}
          onConfirm={() => {
            answer.mutate(null, {
              onSuccess: () => {
                show(t('mobile.toast.confirmed'));
              },
              onError: fail,
            });
          }}
          onBroken={(why) => {
            answer.mutate(why, {
              onSuccess: () => {
                show(t('mobile.toast.reopened'));
              },
              onError: fail,
            });
          }}
        />
      ) : null}
      <Heading text={t('mobile.incident.conversation')} />
      {(conversation.data?.items ?? []).map((entry) => (
        <Card key={entry.id}>
          <Text style={[styles.author, { color: palette.text }]}>
            {entry.by_you ? t('mobile.you') : (entry.author_name ?? t('mobile.req.support_team'))}
          </Text>
          <Text style={{ color: palette.text }}>{entry.body.replace(/<[^>]+>/g, ' ').trim()}</Text>
        </Card>
      ))}
      <Field
        testID="request-message"
        label={t('mobile.req.add_message')}
        value={message}
        onChange={setMessage}
        placeholder={t('mobile.req.message_placeholder')}
      />
      <Button
        testID="request-message-send"
        title={t('mobile.incident.send')}
        busy={reply.isPending}
        onPress={() => {
          const body = message.trim();
          if (body === '') return;
          reply.mutate(body, {
            onSuccess: () => {
              setMessage('');
              show(t('mobile.toast.message_sent'));
            },
            onError: fail,
          });
        }}
      />
    </Screen>
  );
}

export function ServiceRequestDetail({ id }: { id: string }) {
  const t = useLabels();
  const palette = usePalette();
  const queryClient = useQueryClient();
  const show = useToast((state) => state.show);
  const record = usePortalRequest(id);
  const progress = usePortalRequestSteps(id);
  const answer = useAnswerRequest(id);
  useRecordChannel('wi', id, () => {
    void queryClient.invalidateQueries({ queryKey: ['portal', 'service-requests'] });
  });
  const fail = (error: unknown) => {
    show(t(isApiError(error) ? error.messageKey : 'errors.internal_error'));
  };
  const item = record.data;
  if (item === undefined) {
    return (
      <Screen title={t('mobile.nav.requests')} aside={<Back />}>
        {record.isError ? (
          <Muted text={t('errors.not_found')} />
        ) : (
          <ActivityIndicator color={palette.primary} />
        )}
      </Screen>
    );
  }
  const at = stageIndex(item.portal_status);
  const stages = STAGES.map((stage, index) => ({
    label: t(`portal_status.${stage}`),
    done: index < at,
    current: index === at,
  }));
  const fulfilment = (progress.data?.items ?? []).map((step) => ({
    label: step.title ?? '',
    done: step.done,
    current: false,
  }));
  return (
    <Screen title={item.display_id} aside={<Back />}>
      <Row>
        <Chip
          testID="request-status"
          text={t(`portal_status.${item.portal_status}`)}
          tone={portalStatusTone(item.portal_status)}
        />
      </Row>
      <Text style={[styles.title, { color: palette.text }]}>{item.subject}</Text>
      {item.portal_status === 'awaiting_approval' ? (
        <Muted text={t('mobile.req.waiting_approval')} />
      ) : null}
      <Timeline steps={stages} />
      {fulfilment.length > 0 ? (
        <>
          <Heading text={t('mobile.req.progress')} />
          <Timeline steps={fulfilment} />
        </>
      ) : null}
      {item.portal_status === 'resolved' ? (
        <FixQuestion
          busy={answer.isPending}
          onConfirm={() => {
            answer.mutate(
              { confirmed: true },
              {
                onSuccess: () => {
                  show(t('mobile.toast.confirmed'));
                },
                onError: fail,
              },
            );
          }}
          onBroken={(why) => {
            answer.mutate(
              { confirmed: false, comment: why },
              {
                onSuccess: () => {
                  show(t('mobile.toast.reopened'));
                },
                onError: fail,
              },
            );
          }}
        />
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 20, fontWeight: '700', lineHeight: 26 },
  step: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 32 },
  dot: { width: 20, height: 20, borderRadius: 10, borderWidth: 2 },
  buttons: { flexDirection: 'row', gap: SPACE.sm },
  flex: { flex: 1 },
  author: { fontSize: 13, fontWeight: '700' },
});
