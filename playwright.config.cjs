const { defineConfig } = require("@playwright/test");
module.exports = defineConfig({
  testDir: "./tests/browser",
  timeout: 120000,
  workers: 1,
  use: {
    baseURL: process.env.STEMLAB_TEST_URL || "http://127.0.0.1:8765",
    headless: true,
  },
});
