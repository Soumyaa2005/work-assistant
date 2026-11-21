from __future__ import annotations
import re

STOP = set("""a an the of to for and or in on at is are was were be been it this that with from by as about what
who whom which when where how did do does done has have had me my i you your we our us they them their he she
his her its not no yes any some please send show tell give get got can could should would will now status
owns own owner handles handle responsible due deadline whats what's""".split())

_word = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")
_SUFFIXES = ("ing", "er", "ed", "s")

INJECTION = re.compile(
    r"\bassistant\s*:|\bsystem\s*:|<\s*/?\s*system|\[\s*system|"
    r"ignore (your|all|any|previous|the above|prior|earlier)|disregard (your|all|any|previous|prior|the above)|"
    r"forget (all |your |any |previous |prior )?(instructions|rules)|override (your|all|any|previous|the) (instructions|rules|guidelines|settings|safeguards)|"
    r"\bmark\b.{0,40}\bas\b.{0,12}\b(at risk|healthy|approved|green|red)|system prompt|developer mode|jailbreak|"
    r"you must now|you are now|new instructions|act as (the |an? )|pretend (you|to)|"
    r"reveal .{0,40}(private|confidential|secret|other client|other compan)|do not (tell|mention|follow)|"
    r"disregard\b.{0,40}\b(earlier|previous|prior|above|told)\b|\b(?:note|message|instructions?)\s+(?:to|for)\s+(?:the\s+)?(?:assistant|ai|bot|model|llm)\b|"
    r"\b(?:assistant|ai|chatbot|llm)\b\s*[,:]\s*(?:please\s+)?(?:always|never|do|reply|respond|say|report|mark|ignore|forget|tell|answer|output)\b|"
    r"\bplease\s+always\s+(?:report|say|answer|respond|reply|tell)\s+(?:that|everyone|the\s+reader)\b",
    re.I)

_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATE = (r"(?:\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MON + r"\b|" + _MON + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?\b)")
_DATE_RX = re.compile(r"(?i)(?:(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + _MON + r")|(" + _MON + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?)")

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def norm_date(s: str) -> str | None:
    """'14th November' / 'Nov 14' / '14 nov' -> '14 Nov'."""
    m = _DATE_RX.search(s or "")
    if not m:
        return None
    day, mon = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
    return f"{int(day)} {mon[:3].capitalize()}"


def tokens(s: str) -> list[str]:
    return [t.lower() for t in _word.findall(s or "")]


def stem(t: str) -> str:
    for _ in range(2):
        for suf in _SUFFIXES:
            if t.endswith(suf) and len(t) - len(suf) >= 3:
                t = t[: -len(suf)]
                break
    return t


def terms(s: str) -> set[str]:
    return {stem(t) for t in tokens(s) if t not in STOP and len(t) > 1}


def sentences(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", s or "") if x.strip()]


def first_sentence(s: str, limit: int = 220) -> str:
    ss = sentences(s)
    return (ss[0] if ss else (s or ""))[:limit]


def cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s
