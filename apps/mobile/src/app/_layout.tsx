import {
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
} from "@expo-google-fonts/inter";
import { Unbounded_600SemiBold } from "@expo-google-fonts/unbounded";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { Platform, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { setApiLocale } from "@/lib/api";
import { I18nProvider, useI18n } from "@/lib/i18n";
import { SessionProvider, useSession } from "@/lib/session";
import { Launch } from "@/components/Launch";
import { ThemeProvider, useTheme } from "@/theme/ThemeProvider";

void SplashScreen.preventAutoHideAsync();

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

/**
 * The app opens on sign-in: nothing but the sign-in screens is reachable without an account,
 * and signing out returns there. Until the stored session is restored, the launch screen.
 */
function Routes() {
  const { t } = useI18n();
  const { c, scheme } = useTheme();
  const { user, offline, retry } = useSession();
  if (user === undefined) {
    return (
      <>
        <StatusBar style="light" />
        <Launch
          {...(offline
            ? { offline: { text: t("common.loadError"), retry: t("common.retry"), onRetry: retry } }
            : {})}
        />
      </>
    );
  }
  const signedIn = user !== null;
  return (
    <>
      <StatusBar style={scheme === "dark" ? "light" : "dark"} />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: c.bg } }}>
        <Stack.Protected guard={signedIn}>
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="brand/[slug]" />
          <Stack.Screen name="checkout" />
          <Stack.Screen name="order/[id]" />
          <Stack.Screen name="account" />
          <Stack.Screen name="promo" />
          <Stack.Screen
            name="choose"
            options={{
              presentation: "formSheet",
              sheetAllowedDetents: "fitToContents",
              sheetGrabberVisible: true,
              sheetCornerRadius: 24,
            }}
          />
        </Stack.Protected>
        <Stack.Protected guard={!signedIn}>
          <Stack.Screen name="sign-in" />
        </Stack.Protected>
      </Stack>
    </>
  );
}

function Shell() {
  const { c } = useTheme();
  const { locale } = useI18n();
  setApiLocale(locale);

  return (
    // The web preview is shown at phone width; on a device the view fills the screen.
    <View style={{ flex: 1, backgroundColor: Platform.OS === "web" ? c.muted : c.bg }}>
      <View
        style={{
          flex: 1,
          width: "100%",
          maxWidth: Platform.OS === "web" ? 430 : undefined,
          alignSelf: "center",
          backgroundColor: c.bg,
        }}
      >
        <Routes />
      </View>
    </View>
  );
}

export default function RootLayout() {
  const [loaded] = useFonts({
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
    Unbounded_600SemiBold,
  });

  useEffect(() => {
    if (loaded) void SplashScreen.hideAsync();
  }, [loaded]);

  if (!loaded) return null;

  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <I18nProvider>
            <SessionProvider>
              <Shell />
            </SessionProvider>
          </I18nProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
