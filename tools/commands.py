"""The command language's grammar (docs/research/command-language.md): the engine's tokenizer and the
command manager's verb table. The viewer runs commands itself (TronViewer/.../Commands.cs, the same
tokenizer, keyframer key commands included); this copy serves the tests that check both against every
command string in the levels.

Tokenizer: ConParse (ltjs conparse.cpp cp_GetNextToken / cp_Parse, the same loop in Tron's Lithtech.exe).
The levels' command strings and what they run (level_commands, executed) also give the exporter the
names spawners create (spawn_names).
"""
import collections
import re


MAX_ARGS = 30        # PARSE_MAXARGS: words per statement; the 30th ends the statement and the parse
MAX_ARG_LEN = 256    # PARSE_MAXARGLEN: characters kept per word

# CCommandMgr::s_ValidCmds: verb -> word count, verb included (Tron's object.lto has the same table).
VERBS = {"LISTCOMMANDS": 1, "MSG": 3, "VMSG": 3, "RAND": 4, "RAND2": 3, "RAND3": 4, "RAND4": 5, "RAND5": 6,
         "RAND6": 7, "RAND7": 8, "RAND8": 9, "REPEAT": 6, "REPEATID": 7, "DELAY": 3, "DELAYID": 4, "LOOP": 4,
         "LOOPID": 5, "ABORT": 2, "SET": 3, "ADD": 3, "SUB": 3, "IF": 4, "INT": 3, "OBJ": 3, "WHEN": 4,
         "SHOWVAR": 3}

_NO_TOKEN, _TOKEN, _SEMICOLON = range(3)
_DEPTH_MASK = 0xffffffff   # the paren depth is an unsigned 32-bit LTBOOL: a stray ')' wraps it


def _separator(c):
    return c == ";" or ord(c) <= 31 or ord(c) == 127


def _next_token(s, i):
    """cp_GetNextToken from position i: (status, token, new position)."""
    while i < len(s) and s[i] == " ":
        i += 1
    if i >= len(s):
        return _NO_TOKEN, "", i
    tok, depth = [], 0

    def add(c):
        if len(tok) < MAX_ARG_LEN:
            tok.append(c)

    while True:
        c = s[i] if i < len(s) else "\0"
        end = False
        if c == "\0":
            end = True
        elif c == "%":
            i += 1
            if i >= len(s) or s[i] == "\0":
                end = True
            else:
                add(s[i])
        elif _separator(c):
            if not tok:
                return _SEMICOLON, "", i + 1
            return _TOKEN, "".join(tok), i
        elif c == "(":
            depth = (depth + 1) & _DEPTH_MASK
            if depth != 1:
                add(c)
        elif c == ")":
            depth = (depth - 1) & _DEPTH_MASK
            if depth == 0:
                i += 1
                end = True
            else:
                add(c)
        elif c == '"':
            if depth:
                i += 1
                end = True
            else:
                depth = 1
        elif c == " " and depth == 0:
            end = True
        else:
            add(c)
        if end:
            return (_TOKEN if tok else _NO_TOKEN), "".join(tok), i
        i += 1


def statements(text):
    """The statements of a command string, each its list of words, as the engine's ConParse::Parse
    loop sees them (empty statements included; callers skip them)."""
    out, i = [], 0
    while True:
        args, more = [], False
        while True:
            status, tok, i = _next_token(text, i)
            if status == _NO_TOKEN:
                break
            if status == _SEMICOLON:
                more = True
                break
            args.append(tok)
            if len(args) >= MAX_ARGS:
                break
        out.append(args)
        if not more:
            return out


def verb_count(words):
    """The verb's word count if `words` is a statement the command manager runs, else None."""
    if not words:
        return None
    n = VERBS.get(words[0].upper())
    return n if n == len(words) else None


def is_valid(text):
    """CCommandMgr::IsValidCmd: whether a command string runs at all (only its first statement counts)."""
    return verb_count(statements(text)[0]) is not None


# ---- The levels' command strings ----

# Properties the engine reads as command strings: a name ending in Command / Cmd with an optional number
# (not CustomCmd*), CommandObject events EventTnEm (the part after '|'), AI Initial / ActivateOn /
# ActivateOff, ArchiveBin OnWithdrawN, Optimizer OnActivate / OnOptimize.
PROP = re.compile(r"(?i)((?<!custom)(command|cmd)\d*$|^EventT\d+E\d+$|^(Initial|ActivateOn|ActivateOff|"
                  r"OnWithdraw\d*|OnActivate|OnOptimize)$)")
