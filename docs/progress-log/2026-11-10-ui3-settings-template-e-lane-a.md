### 2026-11-10 — UI pass 3: lane A's settings pages on template E (lane A)

Branch feat/ui3-settings-lane-a. Template: docs/architecture/console-design.md, "Settings page (template E, D-147)".

**Done**

- **Incident General:** numbering, defaults and automatic moves are one draft. It still uses useDraft, so If-Match and the "changed elsewhere" notice keep working. Grouped SettingsCards, with no buttons inside them, and one StickySaveBar sending only what changed.
- **Incident Closing:** one card, and the save bar replaces its Save and Reset buttons.
- **SLA settings:** an antd Form whose changes are counted with Form.useWatch. Only the changes are sent.
- **Portal settings:** one draft across the four owners (catalog, incidents, requests, portal). Each owner gets only its own changed fields, with its own If-Match. The switches no longer save on their own.
- **Request settings:** one card and the save bar.
- **Automation routing:** the routing settings and the chosen group's auto-assignment are one save bar; the routing rules stay a list. Switching group drops unsaved assignment edits.
- **Also:**
  - CatalogItemPage's scroll is guarded (jsdom has no scrollIntoView; #315's unhandled error);
  - the default repeat rule seeds once when two runs race (ON CONFLICT on any unique index).

**Tests:** each page's test now proves the bar (its count, then Save sending only the change with If-Match). New tests: General (no card buttons, Discard) and the assignment PUT. The admin suite passes (256), and test_repeat_rules passes 7/7.
