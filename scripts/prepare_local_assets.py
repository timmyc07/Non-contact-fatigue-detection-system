"""在本機補齊封裝圖示；模型僅於明確指定 --download-model 時下載。"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

from PIL import Image, ImageDraw

from gui.model_assets import download_face_model


ROOT = Path(__file__).resolve().parents[1]


def prepare_icons(root: Path = ROOT) -> list[Path]:
    """只補缺檔，讓本機自訂圖示維持原樣。"""
    icons = root / "src-tauri" / "icons"
    source = icons / "icon.png"
    if source.exists():
        with Image.open(source) as image:
            artwork = image.convert("RGBA")
        if artwork.width != artwork.height:
            raise ValueError(f"圖示來源必須為正方形：{source}")
        artwork = artwork.resize((1024, 1024), Image.Resampling.LANCZOS)
    else:
        artwork = Image.new("RGBA", (1024, 1024))
        draw = ImageDraw.Draw(artwork)
        draw.rounded_rectangle((96, 96, 928, 928), radius=184, fill="#140d22")
        draw.ellipse((220, 330, 804, 694), outline="#b3a0ff", width=40)
        draw.ellipse((436, 436, 588, 588), fill="#8fe0c7")
        draw.line(
            [(244, 736), (396, 736), (448, 660), (516, 804), (584, 704), (780, 704)],
            fill="#8fe0c7", width=28, joint="curve",
        )

    targets = [
        (icons / "icon.png", 512),
        (icons / "32x32.png", 32),
        (icons / "128x128.png", 128),
        (icons / "128x128@2x.png", 256),
        (icons / "icon.icns", 1024),
        (icons / "icon-windows.ico", 256),
    ]
    android = root / "flutter_app" / "android" / "app" / "src" / "main" / "res"
    targets.extend(
        (android / f"mipmap-{density}" / "ic_launcher.png", size)
        for density, size in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96),
                              ("xxhdpi", 144), ("xxxhdpi", 192))
    )
    created = []
    for target, size in targets:
        if target.exists():
            continue
        image = artwork.resize((size, size), Image.Resampling.LANCZOS)
        image_format = {".png": "PNG", ".ico": "ICO", ".icns": "ICNS"}[target.suffix]
        content = io.BytesIO()
        image.save(content, format=image_format)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as output:
                output.write(content.getvalue())
        except FileExistsError:
            continue
        created.append(target)
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-model", action="store_true", help="下載並驗證官方 Face Landmarker v1")
    args = parser.parse_args()
    for path in prepare_icons():
        print(f"本機圖示：{path.relative_to(ROOT)}")
    if args.download_model:
        target = ROOT / "models" / "face_landmarker.task"
        if not target.exists():
            download_face_model(target)
        print(f"本機模型：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
