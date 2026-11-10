from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Brand:
    name: str
    tagline: str


DEFAULT_BRANDS = {
    "zh": Brand(name="长话短听", tagline="与最优秀的思想并肩。"),
    "en": Brand(name="The Short Listen", tagline="Keep company with the best minds."),
}
INTRO_TEMPLATES = {
    "zh": "{tagline}这里是{name}。",
    "en": "{tagline} This is {name}.",
}


def brand_for(code: str, name: str | None = None, tagline: str | None = None) -> Brand:
    default = DEFAULT_BRANDS.get(code, DEFAULT_BRANDS["en"])
    return Brand(
        name=name or os.environ.get("PD_BRAND_NAME") or default.name,
        tagline=tagline or os.environ.get("PD_BRAND_TAGLINE") or default.tagline,
    )


def intro(code: str, brand: Brand) -> str:
    return INTRO_TEMPLATES.get(code, INTRO_TEMPLATES["en"]).format(name=brand.name, tagline=brand.tagline)
