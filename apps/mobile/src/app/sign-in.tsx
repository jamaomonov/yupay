import { ApiError } from "@yupay/api-client";
import * as WebBrowser from "expo-web-browser";
import { useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { SocialButtons } from "@/components/auth/SocialButtons";
import { Field } from "@/components/Field";
import { Logo } from "@/components/Logo";
import { Button, Card, T } from "@/components/ui";
import { isEmail, normaliseEmail } from "@/lib/checkout";
import { useI18n } from "@/lib/i18n";
import { register, SocialSignInError, useSession } from "@/lib/session";
import type { Provider } from "@/lib/social-state";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

const WEB_URL = process.env.EXPO_PUBLIC_WEB_URL ?? "https://yupay.uz";
const MIN_PASSWORD = 8;

type Mode = "signIn" | "register";

/** Why a request failed, in the buyer's words. */
function reason(err: unknown, mode: Mode): string {
  if (!(err instanceof ApiError)) return "auth.error";
  if (err.status === 429) return "auth.tooMany";
  if (mode === "register" && err.status === 409) return "auth.exists";
  if (err.status === 403) return "auth.unverified";
  if (err.status === 401) return "auth.wrong";
  return "auth.error";
}

/**
 * The app's front door: nothing else opens without an account. Telegram and Google first,
 * email and password under them, or a new account confirmed by email. Once signed in, the
 * protected routes take over (`app/_layout.tsx`); nothing here navigates.
 */
export default function SignInScreen() {
  const { t, locale } = useI18n();
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { signIn, signInWith } = useSession();
  const [social, setSocial] = useState<Provider | null>(null);

  const [mode, setMode] = useState<Mode>("signIn");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  const emailBad = email !== "" && !isEmail(email);
  const ready =
    isEmail(email) && (mode === "signIn" ? password !== "" : password.length >= MIN_PASSWORD);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      if (mode === "signIn") {
        await signIn(email, password);
      } else {
        await register(email, password, locale);
        setSentTo(normaliseEmail(email));
        setMode("signIn");
      }
    } catch (err) {
      setError(t(reason(err, mode)));
    } finally {
      setBusy(false);
    }
  };

  const withProvider = async (provider: Provider) => {
    setSocial(provider);
    setError(null);
    try {
      await signInWith(provider, locale);
    } catch (err) {
      setError(
        err instanceof SocialSignInError || err instanceof ApiError
          ? t("auth.socialFailed")
          : t("auth.error"),
      );
    } finally {
      setSocial(null);
    }
  };

  const switchMode = () => {
    setMode(mode === "signIn" ? "register" : "signIn");
    setError(null);
  };

  const forgot = () => {
    const prefix = locale === "ru" ? "" : `/${locale}`;
    void WebBrowser.openBrowserAsync(`${WEB_URL}${prefix}/auth/forgot`);
  };

  return (
    <ScrollView
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={{
        paddingTop: insets.top + 8,
        paddingHorizontal: space.gutter,
        paddingBottom: 32,
        gap: 16,
      }}
      keyboardShouldPersistTaps="handled"
    >
      <View style={{ paddingTop: 28, paddingBottom: 8, gap: 18 }}>
        <Logo />
        <View style={{ gap: 6 }}>
          <T variant="display">{mode === "signIn" ? t("auth.title") : t("auth.registerTitle")}</T>
          <T tone="mute">{t("auth.lead")}</T>
        </View>
      </View>

      {sentTo !== null && (
        <Card style={{ padding: 16 }}>
          <T>{t("auth.sent", { email: sentTo })}</T>
        </Card>
      )}

      {mode === "signIn" && (
        <>
          <SocialButtons
            label={(name) => t("auth.with", { name })}
            busy={social}
            onPress={(provider) => void withProvider(provider)}
          />
          <View style={{ flexDirection: "row", alignItems: "center", gap: 10, marginVertical: 2 }}>
            <View style={{ flex: 1, height: 1, backgroundColor: c.border }} />
            <T variant="small" tone="dim">
              {t("auth.or")}
            </T>
            <View style={{ flex: 1, height: 1, backgroundColor: c.border }} />
          </View>
        </>
      )}

      <Field
        label={t("auth.email")}
        value={email}
        onChange={setEmail}
        placeholder="name@mail.uz"
        autoComplete="email"
        keyboardType="email-address"
        textContentType="emailAddress"
        error={emailBad}
        {...(emailBad ? { hint: t("checkout.badEmail") } : {})}
      />
      <Field
        label={t("auth.password")}
        value={password}
        onChange={setPassword}
        secureTextEntry
        autoComplete={mode === "signIn" ? "current-password" : "new-password"}
        textContentType={mode === "signIn" ? "password" : "newPassword"}
        {...(mode === "register" ? { hint: t("auth.passwordHint") } : {})}
      />

      {error !== null && <T tone="danger">{error}</T>}

      <Button
        label={mode === "signIn" ? t("auth.signIn") : t("auth.register")}
        disabled={!ready}
        loading={busy}
        onPress={() => void submit()}
      />

      <View style={{ alignItems: "center", gap: 14, marginTop: 4 }}>
        {mode === "signIn" && (
          <Pressable onPress={forgot} hitSlop={8}>
            <T tone="accent">{t("auth.forgot")}</T>
          </Pressable>
        )}
        <Pressable onPress={switchMode} hitSlop={8}>
          <T tone="mute">
            {mode === "signIn" ? t("auth.noAccount") : t("auth.haveAccount")}{" "}
            <T tone="accent">{mode === "signIn" ? t("auth.register") : t("auth.signIn")}</T>
          </T>
        </Pressable>
      </View>
    </ScrollView>
  );
}
