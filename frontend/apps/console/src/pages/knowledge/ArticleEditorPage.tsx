import {
  App,
  Alert,
  Button,
  Card,
  Flex,
  Form,
  Input,
  Result,
  Select,
  Space,
  Typography,
} from 'antd';
import { TreeSelect } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useBlocker, useNavigate, useParams, useSearchParams } from 'react-router';

import {
  ApiError,
  attachDrafts,
  useCreateKbArticle,
  useKbArticle,
  useKbTopics,
  useKbTypes,
  useNewKbDraft,
  useSaveKbDraft,
  useSession,
  type KbArticle,
  type KbLanguage,
  type KbVersion,
} from '@supportx/api-client';
import {
  ConflictDialog,
  inlineImageIds,
  lengthLimit,
  NoAccess,
  reportError,
  RichTextField,
  useAccess,
  useAppearance,
  useConflict,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { showFieldErrors } from './formErrors';
import { articleLanguage, topicTree, typeName, type TopicNode } from './model';

const AUTOSAVE_MS = 1500;

interface TreeOption {
  value: string;
  title: string;
  children: TreeOption[];
}
const treeOptions = (nodes: TopicNode[]): TreeOption[] =>
  nodes.map((node) => ({
    value: node.key,
    title: node.title,
    children: treeOptions(node.children),
  }));

/** Leaving with unsaved changes asks first (in-app navigation and closing the tab). */
function useLeaveGuard(dirty: boolean) {
  const t = useLabel();
  const { modal } = App.useApp();
  const blocker = useBlocker(dirty);
  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    modal.confirm({
      title: t('knowledge.leave_title'),
      content: t('knowledge.leave_explain'),
      okText: t('knowledge.leave'),
      cancelText: t('knowledge.stay'),
      onOk: () => {
        blocker.proceed();
      },
      onCancel: () => {
        blocker.reset();
      },
    });
  }, [blocker, modal, t]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => {
      window.removeEventListener('beforeunload', warn);
    };
  }, [dirty]);
}

interface NewArticleForm {
  title: string;
  topic_id: string;
  type_code: string;
  language: KbLanguage;
  body_html: string;
  keywords: string[];
}

/** Write a new article: its first draft (REQ-KB-001). Pasted images become article files. */
export function NewArticlePage() {
  const t = useLabel();
  const navigate = useNavigate();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const [params] = useSearchParams();
  const me = useSession().data?.user.id;
  const language = articleLanguage(locale);
  const topics = useKbTopics();
  const types = useKbTypes();
  const create = useCreateKbArticle();
  const [form] = Form.useForm<NewArticleForm>();
  const [key] = useState(() => crypto.randomUUID());
  const [dirty, setDirty] = useState(false);
  useLeaveGuard(dirty && !create.isSuccess);
  const tree = useMemo(
    () => treeOptions(topicTree(topics.data ?? [], language)),
    [topics.data, language],
  );
  if (!can('knowledge.create')) return <NoAccess titleKey="nav.knowledge" />;

  const save = (values: NewArticleForm) => {
    create.mutate(
      {
        // The topic's audience until the article narrows it (REQ-KB-044).
        body: { ...values, own_audience: false, tech_all: true, requesters: 'none' },
        key,
      },
      {
        onSuccess: (article) => {
          setDirty(false);
          attachDrafts('kb_article', article.id, inlineImageIds(values.body_html)).catch(
            reportError,
          );
          void navigate(`/knowledge/articles/${article.id}/edit/${values.language}`, {
            replace: true,
          });
        },
        onError: (error) => {
          if (!showFieldErrors(form, error, t)) reportError(error);
        },
      },
    );
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%', maxWidth: 960 }}>
      <Typography.Title level={1} style={{ margin: 0 }}>
        {t('knowledge.new_article')}
      </Typography.Title>
      <Form<NewArticleForm>
        form={form}
        layout="vertical"
        initialValues={{
          topic_id: params.get('topic') ?? undefined,
          type_code: 'how_to',
          language,
          body_html: '',
          keywords: [],
        }}
        onValuesChange={() => {
          setDirty(true);
        }}
        onFinish={save}
      >
        <Form.Item
          label={t('knowledge.field.title')}
          name="title"
          rules={[{ required: true, whitespace: true, message: t('errors.field.title_required') }]}
        >
          <Input count={lengthLimit(250)} dir="auto" data-testid="kb-title" />
        </Form.Item>
        <Flex gap={12} wrap>
          <Form.Item
            label={t('knowledge.field.topic_id')}
            name="topic_id"
            rules={[{ required: true, message: t('knowledge.choose_topic') }]}
            style={{ flex: '1 1 240px' }}
          >
            <TreeSelect treeDefaultExpandAll treeData={tree} data-testid="kb-topic" />
          </Form.Item>
          <Form.Item
            label={t('knowledge.field.type_code')}
            name="type_code"
            style={{ flex: '1 1 200px' }}
          >
            <Select
              options={(types.data ?? [])
                .filter((type) => !type.retired)
                .map((type) => ({
                  value: type.code,
                  label: typeName(type, type.code, language, t),
                }))}
              data-testid="kb-type"
            />
          </Form.Item>
          <Form.Item
            label={t('knowledge.field.language')}
            name="language"
            style={{ flex: '1 1 160px' }}
          >
            <Select
              options={(['en', 'ar'] as const).map((value) => ({
                value,
                label: t(`knowledge.language.${value}`),
              }))}
              data-testid="kb-new-language"
            />
          </Form.Item>
        </Flex>
        <Form.Item label={t('knowledge.field.body_html')} name="body_html">
          <RichTextField
            label={t('knowledge.field.body_html')}
            callouts
            imageOwnerId={me}
            minHeight={320}
            testId="kb-body-editor"
          />
        </Form.Item>
        <Form.Item label={t('knowledge.field.keywords')} name="keywords">
          <Select mode="tags" tokenSeparators={[',']} open={false} data-testid="kb-keywords" />
        </Form.Item>
        <Space>
          <WriteButton
            type="primary"
            htmlType="submit"
            loading={create.isPending}
            data-testid="kb-create"
          >
            {t('knowledge.save_draft')}
          </WriteButton>
          <Button onClick={() => void navigate(-1)}>{t('actions.cancel')}</Button>
        </Space>
      </Form>
    </Space>
  );
}

