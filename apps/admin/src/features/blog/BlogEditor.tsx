/**
 * Allowlisted article editor. Toolbar buttons wrap the selection; images
 * go through the ``blog_image`` R2 presign so ``sanitize`` will accept them.
 */

import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import Table from "@tiptap/extension-table";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import TableRow from "@tiptap/extension-table-row";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useEffect, useReducer, useRef } from "react";

import { BlogEditorToolbar } from "./BlogEditorToolbar";
import { T } from "./types";

interface Props {
  value: string;
  onChange: (html: string) => void;
  disabled?: boolean;
}

function stringAttr(attrs: Record<string, unknown>, key: string): string {
  const value = attrs[key];
  return typeof value === "string" ? value : "";
}

const CdnImage = Image.extend({
  renderHTML({ HTMLAttributes }: { HTMLAttributes: Record<string, unknown> }) {
    return ["img", { src: stringAttr(HTMLAttributes, "src"), alt: stringAttr(HTMLAttributes, "alt") }];
  },
});

const HrefOnlyLink = Link.extend({
  renderHTML({ HTMLAttributes }: { HTMLAttributes: Record<string, unknown> }) {
    return ["a", { href: stringAttr(HTMLAttributes, "href") }, 0];
  },
});

function isAllowedHref(href: string): boolean {
  return (
    href.startsWith("https://") ||
    href.startsWith("http://") ||
    (href.startsWith("/") && !href.startsWith("//"))
  );
}

export function BlogEditor({ value, onChange, disabled }: Props) {
  const lastEmitted = useRef(value);
  const [, rerender] = useReducer((n: number) => n + 1, 0);
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3] },
        strike: false,
      }),
      HrefOnlyLink.configure({
        openOnClick: false,
        autolink: false,
        validate: isAllowedHref,
      }),
      CdnImage.configure({ allowBase64: false }),
      Table.configure({ resizable: false }),
      TableRow,
      TableHeader,
      TableCell,
      Placeholder.configure({ placeholder: T.form.editorPlaceholder }),
    ],
    content: value,
    editable: disabled !== true,
    immediatelyRender: false,
    editorProps: {
      attributes: {
        class:
          "min-h-64 px-3 py-2 text-sm leading-relaxed outline-none [&_h2]:mt-4 [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:text-base [&_h3]:font-semibold [&_blockquote]:border-l-2 [&_blockquote]:border-[var(--border-default)] [&_blockquote]:pl-3 [&_img]:max-w-full [&_img]:rounded-md [&_table]:w-full [&_td]:border [&_th]:border [&_td]:border-[var(--border-default)] [&_th]:border-[var(--border-default)] [&_td]:px-2 [&_th]:px-2 [&_a]:text-[var(--accent)] [&_a]:underline [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-[var(--bg-muted)] [&_pre]:p-2",
      },
    },
    onUpdate: ({ editor: next }) => {
      const html = next.getHTML();
      lastEmitted.current = html;
      onChange(html);
    },
    onSelectionUpdate: rerender,
  });

  useEffect(() => {
    if (editor === null) return;
    if (value === lastEmitted.current) return;
    lastEmitted.current = value;
    editor.commands.setContent(value, false);
  }, [editor, value]);

  useEffect(() => {
    editor?.setEditable(disabled !== true);
  }, [disabled, editor]);

  if (editor === null) return null;

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)]">
      <BlogEditorToolbar editor={editor} disabled={disabled === true} />
      <EditorContent editor={editor} />
    </div>
  );
}
