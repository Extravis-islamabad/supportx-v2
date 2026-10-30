import {
  AlignCenterOutlined,
  AlignLeftOutlined,
  AlignRightOutlined,
  BoldOutlined,
  ClearOutlined,
  CodeOutlined,
  ConsoleSqlOutlined,
  FontColorsOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
  HighlightOutlined,
  InfoCircleOutlined,
  ItalicOutlined,
  LineOutlined,
  LinkOutlined,
  MenuFoldOutlined,
  MenuOutlined,
  MenuUnfoldOutlined,
  MessageOutlined,
  OrderedListOutlined,
  RedoOutlined,
  SnippetsOutlined,
  StrikethroughOutlined,
  TableOutlined,
  UnderlineOutlined,
  UndoOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons';
import { Placeholder } from '@tiptap/extension-placeholder';
import { TableKit } from '@tiptap/extension-table';
import { EditorContent, useEditor, useEditorState, type Editor } from '@tiptap/react';
import { StarterKit } from '@tiptap/starter-kit';
import { Button, Divider, Dropdown, Flex, Input, Modal, Select, Tooltip } from 'antd';
import type { EditorView } from '@tiptap/pm/view';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';

import { queryKeys, useFileRules, type FileRules } from '@supportx/api-client';
import { usePersonalChannel } from '@supportx/realtime';

import { useAppearance, useLabel } from '../appearance';
import {
  BlockFormat,
  CALLOUTS,
  Callout,
  HIGHLIGHTS,
  HighlightMark,
  TEXT_COLOURS,
  TextColourMark,
  type Alignment,
} from './extensions';
import { ListItemDirection } from './direction';
import { InlineImage, insertImages } from './inlineImage';
import { mentionExtension } from './mention';
import { cleanPastedHtml } from './paste';
import { RichTextStyles } from './styles';
import type { RichTextFieldProps, RichTextTemplate } from './types';

/**
 * The Tiptap editor behind RichTextField (D-036, D-040, D-051; richer toolbar WP-020b). Loaded on
 * demand (its chunk is not part of the shell). What it produces is exactly the server's
 * allow-list (backend/app/shared/richtext.py): StarterKit (three heading sizes, lists, quote,
 * code, horizontal line, link, underline, undo/redo), tables, and our own codes for alignment,
 * indent, palette colours and highlights (extensions.ts), plus @mentions. Every block reads in its
 * own direction (`textDirection: 'auto'`), so Arabic and English paragraphs mix correctly, and
 * alignment and indent are logical (start/end), so they are right in both directions. Pastes from
 * Word, Outlook and the web are cleaned first (paste.ts). The server sanitises every value again.
 *
 * Inline images (WP-022): with `imageOwnerId`, image files pasted or dropped into the text are
 * uploaded as the author's drafts and shown inline once checked (inlineImage.tsx). Images inside
 * pasted HTML (remote addresses) are still dropped (paste.ts): only stored files are kept.
 */
export default function RichTextEditor({
  value,
  onChange,
  placeholder,
  label,
  disabled = false,
  invalid = false,
  testId,
  id,
  mentions,
  templates,
  onManageTemplates,
  minHeight,
  autoFocus = false,
  imageOwnerId,
  callouts = false,
}: RichTextFieldProps) {
  const t = useLabel();
  const [fullScreen, setFullScreen] = useState(false);
  // Filled by <ImageSupport> (only mounted when images are taken): the tenant's file rules.
  const images = useRef<{ ownerId: string | undefined; rules: FileRules | undefined }>({
    ownerId: imageOwnerId,
    rules: undefined,
  });
  useEffect(() => {
    images.current.ownerId = imageOwnerId;
  }, [imageOwnerId]);
  const take = (view: EditorView, files: FileList | null | undefined, pos: number): boolean => {
    const ownerId = images.current.ownerId;
    if (ownerId === undefined || files === null || files === undefined) return false;
    return insertImages(view, Array.from(files), pos, { ownerId, rules: images.current.rules, t });
  };
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3, 4] },
        link: { openOnClick: false, autolink: true, protocols: ['http', 'https', 'mailto'] },
      }),
      TableKit.configure({ table: { resizable: false } }),
      Placeholder.configure({ placeholder: placeholder ?? '' }),
      BlockFormat,
      TextColourMark,
      HighlightMark,
      ListItemDirection,
      ...(mentions === undefined ? [] : [mentionExtension(mentions)]),
      ...(imageOwnerId === undefined ? [] : [InlineImage]),
      ...(callouts ? [Callout] : []),
    ],
    content: value ?? '',
    editable: !disabled,
    autofocus: autoFocus ? 'end' : false,
    textDirection: 'auto',
    editorProps: {
      attributes: {
        role: 'textbox',
        'aria-multiline': 'true',
        'aria-label': label,
        ...(invalid ? { 'aria-invalid': 'true' } : {}),
        ...(id === undefined ? {} : { id }),
        ...(testId === undefined ? {} : { 'data-testid': testId }),
        class: 'sx-richtext sx-richtext-input',
      },
      transformPastedHTML: cleanPastedHtml,
      // Pasted or dropped image files become inline images (WP-022); other pastes into an empty
      // line make the line the first pasted block (its heading level and alignment), instead of
      // ProseMirror merging the pasted text into it (QA C7).
      handlePaste: (view, event, slice) => {
        if (take(view, event.clipboardData?.files, view.state.selection.from)) return true;
        const { $from, empty } = view.state.selection;
        const first = slice.content.firstChild;
        if (!empty || !$from.parent.isTextblock || $from.parent.content.size > 0) return false;
        if (first === null || !first.isTextblock || slice.openStart === 0) return false;
        const start = $from.before();
        const tr = view.state.tr.replaceSelection(slice);
        const line = tr.doc.nodeAt(start);
        if (line?.isTextblock === true) {
          tr.setNodeMarkup(start, first.type, { ...line.attrs, ...first.attrs });
        }
        view.dispatch(tr.scrollIntoView());
        return true;
      },
      handleDrop: (view, event, _slice, moved) => {
        if (moved) return false;
        const at = view.posAtCoords({ left: event.clientX, top: event.clientY });
        return take(view, event.dataTransfer?.files, at?.pos ?? view.state.selection.from);
      },
    },
    onUpdate: ({ editor: current }) => {
      onChange?.(current.isEmpty ? '' : current.getHTML());
    },
    immediatelyRender: true,
  });
  // The form reset the value (or loaded another record): show it without moving the caret twice.
  useEffect(() => {
    if (editor.isDestroyed) return;
    const current = editor.isEmpty ? '' : editor.getHTML();
    if ((value ?? '') !== current) editor.commands.setContent(value ?? '', { emitUpdate: false });
  }, [editor, value]);
  useEffect(() => {
    editor.setEditable(!disabled);
  }, [editor, disabled]);
  // Escape leaves full screen wherever the focus is (QA BUG-05).
  useEffect(() => {
    if (!fullScreen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setFullScreen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
    };
  }, [fullScreen]);
  return (
    <div
      className={`sx-richtext-frame${invalid ? ' sx-richtext-invalid' : ''}${fullScreen ? ' sx-richtext-fullscreen' : ''}`}
      data-testid={testId === undefined ? undefined : `${testId}-frame`}
      // The composer's minimum height; full screen fills the window instead (QA BUG-05).
      style={
        fullScreen || minHeight === undefined
          ? undefined
          : ({ '--sx-editor-min-height': `${String(minHeight)}px` } as CSSProperties)
      }
      {...(fullScreen ? { role: 'dialog', 'aria-modal': true, 'aria-label': label } : {})}
    >
      <RichTextStyles />
      {!disabled && (
        <Toolbar
          editor={editor}
          templates={templates}
          callouts={callouts}
          onManageTemplates={onManageTemplates}
          fullScreen={fullScreen}
          onFullScreen={() => {
            setFullScreen((on) => !on);
            editor.commands.focus();
          }}
        />
      )}
      {imageOwnerId !== undefined && (
        <ImageSupport
          onRules={(found) => {
            images.current.rules = found;
          }}
        />
      )}
      <EditorContent
        editor={editor}
        className="sx-richtext-scroll"
        // A click on the empty space below the text puts the caret at the end (QA BUG-05).
        onMouseDown={(event) => {
          if (event.target === event.currentTarget) {
            event.preventDefault();
            editor.commands.focus('end');
          }
        }}
      />
      <span className="sx-visually-hidden">{t('richtext.hint')}</span>
    </div>
  );
}

