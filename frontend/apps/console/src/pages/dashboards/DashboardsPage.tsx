import { CopyOutlined, HomeOutlined, StarFilled, StarOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Card,
  Flex,
  Input,
  List,
  Modal,
  Result,
  Space,
  Switch,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';

import {
  queryKeys,
  useCreateDashboard,
  useDashboard,
  useDashboards,
  useDeleteDashboard,
  useSetHome,
  useStarDashboard,
  useUpdateDashboard,
  type DashboardBody,
} from '@supportx/api-client';
import { useIsolate, useLabels } from '@supportx/labels';
import { refreshList, usePersonalChannel, useTenantChannel } from '@supportx/realtime';
import {
  ConflictDialog,
  FormProblem,
  lengthLimit,
  NoAccess,
  useAccess,
  useAppearance,
  useConflict,
  useFormProblem,
  WriteButton,
} from '@supportx/ui';

import { DashboardView } from './DashboardView';
import { dashboardName } from './names';

/** Dashboards on screen follow changes made elsewhere (rule c; REQ-DSH-028 AC2 for un-sharing). */
function useDashboardsLive() {
  const queryClient = useQueryClient();
  const refresh = () => {
    refreshList(queryClient, queryKeys.dashboards.all);
  };
  useTenantChannel((message) => {
    if (message.type === 'dashboards.changed') refresh();
  });
  usePersonalChannel((message) => {
    if (message.type === 'dashboards.changed') refresh();
  });
}

/** /dashboards: the picker (REQ-DSH-005); /dashboards/:ref: one dashboard. */
export function DashboardsPage() {
  const { ref } = useParams();
  const { can } = useAccess();
  useDashboardsLive();
  if (!can('reports.view')) return <NoAccess titleKey="nav.dashboards" />;
  return ref ? <DashboardPage dashboardRef={decodeURIComponent(ref)} /> : <Picker />;
}

function Picker() {
  const t = useLabels();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const navigate = useNavigate();
  const list = useDashboards();
  const star = useStarDashboard();
  const [search, setSearch] = useState('');
  const data = list.data;
  const groups = useMemo(() => {
    const items = data?.items ?? [];
    const needle = search.trim().toLocaleLowerCase(locale);
    const shown = items.filter(
      (d) => !needle || dashboardName(d, t, locale).toLocaleLowerCase(locale).includes(needle),
    );
    const favourites = new Set(data?.favourites ?? []);
    return [
      { key: 'favourites', items: shown.filter((d) => favourites.has(d.ref)) },
      { key: 'builtin', items: shown.filter((d) => d.builtin && !favourites.has(d.ref)) },
      {
        key: 'shared',
        items: shown.filter((d) => !d.builtin && d.shared && !favourites.has(d.ref)),
      },
      {
        key: 'mine',
        items: shown.filter((d) => !d.builtin && !d.shared && !favourites.has(d.ref)),
      },
    ].filter((g) => g.items.length > 0);
    // `t` changes identity per render; the locale and data decide the result.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see above
  }, [data, search, locale]);

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Flex justify="space-between" align="center" wrap gap={12}>
        <Typography.Title level={1} style={{ margin: 0 }}>
          {t('nav.dashboards')}
        </Typography.Title>
        {can('dashboards.create') && <NewDashboard />}
      </Flex>
      <Input.Search
        allowClear
        placeholder={t('dashboards.search')}
        aria-label={t('dashboards.search')}
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
        }}
        style={{ maxWidth: 360 }}
        data-testid="dashboards-search"
      />
      {groups.map((group) => (
        <Card
          key={group.key}
          size="small"
          title={t(`dashboards.group_${group.key}`)}
          data-testid={`dashboards-group-${group.key}`}
        >
          <List
            dataSource={group.items}
            renderItem={(d) => {
              const starred = data?.favourites.includes(d.ref) ?? false;
              return (
                <List.Item
                  actions={[
                    <Tooltip
                      key="star"
                      title={t(starred ? 'dashboards.unstar' : 'dashboards.star')}
                    >
                      <Button
                        type="text"
                        aria-label={t(starred ? 'dashboards.unstar' : 'dashboards.star')}
                        aria-pressed={starred}
                        icon={starred ? <StarFilled /> : <StarOutlined />}
                        onClick={() => {
                          star.mutate({ ref: d.ref, starred: !starred });
                        }}
                        data-testid={`dashboards-star-${d.ref}`}
                      />
                    </Tooltip>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space wrap>
                        <Link
                          to={`/dashboards/${encodeURIComponent(d.ref)}`}
                          data-testid={`dashboards-open-${d.ref}`}
                        >
                          {dashboardName(d, t, locale)}
                        </Link>
                        <Tag>{t(d.shared ? 'dashboards.shared' : 'dashboards.private')}</Tag>
                        {data?.home === d.ref && (
                          <Tag icon={<HomeOutlined />}>{t('dashboards.your_home')}</Tag>
                        )}
                      </Space>
                    }
                    description={
                      d.builtin ? t(`dashboard.${d.builtin}.description`) : d.description
                    }
                  />
                </List.Item>
              );
            }}
          />
        </Card>
      ))}
      {list.isSuccess && groups.length === 0 && (
        <Typography.Text type="secondary">{t('dashboards.no_match')}</Typography.Text>
      )}
      <Button
        type="link"
        onClick={() => {
          void navigate('/');
        }}
      >
        {t('dashboards.back_home')}
      </Button>
    </Space>
  );
}

