import { ApiError } from "@yupay/api-client";
import * as WebBrowser from "expo-web-browser";
import { router } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Field } from "@/components/Field";
import { TopBar } from "@/components/TopBar";
import { Button, Card, T } from "@/components/ui";
import { api } from "@/lib/api";
import { isEmail, normaliseEmail } from "@/lib/checkout";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";
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

/** Email and password: sign in, or open an account and confirm it by email. */
export default function SignInScreen() {
  const { t, locale } = useI18n();
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { signIn } = useSession();

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
        if (router.canGoBack()) router.back();
        else router.replace("/profile");
      } else {
        await api.request(`/api/v1/auth/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: normaliseEmail(email), password, locale }),
        });
        setSentTo(normaliseEmail(email));
        setMode("signIn");
      }
    } catch (err) {
      setError(t(reason(err, mode)));
    } finally {
      setBusy(false);
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
        paddingTop: insets.top + 4,
        paddingHorizontal: space.gutter,
        paddingBottom: 32,
        gap: 16,
      }}
      keyboardShouldPersistTaps="handled"
    >
      <TopBar
        title={mode === "signIn" ? t("auth.title") : t("auth.registerTitle")}
        fallback="/profile"
      />

      {sentTo !== null && (
        <Card style={{ padding: 16 }}>
          <T>{t("auth.sent", { email: sentTo })}</T>
        </Card>
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
