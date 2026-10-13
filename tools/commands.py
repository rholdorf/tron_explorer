"""The command language's grammar (docs/research/command-language.md): the engine's tokenizer and the
command manager's verb table. The viewer runs commands itself (TronViewer/.../Commands.cs, the same
tokenizer, keyframer key commands included); this copy serves the tests that check both against every
command string in the levels.

Tokenizer: ConParse (ltjs conparse.cpp cp_GetNextToken / cp_Parse, the same loop in Tron's Lithtech.exe).
"""

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