function NewDashboard() {
  const t = useLabels();
  const navigate = useNavigate();
  const create = useCreateDashboard();
  const problem = useFormProblem();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [key, setKey] = useState(() => crypto.randomUUID());
  return (
    <>
      <WriteButton
        type="primary"
        onClick={() => {
          setOpen(true);
        }}
        data-testid="dashboards-new"
      >
        {t('dashboards.new')}
      </WriteButton>
      <Modal
        open={open}
        title={t('dashboards.new')}
        okText={t('reports.create')}
        cancelText={t('reports.cancel')}
        okButtonProps={{ disabled: name.trim() === '', loading: create.isPending }}
        onCancel={() => {
          setOpen(false);
          problem.clear();
        }}
        onOk={() => {
          problem.clear();
          create.mutate(
            { key, body: { name: name.trim(), shared: false } },
            {
              onSuccess: (made) => {
                setOpen(false);
                setKey(crypto.randomUUID());
                void navigate(`/dashboards/${encodeURIComponent(made.ref)}?edit=1`);
              },
              onError: (error) => {
                problem.show(error);
              },
            },
          );
        }}
      >
        <Input
          aria-label={t('dashboards.name')}
          placeholder={t('dashboards.name')}
          count={lengthLimit(120)}
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
          data-testid="dashboards-new-name"
        />
        <FormProblem problem={problem} />
      </Modal>
    </>
  );
}

