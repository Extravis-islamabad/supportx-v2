import { App, Button } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { useCreateCi } from '@supportx/api-client';
import { applyServerErrors, useForm, zodResolver } from '@supportx/forms';
import {
  FormPage,
  FormProblem,
  NoAccess,
  NotInPlan,
  useLicence,
  WriteButton,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

import { useCmdbRight } from './rights';
import { CiFields } from './CiForm';
import { EMPTY, FIELDS, bodyOf, schema, type Values } from './form';

/** A new configuration item (template B, D-147). */
export function NewCiPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const may = useCmdbRight();
  const { has, isAdmin } = useLicence();
  const create = useCreateCi();
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: EMPTY });
  // One key per form: a retried save creates one CI, not two.
  const [key, setKey] = useState(() => crypto.randomUUID());
  const problem = useFormProblem();
  if (!has('cmdb')) return <NotInPlan titleKey="nav.cmdb" isAdmin={isAdmin} />;
  if (!may('add')) return <NoAccess titleKey="nav.cmdb" />;
  const save = form.handleSubmit((values) => {
    problem.clear();
    create.mutate(
      { body: bodyOf(values), key },
      {
        onSuccess: (saved) => {
          void message.success(saved.display_id);
          void navigate(`/cmdb/${saved.id}`, { replace: true });
        },
        onError: (error) => {
          setKey(crypto.randomUUID());
          if (!applyServerErrors(error, form.setError, FIELDS)) problem.show(error);
        },
      },
    );
  });
  return (
    <FormPage
      testId="ci-new"
      title={t('cmdb.title.new_ci')}
      back={{ label: t('cmdb.title'), onClick: () => void navigate('/cmdb') }}
      notice={<FormProblem problem={problem} />}
      cancel={<Button onClick={() => void navigate('/cmdb')}>{t('actions.cancel')}</Button>}
      primary={
        <WriteButton
          type="primary"
          loading={create.isPending}
          onClick={() => void save()}
          data-testid="ci-save"
        >
          {t('actions.save')}
        </WriteButton>
      }
    >
      <CiFields form={form} />
    </FormPage>
  );
}
