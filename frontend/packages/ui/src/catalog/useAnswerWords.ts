import type { CatalogQuestion } from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';

import { useAppearance, useLabel } from '../appearance';
import { useDateTime } from '../dates';
import { textIn } from './answers';

/**
 * An answer in words (rule d: never a code or an ID): a choice by its words in the reader's
 * language, several as a list, yes/no, dates and times in the reader's zone, files counted, a
 * person by the name the page knows (or "someone" when it may not show it).
 */
export function useAnswerWords(): (
  question: CatalogQuestion,
  value: unknown,
  people?: Record<string, { display_name: string } | undefined>,
) => string {
  const t = useLabel();
  const { locale } = useAppearance();
  const list = useListFormat();
  const dates = useDateTime();
  return (question, value, people) => {
    if (value === null || value === undefined || value === '') return '';
    const word = (code: string) => textIn(question.option_labels?.[code], locale) || code;
    switch (question.kind) {
      case 'choice':
        return typeof value === 'string' ? word(value) : '';
      case 'multi_choice':
        return Array.isArray(value) ? list(value.map((v) => word(String(v)))) : '';
      case 'yes_no':
        return t(value === true ? 'history.yes' : 'history.no');
      case 'date':
        return typeof value === 'string' ? dates.formatDay(value) : '';
      case 'datetime':
        return typeof value === 'string' ? dates.format(value) : '';
      case 'person':
        return typeof value === 'string'
          ? (people?.[value]?.display_name ?? t('catalog.answer.someone'))
          : '';
      case 'attachment':
        return Array.isArray(value) ? t('catalog.answer.files', { count: value.length }) : '';
      default:
        return typeof value === 'number'
          ? value.toLocaleString(locale)
          : typeof value === 'string'
            ? value
            : '';
    }
  };
}
