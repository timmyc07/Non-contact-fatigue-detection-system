import { useFeatureSupport } from "@canva/app-hooks";
import { Button, ImageCard, Rows, Text } from "@canva/app-ui-kit";
import {
  addElementAtCursor,
  addElementAtPoint,
  getDesignMetadata,
} from "@canva/design";
import type { ImageElement, ImageElementAtPoint } from "@canva/design";
import { useState } from "react";
import { FormattedMessage, useIntl } from "react-intl";
// eslint-disable-next-line no-restricted-imports
import flowchartImage from "src/assets/system_flowchart_canva_preview.png";
import * as styles from "styles/components.css";

const FLOWCHART_ASPECT_RATIO = 1800 / 1120;
const FALLBACK_PAGE_WIDTH = 1280;
const FALLBACK_PAGE_HEIGHT = 720;

export const App = () => {
  const intl = useIntl();
  const isSupported = useFeatureSupport();
  const canAddAtPoint = isSupported(addElementAtPoint);
  const canAddAtCursor = isSupported(addElementAtCursor);
  const canInsert = canAddAtPoint || canAddAtCursor;
  const [status, setStatus] = useState<"idle" | "busy" | "done" | "error">(
    "idle",
  );

  const imageAltText = intl.formatMessage({
    defaultMessage:
      "結合影像辨識與生理感測之疲勞偵測系統流程圖，包含影像輸入、臉部推論、行為疲勞分析、rPPG 生理訊號分析、品質評估、融合評分與輸出應用。",
    description: "Accessible description for the system flowchart preview.",
  });

  const insertButtonLabel = intl.formatMessage({
    defaultMessage: "插入流程圖到 Canva",
    description: "Primary button label for inserting the system flowchart.",
  });

  const busyButtonLabel = intl.formatMessage({
    defaultMessage: "插入中...",
    description: "Button label shown while inserting the system flowchart.",
  });

  const unsupportedTooltip = intl.formatMessage({
    defaultMessage: "目前 Canva 頁面不支援插入圖片元素",
    description: "Tooltip shown when inserting images is not supported.",
  });

  const insertTooltip = intl.formatMessage({
    defaultMessage: "將流程圖插入目前設計頁面",
    description: "Tooltip shown on the insert button.",
  });

  const insertFlowchart = async () => {
    if (!canInsert) {
      return;
    }

    setStatus("busy");

    try {
      if (canAddAtPoint) {
        const metadata = await getDesignMetadata();
        const pageWidth =
          metadata.defaultPageDimensions?.width ?? FALLBACK_PAGE_WIDTH;
        const pageHeight =
          metadata.defaultPageDimensions?.height ?? FALLBACK_PAGE_HEIGHT;
        const maxWidth = pageWidth * 0.9;
        const maxHeight = pageHeight * 0.82;
        const width = Math.min(maxWidth, maxHeight * FLOWCHART_ASPECT_RATIO);
        const height = width / FLOWCHART_ASPECT_RATIO;

        const imageElement: ImageElementAtPoint = {
          type: "image",
          dataUrl: flowchartImage,
          altText: { text: imageAltText, decorative: false },
          top: Math.max(0, (pageHeight - height) / 2),
          left: Math.max(0, (pageWidth - width) / 2),
          width,
          height,
        };

        await addElementAtPoint(imageElement);
      } else {
        const imageElement: ImageElement = {
          type: "image",
          dataUrl: flowchartImage,
          altText: { text: imageAltText, decorative: false },
        };

        await addElementAtCursor(imageElement);
      }

      setStatus("done");
    } catch {
      setStatus("error");
    }
  };

  return (
    <div className={styles.scrollContainer}>
      <Rows spacing="2u">
        <div className={styles.header}>
          <Text variant="bold">
            <FormattedMessage
              defaultMessage="系統流程圖設計"
              description="Heading for the Canva flowchart app."
            />
          </Text>
          <Text tone="tertiary" size="small">
            <FormattedMessage
              defaultMessage="影像辨識、rPPG 生理訊號、品質評估與疲勞融合評分"
              description="Subtitle for the Canva flowchart app."
            />
          </Text>
        </div>

        <div className={styles.previewFrame}>
          <ImageCard
            thumbnailUrl={flowchartImage}
            alt={imageAltText}
            borderRadius="standard"
            thumbnailAspectRatio={FLOWCHART_ASPECT_RATIO}
            thumbnailHeight={180}
            thumbnailBackground="secondary"
          />
        </div>

        <Button
          variant="primary"
          onClick={insertFlowchart}
          disabled={!canInsert || status === "busy"}
          tooltipLabel={!canInsert ? unsupportedTooltip : insertTooltip}
          stretch
        >
          {status === "busy" ? busyButtonLabel : insertButtonLabel}
        </Button>

        {status === "done" && (
          <Text tone="tertiary" size="small">
            <FormattedMessage
              defaultMessage="已插入目前 Canva 設計頁面。"
              description="Success message shown after inserting the flowchart."
            />
          </Text>
        )}

        {status === "error" && (
          <Text tone="critical" size="small">
            <FormattedMessage
              defaultMessage="插入失敗，請重新開啟 App 預覽後再試一次。"
              description="Error message shown when inserting the flowchart fails."
            />
          </Text>
        )}

        <div className={styles.summaryCard}>
          <Text variant="bold" size="small">
            <FormattedMessage
              defaultMessage="流程圖區塊"
              description="Summary heading for the flowchart blocks."
            />
          </Text>
          <Text size="small" tone="tertiary">
            <FormattedMessage
              defaultMessage="一般攝影機輸入、共用臉部推論、行為疲勞分析、rPPG 生理訊號估測、品質守門、融合評分、即時告警、記錄、Web 與回放。"
              description="Summary text describing flowchart blocks."
            />
          </Text>
        </div>
      </Rows>
    </div>
  );
};
