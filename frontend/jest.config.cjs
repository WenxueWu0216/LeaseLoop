/** @type {import('jest').Config} */
module.exports = {
  testEnvironment: "jsdom",
  roots: ["<rootDir>/src"],
  setupFilesAfterEnv: ["<rootDir>/src/test/setup.ts"],
  transform: { "^.+\\.tsx?$": ["ts-jest", { tsconfig: "tsconfig.jest.json" }] },
  moduleNameMapper: { "\\.css$": "<rootDir>/src/test/styleStub.cjs" },
  collectCoverageFrom: ["src/**/*.{ts,tsx}", "!src/main.tsx", "!src/test/**"],
};
