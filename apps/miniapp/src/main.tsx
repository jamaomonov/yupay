import { createRoot } from "react-dom/client";

import App from "./App";
// Self-hosted, and that is the point: this used to be a `<link>` to
// fonts.googleapis.com in `index.html`, which blocks rendering. A network that
// cannot reach Google fast did not get a slow page, it got no page — inside
// Telegram, «Не удалось загрузить YuPay». Bundled here, the font travels with
// the app from our own origin and can no longer stop it from starting.
// Variable weights cover the 400-700 range `index.css` asks for in one file.
import "@fontsource-variable/rubik";
import "./index.css";

// Auth + prefetch are owned by ``BootstrapGate`` (inside <App />) so we can
// surface progress and retry on failure instead of fire-and-forget.
createRoot(document.getElementById("root")!).render(<App />);
