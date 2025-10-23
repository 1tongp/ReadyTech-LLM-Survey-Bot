import js from '@eslint/js'
import globals from 'globals'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import importPlugin from 'eslint-plugin-import'
import prettier from 'eslint-config-prettier'

export default [
    { ignores: ['dist', 'build', 'coverage', 'node_modules', 'vite.config.*', '**/*.config.*'] },
    js.configs.recommended,
    {
        files: ['src/**/*.{js,jsx}'],
        languageOptions: {
            ecmaVersion: 'latest',
            sourceType: 'module',
            parserOptions: { ecmaFeatures: { jsx: true } },
            globals: { ...globals.browser, ...globals.node },
        },
        plugins: { react, 'react-hooks': reactHooks, import: importPlugin, 'jsx-a11y': jsxA11y },
        settings: {
            react: { version: 'detect', jsxRuntime: 'automatic' }, // 现代 JSX 运行时
        },
        rules: {
            // 关键：告诉 ESLint “JSX 里用到的变量算已使用”
            'react/jsx-uses-vars': 'warn',
            'react/jsx-uses-react': 'off', // React 17+ 可关，开着也不影响

            'react/prop-types': 'off',
            'no-console': ['warn', { allow: ['warn', 'error'] }],
            'import/order': [
                'warn',
                { 'newlines-between': 'always', alphabetize: { order: 'asc', caseInsensitive: true } },
            ],
        },
    },
    prettier,
]
