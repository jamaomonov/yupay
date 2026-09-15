import { Fragment } from "react";

/**
 * The small slice of Markdown the contract's descriptions actually use.
 *
 * Paragraphs, `-` lists, `` `code` `` and `**bold**` — and nothing else. A
 * full Markdown renderer is 30–60 KB of dependency to read four constructs,
 * and every one of them would then be a construct somebody could put in a
 * field description and have rendered as arbitrary HTML on a page other
 * people read. This escapes by construction: it emits React elements and
 * never a string of markup.
 */
export function Prose({ text, className }: { text: string; className?: string }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <div className={className}>
      {blocks.map((block, index) => {
        const lines = block.split("\n");
        if (lines.every((line) => line.trimStart().startsWith("- "))) {
          return (
            <ul key={index} className="ml-4 mt-2 list-disc space-y-1.5 first:mt-0">
              {lines.map((line, item) => (
                <li key={item}>
                  <Inline text={line.trimStart().slice(2)} />
                </li>
              ))}
            </ul>
          );
        }
        if (block.startsWith("```")) {
          return (
            <pre
              key={index}
              className="bg-card-2 rounded-btn mt-3 overflow-x-auto p-3 font-mono text-[12px] first:mt-0"
            >
              <code>{block.replaceAll("```", "").trim()}</code>
            </pre>
          );
        }
        return (
          <p key={index} className="mt-3 leading-relaxed first:mt-0">
            <Inline text={block.replaceAll("\n", " ")} />
          </p>
        );
      })}
    </div>
  );
}

/** `code` and **bold**, in one pass so neither can swallow the other. */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
          return (
            <code
              key={index}
              className="bg-card-2 text-foreground rounded px-1 py-0.5 font-mono text-[0.9em]"
            >
              {part.slice(1, -1)}
            </code>
          );
        }
        if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
          return (
            <strong key={index} className="text-foreground font-semibold">
              {part.slice(2, -2)}
            </strong>
          );
        }
        return <Fragment key={index}>{part}</Fragment>;
      })}
    </>
  );
}
