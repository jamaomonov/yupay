import {
  Bold,
  Code,
  Heading2,
  Heading3,
  ImagePlus,
  Italic,
  Link as LinkIcon,
  List,
  ListOrdered,
  Minus,
  Quote,
  Table as TableIcon,
} from "lucide-react";
import { useId, useRef, type ReactNode } from "react";

import { T } from "./types";

import type { Editor } from "@tiptap/react";

import { uploadRasterMedia } from "@/lib/uploadMedia";

interface Props {
  editor: Editor;
  disabled: boolean;
}

function readLinkHref(editor: Editor): string {
  const attrs: unknown = editor.getAttributes("link");
  if (typeof attrs !== "object" || attrs === null || !("href" in attrs)) {
    return "";
  }
  const href = attrs.href;
  return typeof href === "string" ? href : "";
}

function ToolButton({
  label,
  active,
  disabled,
  onClick,
  children,
}: {
  label: string;
  active?: boolean;
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active === true}
      disabled={disabled}
      onClick={onClick}
      className={[
        "grid size-8 place-items-center rounded text-[var(--text-secondary)]",
        "hover:bg-[var(--bg-muted)] hover:text-[var(--text-primary)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
        active === true ? "bg-[var(--bg-muted)] text-[var(--text-primary)]" : "",
        disabled ? "opacity-50" : "",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

export function BlogEditorToolbar({ editor, disabled }: Props) {
  const inputId = useId();
  const fileRef = useRef<HTMLInputElement>(null);

  function setLink(): void {
    const previous = readLinkHref(editor);
    const href = window.prompt(T.form.linkPrompt, previous);
    if (href === null) return;
    if (href.trim() === "") {
      editor.chain().focus().extendMarkRange("link").unsetLink().run();
      return;
    }
    editor.chain().focus().extendMarkRange("link").setLink({ href: href.trim() }).run();
  }

  async function onImageFile(file: File): Promise<void> {
    const alt = window.prompt(T.form.imageAltPrompt, file.name.replace(/\.[^.]+$/, "")) ?? "";
    if (!alt.trim()) return;
    try {
      const src = await uploadRasterMedia("blog_image", file);
      editor
        .chain()
        .focus()
        .setImage({ src, alt: alt.trim().slice(0, 200) })
        .run();
    } catch (exc) {
      window.alert(
        exc instanceof Error ? exc.message : T.form.error.replace("{message}", "upload"),
      );
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-0.5 border-b border-[var(--border-default)] px-1 py-1">
      <ToolButton
        label={T.form.tools.h2}
        active={editor.isActive("heading", { level: 2 })}
        disabled={disabled}
        onClick={() => {
          editor.chain().focus().toggleHeading({ level: 2 }).run();
        }}
      >
        <Heading2 className="size-4" />
      </ToolButton>
      <ToolButton
        label={T.form.tools.h3}
        active={editor.isActive("heading", { level: 3 })}
        disabled={disabled}
        onClick={() => {
          editor.chain().focus().toggleHeading({ level: 3 }).run();
        }}
      >
        <Heading3 className="size-4" />
      </ToolButton>
      <ToolButton
        label={T.form.tools.bold}
        active={editor.isActive("bold")}
        disabled={disabled}
        onClick={() => {
          editor.chain().focus().toggleBold().run();
        }}
      >
        <Bold className="size-4" />
      </ToolButton>
      <ToolButton
        label={T.form.tools.italic}
        active={editor.isActive("italic")}
        disabled={disabled}
        onClick={() => {
          editor.chain().focus().toggleItalic().run();
        }}
      >
        <Italic className="size-4" />
      </ToolButton>
      <ToolButton
        label={T.form.tools.ul}
        active={editor.isActive("bulletList")}
        disabled={disabled}
        onClick={() => {
          editor.chain().focus().toggleBulletList().run();
        }}
      >
        <List className="size-4" />
      </ToolButton>
      <ToolButton
        label={T.form.tools.ol}
        active={editor.isActive("orderedList")}
        disabled={disabled}
        onClick={() => {
          editor.chain().focus().toggleOrderedList().run();
        }}
      >
        <ListOrdered className="size-4" />
      </ToolButton>
      <ToolButton
        label={T.form.tools.quote}
        active={editor.isActive("blockquote")}
        disabled={disabled}
        onClick={() => {
          editor.chain().focus().toggleBlockquote().run();
        }}
      >
        <Quote className="size-4" />
      </ToolButton>
      <ToolButton
        label={T.form.tools.code}
        active={editor.isActive("codeBlock")}
        disabled={disabled}
        onClick={() => {
          editor.chain().focus().toggleCodeBlock().run();
        }}
      >
        <Code className="size-4" />
      </ToolButton>
      <ToolButton
        label={T.form.tools.link}
        active={editor.isActive("link")}
        disabled={disabled}
        onClick={setLink}
      >
        <LinkIcon className="size-4" />
      </ToolButton>
      <ToolButton
        label={T.form.tools.hr}
        disabled={disabled}
        onClick={() => {
          editor.chain().focus().setHorizontalRule().run();
        }}
      >
        <Minus className="size-4" />
      </ToolButton>
      <ToolButton
        label={T.form.tools.table}
        disabled={disabled}
        onClick={() => {
          editor.chain().focus().insertTable({ rows: 2, cols: 3, withHeaderRow: true }).run();
        }}
      >
        <TableIcon className="size-4" />
      </ToolButton>
      <ToolButton
        label={T.form.tools.image}
        disabled={disabled}
        onClick={() => {
          fileRef.current?.click();
        }}
      >
        <ImagePlus className="size-4" />
      </ToolButton>
      <input
        id={inputId}
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) void onImageFile(file);
        }}
      />
    </div>
  );
}
