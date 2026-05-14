from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


@dataclass
class HotkeyConfig:
    toggle_metrics: str = "Ctrl+Alt+O"
    toggle_preview: str = "Ctrl+Alt+P"
    start_stop: str = "Ctrl+Alt+S"
    lock_overlay: str = "Ctrl+Alt+F8"
    toggle_all: str = "Ctrl+Alt+A"
    toggle_recording: str = "Ctrl+Alt+F9"


class HotkeySettingsDialog(QDialog):
    def __init__(self, current: HotkeyConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("快捷鍵設定")
        self._cfg = HotkeyConfig(
            toggle_metrics=current.toggle_metrics,
            toggle_preview=current.toggle_preview,
            start_stop=current.start_stop,
            lock_overlay=current.lock_overlay,
            toggle_all=current.toggle_all,
            toggle_recording=current.toggle_recording,
        )

        root = QVBoxLayout(self)
        note = QLabel(
            "以下為快捷鍵編輯器；Windows 將嘗試註冊全域熱鍵。\n"
            "建議使用 Ctrl+Alt+… 避免與其他軟體衝突。"
        )
        note.setWordWrap(True)
        note.setObjectName("hintLabel")
        root.addWidget(note)

        form = QFormLayout()
        root.addLayout(form)

        self._ed_metrics = QKeySequenceEdit()
        self._ed_preview = QKeySequenceEdit()
        self._ed_start = QKeySequenceEdit()
        self._ed_lock = QKeySequenceEdit()
        self._ed_all = QKeySequenceEdit()
        self._ed_rec = QKeySequenceEdit()

        self._ed_metrics.setKeySequence(QKeySequence(self._cfg.toggle_metrics))
        self._ed_preview.setKeySequence(QKeySequence(self._cfg.toggle_preview))
        self._ed_start.setKeySequence(QKeySequence(self._cfg.start_stop))
        self._ed_lock.setKeySequence(QKeySequence(self._cfg.lock_overlay))
        self._ed_all.setKeySequence(QKeySequence(self._cfg.toggle_all))
        self._ed_rec.setKeySequence(QKeySequence(self._cfg.toggle_recording))

        form.addRow("數值 Overlay：", self._ed_metrics)
        form.addRow("鏡頭預覽 Overlay：", self._ed_preview)
        form.addRow("開始／停止：", self._ed_start)
        form.addRow("鎖定 Overlay：", self._ed_lock)
        form.addRow("全部 Overlay 顯示／隱藏：", self._ed_all)
        form.addRow("錄影：", self._ed_rec)

        btn_row = QHBoxLayout()
        btn_restore = QPushButton("恢復預設")
        btn_restore.clicked.connect(self._restore_defaults)
        btn_row.addWidget(btn_restore)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _restore_defaults(self) -> None:
        d = HotkeyConfig()
        self._ed_metrics.setKeySequence(QKeySequence(d.toggle_metrics))
        self._ed_preview.setKeySequence(QKeySequence(d.toggle_preview))
        self._ed_start.setKeySequence(QKeySequence(d.start_stop))
        self._ed_lock.setKeySequence(QKeySequence(d.lock_overlay))
        self._ed_all.setKeySequence(QKeySequence(d.toggle_all))
        self._ed_rec.setKeySequence(QKeySequence(d.toggle_recording))

    def get_config(self) -> HotkeyConfig:
        return HotkeyConfig(
            toggle_metrics=self._ed_metrics.keySequence().toString(),
            toggle_preview=self._ed_preview.keySequence().toString(),
            start_stop=self._ed_start.keySequence().toString(),
            lock_overlay=self._ed_lock.keySequence().toString(),
            toggle_all=self._ed_all.keySequence().toString(),
            toggle_recording=self._ed_rec.keySequence().toString(),
        )


@dataclass
class UserProfile:
    age: int = 28
    height_cm: int = 170
    weight_kg: float = 65.0


class UserProfileDialog(QDialog):
    def __init__(self, profile: UserProfile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("使用者資料")
        self._profile = profile

        root = QVBoxLayout(self)
        group = QGroupBox("身體數值（示範，供日後 rPPG 個人化）")
        form = QFormLayout(group)

        self._age = QSpinBox()
        self._age.setRange(0, 110)
        self._age.setSuffix(" 歲")
        self._age.setValue(profile.age)

        self._height = QSpinBox()
        self._height.setRange(100, 220)
        self._height.setSuffix(" cm")
        self._height.setValue(profile.height_cm)

        self._weight = QDoubleSpinBox()
        self._weight.setRange(30.0, 200.0)
        self._weight.setSingleStep(0.5)
        self._weight.setSuffix(" kg")
        self._weight.setValue(profile.weight_kg)

        self._bmi = QLabel()
        self._height.valueChanged.connect(self._update_bmi)
        self._weight.valueChanged.connect(self._update_bmi)

        form.addRow("年齡：", self._age)
        form.addRow("身高：", self._height)
        form.addRow("體重：", self._weight)
        form.addRow("BMI（自動）：", self._bmi)
        self._update_bmi()

        root.addWidget(group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _update_bmi(self) -> None:
        h_m = self._height.value() / 100.0
        if h_m <= 0:
            self._bmi.setText("—")
            return
        bmi = self._weight.value() / (h_m * h_m)
        self._bmi.setText(f"{bmi:.1f}")

    def get_profile(self) -> UserProfile:
        return UserProfile(
            age=int(self._age.value()),
            height_cm=int(self._height.value()),
            weight_kg=float(self._weight.value()),
        )
