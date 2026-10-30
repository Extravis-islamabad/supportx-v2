import { Empty, Flex, Input, Radio, Spin, Tag, Typography } from 'antd';
import { useMemo, useState } from 'react';

import { useWidgetCatalogue, type WidgetCatalogueEntry } from '@supportx/api-client';
import { useLabels } from '@supportx/labels';

/**
 * The widget catalogue of "Add widget" (D-114): every widget you may add, searchable, grouped
 * by module and section. Widgets whose data comes with a later package are shown, not offered.
 */
export function WidgetCataloguePicker({
  value,
  onChange,
}: {
  value: string | undefined;
  onChange: (entry: WidgetCatalogueEntry) => void;
}) {
  const t = useLabels();
  const catalogue = useWidgetCatalogue();
  const [search, setSearch] = useState('');

  const groups = useMemo(() => {
    const data = catalogue.data;
    if (!data) return [];
    const words = search.trim().toLocaleLowerCase();
    const found = data.entries.filter((entry) => {
      if (words === '') return true;
      const text = [
        t(entry.title_key),
        t(`${entry.title_key}.description`),
        t(`widget_section.${entry.section}`),
        t(`report_folder.${entry.module}`),
      ]
        .join(' ')
        .toLocaleLowerCase();
      return words.split(/\s+/).every((word) => text.includes(word));
    });
    const modules = [...new Set(found.map((e) => e.module))];
    return modules.map((module) => ({
      module,
      sections: data.sections
        .map((section) => ({
          section,
          entries: found.filter((e) => e.module === module && e.section === section),
        }))
        .filter((s) => s.entries.length > 0),
    }));
  }, [catalogue.data, search, t]);

  if (catalogue.data === undefined) {
    return catalogue.isError ? (
      <Typography.Text type="secondary">{t('dashboards.widget_failed')}</Typography.Text>
    ) : (
      <Spin />
    );
  }
  return (
    <Flex vertical gap={12}>
      <Input.Search
        allowClear
        value={search}
        placeholder={t('dashboards.catalogue_search')}
        aria-label={t('dashboards.catalogue_search')}
        onChange={(event) => {
          setSearch(event.target.value);
        }}
        data-testid="dashboard-catalogue-search"
      />
      {groups.length === 0 ? (
        <Empty description={t('dashboards.catalogue_empty')} />
      ) : (
        <div style={{ maxHeight: 360, overflow: 'auto' }} data-testid="dashboard-catalogue">
          <Radio.Group
            value={value}
            onChange={(event) => {
              const entry = catalogue.data.entries.find((e) => e.code === event.target.value);
              if (entry?.coming_with === null) onChange(entry);
            }}
            style={{ width: '100%' }}
          >
            {groups.map(({ module, sections }) => (
              <section key={module} aria-label={t(`report_folder.${module}`)}>
                <Typography.Title level={5}>{t(`report_folder.${module}`)}</Typography.Title>
                {sections.map(({ section, entries }) => (
                  <fieldset key={section} style={{ border: 0, margin: '0 0 12px', padding: 0 }}>
                    <legend>
                      <Typography.Text strong>{t(`widget_section.${section}`)}</Typography.Text>
                    </legend>
                    <Flex vertical gap={6}>
                      {entries.map((entry) => (
                        <Radio
                          key={entry.code}
                          value={entry.code}
                          disabled={entry.coming_with !== null}
                          data-testid={`dashboard-catalogue-${entry.code}`}
                        >
                          <Flex vertical>
                            <span>
                              {t(entry.title_key)}
                              {entry.coming_with !== null && (
                                <Tag style={{ marginInlineStart: 8 }}>
                                  {t(`widget_coming.${entry.coming_with}`)}
                                </Tag>
                              )}
                            </span>
                            <Typography.Text type="secondary">
                              {t(`${entry.title_key}.description`)}
                            </Typography.Text>
                          </Flex>
                        </Radio>
                      ))}
                    </Flex>
                  </fieldset>
                ))}
              </section>
            ))}
          </Radio.Group>
        </div>
      )}
    </Flex>
  );
}
