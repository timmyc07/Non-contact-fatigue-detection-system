import { useFeatureSupport } from "@canva/app-hooks";
import { TestAppI18nProvider } from "@canva/app-i18n-kit";
import { TestAppUiProvider } from "@canva/app-ui-kit";
import {
  addElementAtCursor,
  addElementAtPoint,
  getDesignMetadata,
} from "@canva/design";
import type { Feature } from "@canva/platform";
import { fireEvent, render, waitFor } from "@testing-library/react";
import type { RenderResult } from "@testing-library/react";
import type { ReactNode } from "react";
import { App } from "../app";

function renderInTestProvider(node: ReactNode): RenderResult {
  return render(
    <TestAppI18nProvider>
      <TestAppUiProvider>{node}</TestAppUiProvider>
    </TestAppI18nProvider>,
  );
}

jest.mock("@canva/app-hooks");

describe("System flowchart Canva app", () => {
  const mockIsSupported = jest.fn();
  const mockUseFeatureSupport = jest.mocked(useFeatureSupport);
  const mockGetDesignMetadata = jest.mocked(getDesignMetadata);
  let imageWidth: number;
  let imageHeight: number;
  let decodeFails: boolean;

  beforeEach(() => {
    jest.resetAllMocks();
    imageWidth = 1800;
    imageHeight = 1280;
    decodeFails = false;
    jest.spyOn(window, "Image").mockImplementation(() => {
      const image = document.createElement("img");
      Object.defineProperties(image, {
        naturalWidth: { get: () => imageWidth },
        naturalHeight: { get: () => imageHeight },
        src: {
          set: () => {
            queueMicrotask(() =>
              image.dispatchEvent(new Event(decodeFails ? "error" : "load")),
            );
          },
        },
      });
      return image;
    });
    mockIsSupported.mockImplementation(
      (fn: Feature) => fn === addElementAtPoint,
    );
    mockUseFeatureSupport.mockReturnValue(mockIsSupported);
    mockGetDesignMetadata.mockResolvedValue({
      defaultPageDimensions: {
        width: 1280,
        height: 720,
      },
      pageMetadata: [],
      durationInSeconds: 0,
    });
  });

  afterEach(() => jest.restoreAllMocks());

  const chooseImage = (result: RenderResult, type = "image/png") => {
    const input = result.container.querySelector('input[type="file"]');
    if (!input) {
      throw new Error("Local file input is missing");
    }
    fireEvent.change(input, {
      target: { files: [new File(["local image"], "flowchart", { type })] },
    });
  };

  const insertButton = (result: RenderResult) =>
    result.getByRole("button", {
      name: "插入流程圖到 Canva",
    });

  it("requires a local image before insertion", () => {
    const result = renderInTestProvider(<App />);

    expect(insertButton(result).getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(insertButton(result));
    expect(addElementAtPoint).not.toHaveBeenCalled();
    expect(addElementAtCursor).not.toHaveBeenCalled();
    expect(result.getByText(/請先選擇本機圖片/)).toBeTruthy();
  });

  it("inserts a selected local image using its actual aspect ratio", async () => {
    imageWidth = 900;
    imageHeight = 1200;
    const result = renderInTestProvider(<App />);
    chooseImage(result);
    await waitFor(() =>
      expect(insertButton(result).getAttribute("aria-disabled")).not.toBe(
        "true",
      ),
    );
    expect(addElementAtPoint).not.toHaveBeenCalled();
    fireEvent.click(insertButton(result));

    await waitFor(() => expect(addElementAtPoint).toHaveBeenCalledTimes(1));
    expect(mockIsSupported).toHaveBeenCalledWith(addElementAtPoint);
    expect(mockIsSupported).toHaveBeenCalledWith(addElementAtCursor);
    expect(addElementAtPoint).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "image",
        dataUrl: expect.stringMatching(/^data:image\/png;base64,/),
        width: expect.closeTo(442.8),
        height: expect.closeTo(590.4),
        left: expect.closeTo(418.6),
        top: expect.closeTo(64.8),
      }),
    );
  });

  it("supports JPEG insertion at the cursor", async () => {
    mockIsSupported.mockImplementation(
      (fn: Feature) => fn === addElementAtCursor,
    );
    const result = renderInTestProvider(<App />);
    chooseImage(result, "image/jpeg");
    await waitFor(() =>
      expect(insertButton(result).getAttribute("aria-disabled")).not.toBe(
        "true",
      ),
    );
    fireEvent.click(insertButton(result));

    await waitFor(() => expect(addElementAtCursor).toHaveBeenCalledTimes(1));
    expect(addElementAtCursor).toHaveBeenCalledWith(
      expect.objectContaining({
        dataUrl: expect.stringMatching(/^data:image\/jpeg;base64,/),
      }),
    );
    expect(addElementAtPoint).not.toHaveBeenCalled();
    expect(getDesignMetadata).not.toHaveBeenCalled();
  });

  it("keeps insertion disabled when Canva does not support images", async () => {
    mockIsSupported.mockReturnValue(false);
    const result = renderInTestProvider(<App />);
    chooseImage(result);
    await waitFor(() => expect(result.queryByRole("status")).toBeNull());

    expect(insertButton(result).getAttribute("aria-disabled")).toBe("true");
    expect(addElementAtPoint).not.toHaveBeenCalled();
    expect(addElementAtCursor).not.toHaveBeenCalled();
  });

  it("rejects unsupported files without reading or uploading them", () => {
    const read = jest.spyOn(FileReader.prototype, "readAsDataURL");
    const result = renderInTestProvider(<App />);
    chooseImage(result, "image/svg+xml");

    expect(result.getByRole("alert").textContent).toContain(
      "有效的 PNG 或 JPEG",
    );
    expect(insertButton(result).getAttribute("aria-disabled")).toBe("true");
    expect(read).not.toHaveBeenCalled();
    expect(addElementAtPoint).not.toHaveBeenCalled();
  });

  it("reports image decoding failures and keeps insertion disabled", async () => {
    decodeFails = true;
    const result = renderInTestProvider(<App />);
    chooseImage(result);

    await waitFor(() => expect(result.getByRole("alert")).toBeTruthy());
    expect(insertButton(result).getAttribute("aria-disabled")).toBe("true");
    expect(addElementAtPoint).not.toHaveBeenCalled();
  });

  it("reports local file reading failures", () => {
    jest
      .spyOn(FileReader.prototype, "readAsDataURL")
      .mockImplementation(function (this: FileReader) {
        this.dispatchEvent(new Event("error"));
      });
    const result = renderInTestProvider(<App />);
    chooseImage(result);

    expect(result.getByRole("alert")).toBeTruthy();
    expect(insertButton(result).getAttribute("aria-disabled")).toBe("true");
  });

  it("preserves the Canva insertion error message", async () => {
    jest
      .mocked(addElementAtPoint)
      .mockRejectedValue(new Error("Canva unavailable"));
    const result = renderInTestProvider(<App />);
    chooseImage(result);
    await waitFor(() =>
      expect(insertButton(result).getAttribute("aria-disabled")).not.toBe(
        "true",
      ),
    );
    fireEvent.click(insertButton(result));

    await waitFor(() => expect(result.getByText(/插入失敗/)).toBeTruthy());
  });

  it("should have a consistent snapshot", () => {
    const result = renderInTestProvider(<App />);
    expect(result.container).toMatchSnapshot();
  });
});
