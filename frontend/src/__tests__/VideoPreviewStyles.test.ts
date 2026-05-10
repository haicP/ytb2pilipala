import { describe, expect, test } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

describe("video preview styles", () => {
  test("does not override native webkit media controls panel background", () => {
    const css = readFileSync(resolve(__dirname, "../styles.css"), "utf-8");

    expect(css).not.toContain("::-webkit-media-controls-panel");
  });
});
