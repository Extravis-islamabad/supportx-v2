// SupportX ESLint plugin (WP-010): keeps raw system values and untranslated text off the screen
// (architecture.md §9.5 "labels, not enums", CLAUDE.md rule d). Text goes through t()/label().

/** Props that hold machine codes: status codes, types, enum keys, problem codes. */
const CODE_PROPERTY =
  /^(status|state|state_reason|reason|user_type|type|kind|code|edition|feature|locale|role|priority|category|severity|impact|urgency|message_key|event_type)$|_(code|type|status|state|key|reason)$/;

/** Attributes whose value the user reads (or hears, for screen readers). */
const VISIBLE_ATTRIBUTES = new Set([
  'title',
  'label',
  'placeholder',
  'aria-label',
  'alt',
  'message',
  'description',
  'tooltip',
  'okText',
  'cancelText',
  'subTitle',
  'emptyText',
  'children',
]);

const LETTER = /\p{L}/u;

function isCodeValue(node) {
  if (node.type === 'ChainExpression') return isCodeValue(node.expression);
  if (node.type === 'MemberExpression' && !node.computed && node.property.type === 'Identifier') {
    return CODE_PROPERTY.test(node.property.name);
  }
  if (node.type === 'Identifier') return CODE_PROPERTY.test(node.name);
  if (node.type === 'TemplateLiteral') return node.expressions.some(isCodeValue);
  if (node.type === 'ConditionalExpression')
    return isCodeValue(node.consequent) || isCodeValue(node.alternate);
  if (node.type === 'LogicalExpression') return isCodeValue(node.left) || isCodeValue(node.right);
  return false;
}

function visibleAttribute(node) {
  return (
    node.parent?.type === 'JSXAttribute' &&
    node.parent.name.type === 'JSXIdentifier' &&
    VISIBLE_ATTRIBUTES.has(node.parent.name.name)
  );
}

/** {user.status} as a child or visible attribute: renders a code. Wrap it: {t(`user_status.${...}`)}. */
const noRawEnum = {
  meta: {
    type: 'problem',
    docs: { description: 'Disallow rendering raw enum/code values in JSX; render their label.' },
    messages: {
      raw: 'Raw code value "{{name}}" rendered in JSX. Render its label instead, e.g. t(`<prefix>.${value}`) (architecture.md §9.5).',
    },
    schema: [],
  },
  create(context) {
    return {
      JSXExpressionContainer(node) {
        const inChildren = node.parent.type === 'JSXElement' || node.parent.type === 'JSXFragment';
        if (!inChildren && !visibleAttribute(node)) return;
        if (node.expression.type === 'JSXEmptyExpression') return;
        if (isCodeValue(node.expression)) {
          context.report({
            node,
            messageId: 'raw',
            data: { name: context.sourceCode.getText(node.expression) },
          });
        }
      },
    };
  },
};

/** Hard-coded words in JSX text or visible attributes: they would never be translated. */
const noLiteralText = {
  meta: {
    type: 'problem',
    docs: { description: 'Disallow hard-coded user-visible text in JSX; use labels.' },
    messages: {
      literal:
        'Hard-coded text "{{text}}" in JSX. Use a label: t(\'some.key\') (CLAUDE.md rule d).',
    },
    schema: [],
  },
  create(context) {
    const check = (node, text) => {
      const trimmed = text.trim();
      if (trimmed !== '' && LETTER.test(trimmed)) {
        context.report({ node, messageId: 'literal', data: { text: trimmed.slice(0, 40) } });
      }
    };
    return {
      JSXText(node) {
        check(node, node.value);
      },
      Literal(node) {
        if (typeof node.value === 'string' && visibleAttribute(node)) check(node, node.value);
      },
    };
  },
};

/**
 * Channel hooks name the queries they cover (architecture.md §8.3): on a refresh (the
 * first-subscribe catch-up or a lost channel) the hook refreshes those keys itself, so a handler
 * that filters on message types can't drop it. The value is the options argument's position.
 */
const CHANNEL_HOOKS = new Map([
  ['useChannel', 2],
  ['useTenantChannel', 1],
  ['usePersonalChannel', 1],
  ['useListChannel', 2],
  ['useRecordEvents', 3],
  ['useRecordChannel', 3],
]);

const channelCovers = {
  meta: {
    type: 'problem',
    docs: { description: 'Channel hooks say which queries they cover (`covers`).' },
    schema: [],
    messages: {
      covers:
        "Say which queries this channel covers ({ covers: [...] }; [] with a comment if none), so a refresh can't be dropped (architecture.md §8.3).",
    },
  },
  create(context) {
    return {
      CallExpression(node) {
        if (node.callee.type !== 'Identifier') return;
        const at = CHANNEL_HOOKS.get(node.callee.name);
        if (at === undefined) return;
        if (node.arguments.some((a) => a.type === 'SpreadElement')) return;
        const options = node.arguments[at];
        if (options === undefined) {
          context.report({ node, messageId: 'covers' });
          return;
        }
        if (options.type !== 'ObjectExpression') return; // a variable: its type requires covers
        const named = options.properties.some(
          (p) =>
            p.type === 'Property' &&
            !p.computed &&
            ((p.key.type === 'Identifier' && p.key.name === 'covers') ||
              (p.key.type === 'Literal' && p.key.value === 'covers')),
        );
        if (!named) context.report({ node: options, messageId: 'covers' });
      },
    };
  },
};

const plugin = {
  meta: { name: '@supportx/eslint-plugin' },
  rules: {
    'no-raw-enum': noRawEnum,
    'no-literal-text': noLiteralText,
    'channel-covers': channelCovers,
  },
};

export default plugin;