/**
 * What inline images need from the app (WP-022): the tenant's file rules (refuse early) and the
 * personal channel (a draft's scan finished: its placeholder becomes the image).
 */
function ImageSupport({ onRules }: { onRules: (rules: FileRules | undefined) => void }) {
  const rules = useFileRules();
  const queryClient = useQueryClient();
  useEffect(() => {
    onRules(rules.data);
  }, [rules.data, onRules]);
  usePersonalChannel((event) => {
    if (event.type === 'files.changed') {
      for (const fileId of event.ids) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.files.detail(fileId) });
      }
    }
  });
  return null;
}

function Tool({
  title,
  icon,
  active,
  disabled,
  onClick,
  testId,
}: {
  title: string;
  icon: ReactNode;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
  testId: string;
}) {
  return (
    <Tooltip title={title}>
      <Button
        size="small"
        type={active === true ? 'primary' : 'text'}
        aria-label={title}
        aria-pressed={active}
        disabled={disabled}
        icon={icon}
        onMouseDown={(event) => {
          event.preventDefault(); // keep the selection in the editor
        }}
        onClick={onClick}
        data-testid={testId}
      />
    </Tooltip>
  );
}

const Gap = () => <Divider type="vertical" style={{ marginInline: 2, height: 20 }} />;

function Swatch({ kind, code }: { kind: 'text' | 'highlight'; code: string | null }) {
  return (
    <span
      aria-hidden
      className={`sx-swatch sx-swatch-${kind}`}
      data-color={code ?? undefined}
      style={{ display: 'inline-block', width: 14, height: 14, borderRadius: 3 }}
    />
  );
}

