import { Alert, Button, Card, Flex, Form, Input, Typography } from 'antd';
import { useState } from 'react';

import { useSession, useUpdateUser, useUser, type UserDetail } from '@supportx/api-client';

import { useLabel } from './appearance';
import { reportError } from './errors';
import { lengthLimit } from './lengthLimit';

const NUMBER_MAX = 50;
const SOURCE_LABEL = { entra: 'directory_source.entra', ldap: 'directory_source.ldap' } as const;

/**
 * Your phone and mobile in My account (REQ-PRT-013 AC2/AC3, WP-028), in the portal and the
 * console. Editable only when the tenant allows it (the server says so in `contact_editable`);
 * numbers a directory keeps are read-only with a note saying which one, and the API refuses
 * them too: the screen never decides on its own.
 */
export function ContactDetailsCard() {
  const me = useSession().data?.user.id;
  const user = useUser(me);
  if (user.data === undefined) return null;
  // Keyed by version: a saved or live-updated record starts the form from the new values.
  return <ContactDetails key={user.data.version} user={user.data} />;
}

function ContactDetails({ user: data }: { user: UserDetail }) {
  const t = useLabel();
  const update = useUpdateUser(data.id);
  const [phone, setPhone] = useState(data.phone ?? '');
  const [mobile, setMobile] = useState(data.mobile ?? '');

  const editable = data.contact_editable;
  const source = data.directory_source;
  const changed = phone.trim() !== (data.phone ?? '') || mobile.trim() !== (data.mobile ?? '');
  const shown = (value: string | null) => value ?? t('account.contact.none');

  return (
    <Card title={t('account.contact.title')} data-testid="account-contact">
      {source != null && (
        <Alert
          type="info"
          showIcon
          message={t('directory.managed_by')}
          description={t('account.contact.from_directory', { source: t(SOURCE_LABEL[source]) })}
          style={{ marginBottom: 16 }}
          data-testid="account-contact-directory"
        />
      )}
      {editable ? (
        <Form
          layout="vertical"
          onFinish={() => {
            update.mutate(
              {
                changes: { phone: phone.trim() || null, mobile: mobile.trim() || null },
                version: data.version,
              },
              { onError: reportError },
            );
          }}
        >
          <Form.Item label={t('account.contact.phone')} htmlFor="account-phone">
            <Input
              id="account-phone"
              type="tel"
              autoComplete="tel"
              size="large"
              value={phone}
              count={lengthLimit(NUMBER_MAX)}
              onChange={(event) => {
                setPhone(event.target.value);
              }}
              data-testid="account-phone"
            />
          </Form.Item>
          <Form.Item label={t('account.contact.mobile')} htmlFor="account-mobile">
            <Input
              id="account-mobile"
              type="tel"
              autoComplete="tel"
              size="large"
              value={mobile}
              count={lengthLimit(NUMBER_MAX)}
              onChange={(event) => {
                setMobile(event.target.value);
              }}
              data-testid="account-mobile"
            />
          </Form.Item>
          <Button
            type="primary"
            size="large"
            htmlType="submit"
            disabled={!changed}
            loading={update.isPending}
            data-testid="account-contact-save"
          >
            {t('account.contact.save')}
          </Button>
        </Form>
      ) : (
        <Flex vertical gap={8}>
          <Typography.Text>
            {t('account.contact.phone')}: <span dir="ltr">{shown(data.phone)}</span>
          </Typography.Text>
          <Typography.Text>
            {t('account.contact.mobile')}: <span dir="ltr">{shown(data.mobile)}</span>
          </Typography.Text>
          {source == null && (
            <Typography.Text type="secondary" data-testid="account-contact-locked">
              {t('errors.contact_editing_off')}
            </Typography.Text>
          )}
        </Flex>
      )}
    </Card>
  );
}
