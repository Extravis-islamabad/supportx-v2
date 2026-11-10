import { MoreOutlined } from '@ant-design/icons';
import { App, Button, Dropdown, Input, Modal, Space } from 'antd';
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

// Beside "More": the page's 4-action rule (UI pass 2; QA6-KB-01).
const MAX_SHOWN = 3;

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
  only,
  onDecided,
}: {
  article: KbArticle;
  language: KbLanguage;
  onEdit: () => void;
  /** Show only these actions (the approval inbox: approve and send back). */
  only?: readonly (KbStep | 'edit' | 'delete')[];
  /** After a step went through (the inbox moves to the next article). */
  onDecided?: (step: KbStep) => void;
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
          onDecided?.(which);
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

  type Which = KbStep | 'edit' | 'delete';
  const confirmDelete = () => {
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
  };
  const actions: { which: Which; onClick: () => void }[] = [
    { which: 'edit', onClick: onEdit },
    ...(['submit', 'approve', 'reject', 'still_correct', 'withdraw'] as const).map((which) => ({
      which,
      onClick: () => {
        start(which);
      },
    })),
    { which: 'delete', onClick: confirmDelete },
  ];
  // Only what this person may do now is offered (QA6-KB-01, -02): no wall of disabled buttons.
  const offered = actions.filter(
    (a) =>
      (only === undefined || only.includes(a.which)) &&
      stepBlocked(a.which, article, language) === null,
  );
  // Withdraw and delete are in "More", with their confirmation; at most 3 others beside it.
  const destructive = (which: Which) => which === 'withdraw' || which === 'delete';
  const plain = offered.filter((a) => !destructive(a.which));
  const shown = only === undefined ? plain.slice(0, MAX_SHOWN) : plain;
  const more = [
    ...plain.filter((a) => !shown.includes(a)),
    ...offered.filter((a) => destructive(a.which)),
  ];
  const primary = shown.find((a) => a.which === 'submit' || a.which === 'approve')?.which;

  const kind = asking === null ? undefined : NEEDS_TEXT[asking];
  return (
    <Space wrap>
      <ConflictDialog {...conflict.dialog} fieldLabel={(field) => t(`knowledge.field.${field}`)} />
      {shown.map((a) => (
        <WriteButton
          key={a.which}
          type={a.which === primary ? 'primary' : 'default'}
          loading={step.isPending && step.variables.step === a.which}
          onClick={a.onClick}
          data-testid={`kb-action-${a.which}`}
        >
          {t(`knowledge.action.${a.which}`)}
        </WriteButton>
      ))}
      {more.length > 0 && (
        <Dropdown
          trigger={['click']}
          menu={{
            items: more.map((a) => ({
              key: a.which,
              danger: destructive(a.which),
              label: (
                <span data-testid={`kb-action-${a.which}`}>{t(`knowledge.action.${a.which}`)}</span>
              ),
              onClick: a.onClick,
            })),
          }}
        >
          <Button data-testid="kb-more" icon={<MoreOutlined />}>
            {t('actions.more')}
          </Button>
        </Dropdown>
      )}
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
          // Room for its counter above the dialog's buttons (QA6-KB-06).
          style={{ marginBottom: 20 }}
        />
      </Modal>
      {article.withdrawn && only === undefined && (
        <WriteButton
          onClick={() => {
            void navigate(`/knowledge/articles/${article.id}/edit/${language}`);
          }}
          data-testid="kb-republish"
        >
          {t('knowledge.action.republish')}
        </WriteButton>
      )}
    </Space>
  );
}
