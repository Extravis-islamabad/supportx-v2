import { useEffect } from 'react';

/**
 * Ant Design's Form.Item hands its child `aria-required`; Select, TreeSelect and Cascader pass it
 * both to their combobox input (right) and to their outer box, a plain div that may not carry it
 * (axe aria-allowed-attr; the knowledge article's topic, matrix run 42978769692). This takes it
 * off the box only, wherever a select is drawn or re-drawn, so the input keeps saying "required".
 */
const BOX = '.ant-select';

function strip(root: ParentNode): void {
  for (const el of root.querySelectorAll(`${BOX}[aria-required]`)) {
    if (el.getAttribute('role') === null) el.removeAttribute('aria-required');
  }
}

export function useSelectAria(): void {
  useEffect(() => {
    strip(document);
    const observer = new MutationObserver((records) => {
      for (const record of records) {
        const target = record.target;
        if (record.type === 'attributes' && target instanceof Element) {
          if (target.matches(BOX) && target.getAttribute('role') === null) {
            target.removeAttribute('aria-required');
          }
        } else {
          for (const node of record.addedNodes) {
            if (node instanceof Element) {
              if (node.matches(`${BOX}[aria-required]`) && node.getAttribute('role') === null) {
                node.removeAttribute('aria-required');
              }
              strip(node);
            }
          }
        }
      }
    });
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['aria-required'],
    });
    return () => {
      observer.disconnect();
    };
  }, []);
}
