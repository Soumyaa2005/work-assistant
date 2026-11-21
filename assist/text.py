import re

STOP = set("""a an the of to for and or in on at is are was were be been it this that with from by as about what
who whom which when where how did do does done has have had me my i you your we our us they them their he she
his her its not no yes any some please send show tell give get got can could should would will now status
owns own owner handles handle responsible due deadline whats what's""".split())

_word = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")
_SUFFIXES = ("ing", "er", "ed", "s")

INJECTION = re.compile(
    r"\bassistant\s*:|ignore (your|all|any|previous|the above)|disregard (your|all|previous)|"
    r"\bmark\b.{0,40}\bas\b.{0,12}\b(at risk|healthy|approved)|system prompt|you must now|new instructions",
    re.I)


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
