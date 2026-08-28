import { setRequestLocale } from "next-intl/server";

export default async function LandingPage(props: { params: Promise<{ locale: string }> }) {
  const { locale } = await props.params;
  setRequestLocale(locale);
  return <main />;
}
