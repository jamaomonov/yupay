# Sequence diagrams

One `.mmd` per flow, Mermaid `sequenceDiagram`, referenced from
`docs/architecture/module-map.md` and from the module READMEs that own the flow.
AGENTS.md §5 requires one for a new module or a boundary change.

## They must parse

Seventeen of these thirty-nine did not, for two years, and nobody noticed —
because nothing renders them in CI and a broken diagram looks like a fine text
file in a diff. Sixteen failed on the same character. If you add one, parse it
before you commit.

```bash
# mermaid + jsdom, whatever version you have to hand
node -e '
  const { JSDOM } = require("jsdom");
  const dom = new JSDOM("<!doctype html><body></body>", { pretendToBeVisual: true });
  globalThis.window = dom.window; globalThis.document = dom.window.document;
  import("mermaid").then(async ({ default: m }) => {
    m.initialize({ startOnLoad: false, securityLevel: "loose" });
    const fs = require("fs"), dir = ".";
    for (const f of fs.readdirSync(dir).filter((f) => f.endsWith(".mmd"))) {
      try { await m.parse(fs.readFileSync(dir + "/" + f, "utf8")); }
      catch (e) { console.log("FAIL " + f + " :: " + String(e.message).split("\n")[0]); }
    }
  });
'
```

## The character

**A `;` anywhere in diagram text is a statement separator**, so a note reading
`signed; body, never a URL` ends the statement mid-sentence and the parse dies
several lines later with a message that points at the wrong place. That is why
it survived: the error names a line nobody had edited.

The same applies to anything ending in one — an HTML entity like `&gt;` is
`&`, `g`, `t`, `;`, and breaks a diagram for exactly the reason a semicolon
does. Write `>` and `<` plainly; Mermaid accepts both.

Mermaid does have a numeric escape (`#59;`), but the twenty-seven semicolons
this repo had were all ordinary prose punctuation, and an em dash or a comma
says the same thing without a mechanism a reader has to know about. Prefer the
punctuation; keep the escape for a case where the literal character is the
point.

Everything else is unremarkable: `<br/>` for a line break inside a note, and
`%%` for a comment.
