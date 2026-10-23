import { App, Card, Descriptions, Form, Input, Skeleton, Space, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useSession,
  useUpdateUser,
  useUser,
  type UserDetail,
} from '@supportx/api-client';
import { applyServerErrors, FormField, useForm, z, zodResolver } from '@supportx/forms';
import { ConflictDialog, reportError, useLabel, WriteButton } from '@supportx/ui';

const schema = z.object({
  signature: z.string().max(2000, 'errors.field.value_too_long'),
  time_zone: z.string().max(64, 'errors.field.value_too_long'),
});
type Values = z.infer<typeof schema>;
const FIELDS = ['signature', 'time_zone'] as const;

function valuesOf(user: UserDetail): Values {
  return { signature: user.signature ?? '', time_zone: user.time_zone ?? '' };
}

type Field = (typeof FIELDS)[number];

/**
 * Only the fields the user changed (PATCH semantics): a save never overwrites a field someone
 * else changed meanwhile that this user did not touch. Empty inputs clear the preference (null).
 */
function changesOf(values: Values, fields: readonly Field[]) {
  const all = {
    signature: values.signature === '' ? null : values.signature,
    time_zone: values.time_zone.trim() === '' ? null : values.time_zone.trim(),
  };
  return Object.fromEntries(fields.map((name) => [name, all[name]]));
}

/**
 * My profile: the preferences SupportX owns (reply signature, time zone). Saved with If-Match
 * for the version the form was loaded from: if someone saved in between (another tab, another
 * device) the API answers 409 and the conflict dialog lets the user choose.
 */
export function ProfilePage() {
  const t = useLabel();
  const me = useSession().data?.user;
  const user = useUser(me?.id);

  if (me === undefined || user.data === undefined) return <Skeleton active />;
  return (
    <Space direction="vertical" size="large" style={{ width: '100%', maxWidth: 720 }}>
      <Typography.Title level={1}>{t('profile.title')}</Typography.Title>
      <Card>
        <Descriptions column={1} size="small">
          <Descriptions.Item label={t('users.col.name')}>{me.display_name}</Descriptions.Item>
          <Descriptions.Item label={t('users.col.email')}>{me.email}</Descriptions.Item>
          <Descriptions.Item label={t('appearance.language')}>
            {t(`locale.${me.locale}`)}
          </Descriptions.Item>
        </Descriptions>
        <Typography.Text type="secondary">{t('profile.identity')}</Typography.Text>
      </Card>
      <ProfileForm user={user.data} reload={async () => (await user.refetch()).data} />
    </Space>
  );
}

function ProfileForm({
  user,
  reload,
}: {
  user: UserDetail;
  reload: () => Promise<UserDetail | undefined>;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const update = useUpdateUser(user.id);
  // The version this form's values are based on: sent as If-Match on save.
  const [baseVersion, setBaseVersion] = useState(user.version);
  const [conflict, setConflict] = useState(false);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: valuesOf(user) });

  const changedFields = () => FIELDS.filter((name) => form.getFieldState(name).isDirty);
  const save = (values: Values, version: number, fields: readonly Field[]) => {
    update.mutate(
      { changes: changesOf(values, fields), version },
      {
        onSuccess: (saved) => {
          form.reset(valuesOf(saved));
          setBaseVersion(saved.version);
          void message.success(t('profile.saved'));
        },
        onError: (error) => {
          if (error instanceof ApiError && error.isConflict) {
            setConflict(true);
          } else if (!applyServerErrors(error, form.setError, FIELDS)) {
            reportError(error);
          }
        },
      },
    );
  };

  return (
    <Card>
      <Form
        layout="vertical"
        onFinish={() => {
          void form.handleSubmit((values) => {
            save(values, baseVersion, changedFields());
          })();
        }}
      >
        <FormField
          control={form.control}
          name="signature"
          labelKey="profile.signature"
          helpKey="profile.signature_help"
          render={(field) => <Input.TextArea {...field} rows={4} data-testid="profile-signature" />}
        />
        <FormField
          control={form.control}
          name="time_zone"
          labelKey="profile.time_zone"
          helpKey="profile.time_zone_help"
          render={(field) => <Input {...field} data-testid="profile-time-zone" />}
        />
        <Space>
          <WriteButton
            type="primary"
            htmlType="submit"
            loading={update.isPending}
            data-testid="profile-save"
          >
            {t('actions.save')}
          </WriteButton>
          <WriteButton
            onClick={() => {
              form.reset();
            }}
          >
            {t('actions.reset')}
          </WriteButton>
        </Space>
      </Form>
      <ConflictDialog
        open={conflict}
        onReload={() => {
          setConflict(false);
          void reload().then((latest) => {
            if (latest !== undefined) {
              form.reset(valuesOf(latest));
              setBaseVersion(latest.version);
            }
          });
        }}
        onKeepMine={() => {
          setConflict(false);
          // My edited fields, laid over the latest saved version; everything else is theirs.
          const fields = changedFields();
          const mine = form.getValues();
          void reload().then((latest) => {
            if (latest !== undefined) {
              form.reset(valuesOf(latest));
              for (const name of fields) form.setValue(name, mine[name], { shouldDirty: true });
              setBaseVersion(latest.version);
              save(form.getValues(), latest.version, fields);
            }
          });
        }}
      />
    </Card>
  );
}
