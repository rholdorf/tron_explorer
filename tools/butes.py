"""Reader for the game's attribute files (attributes/*.txt, the "butes" format).

    // comment   /* block comment */
    [Section]
    Key = "string" | 123 | 1.5 | <x, y, z> | [a, b] | TRUE | FALSE

Keys are case-insensitive (the files mix Skin0/skin2). Values keep their natural Python type;
strings use backslashes as written.
"""
import re

_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|<[^>]*>|\[[^\]]*\]|[^\s/]+')


def _strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = []
    for line in text.splitlines():
        # // starts a comment unless inside a string
        in_str, cut = False, len(line)
        for i, ch in enumerate(line):
            if ch == '"':
                in_str = not in_str
            elif not in_str and line.startswith("//", i):
                cut = i
                break
        out.append(line[:cut])
    return out


def _value(raw):
    raw = raw.strip()
    if raw.startswith('"'):
        return raw[1:-1]
    if raw.startswith("<") or raw.startswith("["):
        return [float(x) for x in re.split(r"[,\s]+", raw[1:-1].strip()) if x]
    up = raw.upper()
    if up in ("TRUE", "FALSE"):
        return up == "TRUE"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw.rstrip("fF"))
    except ValueError:
        return raw


def load(path):
    """Returns {section name: {lowercased key: value}} in file order."""
    with open(path, "rb") as f:
        text = f.read().decode("latin-1")
    sections, cur = {}, None
    for line in _strip_comments(text):
        s = line.strip()
        if not s:
            continue
        if s.startswith("[") and s.endswith("]") and "=" not in s:
            cur = sections.setdefault(s[1:-1], {})
            continue
        if cur is None or "=" not in s:
            continue
        key, val = s.split("=", 1)
        cur[key.strip().lower()] = _value(val)
    return sections


def indexed(section, prefix):
    """Values of prefix0, prefix1, ... until the first gap (Skin0..SkinN, RenderStyle0..N)."""
    out = []
    while f"{prefix}{len(out)}" in section:
        out.append(section[f"{prefix}{len(out)}"])
    return out


def norm(path):
    """A resource path as written in attribute files and level properties, as the extracted tree names
    it: forward slashes, lower case."""
    return path.replace("\\", "/").strip().lower()
