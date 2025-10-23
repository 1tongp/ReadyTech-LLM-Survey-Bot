module.exports = {
  root: true,
  env: { browser: true, es2021: true, node: true, jest: true },
  settings: { react: { version: 'detect' } },
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module', ecmaFeatures: { jsx: true } },
  extends: [
    'eslint:recommended',
    'plugin:react/recommended',
    'plugin:react-hooks/recommended',
    'plugin:import/recommended',
    'plugin:jsx-a11y/recommended',
    'prettier',
  ],
  plugins: ['react', 'react-hooks', 'import', 'jsx-a11y'],
  rules: {
    'react/prop-types': 'off',
    'no-console': ['warn', { allow: ['warn', 'error'] }],
    'import/order': [
      'warn',
      { 'newlines-between': 'always', alphabetize: { order: 'asc', caseInsensitive: true } },
    ],
  },
  ignorePatterns: ['dist', 'build', 'coverage', 'node_modules', 'vite.config.*', '**/*.config.*'],
}
