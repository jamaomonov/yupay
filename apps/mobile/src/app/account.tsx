import { LogOut } from "lucide-react-native";
import { ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Avatar } from "@/components/Avatar";
import { ListRow } from "@/components/ListRow";
import { TopBar } from "@/components/TopBar";
import { Card, T } from "@/components/ui";
import { accountName } from "@/lib/account";
import { useI18n } from "@/lib/i18n";
import { unregisterPush } from "@/lib/push";
import { useSession } from "@/lib/session";
import { useTheme } from "@/theme/ThemeProvider";
import { space } from "@/theme/tokens";

/** The account: name, how it signs in, its email; sign-out. */
export default function AccountScreen() {
  const { t } = useI18n();
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { user, signOut } = useSession();
  if (user == null) return null;
  const name = accountName(user);
  const email = user.delivery_email ?? user.email;

  return (
    <ScrollView
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={{
        paddingTop: insets.top + 4,
        paddingHorizontal: space.gutter,
        paddingBottom: 32,
        gap: 16,
      }}
    >
      <TopBar title={t("account.title")} fallback="/profile" />

      <View style={{ alignItems: "center", gap: 12, paddingVertical: 12 }}>
        <Avatar name={name} photoUrl={user.photo_url} size={84} />
        <T variant="title">{name}</T>
        {user.sign_in_with != null && <T tone="mute">{t(`profile.via.${user.sign_in_with}`)}</T>}
      </View>

      {email != null && (
        <Card style={{ padding: 16, gap: 4 }}>
          <T variant="label" tone="mute">
            {t("account.email")}
          </T>
          <T>{email}</T>
        </Card>
      )}

      <Card>
        <ListRow
          first
          Icon={LogOut}
          title={t("profile.signOut")}
          tone="danger"
          // The install stops getting this account's pushes before the session goes.
          onPress={() => void unregisterPush().then(signOut)}
        />
      </Card>
    </ScrollView>
  );
}
