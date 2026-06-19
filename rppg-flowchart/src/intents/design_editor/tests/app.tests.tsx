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

  beforeEach(() => {
    jest.resetAllMocks();
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

  it("adds the system flowchart image to the current design", async () => {
    expect(mockUseFeatureSupport).not.toHaveBeenCalled();
    expect(addElementAtPoint).not.toHaveBeenCalled();

    const result = renderInTestProvider(<App />);

    expect(mockUseFeatureSupport).toHaveBeenCalled();
    expect(addElementAtPoint).not.toHaveBeenCalled();

    const insertButton = result.getByRole("button", {
      name: "插入流程圖到 Canva",
    });

    fireEvent.click(insertButton);

    await waitFor(() => expect(addElementAtPoint).toHaveBeenCalledTimes(1));
    expect(mockIsSupported).toHaveBeenCalledWith(addElementAtPoint);
    expect(mockIsSupported).toHaveBeenCalledWith(addElementAtCursor);
    expect(addElementAtPoint).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "image",
        dataUrl: expect.stringMatching(/^data:image\/png;base64,/),
        width: expect.any(Number),
        height: expect.any(Number),
      }),
    );
  });

  it("should have a consistent snapshot", () => {
    const result = renderInTestProvider(<App />);
    expect(result.container).toMatchSnapshot();
  });
});
