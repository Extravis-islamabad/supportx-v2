import { App, Button } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { useCreateAnnouncement, useSession } from '@supportx/api-client';
import { applyServerErrors, useForm, zodResolver } from '@supportx/forms';
import {
  FormPage,
  FormProblem,
  NoAccess,
  useAccess,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { AnnouncementFields } from './AnnouncementForm';
import { bodyOf, EMPTY, FIELDS, schema, type Values } from './form';

/** A new announcement, saved as a draft (publishing is a separate, explicit step). */
export function NewAnnouncementPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { can } = useAccess();
  const create = useCreateAnnouncement();
  // The author owns it unless they pick someone else (the picker shows their name).
  const me = useSession().data?.user.id ?? null;
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { ...EMPTY, owner_id: me },
  });
  // One key per form: a retried save (timeout, double click) creates one announcement, not two.
  const [key, setKey] = useState(() => crypto.randomUUID());
  // A refusal with no field to point at is shown above Save (QA WP-029 BUG-02).
  const problem = useFormProblem();

  if (!can('announcements.manage')) return <NoAccess titleKey="nav.announcements" />;
  const save = form.handleSubmit((values) => {
    problem.clear();
    create.mutate(
      // bodyOf leaves out an empty owner; the API then makes the author the owner.
      { body: { ...EMPTY, owner_id: undefined, ...bodyOf(values) }, key },
      {
        onSuccess: (saved) => {
          void message.success(t('announcements.created', { id: saved.display_id }));
          void navigate(`/announcements/${saved.id}`, { replace: true });
        },
        onError: (error) => {
          // Corrected input is a different request: it needs its own key.
          setKey(crypto.randomUUID());
          if (!applyServerErrors(error, form.setError, FIELDS)) problem.show(error);
        },
      },
    );
  });
  // Template B (D-147): sections in cards and one sticky bar, Cancel before Save draft.
  return (
    <FormPage
      testId="ann-new"
      title={t('announcements.new')}
      back={{ label: t('announcements.back'), onClick: () => void navigate('/announcements') }}
      notice={<FormProblem problem={problem} />}
      cancel={
        <Button onClick={() => void navigate('/announcements')}>{t('actions.cancel')}</Button>
      }
      primary={
        <WriteButton
          type="primary"
          loading={create.isPending}
          onClick={() => void save()}
          data-testid="ann-save"
        >
          {t('announcements.save_draft')}
        </WriteButton>
      }
    >
      <AnnouncementFields form={form} />
    </FormPage>
  );
}
