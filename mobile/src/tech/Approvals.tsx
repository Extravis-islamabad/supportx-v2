import { useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import {
  isApiError,
  useDecideApproval,
  useMyApprovals,
  type components,
} from '@supportx/api-client';
import { useLabels } from '@supportx/labels';
import { usePersonalChannel } from '@supportx/realtime';

import { Button } from '../components/Button';
import { Screen } from '../components/Screen';
import { SPACE, usePalette } from '../theme';
import { TONES } from '../tones';
import { Card, Chip, Field, Muted, Row, Sheet, useToast } from '../ui';
import { personName } from './parts';

type Pending = components['schemas']['PendingApprovalOut'];

/** Approvals waiting for me: approve, or reject with a reason (always required on mobile). */
export function Approvals() {
  const t = useLabels();
  const palette = usePalette();
  const show = useToast((state) => state.show);
  const approvals = useMyApprovals();
  const decide = useDecideApproval();
  const [rejecting, setRejecting] = useState<Pending | null>(null);
  const [reason, setReason] = useState('');
  const [reasonError, setReasonError] = useState(false);
  // A new approval for me, or one decided elsewhere, shows at once (rule 5c).
  usePersonalChannel(() => {
    void approvals.refetch();
  });

  const fail = (error: unknown) => {
    show(t(isApiError(error) ? error.messageKey : 'errors.internal_error'));
  };
  const approve = (item: Pending) => {
    decide.mutate(
      {
        recordId: item.record_id,
        approvalId: item.approval_id,
        version: item.approval_version,
        body: { decision: 'approve', comment: null, private: false },
      },
      {
        onSuccess: () => {
          show(t('mobile.toast.approved', { id: item.display_id }));
          void approvals.refetch();
        },
        onError: fail,
      },
    );
  };
  const confirmReject = () => {
    const text = reason.trim();
    if (rejecting === null) return;
    if (text === '') {
      setReasonError(true);
      return;
    }
    const item = rejecting;
    decide.mutate(
      {
        recordId: item.record_id,
        approvalId: item.approval_id,
        version: item.approval_version,
        body: { decision: 'reject', comment: text, private: false },
      },
      {
        onSuccess: () => {
          setRejecting(null);
          show(t('mobile.toast.rejected', { id: item.display_id }));
          void approvals.refetch();
        },
        onError: fail,
      },
    );
  };

  const items = approvals.data?.items ?? [];
  const people = approvals.data?.people;

  return (
    <Screen
      title={t('mobile.nav.approvals')}
      refreshing={approvals.isRefetching}
      onRefresh={() => void approvals.refetch()}
    >
      {approvals.isPending ? <ActivityIndicator color={palette.primary} /> : null}
      {!approvals.isPending && items.length === 0 ? (
        <Muted testID="approvals-empty" text={t('mobile.approvals.empty')} />
      ) : null}
      {items.map((item) => (
        <Card key={item.approval_id} testID={`approval-${item.display_id}`}>
          <Row style={styles.head}>
            <Text style={[styles.id, { color: palette.textSecondary }]}>{item.display_id}</Text>
            <Chip text={t('mobile.approvals.waiting')} tone={TONES.warning} />
          </Row>
          <Text style={[styles.title, { color: palette.text }]}>{item.subject}</Text>
          <Muted text={personName(people, item.on_behalf_of_id ?? item.requester_id) ?? ''} />
          <View style={styles.buttons}>
            <View style={styles.flex}>
              <Button
                testID={`reject-${item.display_id}`}
                variant="plain"
                title={t('work_item_action.reject')}
                onPress={() => {
                  setReason('');
                  setReasonError(false);
                  setRejecting(item);
                }}
              />
            </View>
            <View style={styles.flex}>
              <Button
                testID={`approve-${item.display_id}`}
                title={t('work_item_action.approve')}
                busy={decide.isPending && decide.variables.approvalId === item.approval_id}
                onPress={() => {
                  approve(item);
                }}
              />
            </View>
          </View>
        </Card>
      ))}

      <Sheet
        visible={rejecting !== null}
        title={t('mobile.approvals.reject_title')}
        onClose={() => {
          setRejecting(null);
        }}
      >
        <Field
          testID="reject-reason"
          label={`${t('mobile.approvals.reason')} *`}
          value={reason}
          onChange={(text) => {
            setReason(text);
            setReasonError(false);
          }}
          error={reasonError ? t('mobile.approvals.reason_required') : null}
        />
        <View style={styles.buttons}>
          <View style={styles.flex}>
            <Button
              variant="plain"
              title={t('mobile.cancel')}
              onPress={() => {
                setRejecting(null);
              }}
            />
          </View>
          <View style={styles.flex}>
            <Button
              testID="confirm-reject"
              title={t('work_item_action.reject')}
              busy={decide.isPending}
              onPress={confirmReject}
            />
          </View>
        </View>
      </Sheet>
    </Screen>
  );
}

const styles = StyleSheet.create({
  head: { justifyContent: 'space-between' },
  id: { fontSize: 12, fontWeight: '700' },
  title: { fontSize: 15, fontWeight: '600' },
  buttons: { flexDirection: 'row', gap: SPACE.sm, marginTop: 4 },
  flex: { flex: 1 },
});
