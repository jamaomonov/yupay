import { createRoot } from "react-dom/client";

import App from "./App";
import { bootstrapAuth } from "./lib/auth";
import "./index.css";

// Fire-and-forget: the app renders immediately with mocks / empty states, then
// re-renders once tokens land. We never block the splash on the network.
void bootstrapAuth();

createRoot(document.getElementById("root")!).render(<App />);
