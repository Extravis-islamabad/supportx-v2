import { CloseOutlined } from '@ant-design/icons';
import { Alert, Button, Flex, Form, Select, Skeleton, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useIncidentTemplates,
  useMajorSettings,
  useUpdateMajorSettings,
  useUser,
} from '@supportx/api-client';
import {
  FormProblem,
  SettingsCard,
  useAppearance,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { templateLabel } from '../../incidents/labels';
import { GroupPicker, UserPicker } from '../../incidents/pickers';

// WP-046b S4 (REQ-INC-141): who is told when an incident is declared major (a group and named
// people) and the template it switches to. Saved at once through its own route (If-Match,
// audited), not through the page's save bar.

function Person({ id, onRemove }: { id: string; onRemove: () => void }) {
  const t = useLabel();
  const user = useUser(id, { silent: true });
  const name = user.data?.display_name ?? t('settings.major.someone');
  return (
    <Flex gap={8} align="center" data-testid={`settings-major-person-${id}`}>
      <bdi>{name}</bdi>
      <Button
        type="text"
        size="small"
        icon={<CloseOutlined aria-hidden />}
        aria-label={t('settings.major.remove_person', { name })}
        onClick={onRemove}
      />
    </Flex>
  );
}

export function MajorSettingsCard() {
  const t = useLabel();
  const { locale } = useAppearance();
  const saved = useMajorSettings();
  const templates = useIncidentTemplates();
  const update = useUpdateMajorSettings();
  const problem = useFormProblem();
  const [conflict, setConflict] = useState(false);
  const [draft, setDraft] = useState<{
    group: string | null;
    people: string[];
    template: string | null;
  } | null>(null);
  const data = saved.data;
  if (data === undefined) {
    // The card keeps its place while it loads, so the page does not jump (lane C).
    return (
      <SettingsCard title={t('settings.major.title')} testId="settings-major">
        <Skeleton active paragraph={{ rows: 3 }} />
      </SettingsCard>
    );
  }
  const shown = draft ?? {
    group: data.group_id ?? null,
    people: data.user_ids,
    template: data.template_id ?? null,
  };
  return (
    <SettingsCard title={t('settings.major.title')} testId="settings-major">
      <Typography.Paragraph type="secondary">{t('settings.major.help')}</Typography.Paragraph>
      <Form layout="vertical" component="div">
        <Form.Item label={t('settings.major.group')} htmlFor="settings-major-group">
          <GroupPicker
            id="settings-major-group"
            value={shown.group}
            onChange={(group) => {
              setDraft({ ...shown, group });
            }}
            testId="settings-major-group"
            ariaLabel={t('settings.major.group')}
          />
        </Form.Item>
        <Form.Item label={t('settings.major.people')} htmlFor="settings-major-add">
          <Flex vertical gap={4}>
            {shown.people.map((id) => (
              <Person
                key={id}
                id={id}
                onRemove={() => {
                  setDraft({ ...shown, people: shown.people.filter((p) => p !== id) });
                }}
              />
            ))}
            <UserPicker
              id="settings-major-add"
              value={null}
              onChange={(id) => {
                if (id !== null && !shown.people.includes(id)) {
                  setDraft({ ...shown, people: [...shown.people, id] });
                }
              }}
              testId="settings-major-add"
              ariaLabel={t('settings.major.add_person')}
            />
          </Flex>
        </Form.Item>
        <Form.Item label={t('settings.major.template')} htmlFor="settings-major-template">
          <Select
            id="settings-major-template"
            allowClear
            value={shown.template}
            placeholder={t('settings.major.no_template')}
            onChange={(next: string | undefined) => {
              setDraft({ ...shown, template: next ?? null });
            }}
            options={(templates.data ?? [])
              .filter((tpl) => !tpl.disabled)
              .map((tpl) => ({ value: tpl.id, label: templateLabel(t, tpl, locale) }))}
            data-testid="settings-major-template"
          />
        </Form.Item>
        <FormProblem problem={problem} />
        {conflict && (
          <Alert
            type="warning"
            showIcon
            role="alert"
            data-testid="settings-major-conflict"
            message={t('settings.major.conflict')}
            action={
              <Button
                size="small"
                data-testid="settings-major-use-theirs"
                onClick={() => {
                  setDraft(null);
                  setConflict(false);
                }}
              >
                {t('settings.major.use_theirs')}
              </Button>
            }
          />
        )}
        <WriteButton
          type="primary"
          disabled={draft === null}
          loading={update.isPending}
          data-testid="settings-major-save"
          onClick={() => {
            problem.clear();
            update.mutate(
              {
                values: {
                  group_id: shown.group,
                  user_ids: shown.people,
                  template_id: shown.template,
                },
                version: data.settings_version,
              },
              {
                onSuccess: () => {
                  setDraft(null);
                  setConflict(false);
                },
                onError: (error) => {
                  // Someone saved meanwhile (409): said in words, with "Use theirs"; the saved
                  // values reload under your draft, so saving again replaces theirs (lane C).
                  if (error instanceof ApiError && error.status === 409) {
                    setConflict(true);
                    void saved.refetch();
                    return;
                  }
                  problem.show(error);
                },
              },
            );
          }}
        >
          {t('actions.save')}
        </WriteButton>
      </Form>
    </SettingsCard>
  );
}
