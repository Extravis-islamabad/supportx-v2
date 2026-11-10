import { EyeOutlined } from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Flex,
  Form,
  Input,
  Popover,
  Radio,
  Select,
  Space,
  Switch,
  Tabs,
  Typography,
} from 'antd';
import dayjs from 'dayjs';
import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';

import {
  ApiError,
  useCatalogCategories,
  useCatalogItem,
  useCreateCatalogItem,
  useIncidentTemplates,
  useSlaPolicies,
  useUnits,
  useUpdateCatalogItem,
  type CatalogItem,
  type CatalogItemInput,
  type Labels,
} from '@supportx/api-client';
import {
  ConflictDialog,
  NoAccess,
  FormPage,
  RichTextField,
  lengthLimit,
  reportError,
  textIn,
  useAccess,
  pickerFormat,
  useAppearance,
  useLabel,
  useLicence,
  WriteButton,
} from '@supportx/ui';

import { UserPicker } from '../../incidents/pickers';
import { fieldMessages, refusalMessages } from '../incidents/helpers';
import { LabelsFields, Problems } from '../incidents/shared';
import { StatusTag } from './CatalogAdminPage';
import { ICONS } from './icons';
import { PlanEditor } from './PlanEditor';
import { PreviewDrawer } from './PreviewDrawer';
import { QuestionsEditor } from './QuestionsEditor';
import { categoryPaths } from './tree';

const LANGUAGES = ['en', 'ar', 'ur'] as const;
const PRIORITIES = ['p1', 'p2', 'p3', 'p4'] as const;
const TABS = ['details', 'form', 'approval', 'assignment', 'fulfilment', 'life'] as const;
type Tab = (typeof TABS)[number];
// The fields publishing needs, by their name on the form and the tab they are on: a refusal
// names the field and opens its tab, never a bare "This field is required." (QA10-P3-08).
const FIELD_PLACES: Record<string, { label: string; tab: Tab }> = {
  names: { label: 'catalog_admin.names', tab: 'details' },
  category_id: { label: 'catalog_admin.category', tab: 'details' },
  template_id: { label: 'catalog_admin.template', tab: 'details' },
  group_id: { label: 'catalog_admin.group', tab: 'assignment' },
};

/** What the form edits: the input fields, starting from the item (or empty for a new one). */
type Draft = CatalogItemInput & { names: Labels };

function draftOf(item: CatalogItem | undefined): Draft {
  if (item === undefined) {
    return {
      names: {},
      summaries: {},
      descriptions: {},
      keywords: {},
      questions: [],
      plan: [],
      audience: 'everyone',
      kind: 'service',
      auto_fulfil: true,
      requesters_see_approval: true,
      default_priority: 'p3',
    };
  }
  return {
    names: item.names,
    summaries: item.summaries,
    descriptions: item.descriptions,
    keywords: item.keywords,
    icon: item.icon,
    category_id: item.category_id,
    extra_category_ids: item.extra_category_ids,
    kind: item.kind,
    template_id: item.template_id,
    audience: item.audience,
    owner_id: item.owner_id,
    featured: item.featured,
    subject_template: item.subject_template,
    requesters_see_approval: item.requesters_see_approval,
    questions: item.questions,
    approval: item.approval,
    plan: item.plan,
    default_priority: item.default_priority,
    requester_sets_priority: item.requester_sets_priority,
    sla_policy_id: item.sla_policy_id,
    group_id: item.group_id,
    technician_id: item.technician_id,
    technician_after_approval: item.technician_after_approval,
    count_approval_time: item.count_approval_time,
    auto_fulfil: item.auto_fulfil,
    publish_at: item.publish_at,
    retire_at: item.retire_at,
  };
}

/** A translated text's place in words ("Question 2: help"), never its path (rule d). */
function fieldWords(t: ReturnType<typeof useLabel>, path: string): string {
  const [part, index, field] = path.split('.');
  const n = Number(index) + 1;
  if (part === 'questions' && field === 'option_labels') {
    return t('catalog_admin.where.option', { n });
  }
  if (part === 'questions') return t(`catalog_admin.where.question_${field ?? 'label'}`, { n });
  if (part === 'plan') return t('catalog_admin.where.task', { n });
  return t(`catalog_admin.field.${part ?? ''}`);
}

