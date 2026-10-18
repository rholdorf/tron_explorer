"""The use prompt's text per ActivateType (attributes/activatetypes.txt; CActivateTypeMgr, CTargetMgr).

Each [ActivateTypeN] section has a Name (what an object's ActivateType prop names) and a cres.dll string
ID per state: StateON for an object on or powering on, StateOFF for off or powering off, -1 for no text.
cres.dll isn't extracted; the comment after each ID is the English string, so that is the text we use.
"""
import functools
import os
import re

_SECTION = re.compile(r"^\s*\[(ActivateType\d+)\]", re.I)
_NAME = re.compile(r'^\s*Name\s*=\s*"([^"]*)"', re.I)
_STATE = re.compile(r"^\s*State(ON|OFF)\s*=\s*(-?\d+)\s*(?://\s*(.*))?$", re.I)


@functools.lru_cache(maxsize=None)
def prompts(extracted):
    """{type name: (StateON text, StateOFF text)}, "" where the state has no text."""
    with open(os.path.join(extracted, "attributes", "activatetypes.txt"), "rb") as f:
        lines = f.read().decode("latin-1").splitlines()
    out, name, states = {}, None, {}

    def flush():
        if name is not None:
            out[name] = (states.get("ON", ""), states.get("OFF", ""))

    for line in lines:
        if _SECTION.match(line):
            flush()
            name, states = None, {}
        elif m := _NAME.match(line):
            name = m.group(1)
        elif m := _STATE.match(line):
            states[m.group(1).upper()] = (m.group(3) or "").strip() if int(m.group(2)) >= 0 else ""
    flush()
    return out


# Classes whose ActivateType is set in code, not by a prop (SecRezzer::ReadProp, object.lto 0x10043660).
CLASS_TYPES = {"SecRezzer": "Disable Secrezzer"}


def level_types(objects, extracted):
    """The ActivateTypes a level's objects (dat85 form) name, by name, with their texts:
    [{"name", "on", "off"}]. Unknown names and <none> are left out."""
    table = prompts(extracted)
    names = {CLASS_TYPES.get(o["class"]) or o["props"].get("ActivateType") for o in objects}
    return [{"name": n, "on": table[n][0], "off": table[n][1]} for n in sorted(n for n in names if n in table)]
