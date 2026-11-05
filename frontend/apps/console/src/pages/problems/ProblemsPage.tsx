import { PlusOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Empty, Flex, Table } from 'antd';
import { Link, useNavigate } from 'react-router';

import { problemKeys, useProblemCatalogue, useProblems } from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import { PageHeader, reportError, useAccess, useDateTime, useLabel } from '@supportx/ui';

import { PriorityTag, StatusTag } from '../incidents/tags';

/**
 * Problems (WP-044a s5): the list, live on the problems list channel (§8), with "New problem"
 * for those who may create one. Views, filters, bulk and export come with WP-044c.
 */
export function ProblemsPage() {
  const t = useLabel();
  const { format } = useDateTime();
  const { can } = useAccess();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const list = useProblems({});
  const catalogue = useProblemCatalogue();
  useListChannel('problems', () => {
    void queryClient.invalidateQueries({ queryKey: [...problemKeys.all, 'list'] });
  });
  if (list.error) reportError(list.error);
  const create = can('problems.create');
  const rows = list.data?.items ?? [];
  const people = list.data?.people ?? {};
  return (
    <Flex vertical gap={16} style={{ width: '100%' }}>
      <PageHeader
        title={t('nav.problems')}
        extra={
          create && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => void navigate('/problems/new')}
              data-testid="prb-new"
            >
              {t('problems.new')}
            </Button>
          )
        }
      />
      <Table
        rowKey="id"
        loading={list.isLoading}
        dataSource={rows}
        pagination={false}
        data-testid="prb-list"
        locale={{
          emptyText: list.isLoading ? (
            <span />
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t('problems.empty')}
              data-testid="prb-empty"
            />
          ),
        }}
        columns={[
          {
            key: 'id',
            title: t('incidents.col.id'),
            width: 130,
            render: (_, row) => (
              <Link to={`/problems/${row.id}`} data-testid={`prb-row-${row.display_id}`}>
                <strong dir="ltr">{row.display_id}</strong>
              </Link>
            ),
          },
          {
            key: 'subject',
            title: t('incidents.col.subject'),
            render: (_, row) => <bdi dir="auto">{row.subject}</bdi>,
          },
          {
            key: 'status',
            title: t('incidents.col.status'),
            render: (_, row) => <StatusTag status={row.status} catalogue={catalogue.data} />,
          },
          {
            key: 'priority',
            title: t('incidents.col.priority'),
            render: (_, row) => (
              <PriorityTag priority={row.priority} source={row.priority_source} />
            ),
          },
          {
            key: 'owner',
            title: t('problems.owner'),
            render: (_, row) =>
              row.technician_id === null ? '' : (people[row.technician_id]?.display_name ?? ''),
          },
          {
            key: 'updated',
            title: t('incidents.col.updated'),
            render: (_, row) => format(row.updated_at),
          },
        ]}
      />
    </Flex>
  );
}
