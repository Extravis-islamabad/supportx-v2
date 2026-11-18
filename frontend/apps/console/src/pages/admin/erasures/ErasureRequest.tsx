import { Alert, App, Button, Flex, Form, Input, Select, Typography } from 'antd';
import { useRef, useState } from 'react';
import { Link } from 'react-router';

import {
  ApiError,
  ERASURE_REASONS,
  OPEN_ERASURE_STATES,
  useErasures,
  useRequestErasure,
  useSession,
  type ErasureReason,
  type UserDetail,
} from '@supportx/api-client';
import { Drawer, SettingsCard, lengthLimit, useAccess, useLabel } from '@supportx/ui';

import { UserPicker } from '../../incidents/pickers';
import { ERASE, MANAGE_HOLDS, sameName, useErasureProblem } from './erasureText';
import { KeepFiles } from './KeepFiles';
import { LegalHoldSection } from './LegalHold';

const REASON_MAX = 1000;

/**
 * PersonDrawer › Privacy: the legal hold (the holds right or the erase right), then the person's
 * open erasure, if any, and "Ask for erasure…" (people.erase).
 * The server refuses yourself, the last tenant admin, a break-glass account, a person on legal
 * hold and a second open erasure; this only hides what it would refuse anyway.
 */
export function PersonPrivacy({ user }: { user: UserDetail }) {
  const t = useLabel();
  const { can } = useAccess();
  const me = useSession().data?.user.id;
  const allowed = can(ERASE);
  const open = useErasures({ personId: user.id, states: OPEN_ERASURE_STATES }, allowed);
  const [asking, setAsking] = useState(false);
  if (!allowed && !can(MANAGE_HOLDS)) return null;
  const current = open.data?.items[0];
  return (
    <Flex vertical gap={16}>
      <LegalHoldSection user={user} />
      {allowed && (
        <SettingsCard title={t('people_erasure.title')} testId="person-privacy">
          <Flex vertical gap={12} align="flex-start">
            {current !== undefined ? (
              <Typography.Text data-testid="person-erasure-open">
                {t('people_erasure.existing')}{' '}
                <Link to={`/admin/erasures/${current.id}`}>
                  {t('people_erasure.existing_open')}
                </Link>
              </Typography.Text>
            ) : (
              me !== user.id && (
                <Button
                  danger
                  onClick={() => {
                    setAsking(true);
                  }}
                  data-testid="person-erasure-ask"
                >
                  {t('people_erasure.request')}
                </Button>
              )
            )}
          </Flex>
          {asking && (
            <ErasureRequestDrawer
              user={user}
              onClose={() => {
                setAsking(false);
              }}
            />
          )}
        </SettingsCard>
      )}
    </Flex>
  );
}

/**
 * Template B in a drawer: the reason, who takes over, the typed name. Submit sends one request
 * with an Idempotency-Key (kept for the drawer's life, so a retry never asks twice) and a recent
 * sign-in (the shared confirmation pop-up asks when the server needs it).
 */