/** Edit one language's draft with autosave (REQ-KB-013): If-Match on the draft's version. */
export function ArticleEditorPage() {
  const t = useLabel();
  const { id, lang } = useParams();
  const language: KbLanguage = lang === 'ar' ? 'ar' : 'en';
  const article = useKbArticle(id);
  const start = useNewKbDraft(id ?? '');
  if (article.error instanceof ApiError && article.error.status === 404) {
    return <Result status="404" title={t('errors.kb_article_not_found')} />;
  }
  if (article.data === undefined) return null;
  const draft = article.data.drafts[language];
  if (!article.data.can_edit) {
    return (
      <div data-testid="kb-not-editor">
        <Result status="403" title={t('knowledge.why.not_editor')} />
      </div>
    );
  }
  if (draft === undefined) {
    const has = article.data.published[language] !== undefined;
    return (
      <Result
        title={t(has ? 'knowledge.start_new_version' : 'knowledge.start_translation', {
          language: t(`knowledge.language.${language}`),
        })}
        extra={
          <WriteButton
            type="primary"
            loading={start.isPending}
            onClick={() => {
              start.mutate(language, { onError: reportError });
            }}
            data-testid="kb-start-draft"
          >
            {t('knowledge.start_draft')}
          </WriteButton>
        }
      />
    );
  }
  return (
    <DraftEditor
      key={`${article.data.id}:${language}`}
      article={article.data}
      draft={draft}
      language={language}
    />
  );
}

type SaveState = 'saved' | 'saving' | 'unsaved' | 'failed';

