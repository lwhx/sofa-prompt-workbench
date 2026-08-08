import eslint from '@eslint/js'
import tseslint from 'typescript-eslint'
import vue from 'eslint-plugin-vue'
import vueParser from 'vue-eslint-parser'

export default tseslint.config(
  { ignores: ['dist', 'coverage'] },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  ...vue.configs['flat/recommended'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parser: vueParser,
      parserOptions: { parser: tseslint.parser, extraFileExtensions: ['.vue'], sourceType: 'module' },
    },
  },
  {
    languageOptions: {
      globals: { window: 'readonly', document: 'readonly', Event: 'readonly', HTMLInputElement: 'readonly', Notification: 'readonly', globalThis: 'readonly' },
    },
    rules: { 'vue/multi-word-component-names': 'off' },
  },
)

