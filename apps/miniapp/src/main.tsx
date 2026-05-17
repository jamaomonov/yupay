import { createRoot } from "react-dom/client";

import App from "./App";
import "./index.css";

// Auth + prefetch are owned by ``BootstrapGate`` (inside <App />) so we can
// surface progress and retry on failure instead of fire-and-forget.
createRoot(document.getElementById("root")!).render(<App />);
