import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input, Select } from "@yupay/ui";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { PostLocaleFields } from "./PostLocaleFields";
import {
  idemHeaders,
  KINDS,
  LOCALES,
  T,
  type AdminPost,
  type Locale,
  type PostKind,
  type PostWriteBody,
  type Translation,
} from "./types";

import type { Brand } from "@/features/catalog/types";

import { Field } from "@/components/Field";
import { ImageUploader } from "@/components/ImageUploader";
import { PageHeader } from "@/components/PageHeader";
import { Spinner } from "@/components/States";
import { useToast } from "@/components/Toast";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";

function emptyTranslation(locale: Locale): Translation {
  return {
    locale,
    slug: "",
    title: "",
    excerpt: "",
    body_html: "",
    seo_title: null,
    seo_description: null,
  };
}

function filled(rows: Translation[]): Translation[] {
  return rows.filter((row) => row.title.trim() && row.slug.trim());
}

export function PostEditPage() {
  const { id } = useParams<{ id: string }>();
  const isNew = id === undefined || id === "new";
  const navigate = useNavigate();
  const toast = useToast();
  const qc = useQueryClient();

  const [kind, setKind] = useState<PostKind>("guide");
  const [brandId, setBrandId] = useState("");
  const [cover, setCover] = useState("");
  const [buyCard, setBuyCard] = useState(true);
  const [pin, setPin] = useState(false);
  const [eventStart, setEventStart] = useState("");
  const [eventEnd, setEventEnd] = useState("");
  const [locale, setLocale] = useState<Locale>("ru");
  const [translations, setTranslations] = useState<Translation[]>(
    LOCALES.map((loc) => emptyTranslation(loc)),
  );
  const [status, setStatus] = useState<AdminPost["status"]>("draft");

  const brandsQ = useQuery({
    queryKey: qk.brands(),
    queryFn: () => apiGet<Brand[]>("/api/v1/admin/catalog/brands"),
  });
  const postQ = useQuery({
    queryKey: qk.blogPost(id ?? ""),
    queryFn: () => apiGet<AdminPost>(`/api/v1/admin/blog/posts/${id ?? ""}`),
    enabled: !isNew,
  });

  useEffect(() => {
    const post = postQ.data;
    if (post === undefined) return;
    setKind(post.kind);
    setBrandId(post.primary_brand_id);
    setCover(post.cover_image_url ?? "");
    setBuyCard(post.show_buy_card);
    setPin(post.pin_on_brand);
    setEventStart(post.event_starts_at ?? "");
    setEventEnd(post.event_ends_at ?? "");
    setStatus(post.status);
    setTranslations(
      LOCALES.map(
        (loc) => post.translations.find((row) => row.locale === loc) ?? emptyTranslation(loc),
      ),
    );
  }, [postQ.data]);

  const current = translations.find((row) => row.locale === locale) ?? emptyTranslation(locale);

  function patchTranslation(patch: Partial<Translation>): void {
    setTranslations((rows) =>
      rows.map((row) => (row.locale === locale ? { ...row, ...patch } : row)),
    );
  }

  function body(): PostWriteBody | null {
    const rows = filled(translations);
    if (!brandId) {
      toast.error(T.form.needBrand);
      return null;
    }
    if (rows.length === 0) {
      toast.error(T.form.needTranslation);
      return null;
    }
    return {
      kind,
      primary_brand_id: brandId,
      show_buy_card: buyCard,
      pin_on_brand: pin,
      cover_image_url: cover.trim() || null,
      event_starts_at: kind === "event" && eventStart ? eventStart : null,
      event_ends_at: kind === "event" && eventEnd ? eventEnd : null,
      translations: rows,
    };
  }

  const save = useMutation({
    mutationFn: async () => {
      const payload = body();
      if (payload === null) throw new Error(T.form.needTranslation);
      if (isNew) {
        return apiPost<AdminPost>("/api/v1/admin/blog/posts", payload, idemHeaders());
      }
      return apiPatch<AdminPost>(`/api/v1/admin/blog/posts/${id}`, payload, idemHeaders());
    },
    onSuccess: (post) => {
      toast.success(T.form.saved);
      void qc.invalidateQueries({ queryKey: qk.blogPosts() });
      if (isNew) {
        void navigate(`/blog/${post.id}`, { replace: true });
      } else {
        void qc.invalidateQueries({ queryKey: qk.blogPost(post.id) });
      }
    },
    onError: (err) => toast.error(T.form.error.replace("{message}", extractApiMessage(err))),
  });

  const publish = useMutation({
    mutationFn: async () => {
      const saved = isNew || save.isPending ? await save.mutateAsync() : { id };
      return apiPost<AdminPost>(`/api/v1/admin/blog/posts/${saved.id}/publish`, {}, idemHeaders());
    },
    onSuccess: (post) => {
      toast.success(T.form.published);
      setStatus(post.status);
      void qc.invalidateQueries({ queryKey: qk.blogPosts() });
      void qc.invalidateQueries({ queryKey: qk.blogPost(post.id) });
    },
    onError: (err) => toast.error(T.form.error.replace("{message}", extractApiMessage(err))),
  });

  const archive = useMutation({
    mutationFn: () =>
      apiPost<AdminPost>(`/api/v1/admin/blog/posts/${id ?? ""}/archive`, {}, idemHeaders()),
    onSuccess: (post) => {
      toast.success(T.form.archived);
      setStatus(post.status);
      void qc.invalidateQueries({ queryKey: qk.blogPosts() });
    },
    onError: (err) => toast.error(T.form.error.replace("{message}", extractApiMessage(err))),
  });

  if (!isNew && postQ.isLoading) return <Spinner label="…" />;

  return (
    <div className="space-y-6">
      <PageHeader
        title={isNew ? T.form.newTitle : T.form.editTitle}
        breadcrumbs={[
          { label: T.list.title, to: "/blog" },
          { label: isNew ? T.form.newTitle : T.form.editTitle },
        ]}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => {
                save.mutate();
              }}
              disabled={save.isPending}
            >
              {T.form.save}
            </Button>
            <Button
              onClick={() => {
                publish.mutate();
              }}
              disabled={publish.isPending}
            >
              {T.form.publish}
            </Button>
            {!isNew && status !== "archived" ? (
              <Button
                variant="ghost"
                onClick={() => {
                  archive.mutate();
                }}
                disabled={archive.isPending}
              >
                {T.form.archive}
              </Button>
            ) : null}
          </div>
        }
      />

      <div className="grid gap-4 md:grid-cols-2">
        <Field label={T.form.kind}>
          {({ inputProps }) => (
            <Select
              {...inputProps}
              value={kind}
              onChange={(e) => {
                const next = KINDS.find((k) => k === e.target.value);
                if (next !== undefined) setKind(next);
              }}
            >
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {T.kind[k]}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={T.form.brand}>
          {({ inputProps }) => (
            <Select
              {...inputProps}
              value={brandId}
              onChange={(e) => {
                setBrandId(e.target.value);
              }}
            >
              <option value="">{T.form.needBrand}</option>
              {(brandsQ.data ?? []).map((b) => (
                <option key={b.id} value={b.id}>
                  {b.translations.find((t) => t.locale === "ru")?.name ?? b.slug}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={T.form.cover}>
          {({ inputProps }) => (
            <div id={inputProps.id}>
              <ImageUploader
                value={cover || null}
                onChange={(url) => {
                  setCover(url);
                }}
                kind="blog_image"
                hint={T.form.coverHint}
              />
            </div>
          )}
        </Field>
        <div className="flex items-end gap-4 pb-2">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={buyCard}
              onChange={(e) => {
                setBuyCard(e.target.checked);
              }}
            />
            {T.form.buyCard}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={pin}
              onChange={(e) => {
                setPin(e.target.checked);
              }}
            />
            {T.form.pin}
          </label>
        </div>
        {kind === "event" ? (
          <>
            <Field label={T.form.eventStart}>
              {({ inputProps }) => (
                <Input
                  {...inputProps}
                  type="datetime-local"
                  value={eventStart.slice(0, 16)}
                  onChange={(e) => {
                    setEventStart(e.target.value ? new Date(e.target.value).toISOString() : "");
                  }}
                />
              )}
            </Field>
            <Field label={T.form.eventEnd}>
              {({ inputProps }) => (
                <Input
                  {...inputProps}
                  type="datetime-local"
                  value={eventEnd.slice(0, 16)}
                  onChange={(e) => {
                    setEventEnd(e.target.value ? new Date(e.target.value).toISOString() : "");
                  }}
                />
              )}
            </Field>
          </>
        ) : null}
      </div>

      <PostLocaleFields
        locale={locale}
        current={current}
        onLocale={setLocale}
        onPatch={patchTranslation}
      />
    </div>
  );
}
