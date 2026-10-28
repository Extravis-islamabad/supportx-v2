import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Segmented,
  Skeleton,
  Space,
  Typography,
} from 'antd';
import { useEffect, useRef, useState } from 'react';

import {
  ApiError,
  queryKeys,
  useSession,
  useSetFormDensity,
  useUpdateUser,
  useUser,
  type FormDensity,
  type UserDetail,
} from '@supportx/api-client';
import { applyServerErrors, FormField, useForm, z, zodResolver } from '@supportx/forms';
import { useRecordChannel, type PresenceMember } from '@supportx/realtime';
import {
  AccountSecurityCard,
  ConflictDialog,
  PresenceAvatars,
  reportError,
  useLabel,
  useLicence,
  WriteButton,
} from '@supportx/ui';

import { AvailabilityCard } from '../AvailabilitySwitch';
import { NotificationPreferencesCard } from '../notifications/NotificationPreferencesCard';

/** Record forms one column with labels above, or compact (WP-020c); saved with the user. */
function FormDensityCard({ userId, value }: { userId: string; value: FormDensity }) {
  const t = useLabel();
  const setDensity = useSetFormDensity(userId);
  return (
    <Card title={t('form_density.title')}>
      <Space direction="vertical">
        <Segmented<FormDensity>
          aria-label={t('form_density.title')}
          value={value}
          onChange={(next) => {
            setDensity.mutate(next, { onError: reportError });
          }}
          options={[
            { value: 'comfortable', label: t('form_density.comfortable') },
            { value: 'compact', label: t('form_density.compact') },
          ]}
          data-testid="profile-density"
        />
        <Typography.Text type="secondary">{t('profile.form_density_help')}</Typography.Text>
      </Space>
    </Card>
  );
}

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
  const licence = useLicence();

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
      <AccountSecurityCard />
      <NotificationPreferencesCard />
      <FormDensityCard userId={me.id} value={me.form_density} />
      {me.user_type === 'technician' && licence.has('incident') && (
        <AvailabilityCard userId={me.id} />
      )}
      <ProfileForm
        user={user.data}
        selfName={me.display_name}
        reload={async () => (await user.refetch()).data}
      />
    </Space>
  );
}

function ProfileForm({
  user,
  selfName,
  reload,
}: {
  user: UserDetail;
  selfName: string;
  reload: () => Promise<UserDetail | undefined>;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const update = useUpdateUser(user.id);
  // The version this form's values are based on: sent as If-Match on save.
  const [baseVersion, setBaseVersion] = useState(user.version);
  const base = useRef(baseVersion);
  useEffect(() => {
    base.current = baseVersion;
  }, [baseVersion]);
  const others = useRef<PresenceMember[]>([]);
  // The 409 itself (null: no conflict): the dialog says who changed which fields.
  const [conflict, setConflict] = useState<unknown>(null);
  // Live (WP-011): a save elsewhere is announced before this user saves; the 409 dialog stays
  // as the safety net. `changedBy` is who saved (a name), null while nothing new arrived.
  const [changedBy, setChangedBy] = useState<string | null>(null);
  const viewers = useRecordChannel('users', user.id, (event) => {
    if (event.type !== 'users.changed' && event.type !== 'refresh') return;
    if (event.version !== undefined && event.version <= base.current) return; // our own save
    void queryClient.invalidateQueries({ queryKey: queryKeys.users.detail(user.id) });
    if (event.type === 'refresh') return;
    const by =
      event.by === user.id
        ? t('live.you_elsewhere', { name: selfName })
        : (others.current.find((v) => v.userId === event.by)?.name ?? t('live.someone'));
    setChangedBy(by);
  });
  useEffect(() => {
    others.current = viewers;
  }, [viewers]);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: valuesOf(user) });
  const takeLatest = () => {
    setChangedBy(null);
    void reload().then((latest) => {
      if (latest !== undefined) {
        form.reset(valuesOf(latest));
        setBaseVersion(latest.version);
      }
    });
  };

  const changedFields = () => FIELDS.filter((name) => form.getFieldState(name).isDirty);
  const save = (values: Values, version: number, fields: readonly Field[]) => {
    update.mutate(
      { changes: changesOf(values, fields), version },
      {
        onSuccess: (saved) => {
          form.reset(valuesOf(saved));
          setBaseVersion(saved.version);
          setChangedBy(null);
          void message.success(t('profile.saved'));
        },
        onError: (error) => {
          if (error instanceof ApiError && error.isConflict) {
            setConflict(error);
          } else if (!applyServerErrors(error, form.setError, FIELDS)) {
            reportError(error);
          }
        },
      },
    );
  };

  return (
    <Card extra={<PresenceAvatars viewers={viewers} selfUserId={user.id} />}>
      {changedBy !== null && (
        <Alert
          type="warning"
          showIcon
          role="status"
          data-testid="live-change-notice"
          style={{ marginBottom: 16 }}
          message={t('live.changed_by', { name: changedBy })}
          action={
            <Button size="small" onClick={takeLatest} data-testid="live-change-reload">
              {t('live.reload')}
            </Button>
          }
        />
      )}
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
        open={conflict !== null}
        error={conflict}
        fieldLabel={(field) =>
          t(field === 'nav_layout' ? 'appearance.navigation' : `profile.${field}`)
        }
        onReload={() => {
          setConflict(null);
          takeLatest();
        }}
        onKeepMine={() => {
          setConflict(null);
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
