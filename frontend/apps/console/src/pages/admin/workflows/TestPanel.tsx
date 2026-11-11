import {
  App,
  Button,
  Descriptions,
  Flex,
  Form,
  Input,
  InputNumber,
  Radio,
  Select,
  Typography,
} from 'antd';
import { useEffect, useState } from 'react';

import {
  useAnswerTestRun,
  useFindRecord,
  useLiveCall,
  useStartTestRun,
  useTestRun,
  type TestAnswerIn,
  type TestRunOut,
  type WorkflowOut,
} from '@supportx/api-client';
import { ToneTag, WriteButton, reportError, useLabel } from '@supportx/ui';

import { isKnownPort } from './nodes';

// What a wait can hear (the server's WaitEvent): the change the admin describes.
const EVENTS = [
  'field_changed',
  'status_changed',
  'note_added',
  'requester_replied',
  'approval_decided',
  'task_completed',
  'worklog_added',
] as const;
// The commands a live call may make (the coordinator, 2026-11-11): never a function.
const LIVE = new Set(['call_webhook', 'notify']);
const UNITS = [
  ['minutes', 60],
  ['hours', 3600],
  ['days', 86_400],
] as const;

export interface TestHighlight {
  passed: Set<string>;
  /** The nodes the run is at now. */
  at: Set<string>;
}

interface Pending {
  id: string;
  node: string;
  kind: string;
}

const pendingOf = (run: TestRunOut): Pending[] =>
  run.pending.map((p) => ({ id: String(p.id), node: String(p.node), kind: String(p.kind) }));

/**
 * Test mode (REQ-WF-022): the saved draft runs on a record's facts or on sample values, and
 * nothing is applied. Each step it asks for waits here for the admin's answer; a described
 * change wakes its waits; the clock can be moved on for timers. The path it took and where it
 * is now are marked on the canvas. One live call per run, for a webhook or notify step on a
 * real record, after a confirm that says it is audited.
 */