/** One dashboard (also the home page's): its header, actions and the live grid. */
export function DashboardPage({ dashboardRef, home }: { dashboardRef: string; home?: boolean }) {
  const t = useLabels();
  const isolate = useIsolate();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const navigate = useNavigate();
  const found = useDashboard(dashboardRef);
  const list = useDashboards();
  const star = useStarDashboard();
  const setHome = useSetHome();
  const create = useCreateDashboard();
  const update = useUpdateDashboard(dashboardRef);
  const remove = useDeleteDashboard(dashboardRef);
  const problem = useFormProblem();
  const conflict = useConflict();
  const [editing, setEditing] = useState(
    () => new URLSearchParams(window.location.search).get('edit') === '1',
  );
  const [pending, setPending] = useState<DashboardBody>();
  const dashboard = found.data;

  if (found.isError) {
    // Deleted, or no longer shared with this viewer (REQ-DSH-028 AC2): say so, keep them going.
    return (
      <Result
        status="404"
        title={t('errors.dashboard_not_found')}
        extra={
          <Link to="/dashboards" data-testid="dashboard-gone">
            {t('dashboards.choose_another')}
          </Link>
        }
      />
    );
  }
  if (!dashboard) return null;
  const name = dashboardName(dashboard, t, locale);
  const starred = list.data?.favourites.includes(dashboard.ref) ?? false;
  const isHome = list.data?.home === dashboard.ref;

  const save = (body: DashboardBody, version = dashboard.version) => {
    update.mutate(
      { changes: { body }, version },
      {
        onSuccess: () => {
          setEditing(false);
          setPending(undefined);
        },
        onError: (error) => {
          if (conflict.take(error)) setPending(body);
          else problem.show(error);
        },
      },
    );
  };
  const copy = () => {
    create.mutate(
      {
        key: crypto.randomUUID(),
        body: {
          name: t('reports.copy_of', { name: isolate(name) }).replace(/[⁨⁩]/g, ''),
          copied_from: dashboard.ref,
          shared: false,
          body: dashboard.body,
        },
      },
      {
        onSuccess: (made) => {
          void navigate(`/dashboards/${encodeURIComponent(made.ref)}`);
        },
        onError: (error) => {
          problem.show(error);
        },
      },
    );
  };

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Flex justify="space-between" align="center" wrap gap={12}>
        <Space wrap align="center">
          <Typography.Title
            level={home ? 2 : 1}
            style={{ margin: 0 }}
            data-testid="dashboard-title"
          >
            {name}
          </Typography.Title>
          <Tag>{t(dashboard.shared ? 'dashboards.shared' : 'dashboards.private')}</Tag>
        </Space>
        <Space wrap>
          <Button
            type="text"
            aria-label={t(starred ? 'dashboards.unstar' : 'dashboards.star')}
            aria-pressed={starred}
            icon={starred ? <StarFilled /> : <StarOutlined />}
            onClick={() => {
              star.mutate({ ref: dashboard.ref, starred: !starred });
            }}
          />
          {!home && (
            <Button
              icon={<HomeOutlined />}
              disabled={isHome}
              onClick={() => {
                setHome.mutate(dashboard.ref);
              }}
              data-testid="dashboard-set-home"
            >
              {t(isHome ? 'dashboards.is_home' : 'dashboards.set_home')}
            </Button>
          )}
          {home && (
            <Link to="/dashboards" data-testid="dashboard-change-home">
              {t('dashboards.other_dashboards')}
            </Link>
          )}
          {can('dashboards.create') && (
            <WriteButton icon={<CopyOutlined />} onClick={copy} data-testid="dashboard-copy">
              {t('dashboards.copy')}
            </WriteButton>
          )}
          {dashboard.can_edit && !editing && (
            <WriteButton
              onClick={() => {
                setEditing(true);
              }}
              data-testid="dashboard-edit"
            >
              {t('dashboards.edit')}
            </WriteButton>
          )}
          {dashboard.can_edit && (
            <Tooltip title={can('dashboards.share') ? undefined : t('dashboards.cannot_share')}>
              <Space>
                <Switch
                  checked={dashboard.shared}
                  disabled={!can('dashboards.share')}
                  aria-label={t('dashboards.share_everyone')}
                  onChange={(shared) => {
                    update.mutate(
                      { changes: { shared }, version: dashboard.version },
                      {
                        onError: (error) => {
                          if (!conflict.take(error)) problem.show(error);
                        },
                      },
                    );
                  }}
                  data-testid="dashboard-share"
                />
                <Typography.Text>{t('dashboards.share_everyone')}</Typography.Text>
              </Space>
            </Tooltip>
          )}
          {dashboard.can_edit && (
            <Button
              danger
              onClick={() => {
                Modal.confirm({
                  title: t('dashboards.delete_confirm', { name: isolate(name) }),
                  okText: t('reports.delete'),
                  okButtonProps: { danger: true },
                  cancelText: t('reports.cancel'),
                  onOk: () =>
                    remove.mutateAsync(dashboard.version).then(
                      () => {
                        void navigate('/dashboards');
                      },
                      (error: unknown) => {
                        problem.show(error);
                      },
                    ),
                });
              }}
              data-testid="dashboard-delete"
            >
              {t('reports.delete')}
            </Button>
          )}
        </Space>
      </Flex>
      <FormProblem problem={problem} />
      <DashboardView
        key={`${dashboard.ref}:${String(dashboard.version)}`}
        dashboard={dashboard}
        editing={editing}
        onDone={(body) => {
          save(body);
        }}
        onCancel={() => {
          setEditing(false);
        }}
      />
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={() => t('dashboards.layout')}
        onReload={() => {
          conflict.clear();
          update.reset();
          setEditing(false);
          setPending(undefined);
        }}
        onKeepMine={() => {
          conflict.clear();
          update.reset();
          if (pending) save(pending, conflict.latestVersion ?? dashboard.version);
        }}
      />
    </Space>
  );
}
