import { App, Button, Card, Space, Typography } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { useCreateAnnouncement } from '@supportx/api-client';
import { applyServerErrors, useForm, zodResolver } from '@supportx/forms';
import { NoAccess, reportError, useAccess, useLabel, WriteButton } from '@supportx/ui';

import { AnnouncementFields } from './AnnouncementForm';
import { bodyOf, EMPTY, FIELDS, schema, type Values } from './form';

/** A new announcement, saved as a draft (publishing is a separate, explicit step). */
export function NewAnnouncementPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { can } = useAccess();
  const create = useCreateAnnouncement();
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: EMPTY });
  // One key per form: a retried save (timeout, double click) creates one announcement, not two.
  const [key, setKey] = useState(() => crypto.randomUUID());

  if (!can('announcements.manage')) return <NoAccess titleKey="nav.announcements" />;
  const save = form.handleSubmit((values) => {
    create.mutate(
      { body: { ...EMPTY, ...bodyOf(values) }, key },
      {
        onSuccess: (saved) => {
          void message.success(t('announcements.created', { id: saved.display_id }));
          void navigate(`/announcements/${saved.id}`, { replace: true });
        },
        onError: (error) => {
          // Corrected input is a different request: it needs its own key.
          setKey(crypto.randomUUID());
          if (!applyServerErrors(error, form.setError, FIELDS)) reportError(error);
        },
      },
    );
  });
  return (
    <Space direction="vertical" size="large" style={{ width: '100%', maxWidth: 860 }}>
      <Typography.Title level={1}>{t('announcements.new')}</Typography.Title>
      <Card>
        <AnnouncementFields
          form={form}
          footer={
            <Space>
              <WriteButton
                type="primary"
                loading={create.isPending}
                onClick={() => void save()}
                data-testid="ann-save"
              >
                {t('announcements.save_draft')}
              </WriteButton>
              <Button onClick={() => void navigate('/announcements')}>{t('actions.cancel')}</Button>
            </Space>
          }
        />
      </Card>
    </Space>
  );
}
