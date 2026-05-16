import next from "@next/eslint-plugin-next";

import react from "./react.js";

export default [
  ...react,
  {
    plugins: { "@next/next": next },
    rules: {
      ...next.configs.recommended.rules,
      ...next.configs["core-web-vitals"].rules,
    },
  },
];
