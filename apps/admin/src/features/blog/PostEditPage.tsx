import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { FaqEditor } from "./FaqEditor";
import { eventPhase, otherPublishedPins, packFaqs, type FaqDraft } from "./form";
import { PostLocaleFields } from "./PostLocaleFields";
import { PostMetaFields } from "./PostMetaFields";
import {
  idemHeaders,
  LOCALES,
  T,
  type AdminPost,
  type AdminPostList,
  type Locale,
  type PostKind,
  type PostWriteBody,
  type Translation,
} from "./types";

import type { Brand } from "@/features/catalog/types";

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
  const [scheduleAt, setScheduleAt] = useState("");
  const [locale, setLocale] = useState<Locale>("ru");
  const [translations, setTranslations] = useState<Translation[]>(
    LOCALES.map((loc) => emptyTranslation(loc)),
  );
  const [faqs, setFaqs] = useState<FaqDraft[]>([]);
  const [status, setStatus] = useState<AdminPost["status"]>("draft");

  const brandsQ = useQuery({
    queryKey: qk.brands(),
    queryFn: () => apiGet<Brand[]>("/api/v1/admin/catalog/brands"),
  });
  const listQ = useQuery({
    queryKey: qk.blogPosts(),
    queryFn: () => apiGet<AdminPostList>("/api/v1/admin/blog/posts"),
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
    setScheduleAt(post.scheduled_for ?? "");
    setStatus(post.status);
    setFaqs(post.faqs);
    setTranslations(
      LOCALES.map(
        (loc) => post.translations.find((row) => row.locale === loc) ?? emptyTranslation(loc),
      ),
    );
  }, [postQ.data]);

  const current = translations.find((row) => row.locale === locale) ?? emptyTranslation(locale);
  const otherPins = otherPublishedPins(listQ.data?.items ?? [], brandId, isNew ? undefined : id);

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
    if (kind === "event") {
      const phase = eventPhase(eventStart, eventEnd);
      if (phase === "missing" || phase === "invalid") {
        toast.error(T.form.eventNeedWindow);
        return null;
      }
    }
    const packed = packFaqs(faqs);
    if (packed === "incomplete") {
      toast.error(T.form.faqIncomplete);
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
      faqs: packed,
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
      const saved = await save.mutateAsync();
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

  const schedule = useMutation({
    mutationFn: async () => {
      if (!scheduleAt || Date.parse(scheduleAt) <= Date.now()) {
        throw new Error(T.form.needSchedule);
      }
      const saved = await save.mutateAsync();
      return apiPost<AdminPost>(
        `/api/v1/admin/blog/posts/${saved.id}/schedule`,
        { scheduled_for: scheduleAt },
        idemHeaders(),
      );
    },
    onSuccess: (post) => {
      toast.success(T.form.scheduled);
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

  const canSchedule = status === "draft" || status === "scheduled";

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
            {canSchedule ? (
              <Button
                variant="ghost"
                onClick={() => {
                  schedule.mutate();
                }}
                disabled={schedule.isPending}
              >
                {T.form.schedule}
              </Button>
            ) : null}
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

      <PostMetaFields
        kind={kind}
        brandId={brandId}
        cover={cover}
        buyCard={buyCard}
        pin={pin}
        otherPins={otherPins}
        eventStart={eventStart}
        eventEnd={eventEnd}
        scheduleAt={scheduleAt}
        canSchedule={canSchedule}
        brands={brandsQ.data ?? []}
        onKind={setKind}
        onBrandId={setBrandId}
        onCover={setCover}
        onBuyCard={setBuyCard}
        onPin={setPin}
        onEventStart={setEventStart}
        onEventEnd={setEventEnd}
        onScheduleAt={setScheduleAt}
      />

      <PostLocaleFields
        locale={locale}
        current={current}
        onLocale={setLocale}
        onPatch={patchTranslation}
      />
      <FaqEditor locale={locale} items={faqs} onChange={setFaqs} />
    </div>
  );
}
