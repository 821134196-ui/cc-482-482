"""样例照片生成：本地目录存放装窑照与成品照（SVG 占位图）。"""
from __future__ import annotations

import os


def loading_photo_svg(batch_name: str, kiln_name: str, shelf_count: int, item_count: int) -> str:
    """装窑照片占位图：窑内剖面 + 棚板层。"""
    width, height = 480, 320
    shelves = []
    top, bottom = 70, 280
    for i in range(shelf_count):
        y = top + (bottom - top) * i / max(1, shelf_count - 1)
        shelves.append(
            f'<line x1="90" y1="{y:.0f}" x2="390" y2="{y:.0f}" stroke="#8a7a68" stroke-width="5"/>')
        for j in range(min(item_count // shelf_count + 1, 5)):
            x = 130 + j * 55
            shelves.append(
                f'<path d="M{x} {y - 4:.0f} q6 -22 14 -22 q8 0 14 22 z" '
                f'fill="#c98f5f" stroke="#8a5a33" stroke-width="1.5"/>')
    shelves_svg = "".join(shelves)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="{width}" height="{height}" fill="#f7f1e8"/>
  <rect x="60" y="40" width="360" height="260" rx="26" fill="#e8dfcf" stroke="#b09a7c" stroke-width="3"/>
  <rect x="84" y="56" width="312" height="228" rx="16" fill="#4a3b2e"/>
  {shelves_svg}
  <text x="240" y="30" text-anchor="middle" font-size="16" fill="#3b332b" font-family="sans-serif">装窑照片 · {batch_name}</text>
  <text x="240" y="312" text-anchor="middle" font-size="12" fill="#8a7a68" font-family="sans-serif">{kiln_name} · 共 {item_count} 件作品</text>
</svg>"""


def finished_photo_svg(code: str, glaze_color: str, dims: str) -> str:
    """成品照片占位图：釉色小花瓶。"""
    width, height = 360, 360
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="{width}" height="{height}" fill="#f7f1e8"/>
  <ellipse cx="180" cy="320" rx="110" ry="14" fill="#e3d9c6"/>
  <path d="M150 90 q-6 30 -34 60 q-40 44 -40 96 q0 60 104 60 q104 0 104 -60 q0 -52 -40 -96 q-28 -30 -34 -60 z"
        fill="{glaze_color}" stroke="#3b332b" stroke-width="2.5"/>
  <ellipse cx="180" cy="90" rx="30" ry="9" fill="#fdfaf3" stroke="#3b332b" stroke-width="2.5"/>
  <path d="M120 210 q60 26 120 0" stroke="#ffffff" stroke-opacity="0.45" stroke-width="7" fill="none"/>
  <text x="180" y="46" text-anchor="middle" font-size="18" fill="#3b332b" font-family="sans-serif">成品 · {code}</text>
  <text x="180" y="345" text-anchor="middle" font-size="12" fill="#8a7a68" font-family="sans-serif">{dims}</text>
</svg>"""


def write_seed_photos(photos_dir: str) -> dict[str, str]:
    """生成样例照片文件，返回 {逻辑名: 文件名}。"""
    os.makedirs(photos_dir, exist_ok=True)
    files = {
        "loading_b2": ("seed_loading_b2.svg",
                       loading_photo_svg("一号窑·素烧·今日", "一号窑", 4, 2)),
        "loading_b4": ("seed_loading_b4.svg",
                       loading_photo_svg("二号窑·釉烧·样例", "二号窑", 3, 4)),
        "finished_w01": ("seed_finished_w01.svg",
                         finished_photo_svg("W001", "#7fb3d5", "12×12×15 cm")),
        "finished_w02": ("seed_finished_w02.svg",
                         finished_photo_svg("W002", "#e2631e", "10×10×9 cm")),
    }
    out = {}
    for key, (filename, svg) in files.items():
        path = os.path.join(photos_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        out[key] = filename
    return out
