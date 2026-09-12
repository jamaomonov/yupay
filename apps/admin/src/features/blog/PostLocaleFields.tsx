import { Button, Input } from "@yupay/ui";

import { BlogEditor } from "./BlogEditor";
import { LOCALES, T, type Locale, type Translation } from "./types";

import { Field } from "@/components/Field";

interface Props {
  locale: Locale;
  current: Translation;
  onLocale: (locale: Locale) => void;
  onPatch: (patch: Partial<Translation>) => void;
}

export function PostLocaleFields({ locale, current, onLocale, onPatch }: Props) {
  return (
    <>
      <div className="flex gap-2">
        {LOCALES.map((loc) => (
          <Button
            key={loc}
            type="button"
            variant={locale === loc ? "primary" : "ghost"}
            onClick={() => {
              onLocale(loc);
            }}
          >
            {loc.toUpperCase()}
          </Button>
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label={T.form.title}>
          {({ inputProps }) => (
            <Input
              {...inputProps}
              value={current.title}
              onChange={(e) => {
                onPatch({ title: e.target.value });
              }}
            />
          )}
        </Field>
        <Field label={T.form.slug}>
          {({ inputProps }) => (
            <Input
              {...inputProps}
              value={current.slug}
              onChange={(e) => {
                onPatch({ slug: e.target.value });
              }}
            />
          )}
        </Field>
        <Field label={T.form.excerpt}>
          {({ inputProps }) => (
            <Input
              {...inputProps}
              value={current.excerpt}
              onChange={(e) => {
                onPatch({ excerpt: e.target.value });
              }}
            />
          )}
        </Field>
        <Field label={T.form.seoTitle}>
          {({ inputProps }) => (
            <Input
              {...inputProps}
              value={current.seo_title ?? ""}
              onChange={(e) => {
                onPatch({ seo_title: e.target.value || null });
              }}
            />
          )}
        </Field>
      </div>
      <Field label={T.form.body}>
        {({ inputProps }) => (
          <div id={inputProps.id}>
            <BlogEditor
              key={locale}
              value={current.body_html}
              onChange={(html) => {
                onPatch({ body_html: html });
              }}
            />
          </div>
        )}
      </Field>
    </>
  );
}
