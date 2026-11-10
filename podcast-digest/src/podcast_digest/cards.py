from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


PORTRAIT = (1080, 1440)
LANDSCAPE = (1920, 1080)
FONT_CANDIDATES = {
    "bold": [("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
             ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0)],
    "regular": [("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
                ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0)],
}
NO_LINE_START = "，。、；：！？）」』”’》,.;:!?)"
TOKEN_RE = re.compile(r"[A-Za-z0-9][\w.\-'’%+/]*\s*|\s+|.", re.UNICODE)


@dataclass(frozen=True)
class Theme:
    background: str
    accent: str
    text: str
    muted: str
    panel: str


THEMES = {
    "professional": Theme("#F5F7FA", "#1F3A5F", "#16202C", "#5B6675", "#FFFFFF"),
    "warm": Theme("#FBF6EE", "#E2583E", "#2A211C", "#7A6A60", "#FFFFFF"),
}


def theme_for(style: str) -> Theme:
    return THEMES["professional" if style == "professional" else "warm"]


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("Image cards need Pillow: pip install 'podcast-digest[social]'") from exc
    return Image, ImageDraw, ImageFont


@lru_cache(maxsize=64)
def font(weight: str, size: int) -> "ImageFont.FreeTypeFont":
    for path, index in FONT_CANDIDATES[weight]:
        if Path(path).exists():
            return _pil()[2].truetype(path, size, index=index)
    raise FileNotFoundError("No CJK font found; install fonts-noto-cjk")