AI_MIXED = {"Initial", "ActivateOn", "ActivateOff"}   # CAIHuman: split the AI's way (SendMixedTriggerMsgToObject)
# Words of a verb that are nested commands.
NESTED = {"DELAY": [2], "DELAYID": [3], "LOOP": [3], "LOOPID": [4], "REPEAT": [5], "REPEATID": [6], "RAND": [2, 3],
          **{f"RAND{n}": list(range(1, n + 1)) for n in range(2, 9)}}
PLAYER_NAMES = {"player", "activeplayer", "otherplayers"}   # the names that resolve without an object


def level_commands(w):
    """(class, property, command string) for every command string in a loaded level (dat85): every
    non-empty PROP string, and every KeyFramer key command. "<none>" (the editor's empty value) and
    numbers aren't commands."""
    import keyframer
    out = []
    for o in w.objects:
        for k, v in o["props"].items():
            if not isinstance(v, str) or not PROP.search(k):
                continue
            if re.fullmatch(r"(?i)EventT\d+E\d+", k):
                v = v.split("|", 1)[1] if "|" in v else ""
            if v.strip() and v.strip() != "<none>" and not re.fullmatch(r"[\d.\s-]+", v):
                out.append((o["class"], k, v))
        if o["class"] == "KeyFramer":
            index = o["props"].get("KeyDataIndex", -1.0)
            if 0 <= index < len(w.blind):
                out += [("KeyFramer", "key", k["command"]) for k in keyframer.read_keys(w.blind[int(index)][1])
                        if k["command"].strip()]
    return out


def mixed_parts(text):
    """ParseTriggerMsg (ltjs serverutilities.cpp): the AI's split of a mixed message, on ';' outside
    parentheses and quotes. Parts that are valid commands run as commands."""
    parts, start, depth, quote = [], 0, 0, False
    for i, c in enumerate(text):
        if c == "(" and not quote:
            depth += 1
        elif c == ")" and not quote and depth:
            depth -= 1
        elif c == '"':
            quote = not quote
        elif c == ";" and not quote and not depth:
            parts.append(text[start:i])
            start = i + 1
    return parts + [text[start:]]


def executed(prop, text):
    """Every statement a command property can run, its verb and word count right: the string's own,
    the nested commands of delay / loop / rand..., and messages that are themselves commands
    (`msg player (add inner 1)`). AI mixed messages run their valid parts."""
    out = []

    def walk(t):
        for words in statements(t):
            if verb_count(words) is None:
                continue
            out.append(words)
            verb = words[0].upper()
            for i in NESTED.get(verb, []):
                if is_valid(words[i]):
                    walk(words[i])
            if verb == "MSG" and is_valid(words[2]):
                walk(words[2])

    for part in mixed_parts(text) if prop in AI_MIXED else [text]:
        if is_valid(part):
            walk(part)
    return out


def target_name(target):
    """A msg target's object name: a `<Class>` prefix is ignored ("" is the active target)."""
    return re.sub(r"^<[^>]*>", "", target)


def spawn_names(w):
    """The names Spawners give the objects they create, with the class of each spawner's Target template:
    [{"name", "cls"}] (cls "" when the Target names no template). A name counts when any command of the
    level sends `spawn <name>` or `spawnfrom <object> <name>` to a Spawner, directly or through Groups,
    whether or not it ever runs (docs/research/no-object-targets.md). Templates never exist, so they
    don't receive messages."""
    live = collections.defaultdict(list)
    templates = {}
    for o in w.objects:
        name = o["props"].get("Name", "").lower()
        if o["props"].get("Template"):
            templates.setdefault(name, o["class"])
        else:
            live[name].append(o)

    def spawners(name, seen):
        if name in seen:
            return []
        out = []
        for o in live.get(name, []):
            if o["class"] == "Spawner":
                out.append(o)
            elif o["class"] == "Group":
                out += [s for i in range(1, 51) if o["props"].get(f"Object{i}")
                        for s in spawners(o["props"][f"Object{i}"].lower(), seen | {name})]
        return out

    found = {}
    for _, prop, text in level_commands(w):
        for words in executed(prop, text):
            if words[0].upper() != "MSG":
                continue
            to = spawners(target_name(words[1]).lower(), frozenset())
            for m in statements(words[2]) if to else []:
                verb = m[0].lower() if m else ""
                name = m[1] if verb == "spawn" and len(m) >= 2 else m[2] if verb == "spawnfrom" and len(m) >= 3 else ""
                for s in to if name else []:
                    found.setdefault(name.lower(), {"name": name,
                                                    "cls": templates.get(s["props"].get("Target", "").lower(), "")})
    return sorted(found.values(), key=lambda s: s["name"].lower())
