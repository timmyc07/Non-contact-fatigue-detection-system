"""Build the formal practical project report as a PDF.

The layout follows ``docs/電子工程系實務專題報告格式及內容.pdf``:
A4 paper, 2.54/2.91/3.17/3.17 cm margins, 16/14/12 pt heading
hierarchy, and 12 pt body text with at least 16 pt line height.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
OUTPUT_PDF = DOCS_DIR / "無人機駕駛員疲勞狀態監測系統_實務專題報告.pdf"
SUMMARY_CSV = ROOT / "recordings" / "utarldd_runs" / "20260607_122601" / "utarldd_summary_20260607_122601.csv"
VALIDATION_CSV = ROOT / "recordings" / "utarldd_runs" / "20260607_122601" / "utarldd_validation_report_20260607_122601.csv"
FLOWCHART_PREVIEW = DOCS_DIR / "system_flowchart_canva_preview.png"

CH_FONT = "MicrosoftJhengHei"
CH_BOLD = "MicrosoftJhengHei-Bold"
EN_FONT = "Times-Roman"
ACCENT = colors.HexColor("#1F4E79")
LIGHT_FILL = colors.HexColor("#E8EEF5")
GRID = colors.HexColor("#8EA9C1")
MUTED = colors.HexColor("#666666")


@dataclass(frozen=True)
class LabelMetrics:
    label: str
    class_name: str
    completed: int
    failed: int
    face_rate: float
    fatigue_avg: float
    fatigue_p95: float
    fused_avg: float
    fused_p95: float
    perclos_avg: float
    perclos_max_avg: float
    low_vigilance_ratio: float
    drowsy_critical_ratio: float


def register_fonts() -> None:
    regular_candidates = [
        Path("C:/Windows/Fonts/msjh.ttc"),
        Path("C:/Windows/Fonts/NotoSansTC-VF.ttf"),
        Path("C:/Windows/Fonts/kaiu.ttf"),
    ]
    bold_candidates = [
        Path("C:/Windows/Fonts/msjhbd.ttc"),
        Path("C:/Windows/Fonts/NotoSansTC-VF.ttf"),
        Path("C:/Windows/Fonts/msjh.ttc"),
    ]
    regular = next((path for path in regular_candidates if path.exists()), None)
    bold = next((path for path in bold_candidates if path.exists()), regular)
    if regular is None or bold is None:
        raise RuntimeError("找不到可用中文字型，請安裝 Microsoft JhengHei 或 Noto Sans TC。")
    pdfmetrics.registerFont(TTFont(CH_FONT, str(regular)))
    pdfmetrics.registerFont(TTFont(CH_BOLD, str(bold)))


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ProjectTitle",
            parent=base["Title"],
            fontName=CH_BOLD,
            fontSize=16,
            leading=20,
            alignment=TA_CENTER,
            textColor=colors.black,
            spaceAfter=8,
        ),
        "subtitle": ParagraphStyle(
            "ProjectSubtitle",
            parent=base["Normal"],
            fontName=EN_FONT,
            fontSize=12,
            leading=16,
            alignment=TA_CENTER,
            textColor=MUTED,
            spaceAfter=8,
        ),
        "h1": ParagraphStyle(
            "Heading1Custom",
            parent=base["Heading1"],
            fontName=CH_BOLD,
            fontSize=16,
            leading=20,
            textColor=ACCENT,
            spaceBefore=12,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "Heading2Custom",
            parent=base["Heading2"],
            fontName=CH_BOLD,
            fontSize=14,
            leading=18,
            textColor=ACCENT,
            spaceBefore=10,
            spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "Heading3Custom",
            parent=base["Heading3"],
            fontName=CH_BOLD,
            fontSize=12,
            leading=16,
            textColor=ACCENT,
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "BodyCustom",
            parent=base["Normal"],
            fontName=CH_FONT,
            fontSize=12,
            leading=16,
            alignment=TA_LEFT,
            wordWrap="CJK",
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "SmallCustom",
            parent=base["Normal"],
            fontName=CH_FONT,
            fontSize=9.5,
            leading=13,
            wordWrap="CJK",
        ),
        "caption": ParagraphStyle(
            "CaptionCustom",
            parent=base["Normal"],
            fontName=CH_FONT,
            fontSize=10,
            leading=14,
            alignment=TA_CENTER,
            textColor=MUTED,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "toc": ParagraphStyle(
            "TocCustom",
            parent=base["Normal"],
            fontName=CH_FONT,
            fontSize=11,
            leading=16,
            wordWrap="CJK",
        ),
    }


def p(text: str, styles: dict[str, ParagraphStyle], style: str = "body") -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), styles[style])


def heading(text: str, styles: dict[str, ParagraphStyle], level: int = 1) -> Paragraph:
    return p(text, styles, f"h{level}")


def bullet_list(items: list[str], styles: dict[str, ParagraphStyle]) -> ListFlowable:
    return ListFlowable(
        [ListItem(p(item, styles, "body"), leftIndent=12) for item in items],
        bulletType="bullet",
        leftIndent=18,
        bulletFontName=CH_FONT,
        bulletFontSize=10,
    )


def numbered_list(items: list[str], styles: dict[str, ParagraphStyle]) -> ListFlowable:
    return ListFlowable(
        [ListItem(p(item, styles, "body"), leftIndent=12) for item in items],
        bulletType="1",
        leftIndent=18,
        bulletFontName=EN_FONT,
        bulletFontSize=10,
    )


def table(data: list[list[Any]], col_widths: list[float] | None = None, font_size: float = 9.5) -> Table:
    converted = []
    small_style = ParagraphStyle("TableCell", fontName=CH_FONT, fontSize=font_size, leading=font_size + 3, wordWrap="CJK")
    for row in data:
        converted.append([cell if hasattr(cell, "wrap") else Paragraph(str(cell), small_style) for cell in row])
    widths = [w * cm for w in col_widths] if col_widths else None
    t = Table(converted, colWidths=widths, repeatRows=1, hAlign="CENTER")
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), CH_FONT),
                ("FONTSIZE", (0, 0), (-1, -1), font_size),
                ("LEADING", (0, 0), (-1, -1), font_size + 3),
                ("BACKGROUND", (0, 0), (-1, 0), LIGHT_FILL),
                ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.35, GRID),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


class ProjectDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str) -> None:
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=3.17 * cm,
            rightMargin=3.17 * cm,
            topMargin=2.54 * cm,
            bottomMargin=2.91 * cm,
            title="無人機駕駛員疲勞狀態監測系統_實務專題報告",
            author="non_contact_fatigue_detection_system",
        )
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="normal")
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=self.draw_footer)])

    def draw_footer(self, canvas, doc) -> None:  # noqa: ANN001
        canvas.saveState()
        canvas.setFont(CH_FONT, 9)
        canvas.setFillColor(MUTED)
        canvas.drawCentredString(A4[0] / 2, 1.35 * cm, f"無人機駕駛員疲勞狀態監測系統 - 第 {doc.page} 頁")
        canvas.restoreState()


def read_validation_metrics() -> tuple[list[LabelMetrics], str]:
    if not VALIDATION_CSV.exists():
        return (
            [
                LabelMetrics("0", "Alert", 12, 0, 99.98, 0.031, 0.095, 0.060, 0.156, 2.46, 6.67, 29.43, 0.03),
                LabelMetrics("5", "Low Vigilant", 12, 0, 99.89, 0.026, 0.082, 0.048, 0.144, 2.68, 12.69, 21.88, 0.03),
                LabelMetrics("10", "Drowsy", 12, 0, 99.93, 0.030, 0.076, 0.054, 0.134, 5.10, 17.03, 28.12, 3.99),
            ],
            "完整上升 2/12；Drowsy 高於 Alert 4/12；資料完整；目前不支持分類有效",
        )

    metrics: list[LabelMetrics] = []
    run_summary = ""
    with VALIDATION_CSV.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["列類型"] == "run_summary":
                run_summary = f"{row['趨勢判定']}；{row['結論']}"
            if row["列類型"] != "label_summary":
                continue
            metrics.append(
                LabelMetrics(
                    row["資料集標籤"],
                    row["警覺類別"],
                    int(row["完成影片數"]),
                    int(row["失敗影片數"]),
                    float(row["人臉偵測率平均(%)"]),
                    float(row["平均疲勞分數"]),
                    float(row["95分位疲勞分數"]),
                    float(row["平均融合分數"]),
                    float(row["95分位融合分數"]),
                    float(row["平均PERCLOS(%)"]),
                    float(row["最高PERCLOS平均(%)"]),
                    float(row["低警覺比例(%)"]),
                    float(row["嗜睡危急比例(%)"]),
                )
            )
    return metrics, run_summary


def add_bar_table(story: list[Any], styles: dict[str, ParagraphStyle], metrics: list[LabelMetrics], title: str) -> None:
    rows = [["類別", "平均 PERCLOS", "最高 PERCLOS 均值", "平均融合分數", "嗜睡/危急比例"]]
    max_perclos = max(m.perclos_max_avg for m in metrics) or 1
    max_fused = max(m.fused_p95 for m in metrics) or 1
    max_state = max(m.drowsy_critical_ratio for m in metrics) or 1
    for m in metrics:
        rows.append(
            [
                m.class_name,
                f"{m.perclos_avg:.2f}% {'█' * max(1, round(m.perclos_avg / max_perclos * 12))}",
                f"{m.perclos_max_avg:.2f}% {'█' * max(1, round(m.perclos_max_avg / max_perclos * 12))}",
                f"{m.fused_avg:.3f} / p95 {m.fused_p95:.3f} {'█' * max(1, round(m.fused_p95 / max_fused * 12))}",
                f"{m.drowsy_critical_ratio:.2f}% {'█' * max(1, round(m.drowsy_critical_ratio / max_state * 12))}",
            ]
        )
    story.extend([heading(title, styles, 3), table(rows, [2.5, 3.1, 3.4, 4.1, 3.0], 8.8), Spacer(1, 8)])


def add_cover_and_front_matter(story: list[Any], styles: dict[str, ParagraphStyle]) -> None:
    story.extend(
        [
            p("電子工程系實務專題報告", styles, "title"),
            Spacer(1, 0.45 * cm),
            p("無人機駕駛員疲勞狀態監測系統", styles, "title"),
            p("UAV Operator Fatigue State Monitoring System Based on MediaPipe and rPPG", styles, "subtitle"),
            Spacer(1, 1.0 * cm),
            table(
                [
                    ["項目", "內容"],
                    ["學校", "請填寫"],
                    ["系級", "電子工程系 / 請填寫班級"],
                    ["組員", "請填寫姓名與學號"],
                    ["指導老師", "請填寫"],
                    ["專題類型", "軟體系統、電腦視覺、訊號處理、桌面 GUI 與資料分析"],
                    ["完成日期", "2026 年 6 月 20 日"],
                    ["產出檔案", "本 PDF 報告、專題海報檔、展示簡報與系統原始碼"],
                ],
                [3.5, 11.0],
                10,
            ),
            Spacer(1, 0.4 * cm),
            p("說明：本頁保留個人欄位供送審前填寫；技術內容、測試數據與系統限制依本 repo 既有程式、文件與回測資料撰寫。", styles),
            PageBreak(),
            heading("中文摘要", styles, 1),
            p("本專題完成一套面向無人機遠端駕駛員的非接觸式疲勞與警覺度監測系統。系統使用一般 RGB 攝影機擷取操作員臉部影像，透過 MediaPipe Face Landmarker 取得臉部特徵點、虹膜位置、表情係數與姿態資訊，再分別進行行為疲勞分析與 rPPG 遠端生理訊號估測。行為疲勞分析包含 EAR 眼睛開合、PERCLOS 閉眼時間比例、眨眼時序、視線穩定度、頭部姿態、微睡眠與哈欠等特徵；rPPG 子系統則以臉部皮膚 ROI、POS 訊號分離、Butterworth 帶通濾波、Welch 頻譜峰值搜尋與 IBI/HRV 估算提供 BPM、SQI 與壓力趨勢輔助資訊。", styles),
            p("系統以 PySide6 建立桌面 GUI，整合 OpenCV 攝影機擷取、即時標註預覽、SQLite 指標紀錄、影片錄製、警報器設定與 Flask-SocketIO Web dashboard。為避免 rPPG 與疲勞分析重複推論同一影格，主流程使用單一 MediaPipe Face Landmarker 將結果分流到兩條分析管線，再由融合評分器以行為疲勞為主、rPPG 為輔輸出整體疲勞分數。系統另建立 UTA-RLDD 影片回放驗證流程，可將資料集影片視為可重現離線鏡頭，產生 SQLite、CSV、HTML 與 manifest 報表。", styles),
            p("測試結果顯示，2026-06-07 批次共處理 36 支 UTA-RLDD 影片，完成率 100%，平均人臉偵測率約 99.93%。PERCLOS 與嗜睡/危急 frame 比例在 Drowsy 類別較高，表示眼部閉合特徵對部分嗜睡影片有反應；但平均融合分數未隨 Alert、Low Vigilant、Drowsy 單調上升，因此目前不能宣稱已完成高準確率三分類模型。結論上，本專題已完成可即時運作、可記錄、可回放驗證的疲勞監測原型；後續仍需以無人機操作場域資料進行人工標註、門檻校正與誤報漏報評估。", styles),
            p("關鍵詞：無人機駕駛員、疲勞監測、MediaPipe、rPPG、PERCLOS、PySide6、Web dashboard。", styles),
            PageBreak(),
            heading("English Abstract", styles, 1),
            p("This project implements a non-contact fatigue and vigilance monitoring prototype for remote UAV operators. A standard RGB camera captures facial video, and MediaPipe Face Landmarker provides facial landmarks, iris landmarks, blendshape scores, and pose-related outputs. The system then runs two analysis paths: behavior-based fatigue estimation and remote photoplethysmography. The behavior path measures eye aspect ratio, PERCLOS, blink temporal patterns, gaze stability, head pose, microsleep-like nodding, mouth opening, and yawning. The rPPG path extracts facial skin regions of interest, applies POS pulse separation, Butterworth band-pass filtering, Welch spectral peak analysis, and IBI/HRV estimation to provide BPM, SQI, and stress-related diagnostic indicators.", styles),
            p("The implementation includes a PySide6 desktop GUI, OpenCV camera capture, real-time overlays, SQLite recording, video recording, alarm configuration, and a Flask-SocketIO web dashboard. To avoid duplicate inference, the main pipeline uses one shared Face Landmarker instance and dispatches its outputs to both behavior and rPPG engines before a conservative fusion scorer combines them. The system also provides a UTA-RLDD replay pipeline that treats dataset videos as deterministic offline camera inputs and exports SQLite, CSV, HTML, and manifest reports.", styles),
            p("In the 2026-06-07 replay batch, 36 UTA-RLDD videos were processed successfully with a 100% completion rate and an average face detection rate of approximately 99.93%. PERCLOS and severe drowsiness-related frame ratios were higher in the Drowsy class, but the fused fatigue score did not monotonically increase from Alert to Low Vigilant to Drowsy. Therefore, this project should be presented as a working monitoring prototype and reproducible validation platform, not as a fully validated high-accuracy fatigue classifier.", styles),
            p("Keywords: UAV operator, fatigue monitoring, MediaPipe, rPPG, PERCLOS, PySide6, Web dashboard.", styles),
            PageBreak(),
            heading("目錄", styles, 1),
            p("1. 緒言<br/>2. 簡介<br/>3. 理論<br/>4. 軟、硬體分析<br/>5. 測試結果<br/>6. 結論<br/>7. 建議<br/>8. 附錄<br/>9. 參考資料", styles, "toc"),
            PageBreak(),
            heading("圖目錄", styles, 1),
            table(
                [
                    ["圖號", "圖名"],
                    ["圖 1", "系統流程圖預覽"],
                    ["圖 2", "UTA-RLDD 回測指標比較表"],
                ],
                [3.0, 11.0],
                10,
            ),
            PageBreak(),
        ]
    )


def add_main_content(story: list[Any], styles: dict[str, ParagraphStyle], metrics: list[LabelMetrics], run_summary: str) -> None:
    story.extend(
        [
            heading("1. 緒言", styles, 1),
            heading("1.1 研究背景", styles, 2),
            p("無人機在巡檢、救災、測繪、農業、公共安全與教育訓練等場域快速普及。許多任務雖然由無人機在空中執行，但真正的判斷與操控仍由地面操作員負責。長時間盯著地面站畫面、等待事件發生、在低刺激監控與高壓任務之間切換，容易造成警覺度下降、反應時間變慢或注意力漏失。", styles),
            p("因此，本專題以一般攝影機作為主要感測器，結合電腦視覺與 rPPG 訊號處理，建立一套可在桌面環境即時運作的疲勞監測原型。系統不是醫療診斷工具，也不是安全關鍵自動接管系統；它的定位是輔助觀察、早期提示與資料紀錄。", styles),
            heading("1.2 研究目的", styles, 2),
            numbered_list(
                [
                    "使用單一 RGB 攝影機即時擷取操作員臉部狀態，降低硬體部署成本。",
                    "以 MediaPipe Face Landmarker 取得臉部、眼睛、嘴部、虹膜與姿態資訊。",
                    "設計可解釋的行為疲勞特徵，包括 EAR、PERCLOS、眨眼時序、凝視、頭姿、微睡眠與哈欠。",
                    "加入 rPPG 心率與品質診斷作為輔助生理資訊，但不讓低品質 rPPG 主導疲勞判斷。",
                    "建立桌面 GUI、Web dashboard、SQLite 紀錄、影片錄製與可重現回放驗證流程。",
                ],
                styles,
            ),
            heading("1.3 專題範圍與限制", styles, 2),
            p("本專題完成的是工程原型與驗證平台，而非已通過臨床、法規或安全認證的產品。系統輸出應解讀為警覺度趨勢與工程診斷資料。光線、眼鏡、瀏海、鏡頭角度、自動曝光、頭部快速移動、膚色差異與任務行為都可能影響結果。", styles),
            heading("2. 簡介", styles, 1),
            heading("2.1 製作動機", styles, 2),
            p("專題的核心動機是把汽車駕駛疲勞偵測中常見的眼部與臉部行為特徵，轉換到無人機遠端操作員情境。無人機操作員的風險不只在移動速度，也在持續監控、判斷與操控時的注意力維持。", styles),
            heading("2.2 製作方法", styles, 2),
            p("系統以 Python 為主要開發語言。桌面介面使用 PySide6，影像擷取與影像處理使用 OpenCV，臉部特徵擷取使用 MediaPipe Face Landmarker，訊號處理使用 NumPy 與 SciPy，Web dashboard 使用 Flask 與 Flask-SocketIO，資料紀錄使用 SQLite。", styles),
        ]
    )
    if FLOWCHART_PREVIEW.exists():
        story.extend([Spacer(1, 6), Image(str(FLOWCHART_PREVIEW), width=13.8 * cm, height=8.0 * cm), p("圖 1 系統流程圖預覽", styles, "caption")])
    story.extend(
        [
            heading("2.3 主要成果", styles, 2),
            bullet_list(
                [
                    "完成即時桌面 GUI，可顯示 camera preview、MediaPipe 標註、rPPG ROI、疲勞狀態、融合分數與警報狀態。",
                    "完成 rPPG 子系統，可輸出 BPM、RMSSD、SDNN、LF/HF、SQI、品質分數與 BPM guard 診斷。",
                    "完成行為疲勞子系統，可輸出 OK、LOW_VIGILANCE、DROWSY、CRITICAL、MICROSLEEP 等狀態。",
                    "完成 Web dashboard，即時推送 metrics 與 JPEG preview，並能回放 SQLite 紀錄。",
                    "完成 UTA-RLDD replay，可批次輸出 SQLite、summary CSV、validation CSV、HTML 報表與 manifest。",
                ],
                styles,
            ),
            heading("3. 理論", styles, 1),
            heading("3.1 MediaPipe Face Landmarker", styles, 2),
            p("MediaPipe Face Landmarker 是本專題唯一直接使用的 AI 模型。系統將 OpenCV 取得的 BGR frame 轉為 RGB，再包裝成 MediaPipe Image，以 RunningMode.VIDEO 與遞增 timestamp_ms 執行 detect_for_video。模型輸出 478 個 normalized face landmarks、blendshape scores 與 facial transformation matrices。", styles),
            heading("3.2 EAR 與 PERCLOS", styles, 2),
            p("EAR 使用眼睛 6 個 landmark 估算眼睛開合程度，公式為 EAR = (||p2 - p6|| + ||p3 - p5||) / (2 ||p1 - p4||)。系統啟動後先收集個人開眼 baseline，再以 baseline 乘上比例產生閉眼門檻，避免固定 EAR 門檻受到眼型、鏡頭角度與眼鏡影響。", styles),
            p("PERCLOS 則計算一段滑動時間窗內的閉眼時間比例：PERCLOS = closed_eye_time / valid_observation_time。本系統以 60 秒 sliding window 計算 PERCLOS，低警覺工程門檻約為 0.10，明顯嗜睡工程門檻約為 0.25。", styles),
            heading("3.3 眨眼時序、凝視與頭部姿態", styles, 2),
            p("低警覺不一定立即表現為長時間閉眼，因此系統記錄每次眨眼的 duration、amplitude 與 opening velocity，使用前 12 次有效眨眼建立個人 baseline。虹膜位置用於估計 gaze x/y、fixation duration、saccadic velocity 與 saccade frequency；頭部姿態則以 solvePnP 與簡化臉部 3D template 推估 pitch、yaw、roll。", styles),
            heading("3.4 rPPG 與 POS 訊號分離", styles, 2),
            p("rPPG 利用臉部皮膚反射光中隨脈搏產生的微小色彩變化估計心率。本系統選取額頭、左右臉頰與眉心附近 ROI，計算平均 RGB 時序，再使用 POS 方法降低光照共同變動。取得 pulse waveform 後，系統使用 Butterworth band-pass 保留合理心率頻帶，再用 Welch PSD 找主要峰值估算 BPM。", styles),
            heading("3.5 融合分數與創意設計", styles, 2),
            p("融合器預設行為疲勞權重 85%，rPPG 權重 15%；若 rPPG 的 SQI、quality score 或 ROI 數不足，rPPG 權重降為 0，避免低品質生理訊號造成誤判。此設計保留可解釋性：每一次警示都能回到 PERCLOS、眨眼時序、凝視、頭姿、哈欠或 rPPG 品質欄位。", styles),
            heading("4. 軟、硬體分析", styles, 1),
            heading("4.1 硬體架構與電路分析", styles, 2),
            p("本專題沒有自製電路板，因此電路分析以訊號路徑與介面分析呈現。攝影機透過 USB 或內建匯流排輸出影像資料，PC 端以 OpenCV VideoCapture 讀取 frame。警示音透過作業系統音訊裝置輸出，SQLite 與影片檔則儲存在本機磁碟。", styles),
            table(
                [
                    ["硬體", "責任", "分析"],
                    ["USB / 內建攝影機", "提供 RGB 影像", "影像 FPS、解析度、自動曝光與光源穩定度會直接影響 Face Landmarker 與 rPPG。"],
                    ["Notebook / PC", "執行 Python、MediaPipe、OpenCV、GUI 與 Web server", "CPU 與記憶體需同時負擔影像解碼、臉部推論、訊號處理與 UI 更新。"],
                    ["螢幕", "顯示 GUI、overlay 與 Web dashboard", "顯示層不應阻塞分析層，因此 preview 有 FPS 節流與最新影格策略。"],
                    ["喇叭", "播放警示音", "可依 LOW_VIGILANCE、DROWSY、CRITICAL、MICROSLEEP 設定不同音效。"],
                ],
                [3.2, 4.2, 7.2],
                8.8,
            ),
            Spacer(1, 8),
            heading("4.2 軟體模組分析", styles, 2),
            table(
                [
                    ["模組", "代表檔案", "責任"],
                    ["桌面啟動", "main.py", "設定 Qt plugin 路徑、檢查 Linux xcb runtime、啟動 PySide6 主視窗。"],
                    ["主控制台", "gui/main_window.py", "管理相機、分析 worker、錄影、Web dashboard、UTA-RLDD replay 與 UI 狀態。"],
                    ["共用臉部推論", "gui/combined_worker.py", "單一 Face Landmarker 對每個 frame 推論一次，分送給 rPPG 與疲勞分析。"],
                    ["行為疲勞", "gui/fatigue_engine.py", "計算 EAR、PERCLOS、眨眼、凝視、頭姿、MAR、哈欠與品質分數。"],
                    ["rPPG", "rppg/rppg_worker.py", "建立 ROI、POS pulse、濾波、Welch BPM、HRV、SQI 與 BPM guard。"],
                    ["Web dashboard", "gui/web_server.py / gui/web_ui", "Socket.IO 即時 metrics、JPEG preview、歷史 DB 回放與影片串流。"],
                    ["回放驗證", "gui/video_replay.py / scripts/utarldd_replay.py", "用 UTA-RLDD 影片重用正式 pipeline，輸出 DB/CSV/HTML/manifest。"],
                ],
                [3.0, 4.6, 7.0],
                8.4,
            ),
            Spacer(1, 8),
            heading("4.3 主要程式流程", styles, 2),
            p("CombinedWorker 的程式設計重點是「一個 frame 只做一次臉部推論」。它從最新影格佇列取出 BGR frame，轉成 RGB MediaPipe Image，呼叫 FaceLandmarker.detect_for_video。若偵測到臉，先讓 FatigueEngine 產生行為 metrics，再讓 rPPG pipeline 取 ROI 與計算生理 metrics，最後由 FatigueFuser 產生 fused score 並輸出到 GUI、Web 與 recorder。", styles),
            heading("5. 測試結果", styles, 1),
            heading("5.1 測試方法", styles, 2),
            p("本專題使用三層驗證：第一層是 pytest 自動測試；第二層是固定影片回放，使用 UTA-RLDD 影片建立可重現時間軸；第三層是人工情境測試建議，例如清醒注視、自然眨眼、閉眼、瞇眼、低頭、哈欠與轉頭等場景。", styles),
            heading("5.2 UTA-RLDD 回放數據", styles, 2),
            p(f"本報告採用 repo 內既有正式回測 20260607_122601。validation report 結論為：{run_summary}。這表示資料處理與人臉偵測穩定，但目前融合分數尚未充分支持 Alert、Low Vigilant、Drowsy 三分類。", styles),
            table(
                [["Label", "類別", "完成/失敗", "臉偵測率(%)", "平均PERCLOS(%)", "最高PERCLOS均值(%)", "平均融合", "95分位融合", "嗜睡危急比例(%)"]]
                + [
                    [
                        m.label,
                        m.class_name,
                        f"{m.completed}/{m.failed}",
                        f"{m.face_rate:.2f}",
                        f"{m.perclos_avg:.2f}",
                        f"{m.perclos_max_avg:.2f}",
                        f"{m.fused_avg:.3f}",
                        f"{m.fused_p95:.3f}",
                        f"{m.drowsy_critical_ratio:.2f}",
                    ]
                    for m in metrics
                ],
                [1.2, 2.0, 1.5, 1.8, 1.8, 2.0, 1.4, 1.4, 1.8],
                7.8,
            ),
            Spacer(1, 8),
        ]
    )
    add_bar_table(story, styles, metrics, "圖 2 UTA-RLDD 回測指標比較表")
    story.extend(
        [
            heading("5.3 測試判讀", styles, 2),
            bullet_list(
                [
                    "工程可用性良好：36 支影片皆完成，失敗數為 0，人臉偵測率三類皆約 99.9%。",
                    "PERCLOS 有部分支持：Drowsy 的平均 PERCLOS 約 5.10%，高於 Alert 的 2.46% 與 Low Vigilant 的 2.68%。",
                    "嚴重狀態比例有反應：Drowsy 的嗜睡/危急 frame 比例約 3.99%，高於 Alert 與 Low Vigilant 的約 0.03%。",
                    "融合分數尚未支持三分類：平均融合分數在 Alert、Low Vigilant、Drowsy 分別約 0.060、0.048、0.054，未呈現單調上升。",
                    "UTA-RLDD label 是整段影片類別，不是逐幀 ground truth，因此不能直接宣稱逐幀 accuracy、precision 或 recall。",
                ],
                styles,
            ),
            heading("5.4 自動測試覆蓋", styles, 2),
            table(
                [
                    ["測試類別", "覆蓋重點"],
                    ["rPPG", "合成 BPM、band-pass、Welch peak、IBI outlier、BPM guard、ROI jitter 與面積穩定度。"],
                    ["MediaPipe fatigue", "tuning profile、blendshape baseline、品質 gate、融合 15/85 權重與低 SQI 降權。"],
                    ["Web dashboard", "Socket.IO 連線、request_metrics history/latest、JPEG preview、playback API 與 UTA-RLDD DB 列表。"],
                    ["UTA-RLDD replay", "label 解析、影片探索、summary/full CSV、validation report、HTML 報表、manifest、平行模式錯誤處理。"],
                    ["告警器", "狀態對應音效、冷卻時間、優先級與 fallback。"],
                ],
                [3.0, 11.6],
                8.8,
            ),
            Spacer(1, 8),
            heading("6. 結論", styles, 1),
            p("本專題完成一套可即時執行的無人機駕駛員疲勞狀態監測原型。系統整合 MediaPipe 臉部特徵、rPPG 訊號處理、行為疲勞分析、融合評分、桌面 GUI、Web dashboard、SQLite 紀錄、影片錄製、警報與 UTA-RLDD 回放驗證。", styles),
            p("測試結果也清楚指出目前限制：系統可以穩定處理影片並取得高人臉偵測率，PERCLOS 對 Drowsy 類別有一定反應，但融合分數尚未與資料集三分類穩定對齊。因此本專題應定位為疲勞監測原型與驗證平台，而非已完成高準確率分類器。", styles),
            heading("7. 建議", styles, 1),
            heading("7.1 對後續學弟妹的建議", styles, 2),
            numbered_list(
                [
                    "先建立無人機操作員專用資料集，包含清醒監控、長時間專注、低警覺、閉眼、哈欠、看遙控器、看平板、轉頭與光線變化等場景。",
                    "每段影片應加入人工事件標註，例如眨眼、長閉眼、哈欠、低頭、遮擋與說話，才能計算 precision、recall、F1 與 false alarm rate。",
                    "調整 PERCLOS、blink temporal、LOW_VIGILANCE 與融合權重前，請固定使用同一批 replay 做 A/B 比較，避免主觀調參。",
                    "rPPG 若要驗證 BPM 準確率，需同步手錶、胸帶、指夾式 PPG 或 ECG 參考；UTA-RLDD 不能提供 BPM ground truth。",
                    "若要導入 CNN、LSTM 或 Transformer，建議先以現有 SQLite 特徵做離線比較，不要直接替換即時主流程。",
                ],
                styles,
            ),
            heading("7.2 未來功能方向", styles, 2),
            bullet_list(
                [
                    "新增 replay 專用 calibration namespace，避免本機 webcam baseline 影響資料集回放。",
                    "加入門檻 sweep 工具，自動比較不同 PERCLOS、眨眼時序與融合權重設定。",
                    "建立 A/B 報表，比較兩次 run 的 false alarm、miss risk 與有效幀比例。",
                    "加入任務事件輸入，例如任務開始、起飛、巡檢、返航與緊急事件，讓疲勞分數能與任務階段對齊。",
                ],
                styles,
            ),
            heading("8. 附錄", styles, 1),
            heading("附錄 A PDF 格式規範對照", styles, 2),
            table(
                [
                    ["規範項目", "本報告處理方式"],
                    ["紙張", "A4，21.0 cm x 29.7 cm。"],
                    ["邊界", "上 2.54 cm、下 2.91 cm、左 3.17 cm、右 3.17 cm。"],
                    ["標題", "中文新細明體系統等價字型 16 pt 粗體；PDF 使用內嵌 CJK 字型避免缺字。"],
                    ["次標題", "14 pt 粗體。"],
                    ["小次標題", "12 pt 粗體。"],
                    ["摘要內文", "12 pt，行距至少 16 pt。"],
                    ["必要章節", "首頁、中文摘要、英文摘要、目錄、圖目錄、緒言、簡介、理論、軟硬體分析、測試結果、結論、建議、附錄、參考資料皆已建立。"],
                ],
                [4.0, 10.6],
                9,
            ),
            Spacer(1, 8),
            heading("附錄 B 主要操作指令", styles, 2),
            table(
                [
                    ["用途", "指令"],
                    ["建立環境", "py -3 -m venv .venv；.\\.venv\\Scripts\\python -m pip install -r requirements.txt"],
                    ["啟動 GUI", "python main.py"],
                    ["Ubuntu 安裝", "bash scripts/setup_ubuntu.sh"],
                    ["執行測試", ".\\.venv\\Scripts\\python.exe -m pytest -q"],
                    ["UTA-RLDD replay", ".\\.venv\\Scripts\\python.exe -m scripts.utarldd_replay <dataset_root> --jobs 4"],
                    ["產生本 PDF", ".\\.venv\\Scripts\\python.exe scripts\\build_practical_project_report_pdf.py"],
                ],
                [4.0, 10.6],
                8.8,
            ),
            Spacer(1, 8),
            heading("附錄 C 授權同意書與送審資料提醒", styles, 2),
            p("PDF 規範提醒期末實務專題報告需上傳完整報告檔及評審當天海報檔，且包含授權同意書。本 repo 未提供校方授權同意書範本，因此本報告只保留提醒。送審前請依系上最新表單另附授權同意書，並補齊首頁個人欄位。", styles),
            heading("9. 參考資料", styles, 1),
        ]
    )
    refs = [
        "MediaPipe Face Landmarker Python guide, https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python",
        "MediaPipe Face Landmarks Detection guide, https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker",
        "Camillo Lugaresi et al., MediaPipe: A Framework for Building Perception Pipelines, arXiv:1906.08172, 2019.",
        "W. Wang, A. C. den Brinker, S. Stuijk, G. de Haan, Algorithmic Principles of Remote PPG, IEEE Transactions on Biomedical Engineering, 2017.",
        "Peter D. Welch, The Use of Fast Fourier Transform for the Estimation of Power Spectra, IEEE Transactions on Audio and Electroacoustics, 1967.",
        "SciPy signal API reference, https://docs.scipy.org/doc/scipy/reference/signal.html",
        "OpenCV VideoCapture documentation, https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html",
        "OpenCV solvePnP documentation, https://docs.opencv.org/4.x/d5/d1f/calib3d_solvePnP.html",
        "Qt for Python / PySide6 documentation, https://doc.qt.io/qtforpython-6/",
        "Flask-SocketIO documentation, https://flask-socketio.readthedocs.io/",
        "Tereza Soukupova and Jan Cech, Real-Time Eye Blink Detection using Facial Landmarks, 2016.",
        "National Highway Traffic Safety Administration, Development of a Drowsy Driver Detection System, DOT HS 808 247, 1998.",
        "UTA-RLDD official site, https://sites.google.com/view/utarldd/home",
        "Reza Ghoddoosian, Marnim Galib, Vassilis Athitsos, A Realistic Dataset and Baseline Temporal Model for Early Drowsiness Detection, CVPR Workshops, 2019.",
        "本專案 README.md、docs/system_overview_technical_report.md、docs/rppg_technical_report_v2.md、docs/mediapipe_fatigue_technical_report.md、docs/utarldd_replay_validation_report.md。",
    ]
    for idx, ref in enumerate(refs, 1):
        story.append(p(f"{idx}. {ref}", styles))


def build_pdf() -> Path:
    register_fonts()
    styles = make_styles()
    metrics, run_summary = read_validation_metrics()
    story: list[Any] = []
    add_cover_and_front_matter(story, styles)
    add_main_content(story, styles, metrics, run_summary)
    DOCS_DIR.mkdir(exist_ok=True)
    doc = ProjectDocTemplate(str(OUTPUT_PDF))
    doc.build(story)
    return OUTPUT_PDF


if __name__ == "__main__":
    print(build_pdf())
