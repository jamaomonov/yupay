import js from "@eslint/js";
import tseslint from "typescript-eslint";
import prettier from "eslint-config-prettier";
import importPlugin from "eslint-plugin-import";

export default tseslint.config(
  {
    ignores: [
      "**/dist/**",
      "**/.next/**",
      "**/.turbo/**",
      "**/node_modules/**",
      "**/coverage/**",
      "**/generated/**",
      // Config files live outside tsconfig's include and aren't worth typechecking.
      "**/eslint.config.{js,mjs,cjs}",
      "**/vitest.config.{ts,js,mjs}",
      "**/playwright.config.{ts,js}",
      "**/next.config.{ts,js,mjs}",
      "**/postcss.config.{ts,js,mjs}",
      "**/tailwind.config.{ts,js,mjs}",
      "**/*.config.{ts,js,mjs}",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,
  {
    plugins: { import: importPlugin },
    languageOptions: {
      parserOptions: {
        projectService: {
          allowDefaultProject: ["*.config.*", "eslint.config.*"],
        },
        tsconfigRootDir: process.cwd(),
      },
    },
    rules: {
      "no-console": ["warn", { allow: ["warn", "error"] }],
      "no-debugger": "error",
      "@typescript-eslint/consistent-type-imports": [
        "error",
        { prefer: "type-imports", fixStyle: "inline-type-imports" },
      ],
      "@typescript-eslint/no-misused-promises": [
        "error",
        { checksVoidReturn: false },
      ],
      "@typescript-eslint/switch-exhaustiveness-check": "error",
      "@typescript-eslint/no-explicit-any": "error",
      "import/order": [
        "warn",
        {
          groups: [
            "builtin",
            "external",
            "internal",
            ["parent", "sibling", "index"],
            "type",
          ],
          "newlines-between": "always",
          alphabetize: { order: "asc", caseInsensitive: true },
        },
      ],
    },
  },
  prettier,
);
