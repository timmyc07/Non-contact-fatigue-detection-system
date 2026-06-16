"""疲勞警報器設定對話框。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from gui.alarm_config import (
    ALARM_SCENARIO_KEYS,
    SCENARIO_LABELS,
    SUPPORTED_SOUND_SUFFIXES,
    AlarmConfig,
    AlarmScenarioConfig,
)
from gui.alarm_player import FatigueAlarmController


class AlarmSettingsDialog(QDialog):
    def __init__(
        self,
        current: AlarmConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("警報器設定")
        self.setMinimumWidth(640)
        self._config = AlarmConfig.from_dict(current.to_dict())

        root = QVBoxLayout(self)
        note = QLabel(
            "當疲勞狀態達到指定等級時播放音效。預設音效路徑為 assets/alerts/；"
            "若檔案尚未放置，可啟用內建提示音作為備援。"
        )
        note.setWordWrap(True)
        note.setObjectName("hintLabel")
        root.addWidget(note)

        self._chk_enabled = QCheckBox("啟用警報器")
        self._chk_enabled.setChecked(self._config.enabled)
        root.addWidget(self._chk_enabled)

        general = QGroupBox("一般設定")
        general_form = QFormLayout(general)

        self._sld_volume = QSlider(Qt.Orientation.Horizontal)
        self._sld_volume.setRange(0, 100)
        self._sld_volume.setValue(self._config.volume)
        self._lbl_volume = QLabel(f"{self._config.volume}%")
        volume_row = QHBoxLayout()
        volume_row.addWidget(self._sld_volume, 1)
        volume_row.addWidget(self._lbl_volume)
        self._sld_volume.valueChanged.connect(
            lambda value: self._lbl_volume.setText(f"{value}%")
        )
        general_form.addRow("音量：", volume_row)

        self._spin_delay = QDoubleSpinBox()
        self._spin_delay.setRange(0.0, 10.0)
        self._spin_delay.setSingleStep(0.5)
        self._spin_delay.setSuffix(" 秒")
        self._spin_delay.setValue(self._config.trigger_delay_sec)
        general_form.addRow("進入狀態後延遲：", self._spin_delay)

        self._spin_repeat = QDoubleSpinBox()
        self._spin_repeat.setRange(5.0, 120.0)
        self._spin_repeat.setSingleStep(5.0)
        self._spin_repeat.setSuffix(" 秒")
        self._spin_repeat.setValue(self._config.repeat_interval_sec)
        general_form.addRow("同級重複間隔：", self._spin_repeat)

        self._chk_repeat_critical = QCheckBox("危急／微睡眠狀態持續重複播放")
        self._chk_repeat_critical.setChecked(self._config.repeat_while_critical)
        general_form.addRow("", self._chk_repeat_critical)

        self._chk_builtin = QCheckBox("未設定音效檔或檔案不存在時，使用內建提示音")
        self._chk_builtin.setChecked(self._config.use_builtin_fallback)
        general_form.addRow("", self._chk_builtin)

        root.addWidget(general)

        scenarios = QGroupBox("情境音效")
        grid = QGridLayout(scenarios)
        grid.setColumnStretch(2, 1)

        headers = ("啟用", "情境", "音效檔路徑", "")
        for col, title in enumerate(headers):
            grid.addWidget(QLabel(f"<b>{title}</b>"), 0, col)

        self._scenario_enabled: dict[str, QCheckBox] = {}
        self._scenario_path: dict[str, QLineEdit] = {}
        self._preview_controller = FatigueAlarmController(self._config, self)

        for row, key in enumerate(ALARM_SCENARIO_KEYS, start=1):
            scfg = self._config.scenarios[key]

            chk = QCheckBox()
            chk.setChecked(scfg.enabled)
            self._scenario_enabled[key] = chk
            grid.addWidget(chk, row, 0)

            grid.addWidget(QLabel(SCENARIO_LABELS[key]), row, 1)

            path_edit = QLineEdit(scfg.sound_path)
            path_edit.setPlaceholderText("選擇 .wav / .mp3 等音效檔")
            self._scenario_path[key] = path_edit
            grid.addWidget(path_edit, row, 2)

            row_actions = QHBoxLayout()
            btn_browse = QPushButton("瀏覽…")
            btn_preview = QPushButton("試聽")
            btn_browse.clicked.connect(lambda _checked=False, k=key: self._browse_sound(k))
            btn_preview.clicked.connect(lambda _checked=False, k=key: self._preview_sound(k))
            row_actions.addWidget(btn_browse)
            row_actions.addWidget(btn_preview)
            grid.addLayout(row_actions, row, 3)

        root.addWidget(scenarios)

        btn_row = QHBoxLayout()
        btn_restore = QPushButton("恢復預設")
        btn_restore.clicked.connect(self._restore_defaults)
        btn_row.addWidget(btn_restore)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse_sound(self, scenario: str) -> None:
        filters = "音效檔 (*.wav *.mp3 *.ogg *.flac);;所有檔案 (*.*)"
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"選擇 {SCENARIO_LABELS[scenario]} 音效",
            self._scenario_path[scenario].text() or str(Path.home()),
            filters,
        )
        if path:
            self._scenario_path[scenario].setText(path)

    def _preview_sound(self, scenario: str) -> None:
        preview_cfg = self._build_config_from_fields()
        self._preview_controller.set_config(preview_cfg)
        if not self._preview_controller.preview_scenario(scenario):
            QMessageBox.warning(
                self,
                "試聽失敗",
                "無法播放音效。請確認路徑正確，或啟用內建提示音。",
            )

    def _restore_defaults(self) -> None:
        defaults = AlarmConfig.defaults()
        self._config = defaults
        self._chk_enabled.setChecked(defaults.enabled)
        self._sld_volume.setValue(defaults.volume)
        self._spin_delay.setValue(defaults.trigger_delay_sec)
        self._spin_repeat.setValue(defaults.repeat_interval_sec)
        self._chk_repeat_critical.setChecked(defaults.repeat_while_critical)
        self._chk_builtin.setChecked(defaults.use_builtin_fallback)
        for key in ALARM_SCENARIO_KEYS:
            scfg = defaults.scenarios[key]
            self._scenario_enabled[key].setChecked(scfg.enabled)
            self._scenario_path[key].setText(scfg.sound_path)

    def _build_config_from_fields(self) -> AlarmConfig:
        scenarios: dict[str, AlarmScenarioConfig] = {}
        for key in ALARM_SCENARIO_KEYS:
            scenarios[key] = AlarmScenarioConfig(
                enabled=self._scenario_enabled[key].isChecked(),
                sound_path=self._scenario_path[key].text().strip(),
            )
        return AlarmConfig(
            enabled=self._chk_enabled.isChecked(),
            volume=int(self._sld_volume.value()),
            trigger_delay_sec=float(self._spin_delay.value()),
            repeat_interval_sec=float(self._spin_repeat.value()),
            repeat_while_critical=self._chk_repeat_critical.isChecked(),
            use_builtin_fallback=self._chk_builtin.isChecked(),
            scenarios=scenarios,
        )

    def _validate_paths(self) -> bool:
        cfg = self._build_config_from_fields()
        missing: list[str] = []
        invalid_suffix: list[str] = []

        for key in ALARM_SCENARIO_KEYS:
            scfg = cfg.scenarios[key]
            if not scfg.enabled:
                continue
            path_text = scfg.sound_path.strip()
            if not path_text:
                continue
            path = Path(path_text)
            if not path.is_file():
                missing.append(f"{SCENARIO_LABELS[key]}：{path_text}")
                continue
            if path.suffix.lower() not in SUPPORTED_SOUND_SUFFIXES:
                invalid_suffix.append(f"{SCENARIO_LABELS[key]}：{path.suffix}")

        if missing and not cfg.use_builtin_fallback:
            QMessageBox.warning(
                self,
                "音效檔不存在",
                "以下已啟用的情境找不到音效檔，且未啟用內建提示音：\n"
                + "\n".join(missing),
            )
            return False

        if invalid_suffix:
            QMessageBox.warning(
                self,
                "不支援的格式",
                "以下音效副檔名可能無法播放：\n" + "\n".join(invalid_suffix),
            )
            return False
        return True

    def _on_accept(self) -> None:
        if not self._validate_paths():
            return
        self._config = self._build_config_from_fields()
        self.accept()

    def get_config(self) -> AlarmConfig:
        return AlarmConfig.from_dict(self._config.to_dict())