export function ErasureRequestDrawer({ user, onClose }: { user: UserDetail; onClose: () => void }) {
  const t = useLabel();
  const { message } = App.useApp();
  const ask = useRequestErasure(user.id);
  const problemOf = useErasureProblem();
  const key = useRef(crypto.randomUUID());
  const [reason, setReason] = useState<ErasureReason>();
  const [text, setText] = useState('');
  const [successor, setSuccessor] = useState<string | null>(null);
  const [typed, setTyped] = useState('');
  const [said, setSaid] = useState<string>();
  const [fields, setFields] = useState<Record<string, string>>({});
  const [kept, setKept] = useState<Record<string, string>>({});
  const named = sameName(typed, user.display_name);
  const reasoned = Object.values(kept).every((r) => r.trim() !== '');
  const ready = reason !== undefined && successor !== null && named && reasoned;
  const submit = () => {
    if (!ready) return;
    setSaid(undefined);
    setFields({});
    ask.mutate(
      {
        key: key.current,
        body: {
          reason_code: reason,
          reason_text: text.trim() === '' ? null : text.trim(),
          successor_id: successor,
          keep_files: Object.fromEntries(Object.entries(kept).map(([id, why]) => [id, why.trim()])),
          confirm_name: typed.trim(),
        },
      },
      {
        onSuccess: () => {
          void message.success(t('people_erasure.requested'));
          onClose();
        },
        onError: (error) => {
          if (error instanceof ApiError && error.fieldErrors.length > 0) {
            setFields(
              Object.fromEntries(
                error.fieldErrors.map((f) => [
                  f.field.replace(/^body\./u, ''),
                  t(f.message_key, f.params ?? {}),
                ]),
              ),
            );
            return;
          }
          setSaid(problemOf(error));
        },
      },
    );
  };
  const help = (field: string) => fields[field];
  return (
    <Drawer
      open
      onClose={onClose}
      width={520}
      destroyOnHidden
      title={t('people_erasure.new_title', { name: user.display_name })}
      data-testid="erasure-request"
      footer={
        <Flex gap={8} justify="flex-end">
          <Button onClick={onClose} data-testid="erasure-request-cancel">
            {t('actions.cancel')}
          </Button>
          <Button
            type="primary"
            danger
            disabled={!ready}
            loading={ask.isPending}
            onClick={submit}
            data-testid="erasure-request-submit"
          >
            {t('people_erasure.request_submit')}
          </Button>
        </Flex>
      }
    >
      <Flex vertical gap={12}>
        <Typography.Text>{t('people_erasure.request_explain')}</Typography.Text>
        {said !== undefined && (
          <Alert
            type="error"
            showIcon
            role="alert"
            message={said}
            data-testid="erasure-request-said"
          />
        )}
        <Form layout="vertical" onFinish={submit}>
          <Form.Item
            label={t('people_erasure.reason')}
            htmlFor="erasure-reason"
            required
            validateStatus={help('reason_code') === undefined ? undefined : 'error'}
            help={help('reason_code')}
          >
            <Select<ErasureReason>
              id="erasure-reason"
              value={reason}
              onChange={setReason}
              options={ERASURE_REASONS.map((r) => ({
                value: r,
                label: t(`people_erasure.reason.${r}`),
              }))}
              data-testid="erasure-request-reason"
            />
          </Form.Item>
          <Form.Item
            label={t('people_erasure.reason_text')}
            htmlFor="erasure-reason-text"
            extra={t('people_erasure.reason_text_hint')}
            validateStatus={help('reason_text') === undefined ? undefined : 'error'}
            help={help('reason_text')}
          >
            <Input.TextArea
              id="erasure-reason-text"
              rows={3}
              count={lengthLimit(REASON_MAX)}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
              }}
              data-testid="erasure-request-text"
            />
          </Form.Item>
          <Form.Item
            label={t('people_erasure.successor')}
            htmlFor="erasure-successor"
            required
            validateStatus={help('successor_id') === undefined ? undefined : 'error'}
            help={help('successor_id')}
          >
            <UserPicker
              id="erasure-successor"
              value={successor}
              onChange={(next) => {
                setSuccessor(next);
              }}
              testId="erasure-request-successor"
              ariaLabel={t('people_erasure.successor')}
            />
          </Form.Item>
          <KeepFiles
            userId={user.id}
            kept={kept}
            onChange={setKept}
            problems={Object.fromEntries(
              Object.entries(fields)
                .filter(([field]) => field.startsWith('keep_files.'))
                .map(([field, text]) => [field.slice('keep_files.'.length), text]),
            )}
          />
          {help('keep_files') !== undefined && (
            <Typography.Text type="danger">{help('keep_files')}</Typography.Text>
          )}
          <Form.Item
            label={t('people_erasure.confirm_label', { name: user.display_name })}
            htmlFor="erasure-confirm-name"
            required
            validateStatus={help('confirm_name') === undefined ? undefined : 'error'}
            help={help('confirm_name')}
          >
            <Input
              id="erasure-confirm-name"
              autoComplete="off"
              value={typed}
              onChange={(e) => {
                setTyped(e.target.value);
              }}
              data-testid="erasure-request-name"
            />
          </Form.Item>
        </Form>
      </Flex>
    </Drawer>
  );
}
