import { describe, expect, it } from "vitest";

import { ApiError } from "./client";

describe("ApiError", () => {
  it("flattens DRF validation errors and hides the raw compatibility report", () => {
    const err = new ApiError(400, {
      name: ["You already have a build with this name."],
      items: ["Socket mismatch."],
      compatibility: { errors: [] },
    });
    expect(err.message).toBe("name: You already have a build with this name.\nitems: Socket mismatch.");
  });

  it("uses detail as-is", () => {
    expect(new ApiError(404, { detail: "Not found." }).message).toBe("Not found.");
  });
});
