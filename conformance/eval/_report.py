"""What the questions share: reading what an Agent told the person, in English or Chinese.

An Agent writes its report in its own words and markup, so these checks look for meaning, not
for one exact sentence.
"""
import re

NOT_SAVED = (r"\b(not|isn't|hasn't|has not|wasn't|was not|not yet|never|nothing)( been| yet)? saved\b|\bunsaved\b"
             r"|\bsaved\s*[:：-]?\s*(no|not)\b|未保存|没有保存|尚未保存|还没保存|没保存")
SAVED = (r"\bsaved\s*[:：-]?\s*yes\b|\b(is|was|has been|have been|now|got) saved\b|\bsaved (it|the|board|to disk|all)\b"
         r"|已保存|已经保存|保存好了|保存成功")
NOT_VERIFIED = r"\bnot (been )?verified\b|\bunverified\b|\bverified\s*[:：-]?\s*no\b|未验证|没有验证|没验证"


def plain(text: str) -> str:
    """The text in lower case, without Markdown emphasis, table bars or code marks."""
    return re.sub(r"\s+", " ", re.sub(r"[*`|#>]+", " ", text.lower()))


def says_not_saved(text: str) -> bool:
    return re.search(NOT_SAVED, plain(text)) is not None


def says_saved(text: str) -> bool:
    return re.search(SAVED, plain(text)) is not None


def says_verified(text: str) -> bool:
    words = plain(text)
    return ("verif" in words or "验证" in words) and re.search(NOT_VERIFIED, words) is None