function DraftEditor({
  article,
  draft,
  language,
}: {
  article: KbArticle;
  draft: KbVersion;
  language: KbLanguage;
}) {
  const t = useLabel();
  const me = useSession().data?.user.id;
  const save = useSaveKbDraft(article.id, language);
  const conflict = useConflict();
  const [values, setValues] = useState<{
    title: string;
    body_html: string;
    keywords: string[];
    change_note: string;
    internal_note: string;
  }>({
    title: draft.title,
    body_html: draft.body_html,
    keywords: draft.keywords,
    change_note: draft.change_note ?? '',
    internal_note: draft.internal_note ?? '',
  });
  const [state, setState] = useState<SaveState>('saved');
  const version = useRef(draft.version);
  const attached = useRef(new Set(inlineImageIds(draft.body_html)));
  const locked = draft.status !== 'draft';
  useLeaveGuard(state === 'unsaved' || state === 'saving');

  useEffect(() => {
    if (state !== 'unsaved' || locked) return;
    const timer = setTimeout(() => {
      setState('saving');
      save.mutate(
        { changes: values, version: version.current },
        {
          onSuccess: (saved) => {
            version.current = saved.version;
            setState((current) => (current === 'saving' ? 'saved' : current));
            const fresh = inlineImageIds(values.body_html).filter(
              (fid) => !attached.current.has(fid),
            );
            for (const fid of fresh) attached.current.add(fid);
            attachDrafts('kb_article', article.id, fresh).catch(reportError);
          },
          onError: (error) => {
            setState('failed');
            if (!conflict.take(error)) reportError(error);
          },
        },
      );
    }, AUTOSAVE_MS);
    return () => {
      clearTimeout(timer);
    };
    // Only a change of the values (state "unsaved") starts the timer.
  }, [values, state]); // eslint-disable-line react-hooks/exhaustive-deps -- save/conflict are stable mutation helpers

  const change = (patch: Partial<typeof values>) => {
    setValues((current) => ({ ...current, ...patch }));
    setState('unsaved');
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%', maxWidth: 960 }}>
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        onReload={() => {
          window.location.reload();
        }}
        onKeepMine={() => {
          const current =
            conflict.error instanceof ApiError ? conflict.error.params.current_version : undefined;
          if (typeof current === 'number') version.current = current;
          conflict.clear();
          setState('unsaved');
        }}
        fieldLabel={(field) => t(`knowledge.field.${field}`)}
      />
      <Flex justify="space-between" align="center" wrap gap={12}>
        <Space direction="vertical" size={0}>
          <Typography.Text type="secondary">
            {article.display_id} · {t(`knowledge.language.${language}`)} ·{' '}
            {t('knowledge.version_number', { number: String(draft.number) })}
          </Typography.Text>
          <Typography.Title level={1} style={{ margin: 0 }}>
            {t('knowledge.edit_article')}
          </Typography.Title>
        </Space>
        <Space>
          <Typography.Text type="secondary" role="status" data-testid="kb-save-state">
            {t(`knowledge.save_state.${state}`)}
          </Typography.Text>
          <Link to={`/knowledge/articles/${article.id}`} data-testid="kb-done">
            {t('knowledge.done_editing')}
          </Link>
        </Space>
      </Flex>
      {locked && (
        <Alert
          type="info"
          showIcon
          message={t('errors.kb_draft_in_review')}
          data-testid="kb-locked"
        />
      )}
      {draft.reject_reason !== null && !locked && (
        <Alert
          type="warning"
          showIcon
          message={t('knowledge.sent_back')}
          description={t('history.reason', { reason: draft.reject_reason })}
        />
      )}
      <Card size="small">
        <Form layout="vertical" disabled={locked}>
          <Form.Item label={t('knowledge.field.title')} htmlFor="kb-edit-title">
            <Input
              id="kb-edit-title"
              count={lengthLimit(250)}
              dir={language === 'ar' ? 'rtl' : 'ltr'}
              value={values.title}
              onChange={(event) => {
                change({ title: event.target.value });
              }}
              data-testid="kb-edit-title"
            />
          </Form.Item>
          <div dir={language === 'ar' ? 'rtl' : 'ltr'} lang={language}>
            <RichTextField
              label={t('knowledge.field.body_html')}
              value={values.body_html}
              onChange={(html) => {
                change({ body_html: html });
              }}
              callouts
              imageOwnerId={me}
              minHeight={360}
              disabled={locked}
              testId="kb-edit-body"
            />
          </div>
          <Form.Item label={t('knowledge.field.keywords')} style={{ marginTop: 16 }}>
            <Select
              mode="tags"
              open={false}
              tokenSeparators={[',']}
              value={values.keywords}
              onChange={(keywords: string[]) => {
                change({ keywords });
              }}
              aria-label={t('knowledge.field.keywords')}
            />
          </Form.Item>
          <Form.Item label={t('knowledge.field.change_note')} htmlFor="kb-change-note">
            <Input
              id="kb-change-note"
              count={lengthLimit(500)}
              value={values.change_note}
              onChange={(event) => {
                change({ change_note: event.target.value });
              }}
            />
          </Form.Item>
          <Form.Item
            label={t('knowledge.field.internal_note')}
            help={t('knowledge.internal_note_help')}
            htmlFor="kb-internal-note"
          >
            <Input.TextArea
              id="kb-internal-note"
              rows={2}
              count={lengthLimit(2000)}
              value={values.internal_note}
              onChange={(event) => {
                change({ internal_note: event.target.value });
              }}
            />
          </Form.Item>
        </Form>
      </Card>
    </Space>
  );
}
