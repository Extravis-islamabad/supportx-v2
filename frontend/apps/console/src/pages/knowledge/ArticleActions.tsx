import { App, Button, Input, Modal, Space, Tooltip } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import {
  useDeleteKbArticle,
  useKbStep,
  type KbArticle,
  type KbLanguage,
  type KbStep,
} from '@supportx/api-client';
import {
  ConflictDialog,
  lengthLimit,
  reportError,
  useConflictRetry,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { stepBlocked } from './model';

const NEEDS_TEXT: Partial<Record<KbStep, 'note' | 'reason'>> = {
  submit: 'note',
  reject: 'reason',
  withdraw: 'reason',
};

/** The review steps of one article in one language, with confirmations and reasons. */
export function ArticleActions({
  article,
  language,
  onEdit,
}: {
  article: KbArticle;
  language: KbLanguage;
  onEdit: () => void;
}) {
  const t = useLabel();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const step = useKbStep(article.id);
  const remove = useDeleteKbArticle(article.id);
  const conflict = useConflictRetry();
  const [asking, setAsking] = useState<KbStep | null>(null);
  const [text, setText] = useState('');
  const draft = article.drafts[language];

  const run = (which: KbStep, version: number, value?: string) => {
    step.mutate(
      { step: which, version, language, text: value },
      {
        onSuccess: () => {
          setAsking(null);
          setText('');
          void message.success(t(`knowledge.done.${which}`));
        },
        onError: (error) => {
          if (
            !conflict.take(error, (latest) => {
              run(which, latest, value);
            })
          )
            reportError(error);
        },
      },
    );
  };
  const versionFor = (which: KbStep) =>
    which === 'submit' || which === 'approve' || which === 'reject'
      ? (draft?.version ?? 0)
      : article.version;
  const start = (which: KbStep) => {
    if (NEEDS_TEXT[which] === undefined) run(which, versionFor(which));
    else setAsking(which);
  };
  const deleteIt = (version: number) => {
    remove.mutate(version, {
      onSuccess: () => {
        void message.success(t('knowledge.done.delete'));
        void navigate('/knowledge');
      },
      onError: (error) => {
        if (!conflict.take(error, deleteIt)) reportError(error);
      },
    });
  };

  const button = (which: KbStep | 'edit' | 'delete', onClick: () => void, primary = false) => {
    const why = stepBlocked(which, article, language);
    const control = (
      <WriteButton
        type={primary ? 'primary' : 'default'}
        danger={which === 'delete' || which === 'withdraw'}
        disabled={why !== null}
        loading={step.isPending && step.variables.step === which}
        onClick={onClick}
        data-testid={`kb-action-${which}`}
      >
        {t(`knowledge.action.${which}`)}
      </WriteButton>
    );
    return why === null ? (
      <span key={which}>{control}</span>
    ) : (
      <Tooltip key={which} title={t(why)}>
        <span tabIndex={0} aria-label={`${t(`knowledge.action.${which}`)}: ${t(why)}`}>
          {control}
        </span>
      </Tooltip>
    );
  };

  const kind = asking === null ? undefined : NEEDS_TEXT[asking];
  return (
    <Space wrap>
      <ConflictDialog {...conflict.dialog} fieldLabel={(field) => t(`knowledge.field.${field}`)} />
      {button('edit', onEdit)}
      {button(
        'submit',
        () => {
          start('submit');
        },
        true,
      )}
      {button(
        'approve',
        () => {
          start('approve');
        },
        true,
      )}
      {button('reject', () => {
        start('reject');
      })}
      {button('still_correct', () => {
        start('still_correct');
      })}
      {button('withdraw', () => {
        start('withdraw');
      })}
      {button('delete', () => {
        Modal.confirm({
          title: t('knowledge.confirm_delete'),
          content: t('knowledge.confirm_delete_explain'),
          okText: t('actions.delete'),
          okButtonProps: { danger: true },
          cancelText: t('actions.cancel'),
          onOk: () => {
            deleteIt(article.version);
          },
        });
      })}
      <Modal
        open={asking !== null}
        title={asking === null ? '' : t(`knowledge.action.${asking}`)}
        okText={asking === null ? '' : t(`knowledge.action.${asking}`)}
        okButtonProps={{
          disabled: kind === 'reason' && text.trim() === '',
          danger: asking === 'withdraw',
        }}
        cancelText={t('actions.cancel')}
        confirmLoading={step.isPending}
        onCancel={() => {
          setAsking(null);
        }}
        onOk={() => {
          if (asking !== null) run(asking, versionFor(asking), text);
        }}
        destroyOnHidden
      >
        <label htmlFor="kb-step-text">
          {t(kind === 'note' ? 'knowledge.field.change_note' : 'knowledge.field.reason')}
        </label>
        <Input.TextArea
          id="kb-step-text"
          rows={3}
          count={lengthLimit(kind === 'note' ? 500 : 2000, true)}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
          data-testid="kb-step-text"
        />
      </Modal>
      {article.withdrawn && (
        <Button
          onClick={() => {
            void navigate(`/knowledge/articles/${article.id}/edit/${language}`);
          }}
          data-testid="kb-republish"
        >
          {t('knowledge.action.republish')}
        </Button>
      )}
    </Space>
  );
}
