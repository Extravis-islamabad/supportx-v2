import { Checkbox, Flex, Form, Modal, Radio, Typography } from 'antd';
import { useState } from 'react';

import {
  useProblemFollowUp,
  useStartFollowUp,
  type Problem,
  type ProblemFollowUpCopy,
} from '@supportx/api-client';
import { EmptyText, FormProblem, useFormProblem, useLabel } from '@supportx/ui';

import { BulkProgress } from '../incidents/list/bulk';

/**
 * Follow up the linked incidents (REQ-PRB-055, D-140 Q1): the open ones are listed and ticked by
 * default, any can be unticked, and the chosen text becomes each one's resolution through its
 * own rules. Progress and the result per incident then show live in the bulk drawer.
 */
export function FollowUpDialog({
  item,
  open,
  onClose,
}: {
  item: Problem;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const preview = useProblemFollowUp(item.id, open);
  const start = useStartFollowUp(item.id);
  const problem = useFormProblem();
  const [unticked, setUnticked] = useState<string[]>([]);
  const [copy, setCopy] = useState<ProblemFollowUpCopy>('resolution');
  const [jobId, setJobId] = useState<string | null>(null);
  const rows = preview.data?.incidents ?? [];
  const chosen = rows.map((r) => r.id).filter((id) => !unticked.includes(id));
  const offered: ProblemFollowUpCopy[] = [
    ...(preview.data?.has_resolution ? (['resolution'] as const) : []),
    ...(preview.data?.has_workaround ? (['workaround'] as const) : []),
    ...(preview.data?.has_resolution && preview.data.has_workaround ? (['both'] as const) : []),
  ];
  const close = () => {
    setUnticked([]);
    problem.clear();
    onClose();
  };
  return (
    <>
      <Modal
        open={open}
        title={t('problems.follow_up.title')}
        okText={t('problems.follow_up.start', { count: chosen.length })}
        okButtonProps={{
          disabled: chosen.length === 0 || !offered.includes(copy),
          loading: start.isPending,
          'data-testid': 'prb-follow-up-start',
        }}
        onOk={() => {
          start.mutate(
            { incidentIds: chosen, copy },
            {
              onSuccess: (job) => {
                setJobId(job.id);
                close();
              },
              onError: (error) => problem.show(error),
            },
          );
        }}
        onCancel={close}
        destroyOnHidden
      >
        <Form layout="vertical" data-testid="prb-follow-up">
          <Typography.Paragraph type="secondary">
            {t('problems.follow_up.explain')}
          </Typography.Paragraph>
          {rows.length === 0 ? (
            <EmptyText>{t('problems.follow_up.none')}</EmptyText>
          ) : (
            <Flex vertical gap={4}>
              {rows.map((r) => (
                <Checkbox
                  key={r.id}
                  checked={!unticked.includes(r.id)}
                  onChange={(e) => {
                    setUnticked(
                      e.target.checked ? unticked.filter((u) => u !== r.id) : [...unticked, r.id],
                    );
                  }}
                  data-testid={`prb-follow-up-${r.display_id}`}
                >
                  <strong dir="ltr">{r.display_id}</strong> <bdi dir="auto">{r.subject}</bdi>
                </Checkbox>
              ))}
            </Flex>
          )}
          {offered.length > 0 ? (
            <Form.Item label={t('problems.follow_up.copy')} style={{ marginTop: 12 }}>
              <Radio.Group
                value={copy}
                onChange={(e) => {
                  setCopy(e.target.value as ProblemFollowUpCopy);
                }}
                options={offered.map((o) => ({
                  value: o,
                  label: t(`problem_follow_up_copy.${o}`),
                }))}
              />
            </Form.Item>
          ) : (
            <Typography.Text type="warning">{t('problems.follow_up.no_text')}</Typography.Text>
          )}
          <FormProblem problem={problem} />
        </Form>
      </Modal>
      <BulkProgress
        jobId={jobId}
        onClose={() => {
          setJobId(null);
        }}
      />
    </>
  );
}