/** The fields of `draft` that differ from `item` (a PATCH sends only what changed). */
function changes(draft: Draft, item: CatalogItem): CatalogItemInput {
  const base = draftOf(item) as Record<string, unknown>;
  return Object.fromEntries(
    Object.entries(draft).filter(([k, v]) => compared(k, v) !== compared(k, base[k])),
  );
}

/** A field as compared: the editor marks every block `dir="auto"` when it loads (no change). */
function compared(field: string, value: unknown): string {
  const text = value === undefined ? '' : JSON.stringify(value);
  return field === 'descriptions' ? text.replaceAll(' dir=\\"auto\\"', '') : text;
}

/**
 * One catalog item (WP-031 plan D4): everything it decides, tab by tab, each saying in one line
 * what it controls; the status and its planned changes; a preview as a requester sees the form.
 * Saving sends only what changed, with If-Match; a stale save shows who changed what (409).
 */
export function CatalogItemPage() {
  const { can } = useAccess();
  const licence = useLicence();
  const { id } = useParams();
  if (!licence.has('service_request') || !can('catalog_items.manage')) {
    return <NoAccess titleKey="nav.admin_catalog" />;
  }
  return <ItemEditor key={id} id={id === 'new' ? undefined : id} />;
}

function ItemEditor({ id }: { id: string | undefined }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const loaded = useCatalogItem(id);
  const item = loaded.data;
  const [draft, setDraft] = useState<Draft>(() => draftOf(item));
  const [tab, setTab] = useState<Tab>('details');
  const [problems, setProblems] = useState<string[]>([]);
  const [conflict, setConflict] = useState<ApiError | null>(null);
  const [preview, setPreview] = useState(false);
  const [key] = useState(() => crypto.randomUUID());
  const create = useCreateCatalogItem();
  const update = useUpdateCatalogItem();
  // The form follows the item it was opened on; a change someone else saves arrives live but
  // never overwrites typing: the next save meets the 409 and the conflict dialog.
  const [opened, setOpened] = useState<CatalogItem | undefined>(item);
  if (item !== undefined && opened === undefined) {
    // The item arrived after the first render: start the form from it (React's "adjust state
    // while rendering" pattern, not an effect).
    setOpened(item);
    setDraft(draftOf(item));
  }
  const set = (next: Partial<Draft>) => {
    setDraft((d) => ({ ...d, ...next }));
  };
  const dirty = item === undefined || Object.keys(changes(draft, opened ?? item)).length > 0;

  const failed = (error: unknown) => {
    if (error instanceof ApiError && error.isConflict) {
      setConflict(error);
      return;
    }
    const placed =
      error instanceof ApiError && error.status === 422
        ? error.fieldErrors.map((f) => {
            const place = FIELD_PLACES[f.field.replace(/^body\./, '').split('.')[0] ?? ''];
            const words = t(f.message_key, f.params ?? {});
            return { place, words: place === undefined ? words : `${t(place.label)}: ${words}` };
          })
        : [];
    const shown = refusalMessages(
      t,
      error,
      placed.length > 0 ? placed.map((p) => p.words) : fieldMessages(t, error),
    );
    const first = placed.find((p) => p.place !== undefined)?.place;
    if (first !== undefined) setTab(first.tab);
    if (shown.length > 0) {
      setProblems(shown);
      // Seen at once, wherever the person had scrolled to.
      // Guarded: browsers without it (jsdom in tests) simply don't scroll.
      requestAnimationFrame(() => {
        const box = document.querySelector('[data-testid="cat-item-problems"]');
        if (box !== null && typeof box.scrollIntoView === 'function') {
          box.scrollIntoView({ block: 'nearest' });
        }
      });
    } else reportError(error);
  };

  const save = (extra: CatalogItemInput = {}) => {
    setProblems([]);
    if (item === undefined) {
      create.mutate(
        { body: { ...draft, ...extra }, key },
        {
          onSuccess: (made) => {
            void message.success(t('catalog_admin.saved'));
            void navigate(`/admin/catalog/items/${made.id}`, { replace: true });
          },
          onError: failed,
        },
      );
      return;
    }
    update.mutate(
      {
        id: item.id,
        body: { ...changes(draft, opened ?? item), ...extra },
        version: (opened ?? item).version,
      },
      {
        onSuccess: (saved) => {
          setDraft(draftOf(saved));
          setOpened(saved);
          void message.success(t('catalog_admin.saved'));
        },
        onError: failed,
      },
    );
  };

  if (id !== undefined && loaded.isLoading) return null;
  const busy = create.isPending || update.isPending;
  const missing = item?.missing_translations ?? [];
  // Template B's frame (D-147): Save in the sticky footer with Cancel before it, never in the
  // header or the middle of the form; Preview and the item's state stay in the header.
  return (
    <FormPage
      testId="cat-item"
      width="full"
      title={textIn(draft.names, locale) || t('catalog_admin.new_item')}
      back={{ label: t('nav.admin_catalog'), onClick: () => void navigate('/admin/catalog') }}
      cancel={
        <Button onClick={() => void navigate('/admin/catalog')} data-testid="cat-cancel">
          {t('actions.cancel')}
        </Button>
      }
      primary={
        <WriteButton
          type="primary"
          loading={busy}
          disabled={!dirty}
          onClick={() => {
            save();
          }}
          data-testid="cat-save"
        >
          {t('actions.save')}
        </WriteButton>
      }
      extra={
        <Space wrap>
          {item !== undefined && <StatusTag item={item} />}
          {missing.length > 0 && (
            <Popover
              content={
                <ul style={{ margin: 0, paddingInlineStart: 18 }} data-testid="cat-missing-list">
                  {missing.map((m) => (
                    <li key={`${m.field}-${m.language}`}>
                      {t('catalog_admin.missing_item', {
                        field: fieldWords(t, m.field),
                        language: t(`catalog_admin.lang.${m.language}`),
                      })}
                    </li>
                  ))}
                </ul>
              }
            >
              <Button size="small" data-testid="cat-missing">
                {t('catalog_admin.missing', { count: missing.length })}
              </Button>
            </Popover>
          )}
          <Button
            icon={<EyeOutlined />}
            onClick={() => {
              setPreview(true);
            }}
            data-testid="cat-preview"
          >
            {t('catalog_admin.preview')}
          </Button>
        </Space>
      }
    >
      <Problems problems={problems} testId="cat-item-problems" />
      <Tabs
        activeKey={tab}
        onChange={(next) => {
          setTab(next as Tab);
        }}
        items={TABS.map((key) => ({
          key,
          label: t(`catalog_admin.tab.${key}`),
          children: (
            <Card size="small">
              <Typography.Paragraph type="secondary">
                {t(`catalog_admin.tab.${key}_help`)}
              </Typography.Paragraph>
              {key === 'details' && <DetailsTab draft={draft} set={set} />}
              {key === 'form' && (
                <Flex vertical gap={16}>
                  <QuestionsEditor
                    value={draft.questions ?? []}
                    onChange={(questions) => {
                      set({ questions });
                    }}
                    disabled={draft.kind === 'incident_template'}
                  />
                  <Form layout="vertical" component="div">
                    <Form.Item
                      label={t('catalog_admin.subject_template')}
                      help={t('catalog_admin.subject_template_help')}
                    >
                      <Input
                        value={draft.subject_template ?? ''}
                        count={lengthLimit(200)}
                        onChange={(event) => {
                          set({ subject_template: event.target.value || null });
                        }}
                        data-testid="cat-subject-template"
                      />
                    </Form.Item>
                  </Form>
                </Flex>
              )}
              {key === 'approval' && <ApprovalTab draft={draft} set={set} />}
              {key === 'assignment' && <AssignmentTab draft={draft} set={set} />}
              {key === 'fulfilment' && (
                <Flex vertical gap={16}>
                  <PlanEditor
                    value={draft.plan ?? []}
                    onChange={(plan) => {
                      set({ plan });
                    }}
                    disabled={draft.kind === 'incident_template'}
                  />
                  <Flex align="center" gap={12}>
                    <Switch
                      checked={draft.auto_fulfil ?? true}
                      onChange={(auto_fulfil) => {
                        set({ auto_fulfil });
                      }}
                      aria-label={t('catalog_admin.auto_fulfil')}
                    />
                    <Typography.Text>{t('catalog_admin.auto_fulfil')}</Typography.Text>
                  </Flex>
                </Flex>
              )}
              {key === 'life' && (
                <LifeTab
                  item={item}
                  draft={draft}
                  set={set}
                  busy={busy}
                  onStatus={(status) => {
                    save({ status });
                  }}
                />
              )}
            </Card>
          ),
        }))}
      />
      {preview && (
        <PreviewDrawer
          draft={draft}
          onClose={() => {
            setPreview(false);
          }}
        />
      )}
      <ConflictDialog
        open={conflict !== null}
        error={conflict}
        fieldLabel={(field) => t(`catalog_admin.field.${field}`)}
        opened={opened}
        latest={item}
        onReload={() => {
          // Discard mine: the form shows what is saved now.
          setConflict(null);
          void loaded.refetch().then((fresh) => {
            if (fresh.data !== undefined) {
              setDraft(draftOf(fresh.data));
              setOpened(fresh.data);
            }
          });
        }}
        onKeepMine={() => {
          // Keep mine on top of the latest: the next save carries the new version.
          setConflict(null);
          void loaded.refetch().then((fresh) => {
            if (fresh.data !== undefined) setOpened(fresh.data);
          });
        }}
      />
    </FormPage>
  );
}