type HeadingChoice = 'paragraph' | '2' | '3' | '4';

function Toolbar({
  editor,
  callouts,
  templates,
  onManageTemplates,
  fullScreen,
  onFullScreen,
}: {
  editor: Editor;
  callouts: boolean;
  templates: RichTextTemplate[] | undefined;
  onManageTemplates: (() => void) | undefined;
  fullScreen: boolean;
  onFullScreen: () => void;
}) {
  const t = useLabel();
  const { direction } = useAppearance();
  const [linking, setLinking] = useState(false);
  const [href, setHref] = useState('');
  // Re-render the toolbar when the selection or the content changes (active states).
  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e.isActive('bold'),
      italic: e.isActive('italic'),
      underline: e.isActive('underline'),
      strike: e.isActive('strike'),
      code: e.isActive('code'),
      bullets: e.isActive('bulletList'),
      numbers: e.isActive('orderedList'),
      quote: e.isActive('blockquote'),
      codeBlock: e.isActive('codeBlock'),
      link: e.isActive('link'),
      heading: e.isActive('heading', { level: 2 })
        ? '2'
        : e.isActive('heading', { level: 3 })
          ? '3'
          : e.isActive('heading', { level: 4 })
            ? '4'
            : 'paragraph',
      align: (e.getAttributes('paragraph').align ??
        e.getAttributes('heading').align ??
        null) as Alignment | null,
      canUndo: e.can().undo(),
      canRedo: e.can().redo(),
    }),
  });
  const chain = () => editor.chain().focus();
  // Logical alignment, physical icons: "start" is drawn on the left in English, right in Arabic.
  const rtl = direction === 'rtl';
  const startIcon = rtl ? <AlignRightOutlined /> : <AlignLeftOutlined />;
  const endIcon = rtl ? <AlignLeftOutlined /> : <AlignRightOutlined />;
  const indentIcon = rtl ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />;
  const outdentIcon = rtl ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />;
  const align = (value: Alignment) => {
    chain()
      .setAlignment(state.align === value ? null : value)
      .run();
  };
  return (
    <Flex
      gap={2}
      wrap
      align="center"
      className="sx-richtext-toolbar"
      role="toolbar"
      aria-label={t('richtext.toolbar')}
    >
      <Tool
        title={t('richtext.undo')}
        icon={<UndoOutlined />}
        disabled={!state.canUndo}
        onClick={() => chain().undo().run()}
        testId="rt-undo"
      />
      <Tool
        title={t('richtext.redo')}
        icon={<RedoOutlined />}
        disabled={!state.canRedo}
        onClick={() => chain().redo().run()}
        testId="rt-redo"
      />
      <Gap />
      <Select<HeadingChoice>
        size="small"
        variant="borderless"
        aria-label={t('richtext.text_style')}
        value={state.heading as HeadingChoice}
        popupMatchSelectWidth={false}
        // Fixed width: inside a form Ant Design stretches selects to the full line.
        style={{ width: 150, flex: 'none' }}
        onChange={(choice) => {
          if (choice === 'paragraph') chain().setParagraph().run();
          else
            chain()
              .setHeading({ level: Number(choice) as 2 | 3 | 4 })
              .run();
        }}
        options={[
          { value: 'paragraph', label: t('richtext.style.paragraph') },
          { value: '2', label: t('richtext.style.heading_large') },
          { value: '3', label: t('richtext.style.heading_medium') },
          { value: '4', label: t('richtext.style.heading_small') },
        ]}
        data-testid="rt-style"
      />
      <Gap />
      <Tool
        title={t('richtext.bold')}
        icon={<BoldOutlined />}
        active={state.bold}
        onClick={() => chain().toggleBold().run()}
        testId="rt-bold"
      />
      <Tool
        title={t('richtext.italic')}
        icon={<ItalicOutlined />}
        active={state.italic}
        onClick={() => chain().toggleItalic().run()}
        testId="rt-italic"
      />
      <Tool
        title={t('richtext.underline')}
        icon={<UnderlineOutlined />}
        active={state.underline}
        onClick={() => chain().toggleUnderline().run()}
        testId="rt-underline"
      />
      <Tool
        title={t('richtext.strike')}
        icon={<StrikethroughOutlined />}
        active={state.strike}
        onClick={() => chain().toggleStrike().run()}
        testId="rt-strike"
      />
      <Tool
        title={t('richtext.code')}
        icon={<CodeOutlined />}
        active={state.code}
        onClick={() => chain().toggleCode().run()}
        testId="rt-code"
      />
      <Dropdown
        trigger={['click']}
        menu={{
          items: [
            {
              key: 'none',
              icon: <Swatch kind="text" code={null} />,
              label: t('richtext.colour.default'),
              onClick: () => chain().unsetTextColour().run(),
            },
            ...TEXT_COLOURS.map((code) => ({
              key: code,
              icon: <Swatch kind="text" code={code} />,
              label: t(`richtext.colour.${code}`),
              onClick: () => chain().setTextColour(code).run(),
            })),
          ],
        }}
      >
        <Button
          size="small"
          type="text"
          aria-label={t('richtext.text_colour')}
          icon={<FontColorsOutlined />}
          onMouseDown={(event) => {
            event.preventDefault();
          }}
          data-testid="rt-colour"
        />
      </Dropdown>
      <Dropdown
        trigger={['click']}
        menu={{
          items: [
            {
              key: 'none',
              icon: <Swatch kind="highlight" code={null} />,
              label: t('richtext.highlight.none'),
              onClick: () => chain().unsetHighlight().run(),
            },
            ...HIGHLIGHTS.map((code) => ({
              key: code,
              icon: <Swatch kind="highlight" code={code} />,
              label: t(`richtext.highlight.${code}`),
              onClick: () => chain().setHighlight(code).run(),
            })),
          ],
        }}
      >
        <Button
          size="small"
          type="text"
          aria-label={t('richtext.highlight')}
          icon={<HighlightOutlined />}
          onMouseDown={(event) => {
            event.preventDefault();
          }}
          data-testid="rt-highlight"
        />
      </Dropdown>
      <Gap />
      <Tool
        title={t('richtext.align.start')}
        icon={startIcon}
        active={state.align === 'start'}
        onClick={() => {
          align('start');
        }}
        testId="rt-align-start"
      />
      <Tool
        title={t('richtext.align.center')}
        icon={<AlignCenterOutlined />}
        active={state.align === 'center'}
        onClick={() => {
          align('center');
        }}
        testId="rt-align-center"
      />
      <Tool
        title={t('richtext.align.end')}
        icon={endIcon}
        active={state.align === 'end'}
        onClick={() => {
          align('end');
        }}
        testId="rt-align-end"
      />
      <Tool
        title={t('richtext.align.justify')}
        icon={<MenuOutlined />}
        active={state.align === 'justify'}
        onClick={() => {
          align('justify');
        }}
        testId="rt-align-justify"
      />
      <Tool
        title={t('richtext.outdent')}
        icon={outdentIcon}
        onClick={() => chain().outdent().run()}
        testId="rt-outdent"
      />
      <Tool
        title={t('richtext.indent')}
        icon={indentIcon}
        onClick={() => chain().indent().run()}
        testId="rt-indent"
      />
      <Gap />
      <Tool
        title={t('richtext.bullets')}
        icon={<UnorderedListOutlined />}
        active={state.bullets}
        onClick={() => chain().toggleBulletList().run()}
        testId="rt-bullets"
      />
      <Tool
        title={t('richtext.numbers')}
        icon={<OrderedListOutlined />}
        active={state.numbers}
        onClick={() => chain().toggleOrderedList().run()}
        testId="rt-numbers"
      />
      <Tool
        title={t('richtext.quote')}
        icon={<MessageOutlined />}
        active={state.quote}
        onClick={() => chain().toggleBlockquote().run()}
        testId="rt-quote"
      />
      <Tool
        title={t('richtext.code_block')}
        icon={<ConsoleSqlOutlined />}
        active={state.codeBlock}
        onClick={() => chain().toggleCodeBlock().run()}
        testId="rt-code-block"
      />
      <Tool
        title={t('richtext.horizontal_line')}
        icon={<LineOutlined />}
        onClick={() => chain().setHorizontalRule().run()}
        testId="rt-hr"
      />
      <Tool
        title={t('richtext.link')}
        icon={<LinkOutlined />}
        active={state.link}
        onClick={() => {
          setHref((editor.getAttributes('link').href as string | undefined) ?? '');
          setLinking(true);
        }}
        testId="rt-link"
      />
      <Tool
        title={t('richtext.table')}
        icon={<TableOutlined />}
        onClick={() => chain().insertTable({ rows: 2, cols: 2, withHeaderRow: true }).run()}
        testId="rt-table"
      />
      <Gap />
      <Tool
        title={t('richtext.clear_formatting')}
        icon={<ClearOutlined />}
        onClick={() => chain().unsetAllMarks().clearNodes().setAlignment(null).run()}
        testId="rt-clear"
      />
      {callouts && (
        <Dropdown
          trigger={['click']}
          menu={{
            items: [
              ...CALLOUTS.map((kind) => ({
                key: kind,
                label: t(`richtext.callout.${kind}`),
                onClick: () => chain().setCallout(kind).run(),
              })),
              { type: 'divider' as const },
              {
                key: 'none',
                label: t('richtext.callout.remove'),
                onClick: () => chain().unsetCallout().run(),
              },
            ],
          }}
        >
          <Button
            size="small"
            type="text"
            icon={<InfoCircleOutlined />}
            onMouseDown={(event) => {
              event.preventDefault();
            }}
            data-testid="rt-callout"
          >
            {t('richtext.callout')}
          </Button>
        </Dropdown>
      )}
      {templates !== undefined && (
        <Dropdown
          trigger={['click']}
          menu={{
            items: [
              ...(templates.length === 0
                ? [{ key: 'none', disabled: true, label: t('richtext.templates_none') }]
                : templates.map((template) => ({
                    key: template.id,
                    label: <bdi dir="auto">{template.name}</bdi>,
                    onClick: () => chain().insertContent(template.body).run(),
                  }))),
              ...(onManageTemplates === undefined
                ? []
                : [
                    { type: 'divider' as const },
                    {
                      key: 'manage',
                      label: t('richtext.templates_manage'),
                      onClick: onManageTemplates,
                    },
                  ]),
            ],
          }}
        >
          <Button
            size="small"
            type="text"
            icon={<SnippetsOutlined />}
            onMouseDown={(event) => {
              event.preventDefault();
            }}
            data-testid="rt-templates"
          >
            {t('richtext.templates')}
          </Button>
        </Dropdown>
      )}
      <span style={{ flex: 1 }} />
      <Tool
        title={t(fullScreen ? 'richtext.exit_full_screen' : 'richtext.full_screen')}
        icon={fullScreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
        active={fullScreen}
        onClick={onFullScreen}
        testId="rt-full-screen"
      />
      <Modal
        open={linking}
        title={t('richtext.link')}
        okText={t('actions.save')}
        cancelText={t('actions.cancel')}
        onCancel={() => {
          setLinking(false);
        }}
        onOk={() => {
          const target = href.trim();
          if (target === '') chain().unsetLink().run();
          else if (/^(https?:|mailto:)/i.test(target)) {
            chain().extendMarkRange('link').setLink({ href: target }).run();
          }
          setLinking(false);
        }}
        destroyOnHidden
      >
        <label htmlFor="rt-href">{t('richtext.link_address')}</label>
        <Input
          id="rt-href"
          value={href}
          placeholder={t('richtext.link_placeholder')}
          onChange={(event) => {
            setHref(event.target.value);
          }}
          data-testid="rt-href"
        />
      </Modal>
    </Flex>
  );
}
