import {
  BoldOutlined,
  ItalicOutlined,
  LinkOutlined,
  OrderedListOutlined,
  StrikethroughOutlined,
  TableOutlined,
  UnderlineOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons';
import { Placeholder } from '@tiptap/extension-placeholder';
import { TableKit } from '@tiptap/extension-table';
import { EditorContent, useEditor, type Editor } from '@tiptap/react';
import { StarterKit } from '@tiptap/starter-kit';
import { Button, Flex, Input, Modal, Tooltip } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';

import { useLabel } from '../appearance';
import { RichTextStyles } from './styles';
import type { RichTextFieldProps } from './types';

/**
 * The Tiptap editor behind RichTextField (D-036, D-040, D-051). Loaded on demand (its chunk is
 * not part of the shell). What it produces is exactly the server's allow-list
 * (backend/app/shared/richtext.py): StarterKit (headings, lists, quotes, code, link, underline)
 * and tables; every block reads in its own direction (`textDirection: 'auto'`), so Arabic and
 * English paragraphs mix correctly. The server sanitises every value again before storing it.
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
}: RichTextFieldProps) {
  const t = useLabel();
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3, 4] },
        link: { openOnClick: false, autolink: true, protocols: ['http', 'https', 'mailto'] },
      }),
      TableKit.configure({ table: { resizable: false } }),
      Placeholder.configure({ placeholder: placeholder ?? '' }),
    ],
    content: value ?? '',
    editable: !disabled,
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
  return (
    <div className={`sx-richtext-frame${invalid ? ' sx-richtext-invalid' : ''}`}>
      <RichTextStyles />
      {!disabled && <Toolbar editor={editor} />}
      <EditorContent editor={editor} />
      <span className="sx-visually-hidden">{t('richtext.hint')}</span>
    </div>
  );
}

function Tool({
  title,
  icon,
  active,
  onClick,
  testId,
}: {
  title: string;
  icon: ReactNode;
  active?: boolean;
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

function Toolbar({ editor }: { editor: Editor }) {
  const t = useLabel();
  const [linking, setLinking] = useState(false);
  const [href, setHref] = useState('');
  const chain = () => editor.chain().focus();
  return (
    <Flex
      gap={2}
      wrap
      className="sx-richtext-toolbar"
      role="toolbar"
      aria-label={t('richtext.toolbar')}
    >
      <Tool
        title={t('richtext.bold')}
        icon={<BoldOutlined />}
        active={editor.isActive('bold')}
        onClick={() => chain().toggleBold().run()}
        testId="rt-bold"
      />
      <Tool
        title={t('richtext.italic')}
        icon={<ItalicOutlined />}
        active={editor.isActive('italic')}
        onClick={() => chain().toggleItalic().run()}
        testId="rt-italic"
      />
      <Tool
        title={t('richtext.underline')}
        icon={<UnderlineOutlined />}
        active={editor.isActive('underline')}
        onClick={() => chain().toggleUnderline().run()}
        testId="rt-underline"
      />
      <Tool
        title={t('richtext.strike')}
        icon={<StrikethroughOutlined />}
        active={editor.isActive('strike')}
        onClick={() => chain().toggleStrike().run()}
        testId="rt-strike"
      />
      <Tool
        title={t('richtext.bullets')}
        icon={<UnorderedListOutlined />}
        active={editor.isActive('bulletList')}
        onClick={() => chain().toggleBulletList().run()}
        testId="rt-bullets"
      />
      <Tool
        title={t('richtext.numbers')}
        icon={<OrderedListOutlined />}
        active={editor.isActive('orderedList')}
        onClick={() => chain().toggleOrderedList().run()}
        testId="rt-numbers"
      />
      <Tool
        title={t('richtext.link')}
        icon={<LinkOutlined />}
        active={editor.isActive('link')}
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