function PerLanguage({
  value,
  onChange,
  testId,
  limit,
  area,
}: {
  value: Record<string, string> | null | undefined;
  onChange: (next: Record<string, string>) => void;
  testId: string;
  limit: number;
  area?: boolean;
}) {
  const t = useLabel();
  return (
    <Flex vertical gap={8}>
      {LANGUAGES.map((lang) => {
        const props = {
          lang,
          dir: lang === 'en' ? ('ltr' as const) : ('rtl' as const),
          placeholder: t(`settings.name_in.${lang}`),
          'aria-label': t(`settings.name_in.${lang}`),
          count: lengthLimit(limit),
          value: value?.[lang] ?? '',
          'data-testid': `${testId}-${lang}`,
        };
        return area === true ? (
          <Input.TextArea
            key={lang}
            {...props}
            autoSize={{ minRows: 2, maxRows: 4 }}
            onChange={(event) => {
              onChange({ ...(value ?? {}), [lang]: event.target.value });
            }}
          />
        ) : (
          <Input
            key={lang}
            {...props}
            onChange={(event) => {
              onChange({ ...(value ?? {}), [lang]: event.target.value });
            }}
          />
        );
      })}
    </Flex>
  );
}

interface TabProps {
  draft: Draft;
  set: (next: Partial<Draft>) => void;
}

