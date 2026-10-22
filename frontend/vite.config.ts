import { defineConfig } from 'vite';

export default defineConfig({
  envDir: false,
  build: {
    target: 'es2022',
    // The Python server allowlists the generated files and disables caching.
    rolldownOptions: {
      onwarn(warning, warn) {
        // React server directives have no effect in this browser-only application.
        if (warning.code === 'MODULE_LEVEL_DIRECTIVE' && warning.message.includes('use client')) return;
        warn(warning);
      },
      output: {
        entryFileNames: 'assets/app.js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/style[extname]',
      },
    },
  },
});
