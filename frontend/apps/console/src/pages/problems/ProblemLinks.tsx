import { CloseOutlined } from '@ant-design/icons';
import { Alert, Button, Empty, Flex, List, Modal, Select, Skeleton, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  useMergeProblem,
  useProblemLinks,
  useRelatedProblem,
  useSimilarProblems,
  useUnlinkIncident,
  type Problem,
  type ProblemLink,
} from '@supportx/api-client';
import { reportError, useLabel, WriteButton } from '@supportx/ui';

import { useDebounced } from '../../useDebounced';

function Other({ link, hidden }: { link: ProblemLink; hidden: string }) {
  if (link.other_id === null) return <>{hidden}</>;
  const path = link.other_type === 'incident' ? 'incidents' : 'problems';
  return (
    <Link to={`/${path}/${link.other_id}`}>
      <strong dir="ltr">{link.other_display_id}</strong> <bdi dir="auto">{link.other_subject}</bdi>
    </Link>
  );
}

/**
 * The incidents this problem causes (REQ-PRB-043): each can be unlinked. The server checks the
 * incident's edit right, so the button is offered with the problem's edit right and a refusal
 * explains itself.
 */
export function CausedIncidents({ id, canEdit }: { id: string; canEdit: boolean }) {
  const t = useLabel();
  const links = useProblemLinks(id);
  const unlink = useUnlinkIncident(id);
  const rows = (links.data ?? []).filter((l) => l.relation === 'causes');
  if (links.isLoading) return <Skeleton active paragraph={{ rows: 2 }} />;
  if (rows.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('problems.no_incidents')} />;
  }
  return (
    <List
      size="small"
      dataSource={rows}
      data-testid="prb-incidents"
      renderItem={(link) => (
        <List.Item
          actions={
            canEdit && link.other_id !== null
              ? [
                  <Button
                    key="unlink"
                    size="small"
                    type="text"
                    icon={<CloseOutlined />}
                    aria-label={t('problems.unlink', { id: link.other_display_id ?? '' })}
                    data-testid={`prb-unlink-${link.other_display_id ?? ''}`}
                    onClick={() => {
                      if (link.other_id !== null) {
                        unlink.mutate(link.other_id, { onError: reportError });
                      }
                    }}
                  />,
                ]
              : []
          }
        >
          <Other link={link} hidden={t('problems.hidden_incident')} />
        </List.Item>
      )}
    />
  );
}

/** Pick an open problem by its words (the similar-problems search: visible, open ones only). */
function ProblemPicker({
  exclude,
  onPick,
  label,
  testId,
}: {
  exclude: string[];
  onPick: (id: string) => void;
  label: string;
  testId: string;
}) {
  const [search, setSearch] = useState('');
  const found = useSimilarProblems(useDebounced(search, 300));
  return (
    <Select
      showSearch
      filterOption={false}
      value={null}
      placeholder={label}
      aria-label={label}
      onSearch={setSearch}
      onChange={onPick}
      loading={found.isFetching}
      style={{ width: '100%' }}
      options={(found.data ?? [])
        .filter((p) => !exclude.includes(p.id))
        .map((p) => ({ value: p.id, label: `${p.display_id} ${p.subject}` }))}
      data-testid={testId}
    />
  );
}

/** Related problems (REQ-PRB-045): shown on both, added and removed here. */
export function RelatedProblems({ id, canEdit }: { id: string; canEdit: boolean }) {
  const t = useLabel();
  const links = useProblemLinks(id);
  const change = useRelatedProblem(id);
  const rows = (links.data ?? []).filter(
    (l) => l.relation === 'related' && (l.other_type === 'problem' || l.other_id === null),
  );
  if (links.isLoading) return <Skeleton active paragraph={{ rows: 1 }} />;
  return (
    <Flex vertical gap={8} data-testid="prb-related">
      {rows.length === 0 && (
        <Typography.Text type="secondary">{t('problems.related.none')}</Typography.Text>
      )}
      {rows.map((link) => (
        <Flex key={link.id} justify="space-between" align="center" gap={8}>
          <Other link={link} hidden={t('problems.related.hidden')} />
          {canEdit && (
            <Button
              size="small"
              type="text"
              icon={<CloseOutlined />}
              aria-label={t('problems.related.remove', { id: link.other_display_id ?? '' })}
              onClick={() => {
                change.mutate({ remove: link.id, version: link.version }, { onError: reportError });
              }}
            />
          )}
        </Flex>
      ))}
      {canEdit && (
        <ProblemPicker
          exclude={[id, ...rows.flatMap((l) => (l.other_id === null ? [] : [l.other_id]))]}
          label={t('problems.related.add')}
          testId="prb-related-add"
          onPick={(other) => {
            change.mutate({ add: other }, { onError: reportError });
          }}
        />
      )}
    </Flex>
  );
}

/** Choose the problem to merge into, then confirm (REQ-PRB-046). */
export function MergeDialog({
  item,
  open,
  onClose,
}: {
  item: Problem;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const merge = useMergeProblem(item.id);
  const [into, setInto] = useState<string | null>(null);
  return (
    <Modal
      open={open}
      title={t('problems.merge.title', { id: item.display_id })}
      onCancel={onClose}
      destroyOnHidden
      okText={t('problems.merge.confirm')}
      okButtonProps={{ disabled: into === null, loading: merge.isPending }}
      onOk={() => {
        if (into === null) return;
        merge.mutate(
          { into, version: item.version },
          {
            onSuccess: onClose,
            onError: reportError,
          },
        );
      }}
    >
      <Flex vertical gap={12} data-testid="prb-merge-dialog">
        <Typography.Paragraph style={{ margin: 0 }}>
          {t('problems.merge.explain')}
        </Typography.Paragraph>
        <ProblemPicker
          exclude={[item.id]}
          label={t('problems.merge.into')}
          testId="prb-merge-into"
          onPick={setInto}
        />
      </Flex>
    </Modal>
  );
}

/** A merged problem says where it went, with an undo while it is still merged. */
export function MergedBanner({ item }: { item: Problem }) {
  const t = useLabel();
  const links = useProblemLinks(item.id);
  const merge = useMergeProblem(item.id);
  if (item.status !== 'merged') return null;
  const into = (links.data ?? []).find((l) => l.relation === 'merged_into');
  const canEdit = item.operations.find((o) => o.action === 'edit')?.allowed === true;
  return (
    <Alert
      type="info"
      showIcon
      data-testid="prb-merged"
      message={
        into === undefined ? (
          t('problems.merge.merged')
        ) : (
          <span>
            {t('problems.merge.merged_into')}{' '}
            <Other link={into} hidden={t('problems.related.hidden')} />
          </span>
        )
      }
      action={
        canEdit ? (
          <WriteButton
            size="small"
            loading={merge.isPending}
            data-testid="prb-undo-merge"
            onClick={() => {
              merge.mutate({ undo: true, version: item.version }, { onError: reportError });
            }}
          >
            {t('problems.merge.undo')}
          </WriteButton>
        ) : undefined
      }
    />
  );
}
