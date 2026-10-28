import type { Locale as AntLocale } from 'antd/es/locale';
import arEG from 'antd/locale/ar_EG';
import enUS from 'antd/locale/en_US';
import urPK from 'antd/locale/ur_PK';

import { label, type LabelInput, type Locale } from '@supportx/labels';

/**
 * Ant Design's texts that its own Arabic and Urdu locales leave out (or leave in English), by
 * their path in the locale object, and the label each takes instead. Ant Design falls back to
 * English for a missing text, so without these a right-to-left screen showed English words
 * (QA WP-023: the Urdu tables' "No data"). Checked by antdLocales.test.ts: no
 * Ant Design text in ar or ur is left in English.
 */
export const ANTD_GAPS: Readonly<Record<string, LabelInput>> = {
  'Calendar.lang.monthPlaceholder': 'antd.picker.month_placeholder',
  'Calendar.lang.quarterPlaceholder': 'antd.picker.quarter_placeholder',
  'Calendar.lang.weekPlaceholder': 'antd.picker.week_placeholder',
  'Calendar.lang.weekSelect': 'antd.picker.week_select',
  'Calendar.lang.yearPlaceholder': 'antd.picker.year_placeholder',
  'DatePicker.lang.monthPlaceholder': 'antd.picker.month_placeholder',
  'DatePicker.lang.quarterPlaceholder': 'antd.picker.quarter_placeholder',
  'DatePicker.lang.weekPlaceholder': 'antd.picker.week_placeholder',
  'DatePicker.lang.weekSelect': 'antd.picker.week_select',
  'DatePicker.lang.yearPlaceholder': 'antd.picker.year_placeholder',
  'ColorPicker.gradientColor': 'antd.color.gradient',
  'ColorPicker.presetEmpty': 'antd.color.preset_empty',
  'ColorPicker.singleColor': 'antd.color.single',
  'ColorPicker.transparent': 'antd.color.transparent',
  'Form.optional': 'antd.form.optional',
  'Pagination.page_size': 'antd.pagination.page_size',
  'QRCode.expired': 'antd.qr.expired',
  'QRCode.refresh': 'antd.qr.refresh',
  'QRCode.scanned': 'antd.qr.scanned',
  'Table.emptyText': 'antd.table.empty',
  'Table.filterCheckAll': 'antd.table.filter_check_all',
  'Table.filterEmptyText': 'antd.table.filter_empty',
  'Table.filterSearchPlaceholder': 'antd.table.filter_search',
  'Table.selectNone': 'antd.table.select_none',
  'Text.collapse': 'antd.text.collapse',
  'Transfer.deselectAll': 'antd.transfer.deselect_all',
  'Transfer.remove': 'antd.transfer.remove',
  'Transfer.removeAll': 'antd.transfer.remove_all',
  'Transfer.removeCurrent': 'antd.transfer.remove_current',
  'Transfer.selectAll': 'antd.transfer.select_all',
  'Transfer.selectCurrent': 'antd.transfer.select_current',
  'Transfer.selectInvert': 'antd.transfer.select_invert',
};

function completed(base: AntLocale, locale: Locale): AntLocale {
  const result = structuredClone(base) as unknown as Record<string, unknown>;
  for (const [path, key] of Object.entries(ANTD_GAPS)) {
    const parts = path.split('.');
    const last = parts.at(-1) ?? path;
    let node = result;
    for (const part of parts.slice(0, -1)) {
      node[part] = { ...(node[part] ?? {}) };
      node = node[part] as Record<string, unknown>;
    }
    node[last] = label(key, locale);
  }
  return result as unknown as AntLocale;
}

/** Ant Design's locale per UI language, completed from our labels where Ant Design has gaps. */
export const ANT_LOCALES: Readonly<Record<Locale, AntLocale>> = {
  en: enUS,
  ar: completed(arEG, 'ar'),
  ur: completed(urPK, 'ur'),
};