function DetailsTab({ draft, set }: TabProps) {
  const t = useLabel();
  const { locale } = useAppearance();
  const categories = useCatalogCategories();
  const templates = useIncidentTemplates(draft.kind === 'incident_template');
  const paths = useMemo(
    () => categoryPaths(categories.data ?? [], locale),
    [categories.data, locale],
  );
  const categoryOptions = (categories.data ?? []).map((c) => ({
    value: c.id,
    label: paths.get(c.id),
  }));
  const [descriptionLang, setDescriptionLang] = useState<(typeof LANGUAGES)[number]>('en');
  return (
    <Form layout="vertical" component="div">
      <LabelsFields
        value={draft.names}
        onChange={(names) => {
          set({ names });
        }}
        testId="cat-name"
        autoFocus={false}
      />
      <Form.Item label={t('catalog_admin.summary')} help={t('catalog_admin.summary_help')}>
        <PerLanguage
          value={draft.summaries}
          onChange={(summaries) => {
            set({ summaries });
          }}
          testId="cat-summary"
          limit={300}
          area
        />
      </Form.Item>
      <Form.Item label={t('catalog_admin.description')} help={t('catalog_admin.description_help')}>
        <Radio.Group
          value={descriptionLang}
          onChange={(event) => {
            setDescriptionLang(event.target.value as (typeof LANGUAGES)[number]);
          }}
          optionType="button"
          size="small"
          options={LANGUAGES.map((lang) => ({
            value: lang,
            label: t(`settings.name_in.${lang}`),
          }))}
          style={{ marginBottom: 8 }}
        />
        <div dir={descriptionLang === 'en' ? 'ltr' : 'rtl'} lang={descriptionLang}>
          <RichTextField
            key={descriptionLang}
            label={`${t('catalog_admin.description')} (${t(`settings.name_in.${descriptionLang}`)})`}
            value={draft.descriptions?.[descriptionLang] ?? ''}
            onChange={(html) => {
              set({ descriptions: { ...(draft.descriptions ?? {}), [descriptionLang]: html } });
            }}
            testId={`cat-description-${descriptionLang}`}
          />
        </div>
      </Form.Item>
      <Flex gap={16} wrap>
        <Form.Item label={t('catalog_admin.category')} required style={{ minWidth: 260 }}>
          <Select
            allowClear
            value={draft.category_id ?? undefined}
            onChange={(category_id: string | undefined) => {
              set({ category_id: category_id ?? null });
            }}
            options={categoryOptions}
            aria-label={t('catalog_admin.category')}
            data-testid="cat-category"
          />
        </Form.Item>
        <Form.Item
          label={t('catalog_admin.extra_categories')}
          help={t('catalog_admin.extra_categories_help')}
          style={{ minWidth: 260, flex: 1 }}
        >
          <Select
            mode="multiple"
            maxCount={5}
            value={draft.extra_category_ids ?? []}
            onChange={(extra_category_ids: string[]) => {
              set({ extra_category_ids });
            }}
            options={categoryOptions.filter((o) => o.value !== draft.category_id)}
            aria-label={t('catalog_admin.extra_categories')}
          />
        </Form.Item>
        <Form.Item label={t('catalog_admin.icon')} style={{ minWidth: 200 }}>
          <Select
            allowClear
            value={draft.icon ?? undefined}
            onChange={(icon: string | undefined) => {
              set({ icon: icon ?? null });
            }}
            options={ICONS.map((code) => ({ value: code, label: t(`catalog_icon.${code}`) }))}
            aria-label={t('catalog_admin.icon')}
          />
        </Form.Item>
      </Flex>
      <Form.Item label={t('catalog_admin.keywords')} help={t('catalog_admin.keywords_help')}>
        <Flex vertical gap={8}>
          {LANGUAGES.map((lang) => (
            <Select
              key={lang}
              mode="tags"
              tokenSeparators={[',', '،']}
              placeholder={t(`settings.name_in.${lang}`)}
              aria-label={`${t('catalog_admin.keywords')} (${t(`settings.name_in.${lang}`)})`}
              value={draft.keywords?.[lang] ?? []}
              onChange={(words: string[]) => {
                set({ keywords: { ...(draft.keywords ?? {}), [lang]: words } });
              }}
              open={false}
              data-testid={`cat-keywords-${lang}`}
            />
          ))}
        </Flex>
      </Form.Item>
      <Flex gap={16} wrap>
        <Form.Item label={t('catalog_admin.audience')} help={t('catalog_admin.audience_help')}>
          <Radio.Group
            value={draft.audience ?? 'everyone'}
            onChange={(event) => {
              set({ audience: event.target.value as Draft['audience'] });
            }}
            options={(['everyone', 'technicians'] as const).map((a) => ({
              value: a,
              label: t(`catalog_item_audience.${a}`),
            }))}
          />
        </Form.Item>
        <Form.Item label={t('catalog_admin.featured')}>
          <Switch
            checked={draft.featured ?? false}
            onChange={(featured) => {
              set({ featured });
            }}
            aria-label={t('catalog_admin.featured')}
            data-testid="cat-featured"
          />
        </Form.Item>
        <Form.Item label={t('catalog_admin.owner')} style={{ minWidth: 260 }}>
          <UserPicker
            value={draft.owner_id ?? null}
            onChange={(owner_id) => {
              set({ owner_id });
            }}
            testId="cat-owner"
            ariaLabel={t('catalog_admin.owner')}
          />
        </Form.Item>
      </Flex>
      <Form.Item label={t('catalog_admin.kind')} help={t('catalog_admin.kind_help')}>
        <Radio.Group
          value={draft.kind ?? 'service'}
          onChange={(event) => {
            set({ kind: event.target.value as Draft['kind'] });
          }}
          options={(['service', 'incident_template'] as const).map((k) => ({
            value: k,
            label: t(`catalog_item_kind.${k}`),
          }))}
          data-testid="cat-kind"
        />
      </Form.Item>
      {draft.kind === 'incident_template' && (
        <Form.Item label={t('catalog_admin.template')} required>
          <Select
            value={draft.template_id ?? undefined}
            onChange={(template_id: string) => {
              set({ template_id });
            }}
            options={(templates.data ?? [])
              .filter((tpl) => tpl.for_requesters && !tpl.disabled)
              .map((tpl) => ({
                value: tpl.id,
                label: tpl.labels ? textIn(tpl.labels, locale) : (tpl.code ?? tpl.id),
              }))}
            aria-label={t('catalog_admin.template')}
            data-testid="cat-template"
          />
        </Form.Item>
      )}
    </Form>
  );
}

