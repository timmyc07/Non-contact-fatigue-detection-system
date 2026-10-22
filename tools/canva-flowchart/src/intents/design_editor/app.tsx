import { useFeatureSupport } from "@canva/app-hooks";
import { Button, FileInput, ImageCard, Rows, Text } from "@canva/app-ui-kit";
import {
  addElementAtCursor,
  addElementAtPoint,
  getDesignMetadata,
} from "@canva/design";
import type { ImageElement, ImageElementAtPoint } from "@canva/design";
import { useState } from "react";
import { FormattedMessage, useIntl } from "react-intl";
import * as styles from "styles/components.css";

const FALLBACK_PAGE_WIDTH = 1280;
const FALLBACK_PAGE_HEIGHT = 720;

export const App = () => {
  const intl = useIntl();
  const isSupported = useFeatureSupport();
  const canAddAtPoint = isSupported(addElementAtPoint);
  const canAddAtCursor = isSupported(addElementAtCursor);
  const canInsert = canAddAtPoint || canAddAtCursor;
  const [status, setStatus] = useState<
    "idle" | "reading" | "invalid" | "busy" | "done" | "error"
  >("idle");
  const [image, setImage] = useState<{
    dataUrl: string;
    aspectRatio: number;
  } | null>(null);

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

  const readImage = (file: File | undefined) => {
    if (!file) {
      return;
    }
    setImage(null);
    if (file.type !== "image/png" && file.type !== "image/jpeg") {
      setStatus("invalid");
      return;
    }
    setStatus("reading");
    const reader = new FileReader();
    reader.onerror = reader.onabort = () => setStatus("invalid");
    reader.onload = () => {
      const dataUrl = reader.result;
      if (typeof dataUrl !== "string") {
        setStatus("invalid");
        return;
      }
      const preview = new Image();
      preview.onerror = () => setStatus("invalid");
      preview.onload = () => {
        if (preview.naturalWidth <= 0 || preview.naturalHeight <= 0) {
          setStatus("invalid");
          return;
        }
        setImage({
          dataUrl,
          aspectRatio: preview.naturalWidth / preview.naturalHeight,
        });
        setStatus("idle");
      };
      preview.src = dataUrl;
    };
    reader.readAsDataURL(file);
  };

  const insertFlowchart = async () => {
    if (!canInsert || !image || status === "busy") {
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
        const width = Math.min(maxWidth, maxHeight * image.aspectRatio);
        const height = width / image.aspectRatio;

        const imageElement: ImageElementAtPoint = {
          type: "image",
          dataUrl: image.dataUrl,
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
          dataUrl: image.dataUrl,
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

        <div className={styles.filePicker}>
          <label htmlFor="flowchart-file">
            <FormattedMessage
              defaultMessage="選擇本機流程圖（PNG 或 JPEG）"
              description="Label for the local flowchart image file picker."
            />
          </label>
          <FileInput
            id="flowchart-file"
            accept={["image/png", "image/jpeg"]}
            disabled={status === "reading" || status === "busy"}
            onDropAcceptedFiles={(files) => readImage(files[0])}
            onDropRejectedFiles={() => {
              setImage(null);
              setStatus("invalid");
            }}
            stretchButton
          />
          <Text tone="tertiary" size="small">
            <FormattedMessage
              defaultMessage="請先選擇本機圖片。圖片只在本機預覽，按下插入後才會加入 Canva。"
              description="Help text explaining the local image preview and insertion."
            />
          </Text>
        </div>

        {image && (
          <div className={styles.previewFrame}>
            <ImageCard
              thumbnailUrl={image.dataUrl}
              alt={imageAltText}
              borderRadius="standard"
              thumbnailAspectRatio={image.aspectRatio}
              thumbnailHeight={180}
              thumbnailBackground="secondary"
            />
          </div>
        )}

        <Button
          variant="primary"
          onClick={insertFlowchart}
          disabled={!canInsert || !image || status === "busy"}
          tooltipLabel={!canInsert ? unsupportedTooltip : insertTooltip}
          stretch
        >
          {status === "busy" ? busyButtonLabel : insertButtonLabel}
        </Button>

        {status === "reading" && (
          <div role="status">
            <Text tone="tertiary" size="small">
              <FormattedMessage
                defaultMessage="正在讀取本機圖片…"
                description="Status message while reading a local image."
              />
            </Text>
          </div>
        )}

        {status === "invalid" && (
          <div role="alert">
            <Text tone="critical" size="small">
              <FormattedMessage
                defaultMessage="無法讀取圖片，請選擇有效的 PNG 或 JPEG 檔案。"
                description="Error message for an unreadable or unsupported image."
              />
            </Text>
          </div>
        )}

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
