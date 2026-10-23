import { RuleTester } from 'eslint';
import { describe, it } from 'vitest';

import plugin from './index.js';

RuleTester.describe = describe;
RuleTester.it = it;
const tester = new RuleTester({
  languageOptions: {
    ecmaVersion: 2024,
    sourceType: 'module',
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
});

tester.run('no-raw-enum', plugin.rules['no-raw-enum'], {
  valid: [
    'const a = <Tag>{t(`user_status.${user.status}`)}</Tag>;',
    'const a = <span>{label(user.user_type, locale)}</span>;',
    'const a = <span>{user.display_name}</span>;',
    'const a = <Tag color={user.status === "active" ? "green" : "red"} />;',
    'const a = <Row key={item.key} data-status={user.status} />;',
    'const a = <span>{count}</span>;',
  ],
  invalid: [
    { code: 'const a = <Tag>{user.status}</Tag>;', errors: [{ messageId: 'raw' }] },
    { code: 'const a = <td>{row.user_type}</td>;', errors: [{ messageId: 'raw' }] },
    { code: 'const a = <p>{error.code}</p>;', errors: [{ messageId: 'raw' }] },
    { code: 'const a = <p>{entitlements?.edition}</p>;', errors: [{ messageId: 'raw' }] },
    { code: 'const a = <p>{`State: ${licence.state}`}</p>;', errors: [{ messageId: 'raw' }] },
    { code: 'const a = <Tooltip title={ticket.priority} />;', errors: [{ messageId: 'raw' }] },
    { code: 'const a = <p>{status}</p>;', errors: [{ messageId: 'raw' }] },
    { code: 'const a = <p>{x ? y.event_type : "-"}</p>;', errors: [{ messageId: 'raw' }] },
  ],
});

tester.run('no-literal-text', plugin.rules['no-literal-text'], {
  valid: [
    'const a = <Button>{t("actions.save")}</Button>;',
    'const a = <span> · </span>;',
    'const a = <span>42</span>;',
    'const a = <Input data-testid="profile-save" type="text" />;',
    'const a = <Input placeholder={t("users.search")} />;',
  ],
  invalid: [
    { code: 'const a = <Button>Save</Button>;', errors: [{ messageId: 'literal' }] },
    { code: 'const a = <Input placeholder="Search users" />;', errors: [{ messageId: 'literal' }] },
    { code: 'const a = <img alt="Company logo" />;', errors: [{ messageId: 'literal' }] },
    { code: 'const a = <p>حفظ</p>;', errors: [{ messageId: 'literal' }] },
  ],
});
