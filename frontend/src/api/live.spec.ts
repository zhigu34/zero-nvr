import { describe, expect, it } from "vitest"

import { cameraLivePreviewUrl } from "./live"


describe("cameraLivePreviewUrl", () => {
  it("encodes the camera, session, and bounded preview shape", () => {
    expect(
      cameraLivePreviewUrl(
        "camera/one",
        "session two",
        640,
        5
      )
    ).toBe(
      "/api/v1/cameras/camera%2Fone/live/preview.mjpeg" +
      "?media_session_id=session+two&width=640&fps=5"
    )
  })
})