def wrap(draw: "ImageDraw.ImageDraw", text: str, fnt: "ImageFont.FreeTypeFont", width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for token in TOKEN_RE.findall(text):
        candidate = current + token
        if current and draw.textlength(candidate.rstrip(), font=fnt) > width:
            lines.append(current.rstrip())
            current = token.lstrip()
        else:
            current = candidate
    if current.strip():
        lines.append(current.rstrip())
    return balance_cjk_lines(lines)


def balance_cjk_lines(lines: list[str], min_tail: int = 3) -> list[str]:
    """Keeps punctuation off line starts and avoids a one- or two-character last line."""
    lines = list(lines)
    for i in range(1, len(lines)):
        while lines[i] and lines[i][0] in NO_LINE_START:
            lines[i - 1] += lines[i][0]
            lines[i] = lines[i][1:]
    lines = [line for line in lines if line]
    if len(lines) >= 2 and len(lines[-1]) < min_tail:
        prev = lines[-2]
        take = min_tail - len(lines[-1])
        if len(prev) > take + min_tail and all(_is_cjk(c) for c in prev[-take:]):
            lines[-2], lines[-1] = prev[:-take], prev[-take:] + lines[-1]
    return lines


def _is_cjk(char: str) -> bool:
    return "\u3400" <= char <= "\u9fff"


def _fit(draw, text: str, weight: str, size: int, width: int, max_lines: int, min_size: int = 28):
    while True:
        fnt = font(weight, size)
        lines = wrap(draw, text, fnt, width)
        if len(lines) <= max_lines or size <= min_size:
            return fnt, lines
        size -= 4


def _draw_lines(draw, lines, fnt, x, y, fill, spacing=1.35) -> int:
    step = int(fnt.size * spacing)
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += step
    return y


def _pill(draw, x, y, text, theme: Theme, size=34) -> int:
    fnt = font("bold", size)
    pad_x, pad_y = 26, 12
    w = draw.textlength(text, font=fnt)
    height = size + 2 * pad_y + 6
    draw.rounded_rectangle((x, y, x + w + 2 * pad_x, y + height), radius=40, fill=theme.accent)
    draw.text((x + pad_x, y + height / 2), text, font=fnt, fill=theme.panel, anchor="lm")
    return y + size + 2 * pad_y + 6


def render_cover(dest: Path, title: str, subtitle: str, podcast: str, episode: str,
                 theme: Theme, brand: str = "", size=PORTRAIT, footer: str = "AI 辅助整理 · 内容来自原节目",
                 source_prefix: str = "来源：") -> Path:
    image, image_draw, _ = _pil()
    img = image.new("RGB", size, theme.background)
    draw = image_draw.Draw(img)
    w, h = size
    margin = int(w * 0.08)
    landscape = w > h
    draw.rectangle((0, 0, w, 18), fill=theme.accent)
    y = _pill(draw, margin, int(h * 0.09), (brand or "播客精华")[:28], theme, size=34 if not landscape else 38)
    y += int(h * 0.06)
    title_font, title_lines = _fit(draw, title, "bold", 150 if not landscape else 130, w - 2 * margin, 3)
    y = _draw_lines(draw, title_lines, title_font, margin, y, theme.text, 1.25)
    draw.rectangle((margin, y + 20, margin + 140, y + 32), fill=theme.accent)
    y += 80
    sub_font, sub_lines = _fit(draw, subtitle, "regular", 60 if not landscape else 54, w - 2 * margin, 3)
    _draw_lines(draw, sub_lines, sub_font, margin, y, theme.muted)
    foot_font = font("regular", 30)
    bottom = h - int(h * (0.24 if landscape else 0.07))
    ep_lines = wrap(draw, f"{source_prefix}{podcast} · {episode}", foot_font, w - 2 * margin)[:2]
    _draw_lines(draw, ep_lines + [footer], foot_font, margin, bottom - 45 * len(ep_lines), theme.muted, 1.5)
    img.save(dest)
    return dest


def render_card(dest: Path, number: int, page: int, total: int, heading: str, points: list[str],
                podcast: str, theme: Theme, size=PORTRAIT) -> Path:
    image, image_draw, _ = _pil()
    img = image.new("RGB", size, theme.background)
    draw = image_draw.Draw(img)
    w, h = size
    margin = int(w * 0.08)
    draw.rectangle((0, 0, w, 18), fill=theme.accent)
    draw.text((margin, int(h * 0.07)), f"{number:02d}", font=font("bold", 96), fill=theme.accent)
    head_font, head_lines = _fit(draw, heading, "bold", 84, w - 2 * margin, 2)
    y = _draw_lines(draw, head_lines, head_font, margin, int(h * 0.17), theme.text, 1.25) + 40
    panel_top = y
    body_width = w - 2 * margin - 110
    for size_pt in range(60, 30, -2):
        point_font = font("regular", size_pt)
        wrapped = [wrap(draw, p, point_font, body_width) for p in points]
        needed = sum(len(lines) * int(size_pt * 1.45) + int(size_pt * 1.2) for lines in wrapped) + 60
        if panel_top + needed < h - 170:
            break
    draw.rounded_rectangle((margin, panel_top, w - margin, panel_top + needed), radius=36, fill=theme.panel)
    y = panel_top + 40
    for lines in wrapped:
        draw.ellipse((margin + 40, y + size_pt * 0.35, margin + 62, y + size_pt * 0.35 + 22), fill=theme.accent)
        y = _draw_lines(draw, lines, point_font, margin + 86, y, theme.text, 1.45) + int(size_pt * 1.2)
    foot = font("regular", 30)
    draw.text((margin, h - 110), podcast[:40], font=foot, fill=theme.muted)
    label = f"{page}/{total}"
    draw.text((w - margin - draw.textlength(label, font=foot), h - 110), label, font=foot, fill=theme.muted)
    img.save(dest)
    return dest


def render_social_cards(out_dir: Path, post: dict, podcast: str, episode: str, style: str,
                        brand: str = "") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    theme = theme_for(style)
    cards = post["cards"]
    total = len(cards) + 1
    paths = [render_cover(out_dir / "00_cover.png", post["cover_title"], post["cover_subtitle"],
                          podcast, episode, theme, brand=brand)]
    paths += [
        render_card(out_dir / f"{i:02d}_card.png", i, i + 1, total, c["heading"], c["points"], podcast, theme)
        for i, c in enumerate(cards, start=1)
    ]
    return paths