function ApprovalTab({ draft, set }: TabProps) {
  const t = useLabel();
  const licence = useLicence();
  const approval = draft.approval ?? null;
  const approvers = approval?.approvers ?? [];
  const manager = approvers.some((a) => a.kind === 'requested_for_manager');
  const people = approvers.filter((a) => a.kind === 'person');
  const put = (next: Partial<NonNullable<Draft['approval']>>) => {
    set({
      approval: {
        approvers: [],
        comments_required: false,
        self_approval: false,
        ...(approval ?? {}),
        ...next,
      },
    });
  };
  return (
    <Form layout="vertical" component="div">
      <Form.Item label={t('catalog_admin.approval.needed')}>
        <Switch
          checked={approval !== null}
          onChange={(on) => {
            set({
              approval: on
                ? {
                    approvers: [{ kind: 'requested_for_manager', person_id: null }],
                    comments_required: false,
                    self_approval: false,
                  }
                : null,
            });
          }}
          aria-label={t('catalog_admin.approval.needed')}
          data-testid="cat-approval-on"
        />
      </Form.Item>
      {approval !== null && (
        <>
          <Form.Item label={t('catalog_admin.approval.who')}>
            <Flex vertical gap={8}>
              <Switch
                checked={manager}
                onChange={(on) => {
                  put({
                    approvers: on
                      ? [{ kind: 'requested_for_manager', person_id: null }, ...people]
                      : people,
                  });
                }}
                aria-label={t('catalog_approver_kind.requested_for_manager')}
                checkedChildren={t('catalog_approver_kind.requested_for_manager')}
                unCheckedChildren={t('catalog_approver_kind.requested_for_manager')}
                data-testid="cat-approval-manager"
              />
              {people.map((p, i) => (
                <Flex key={p.person_id ?? i} gap={8}>
                  <UserPicker
                    value={p.person_id ?? null}
                    onChange={(person_id) => {
                      const next = [...people];
                      next[i] = { kind: 'person', person_id };
                      put({
                        approvers: [
                          ...(manager
                            ? [{ kind: 'requested_for_manager' as const, person_id: null }]
                            : []),
                          ...next,
                        ],
                      });
                    }}
                    testId={`cat-approver-${String(i)}`}
                    ariaLabel={t('catalog_approver_kind.person')}
                  />
                </Flex>
              ))}
              <WriteButton
                size="small"
                style={{ alignSelf: 'flex-start' }}
                disabled={approvers.length >= 10}
                onClick={() => {
                  put({ approvers: [...approvers, { kind: 'person', person_id: null }] });
                }}
                data-testid="cat-approver-add"
              >
                {t('catalog_admin.approval.add_person')}
              </WriteButton>
            </Flex>
          </Form.Item>
          <Form.Item label={t('catalog_admin.approval.backup')} style={{ maxWidth: 360 }}>
            <UserPicker
              value={approval.backup_id ?? null}
              onChange={(backup_id) => {
                put({ backup_id });
              }}
              testId="cat-approval-backup"
              ariaLabel={t('catalog_admin.approval.backup')}
            />
          </Form.Item>
          <Flex gap={24} wrap>
            <SwitchRow
              label={t('catalog_admin.approval.comments_required')}
              checked={approval.comments_required}
              onChange={(comments_required) => {
                put({ comments_required });
              }}
            />
            <SwitchRow
              label={t('catalog_admin.approval.self_approval')}
              checked={approval.self_approval}
              onChange={(self_approval) => {
                put({ self_approval });
              }}
            />
            <SwitchRow
              label={t('catalog_admin.approval.requesters_see')}
              checked={draft.requesters_see_approval ?? true}
              onChange={(requesters_see_approval) => {
                set({ requesters_see_approval });
              }}
            />
            <SwitchRow
              label={t('catalog_admin.approval.technician_after')}
              checked={draft.technician_after_approval ?? false}
              onChange={(technician_after_approval) => {
                set({ technician_after_approval });
              }}
            />
          </Flex>
        </>
      )}
      {/* REQ-SR-029..033: more stages, parallel, conditions and rules (Professional, built later). */}
      <Alert
        type="info"
        showIcon
        style={{ marginTop: 16 }}
        message={t('catalog_admin.approval.advanced')}
        description={t(
          licence.has('catalog')
            ? 'catalog_admin.approval.advanced_later'
            : 'catalog_admin.approval.advanced_upgrade',
        )}
        data-testid="cat-approval-advanced"
      />
    </Form>
  );
}

function SwitchRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <Flex align="center" gap={8}>
      <Switch checked={checked} onChange={onChange} aria-label={label} />
      <Typography.Text>{label}</Typography.Text>
    </Flex>
  );
}

function AssignmentTab({ draft, set }: TabProps) {
  const t = useLabel();
  const groups = useUnits('groups');
  const policies = useSlaPolicies('service_request');
  return (
    <Form layout="vertical" component="div">
      <Flex gap={16} wrap>
        <Form.Item label={t('catalog_admin.priority')} style={{ minWidth: 200 }}>
          <Select
            value={draft.default_priority ?? undefined}
            onChange={(default_priority: string) => {
              set({ default_priority });
            }}
            options={PRIORITIES.map((p) => ({ value: p, label: t(`work_item_priority.${p}`) }))}
            aria-label={t('catalog_admin.priority')}
          />
        </Form.Item>
        <Form.Item label={t('catalog_admin.requester_sets_priority')}>
          <Switch
            checked={draft.requester_sets_priority ?? false}
            onChange={(requester_sets_priority) => {
              set({ requester_sets_priority });
            }}
            aria-label={t('catalog_admin.requester_sets_priority')}
          />
        </Form.Item>
      </Flex>
      <Flex gap={16} wrap>
        <Form.Item
          label={t('catalog_admin.group')}
          required
          help={t('catalog_admin.group_help')}
          style={{ minWidth: 260 }}
        >
          <Select
            allowClear
            value={draft.group_id ?? undefined}
            onChange={(group_id: string | undefined) => {
              set({ group_id: group_id ?? null });
            }}
            options={(groups.data ?? [])
              .filter((g) => !g.disabled || g.id === draft.group_id)
              .map((g) => ({ value: g.id, label: g.name }))}
            aria-label={t('catalog_admin.group')}
            data-testid="cat-group"
          />
        </Form.Item>
        <Form.Item label={t('catalog_admin.technician')} style={{ minWidth: 260 }}>
          <UserPicker
            value={draft.technician_id ?? null}
            onChange={(technician_id) => {
              set({ technician_id });
            }}
            testId="cat-technician"
            ariaLabel={t('catalog_admin.technician')}
          />
        </Form.Item>
      </Flex>
      <Form.Item label={t('catalog_admin.sla')} help={t('catalog_admin.sla_help')}>
        <Select
          allowClear
          style={{ maxWidth: 360 }}
          value={draft.sla_policy_id ?? undefined}
          onChange={(sla_policy_id: string | undefined) => {
            set({ sla_policy_id: sla_policy_id ?? null });
          }}
          options={(policies.data ?? []).map((p) => ({
            value: p.id,
            label: p.name,
            disabled: !p.enabled,
          }))}
          aria-label={t('catalog_admin.sla')}
        />
      </Form.Item>
      <SwitchRow
        label={t('catalog_admin.count_approval_time')}
        checked={draft.count_approval_time ?? false}
        onChange={(count_approval_time) => {
          set({ count_approval_time });
        }}
      />
    </Form>
  );
}

