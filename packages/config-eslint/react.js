import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";

import base from "./index.js";

export default [
  ...base,
  {
    plugins: { react, "react-hooks": reactHooks },
    languageOptions: {
      globals: { window: "readonly", document: "readonly" },
    },
    settings: { react: { version: "detect" } },
    rules: {
      ...react.configs.recommended.rules,
      ...react.configs["jsx-runtime"].rules,
      ...reactHooks.configs.recommended.rules,
      "react/prop-types": "off",
    },
  },
];
