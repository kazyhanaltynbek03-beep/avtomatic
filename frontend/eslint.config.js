import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import react from "eslint-plugin-react";

export default [
  { ignores: ["dist/**"] },
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ...js.configs.recommended.languageOptions,
      parserOptions: { ecmaVersion: "latest", sourceType: "module", ecmaFeatures: { jsx: true } },
      globals: { window: "readonly", document: "readonly", console: "readonly", navigator: "readonly", FormData: "readonly", fetch: "readonly", location: "readonly", URLSearchParams: "readonly", confirm: "readonly", setTimeout: "readonly", clearTimeout: "readonly", Worker: "readonly", Blob: "readonly", URL: "readonly", self: "readonly" },
    },
    plugins: { react, "react-hooks": reactHooks },
    settings: { react: { version: "detect" } },
    rules: {
      ...js.configs.recommended.rules,
      ...react.configs.recommended.rules,
      "react/prop-types": "off",
      "no-undef": "error",
      "react/react-in-jsx-scope": "off",
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
];