export function TestPanel({
  workflow,
  dirty,
  typeOf,
  onHighlight,
}: {
  workflow: WorkflowOut;
  dirty: boolean;
  typeOf: (node: string) => string;
  onHighlight: (highlight: TestHighlight | null) => void;
}) {
  const t = useLabel();
  const { modal } = App.useApp();
  const [runId, setRunId] = useState<string>();
  const run = useTestRun(runId);
  const start = useStartTestRun();
  const answer = useAnswerTestRun();
  const live = useLiveCall();
  const find = useFindRecord();
  const [on, setOn] = useState<'record' | 'sample'>('record');
  const [displayId, setDisplayId] = useState('');
  const [sample, setSample] = useState('{}');
  const [sampleBad, setSampleBad] = useState(false);
  const [event, setEvent] = useState<(typeof EVENTS)[number]>('field_changed');
  const [amount, setAmount] = useState<number | null>(1);
  const [unit, setUnit] = useState<(typeof UNITS)[number][0]>('hours');

  const data = run.data;
  useEffect(() => {
    if (data === undefined) {
      onHighlight(null);
      return;
    }
    onHighlight({
      passed: new Set(data.steps.map((s) => String(s.node))),
      at: new Set(data.current_nodes ?? []),
    });
  }, [data, onHighlight]);

  const begin = (body: { record_id?: string; sample?: Record<string, unknown> }) => {
    start.mutate(
      { id: workflow.id, key: crypto.randomUUID(), body },
      {
        onSuccess: (made) => {
          setRunId(made.id);
        },
        onError: reportError,
      },
    );
  };
  const onStart = () => {
    if (on === 'record') {
      find.mutate(
        { type: workflow.record_type, value: displayId.trim() },
        {
          onSuccess: (id) => {
            begin({ record_id: id });
          },
          onError: reportError,
        },
      );
      return;
    }
    try {
      const parsed: unknown = JSON.parse(sample);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setSampleBad(true);
        return;
      }
      setSampleBad(false);
      begin({ sample: parsed as Record<string, unknown> });
    } catch {
      setSampleBad(true);
    }
  };
  const send = (body: TestAnswerIn) => {
    if (data === undefined) return;
    answer.mutate({ run: data, body }, { onError: reportError });
  };
  const goLive = (p: Pending) => {
    if (data === undefined) return;
    void modal.confirm({
      title: t('workflows.test.live_title', { node: p.node }),
      content: t('workflows.test.live_body'),
      okText: t('workflows.test.live_ok'),
      cancelText: t('actions.cancel'),
      onOk: () => live.mutateAsync({ run: data, commandId: p.id }).catch(reportError),
    });
  };

  if (data === undefined) {
    return (
      <Form layout="vertical" data-testid="test-start">
        <Typography.Paragraph type="secondary">{t('workflows.test.intro')}</Typography.Paragraph>
        <Form.Item label={t('workflows.test.run_on')}>
          <Radio.Group
            value={on}
            onChange={(e) => {
              setOn(e.target.value as 'record' | 'sample');
            }}
            options={[
              { value: 'record', label: t('workflows.test.on_record') },
              { value: 'sample', label: t('workflows.test.on_sample') },
            ]}
            data-testid="test-on"
          />
        </Form.Item>
        {on === 'record' ? (
          <Form.Item label={t('workflows.test.record_id')} htmlFor="test-record">
            <Input
              id="test-record"
              dir="ltr"
              placeholder={t('workflows.test.record_id_hint')}
              value={displayId}
              onChange={(e) => {
                setDisplayId(e.target.value);
              }}
              data-testid="test-record"
            />
          </Form.Item>
        ) : (
          <Form.Item
            label={t('workflows.test.sample')}
            htmlFor="test-sample"
            validateStatus={sampleBad ? 'error' : undefined}
            help={
              sampleBad
                ? t('workflows.designer.settings_not_json')
                : t('workflows.test.sample_help')
            }
          >
            <Input.TextArea
              id="test-sample"
              dir="ltr"
              rows={5}
              value={sample}
              spellCheck={false}
              style={{ fontFamily: 'monospace', fontSize: 12 }}
              onChange={(e) => {
                setSample(e.target.value);
              }}
              data-testid="test-sample"
            />
          </Form.Item>
        )}
        <WriteButton
          type="primary"
          loading={start.isPending || find.isPending}
          disabled={dirty || (on === 'record' && displayId.trim() === '')}
          whyDisabled={
            dirty ? t('workflows.designer.why.save_first') : t('workflows.test.why.record')
          }
          onClick={onStart}
          data-testid="test-run"
        >
          {t('workflows.test.start')}
        </WriteButton>
      </Form>
    );
  }

  const pending = pendingOf(data);
  const busy = answer.isPending || live.isPending;
  const canLive = data.record_id !== null && data.live_call === null;
  return (
    <Flex vertical gap={12} data-testid="test-run-view">
      <Flex gap={8} align="center" wrap>
        <ToneTag
          tone={
            data.status === 'failed' ? 'error' : data.status === 'finished' ? 'success' : 'info'
          }
          testId="test-status"
        >
          {t(`workflow_instance_status.${data.status}`)}
        </ToneTag>
        <Typography.Text type="secondary">{t('workflows.test.nothing_applied')}</Typography.Text>
      </Flex>
      {pending.length > 0 && (
        <Flex vertical gap={8} data-testid="test-pending">
          <Typography.Text strong>{t('workflows.test.waiting_for')}</Typography.Text>
          {pending.map((p) => {
            const approval = p.kind === 'open_approval';
            return (
              <Flex
                key={p.id}
                vertical
                gap={6}
                style={{ border: '1px solid', borderColor: 'inherit', borderRadius: 6, padding: 8 }}
                data-testid={`test-command-${p.node}`}
              >
                <Typography.Text>
                  {t('workflows.test.step', {
                    type: t(`workflow_node_type.${typeOf(p.node)}`),
                    node: p.node,
                  })}
                </Typography.Text>
                <Flex gap={8} wrap>
                  <Button
                    size="small"
                    disabled={busy}
                    onClick={() => {
                      send(
                        approval
                          ? { command_id: p.id, ok: true, port: 'approved' }
                          : { command_id: p.id, ok: true },
                      );
                    }}
                    data-testid={`test-ok-${p.node}`}
                  >
                    {approval ? t('workflow_port.approved') : t('workflows.test.done')}
                  </Button>
                  <Button
                    size="small"
                    disabled={busy}
                    onClick={() => {
                      send(
                        approval
                          ? { command_id: p.id, ok: true, port: 'rejected' }
                          : { command_id: p.id, ok: false },
                      );
                    }}
                    data-testid={`test-fail-${p.node}`}
                  >
                    {approval ? t('workflow_port.rejected') : t('workflows.test.failed')}
                  </Button>
                  {LIVE.has(p.kind) && canLive && (
                    <Button
                      size="small"
                      danger
                      disabled={busy}
                      onClick={() => {
                        goLive(p);
                      }}
                      data-testid={`test-live-${p.node}`}
                    >
                      {t('workflows.test.live')}
                    </Button>
                  )}
                </Flex>
              </Flex>
            );
          })}
        </Flex>
      )}
      {(data.status === 'waiting' || data.status === 'running') && (
        <>
          <Form layout="vertical">
            <Form.Item label={t('workflows.test.something_happened')} htmlFor="test-event">
              <Flex gap={8} wrap>
                <Select<(typeof EVENTS)[number]>
                  id="test-event"
                  value={event}
                  onChange={setEvent}
                  options={EVENTS.map((e) => ({ value: e, label: t(`workflow_wait_event.${e}`) }))}
                  style={{ minWidth: 200 }}
                  data-testid="test-event"
                />
                <Button
                  disabled={busy}
                  onClick={() => {
                    send({ ok: true, record_changed: event });
                  }}
                  data-testid="test-event-send"
                >
                  {t('workflows.test.tell')}
                </Button>
              </Flex>
            </Form.Item>
            <Form.Item label={t('workflows.test.clock')} htmlFor="test-forward">
              <Flex gap={8} wrap>
                <InputNumber<number>
                  id="test-forward"
                  min={1}
                  precision={0}
                  value={amount}
                  onChange={setAmount}
                  data-testid="test-forward"
                />
                <Select
                  aria-label={t('workflows.form.unit')}
                  value={unit}
                  onChange={setUnit}
                  options={UNITS.map(([u]) => ({ value: u, label: t(`workflows.form.unit_${u}`) }))}
                  style={{ minWidth: 110 }}
                />
                <Button
                  disabled={busy || amount === null}
                  onClick={() => {
                    const per = UNITS.find(([u]) => u === unit)?.[1] ?? 60;
                    send({ ok: true, fast_forward_seconds: (amount ?? 0) * per });
                  }}
                  data-testid="test-forward-send"
                >
                  {t('workflows.test.forward')}
                </Button>
              </Flex>
            </Form.Item>
          </Form>
        </>
      )}
      {Object.keys(data.variables).length > 0 && (
        <Descriptions
          size="small"
          column={1}
          title={t('workflows.test.variables')}
          items={Object.entries(data.variables).map(([k, v]) => ({
            key: k,
            label: <bdi dir="ltr">{k}</bdi>,
            children: <bdi dir="ltr">{JSON.stringify(v)}</bdi>,
          }))}
          data-testid="test-variables"
        />
      )}
      <div>
        <Typography.Text strong>{t('workflows.test.path')}</Typography.Text>
        <ol style={{ margin: '4px 0 0', paddingInlineStart: 20 }} data-testid="test-steps">
          {data.steps.map((s, i) => (
            <li key={`${String(s.node)}-${String(i)}`}>
              {isKnownPort(String(s.result))
                ? t('workflows.test.step_result', {
                    type: t(`workflow_node_type.${String(s.node_type)}`),
                    node: String(s.node),
                    result: t(`workflow_port.${String(s.result)}`),
                  })
                : t('workflows.test.step', {
                    type: t(`workflow_node_type.${String(s.node_type)}`),
                    node: String(s.node),
                  })}
            </li>
          ))}
        </ol>
      </div>
      <Button
        onClick={() => {
          setRunId(undefined);
        }}
        data-testid="test-new"
      >
        {t('workflows.test.new')}
      </Button>
    </Flex>
  );
}
