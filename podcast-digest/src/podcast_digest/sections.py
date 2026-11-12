from __future__ import annotations

import re
from dataclasses import dataclass

MARKER_RE = re.compile(r"^\s*((?:问题[一二三四五六七八九十百零〇两\d]+)|结语|Question \d+|Wrap-up)[：:]\s*", re.M)
CN_DIGITS = "零一二三四五六七八九"


@dataclass(frozen=True)
class Section:
    label: str
    text: str

    @property
    def is_question(self) -> bool:
        return self.label.startswith(("问题", "Question"))

    @property
    def heading(self) -> str:
        """The first sentence after the marker: the question itself for question sections."""
        body = MARKER_RE.sub("", self.text, count=1).strip()
        match = re.match(r"(.+?[？?])", body)
        return (match.group(1) if match else body.split("\n", 1)[0]).strip()


def split_sections(script: str) -> list[Section]:
    """Splits a script at 问题N：/结语： markers. Text before the first marker is the 'opening'."""
    matches = list(MARKER_RE.finditer(script))
    if not matches:
        return [Section("opening", script.strip())]
    sections = []
    if script[: matches[0].start()].strip():
        sections.append(Section("opening", script[: matches[0].start()].strip()))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(script)
        sections.append(Section(match.group(1), script[match.start():end].strip()))
    return sections


def chinese_number(n: int) -> str:
    if n < 10:
        return CN_DIGITS[n]
    tens, ones = divmod(n, 10)
    return ("" if tens == 1 else CN_DIGITS[tens]) + "十" + (CN_DIGITS[ones] if ones else "")