function LifeTab({
  item,
  draft,
  set,
  busy,
  onStatus,
}: TabProps & {
  item: CatalogItem | undefined;
  busy: boolean;
  onStatus: (status: CatalogItem['status']) => void;
}) {
  const t = useLabel();
  // The person's date and time format (lane C's QA10-P3-14), as the shared date fields show it.
  const { dates } = useAppearance();
  const timeFormat = dates.timeFormat === '12h' ? 'hh:mm A' : 'HH:mm';
  const status = item?.status ?? 'draft';
  return (
    <Form layout="vertical" component="div">
      <Flex gap={8} wrap style={{ marginBottom: 16 }}>
        {status !== 'published' && (
          <WriteButton
            type="primary"
            loading={busy}
            onClick={() => {
              onStatus('published');
            }}
            data-testid="cat-publish"
          >
            {t(status === 'retired' ? 'catalog_admin.publish_again' : 'catalog_admin.publish')}
          </WriteButton>
        )}
        {status === 'published' && (
          <WriteButton
            loading={busy}
            onClick={() => {
              onStatus('retired');
            }}
            data-testid="cat-retire"
          >
            {t('catalog_admin.retire')}
          </WriteButton>
        )}
      </Flex>
      <Flex gap={16} wrap>
        {status === 'draft' && (
          <Form.Item
            label={t('catalog_admin.publish_at')}
            help={t('catalog_admin.publish_at_help')}
          >
            <DatePicker
              showTime={{ format: timeFormat }}
              format={pickerFormat(dates, true)}
              value={draft.publish_at ? dayjs(draft.publish_at) : null}
              onChange={(value: dayjs.Dayjs | null) => {
                set({ publish_at: value ? value.toISOString() : null });
              }}
              aria-label={t('catalog_admin.publish_at')}
              data-testid="cat-publish-at"
            />
          </Form.Item>
        )}
        {status !== 'retired' && (
          <Form.Item label={t('catalog_admin.retire_at')}>
            <DatePicker
              showTime={{ format: timeFormat }}
              format={pickerFormat(dates, true)}
              value={draft.retire_at ? dayjs(draft.retire_at) : null}
              onChange={(value: dayjs.Dayjs | null) => {
                set({ retire_at: value ? value.toISOString() : null });
              }}
              aria-label={t('catalog_admin.retire_at')}
              data-testid="cat-retire-at"
            />
          </Form.Item>
        )}
      </Flex>
      <Typography.Text type="secondary">{t('catalog_admin.life_help')}</Typography.Text>
    </Form>
  );
}
