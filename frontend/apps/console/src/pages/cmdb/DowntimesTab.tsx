import { Flex, Form, Input, List, Popconfirm, Space, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  useCiDowntimes,
  useRecordCiDowntime,
  useRemoveCiDowntime,
  type CiDowntime,
  type CiDowntimeSource,
  type CiDowntimeState,
} from '@supportx/api-client';
import {
  DateTimeField,
  EmptyText,
  FormProblem,
  ToneTag,
  WriteButton,
  lengthLimit,
  useAccess,
  useDateTime,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

const DESCRIPTION_MAX = 2000;
const STATE_TONE: Record<CiDowntimeState, 'info' | 'warning' | 'success'> = {
  scheduled: 'info',
  active: 'warning',
  completed: 'success',
};
// A synced downtime opens its record (it changes there, never here).
const RECORD_PATH: Record<Exclude<CiDowntimeSource, 'manual'>, string> = {
  change: '/changes',
  release: '/releases',
  incident: '/incidents',
};

/**
 * A CI's downtimes (WP-053 S5b, REQ-CMDB-020): scheduled, active and completed, live on the CI's
 * channel. One from a change, a release or an incident links to its record and is changed there;
 * one recorded here by hand (`cmdb.record_downtime`) can be removed here.
 */
export function DowntimesTab({ ciId }: { ciId: string }) {
  const t = useLabel();
  const { format } = useDateTime();
  const { can } = useAccess();
  const found = useCiDowntimes(ciId);
  const record = useRecordCiDowntime(ciId);
  const remove = useRemoveCiDowntime(ciId);
  const problem = useFormProblem();
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [startsAt, setStartsAt] = useState<string | null>(null);
  const [endsAt, setEndsAt] = useState<string | null>(null);
  const [description, setDescription] = useState('');
  const rows = found.data?.items ?? [];
  const counts = found.data?.counts;
  const mayRecord = can('cmdb.record_downtime');

  const add = () => {
    if (startsAt === null) return;
    record.mutate(
      {
        key,
        body: {
          starts_at: startsAt,
          ends_at: endsAt,
          description: description.trim() === '' ? null : description.trim(),
        },
      },
      {
        onSuccess: () => {
          setStartsAt(null);
          setEndsAt(null);
          setDescription('');
          setKey(crypto.randomUUID());
          problem.clear();
        },
        onError: (error) => {
          problem.show(error);
        },
      },
    );
  };

  const source = (d: CiDowntime) =>
    d.source === 'manual' || d.source_work_item_id === null ? (
      <span>{t(`cmdb_downtime_source.${d.source}`)}</span>
    ) : (
      <Link
        to={`${RECORD_PATH[d.source]}/${d.source_work_item_id}`}
        data-testid={`ci-downtime-${d.id}-source`}
      >
        {t(`cmdb_downtime_source.${d.source}`)}
      </Link>
    );

  return (
    <Flex vertical gap={12} data-testid="ci-downtimes">
      {counts !== undefined && (
        <Space wrap data-testid="ci-downtime-counts">
          {(['active', 'scheduled', 'completed'] as const).map((state) => (
            <ToneTag key={state} tone={STATE_TONE[state]}>
              {t('cmdb.downtime.count', {
                state: t(`cmdb_downtime_state.${state}`),
                count: counts[state],
              })}
            </ToneTag>
          ))}
        </Space>
      )}
      {rows.length === 0 && !found.isPending ? (
        <EmptyText>{t('cmdb.downtime.none')}</EmptyText>
      ) : (
        <List<CiDowntime>
          dataSource={rows}
          renderItem={(d) => (
            <List.Item
              key={d.id}
              data-testid={`ci-downtime-${d.id}`}
              actions={
                d.editable && mayRecord
                  ? [
                      <Popconfirm
                        key="remove"
                        title={t('cmdb.downtime.remove_confirm')}
                        okText={t('actions.delete')}
                        okButtonProps={{
                          danger: true,
                          'data-testid': `ci-downtime-${d.id}-remove-ok`,
                        }}
                        cancelText={t('actions.cancel')}
                        onConfirm={() => {
                          remove.mutate({ id: d.id, version: d.version });
                        }}
                      >
                        <WriteButton size="small" danger data-testid={`ci-downtime-${d.id}-remove`}>
                          {t('actions.delete')}
                        </WriteButton>
                      </Popconfirm>,
                    ]
                  : []
              }
            >
              <Flex vertical gap={4}>
                <Space wrap>
                  <ToneTag tone={STATE_TONE[d.state]}>
                    {t(`cmdb_downtime_state.${d.state}`)}
                  </ToneTag>
                  <span>{t(`cmdb_downtime_phase.${d.phase}`)}</span>
                  {source(d)}
                  <span>
                    {d.ends_at === null
                      ? t('cmdb.downtime.open_ended', { start: format(d.starts_at) })
                      : `${format(d.starts_at)} – ${format(d.ends_at)}`}
                  </span>
                </Space>
                {d.description !== null && (
                  <Typography.Text type="secondary">{d.description}</Typography.Text>
                )}
              </Flex>
            </List.Item>
          )}
        />
      )}
      {mayRecord && (
        <Form layout="vertical" component="div">
          <Typography.Title level={5}>{t('cmdb.downtime.record')}</Typography.Title>
          <Flex gap={16} wrap align="flex-start">
            <Form.Item label={t('cmdb.downtime.starts')} required htmlFor="ci-downtime-starts">
              <DateTimeField
                id="ci-downtime-starts"
                value={startsAt}
                onChange={setStartsAt}
                testId="ci-downtime-starts"
                hideZone
              />
            </Form.Item>
            <Form.Item label={t('cmdb.downtime.ends')} htmlFor="ci-downtime-ends">
              <DateTimeField
                id="ci-downtime-ends"
                value={endsAt}
                onChange={setEndsAt}
                testId="ci-downtime-ends"
                hideZone
              />
            </Form.Item>
          </Flex>
          <Form.Item label={t('cmdb.downtime.description')} htmlFor="ci-downtime-description">
            <Input.TextArea
              id="ci-downtime-description"
              value={description}
              count={lengthLimit(DESCRIPTION_MAX)}
              autoSize={{ minRows: 2, maxRows: 6 }}
              onChange={(e) => {
                setDescription(e.target.value);
              }}
              data-testid="ci-downtime-description"
            />
          </Form.Item>
          <FormProblem problem={problem} />
          <WriteButton
            disabled={startsAt === null}
            whyDisabled={startsAt === null ? t('cmdb.downtime.need_start') : undefined}
            loading={record.isPending}
            data-testid="ci-downtime-add"
            onClick={add}
          >
            {t('cmdb.downtime.add')}
          </WriteButton>
        </Form>
      )}
    </Flex>
  );
}
