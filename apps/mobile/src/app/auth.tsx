import { router } from "expo-router";
import { useEffect } from "react";

/**
 * Where the `/app-auth` page returns (`yupay://auth?…`). The sign-in screen reads the answer
 * from the browser session; on Android the link also opens this route, which only steps out
 * of the way.
 */
export default function AuthReturn() {
  useEffect(() => {
    if (router.canGoBack()) router.back();
    else router.replace("/profile");
  }, []);
  return null;
}
