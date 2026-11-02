import { LinkOutlined } from '@ant-design/icons';
import { Button, Card, Flex, List, Typography } from 'antd';

import { useKbSuggestions, type KbSnippetPart } from '@supportx/api-client';
import { EmptyText, useAppearance, useLabel } from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { articleLanguage } from './model';

// Suggestions while a technician logs an incident (REQ-INC-021, REQ-KB-062, D-125): the one
// suggestion service, with the reader's own rule. A fixed-width column beside the form, so the
// form never moves while suggestions come and go (REQ-WI-012).

/** Typing pauses this long before asking: the answer still arrives within a second. */
export const SUGGEST_DELAY_MS = 400;

/** A snippet as text with the searched words marked; React escapes every part (never HTML). */
export function Snippet({ parts }: { parts: readonly KbSnippetPart[] }) {
  if (parts.length === 0) return null;
  return (
    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
      {parts.map((part, index) =>
        part.mark ? <mark key={index}>{part.text}</mark> : <span key={index}>{part.text}</span>,
      )}
    </Typography.Text>
  );
}

export function KnowledgeSuggestions({
  text,
  chosen,
  onToggle,
}: {
  /** The subject and the description's text so far. */
  text: string;
  /** Articles to link once the incident exists. */
  chosen: ReadonlySet<string>;
  onToggle: (articleId: string) => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const typed = useDebounced(text, SUGGEST_DELAY_MS).trim();
  const found = useKbSuggestions(typed, articleLanguage(locale));
  const rows = typed.length < 3 ? [] : (found.data ?? []);
  return (
    <Card
      size="small"
      title={t('knowledge.suggest.title')}
      data-testid="kb-suggestions"
      aria-live="polite"
    >
      {typed.length < 3 ? (
        <EmptyText>{t('knowledge.suggest.type_more')}</EmptyText>
      ) : rows.length === 0 && !found.isFetching ? (
        <EmptyText>{t('knowledge.suggest.none')}</EmptyText>
      ) : (
        <List
          size="small"
          dataSource={rows}
          loading={found.isFetching && rows.length === 0}
          renderItem={(row) => {
            const linked = chosen.has(row.id);
            return (
              <List.Item data-testid={`kb-suggestion-${row.id}`}>
                <Flex vertical gap={4} style={{ width: '100%', minWidth: 0 }}>
                  {/* Opens beside the form: what was typed stays where it is. */}
                  <Typography.Link
                    href={`/knowledge/articles/${row.id}`}
                    target="_blank"
                    rel="noopener"
                    lang={row.language}
                    ellipsis
                  >
                    {row.title}
                  </Typography.Link>
                  <Snippet parts={row.snippet ?? []} />
                  <div>
                    <Button
                      size="small"
                      type={linked ? 'primary' : 'default'}
                      icon={<LinkOutlined />}
                      aria-pressed={linked}
                      onClick={() => {
                        onToggle(row.id);
                      }}
                      data-testid={`kb-suggestion-link-${row.id}`}
                    >
                      {t(linked ? 'knowledge.suggest.linked' : 'knowledge.suggest.link')}
                    </Button>
                  </div>
                </Flex>
              </List.Item>
            );
          }}
        />
      )}
    </Card>
  );
}
