# Command language: grammar, dispatch and messages

Research for #29 (map #28). Question: how does the engine parse and run commands, and what does each
class we will support do with its messages?

Sources:

- **ltjs** (`bibendovsky/ltjs`, the NOLF2/Jupiter code Tron builds on):
  `engine/runtime/shared/src/conparse.cpp` (tokenizer), `game/objectdll/objectshared/commandmgr.cpp/.h`
  (verbs, scheduler), `serverutilities.cpp` (`SendTriggerMsgToObjects`, `ParseTriggerMsg`),
  `gamebase.cpp`, `gamebaselite.cpp`, `worldmodel.cpp`, `activeworldmodel.cpp`, `keyframer.cpp`,
  `serversoundfx.cpp`, `trigger.cpp`, `group.cpp`, `eventcounter.cpp`, `commandobject.cpp`,
  `startupcommand.cpp`, `spawner.cpp`, `prop.cpp`, `character.cpp`, `ai.cpp`, `gameservershell.cpp`,
  `engine/runtime/server/src/servermgr.cpp`, `serverde_impl.cpp`.
- **Tron retail binaries**: `Lithtech.exe` (the tokenizer, disassembled at `0x419510`) and
  `extracted/object.lto` (verb table strings at file offset `0x2d32a0`; each `OnTrigger`'s
  function-static `CParsedMsg::CToken` initialisers, which list the message words a class accepts).
- **Levels**: every command string in the 38 `retailsingleplayer` worlds (the charting survey's
  extraction from the `.dat` files, including keyframer key commands), run through an engine-faithful
  Python model of the tokenizer and dispatcher.

Where a claim is from ltjs only (not checked against Tron's binaries) it says so.

## Answer in short

- A command string is a list of **statements** separated by `;` **or any control character**
  (CR, LF, tab). A `;` splits a statement **even inside parentheses**: parentheses group words, but
  they can't hold a `;`. Designers rely on this: the closing parentheses are often left out.
- A statement is words separated by spaces. `( … )` or `" … "` make one word (the outer pair is
  stripped, inner pairs are kept). `%` escapes the next character.
- The first word is the **verb** (any case). The statement runs only if its word count is
  **exactly** the verb's count. An unknown verb or a wrong count skips that statement silently.
- **Every caller checks only the first statement** (`IsValidCmd`) before running a string. If the
  first statement isn't a valid command, **nothing in the string runs**. This is how `*msg`,
  `xmsg`, `COMMENTOUT[…]` and `(FR)msg` comment a string out.
- A verb that **fails** stops the rest of the string. In the levels the only verb that can fail is
  `ABORT` with an id that isn't pending.
- `msg` is **synchronous**: the target handles the message right away, before the next statement
  of the string runs. `delay` queues a command. The queue is ticked once per server frame, before the
  objects update.
- Tron's verb table is NOLF2's, unchanged. Tron adds message words to some classes:
  `EventCounter` `RESET` (used 36 times) and `REPORT`; `KeyFramer` `RESETPATH`; `ActiveWorldModel`
  `ADDPSET` / `REMOVEPSET` / `INFOSTRING`; `WorldModel` `ATTACHSTANDINGON`.
- Validation: all 16,418 command strings in the levels go through the grammar. 15,782 run as a whole,
  599 are AI mixed messages, and 37 never run (32 commented out, plus 5 `addgoal` spawner commands
  that have no verb). Inside the strings that run, 3 statements are typos and get skipped. See
  [Validation](#validation-against-the-levels).

## Tokenizer (ConParse)

`cp_GetNextToken` / `cp_Parse` (ltjs `conparse.cpp`). Tron's `Lithtech.exe` has the same loop,
inlined in `ConParse::Parse` at `0x419510`. It was checked instruction by instruction: `%` = `0x25`,
`;` = `0x3b`, control chars `0x00–0x1f` / `0x7f`, `(` `)` `"`, 30 arguments (`0x1e`), 256 characters
per argument (`0x100`).

```
next_token:
  skip ' ' (only the space character; tab is a separator, see below)
  end of string            -> no token
  depth = 0 (unsigned 32-bit), token = ""
  loop over chars c:
    NUL                    -> end token
    '%'                    -> append the next char verbatim (NUL: end)
    ';' or control char    -> if token empty: consume it, return SEMICOLON
                              else return token (the ';' is seen again by the next call)
                              (no depth check: a ';' inside parentheses splits too)
    '('                    -> depth++; the first '(' is dropped, nested ones are kept
    ')'                    -> depth--; if depth == 0: consume, end token; else keep the ')'
    '"'                    -> if depth != 0: consume, end token; else depth = 1 (dropped)
    ' ' and depth == 0     -> end token
    else                   -> append (a token keeps at most 256 chars)
  an empty token at the end ("()" or "") -> no token: the parse stops there

statement: tokens until SEMICOLON (more statements follow) or no token (last one);
           after 30 tokens the statement ends and so does the whole parse
```

Things that follow from this, all seen in the levels:

- `delay .25 (msg a (hidden 0); msg b off` is two statements: `delay .25 "msg a (hidden 0)"` and
  `msg b off`, which runs **now**. A reader that tracks parentheses would nest `msg b off` inside the
  delay. The engine doesn't (179 strings differ).
- `delay 2.5 (msg x on;)` runs the delay, then a statement whose only word is `)`. That word is
  skipped (48 such leftovers).
- A `)` with nothing open is kept as a character, and the depth wraps to 2³²−1, so spaces stop
  ending words until a `(` brings it back to 0. `LTBOOL` is `unsigned int` (ltjs
  `engine/sdk/inc/ltbasetypes.h`), and Tron's binary tests `depth != 0` after the decrement.
- CR/LF line breaks (931 strings) end statements. With CRLF each break gives one extra empty
  statement, which is ignored.
- `(FR)msg player …` gives first word `FR`: the whole string is dead.

### Mixed messages (AI only)

`CAIHuman` `Initial`, `ActivateOn` and `ActivateOff` don't go through the command manager directly.
`SendMixedTriggerMsgToObject` splits them with `ParseTriggerMsg`, which splits on `;` only
**outside** parentheses and quotes. Each part goes to the AI itself. A part that is a valid command
(`IsValidCmd`) runs as a command, and the rest are AI messages. This is the only paren-aware
splitter, and only the AI uses it.

## Verbs (CCommandMgr::s_ValidCmds)

The count includes the verb. Verbs match case-insensitively (`_stricmp`). Tron's `object.lto` has
the same 26 entries and syntax strings (file offset `0x2d32a0`–`0x2d36fc`).

| Verb | Words | Form | Uses in levels |
|---|---|---|---|
| `MSG` | 3 | `msg <targets> <message>` | 27,830 |
| `VMSG` | 3 | like `msg`, but the targets are object variables | 0 |
| `DELAY` | 3 | `delay <seconds> <cmd>` | 3,707 |
| `DELAYID` | 4 | `delayid <id> <seconds> <cmd>` | 13 |
| `LOOP` | 4 | `loop <min> <max> <cmd>`: every random(min,max) seconds, forever | 2 |
| `LOOPID` | 5 | `loopid <id> <min> <max> <cmd>` | 84 |
| `REPEAT` / `REPEATID` | 6 / 7 | `[id] <minTimes> <maxTimes> <minDelay> <maxDelay> <cmd>` | 0 |
| `ABORT` | 2 | `abort <id>`: removes the **first** pending command with that id | 105 |
| `RAND` | 4 | `rand <p> <cmd1> <cmd2>`: cmd1 with probability p (0.001 ≤ p ≤ 1, else it fails) | 8 |
| `RAND2`…`RAND8` | n+1 | pick one of n commands uniformly | 53 |
| `INT` / `OBJ` | 3 | declare an int / object variable (max 512) | 1 |
| `SET` / `ADD` / `SUB` | 3 | change an int variable | 12 (`add`/`sub`) |
| `IF` / `WHEN` | 4 | `if/when (<expr>) THEN (<cmds>)` | 1 (`when`) |
| `SHOWVAR`, `LISTCOMMANDS` | 3 / 1 | debug | 0 |

Nested commands (`<cmd>`) are single words, so they come in parentheses. A nesting verb checks
`IsValidCmd(<cmd>)` first and **fails** if the check fails. Nesting depth in the levels is at most 2
(for example a `delay` inside `rand3`, or a `msg player (add …)` inside a key command).

### Dispatch (ProcessCmd)

```
ProcessCmd(string):
  for each statement:
    if verb known and word count exact:
      if handler(statement) fails: return            # rest of the string is dropped
    # unknown verb / wrong count: skipped, keep going
```

Every object that runs a command property does `if (IsValidCmd(s)) Process(s, sender, activeTarget)`:
Trigger `CommandN` / `CommandTouch`, CommandObject events and `FinishedCommand`, StartupCommand,
KeyFramer key commands and the `MOVETO` destination command, EventCounter `Event*Cmd`,
ActiveWorldModel (`On/Off/PowerOn/PowerOff/LockedCommand`), Spawner `InitialCommand` and Prop key
commands. `IsValidCmd` parses only the **first** statement. That is the whole commenting-out
mechanism: a first statement that doesn't start with a verb (or has the wrong word count) disables
the whole string.

**Failing handlers** (from ltjs): `ABORT` with no pending command of that id; `DELAY`/`LOOP`/`RAND*`/
`REPEAT*` whose nested command isn't valid; `RAND` with p outside 0.001–1; variable verbs on unknown
variables or full tables; `IF`/`WHEN` expression errors. `MSG` fails only when its target word can't
be parsed at all, so in practice never. In the levels only `ABORT` matters: 59 strings have
statements after an `abort`. For example `Abort flashon1;LoopID flashon2 .5 .5 (msg …)` (m01-02)
starts the loop **only** if `flashon1` was pending, and `abort fps1; abort fps2; abort fps3; abort
fps4;` (intro) stops at the first id that isn't pending.

### msg

```
msg <targets> <message>
  targets: the target word is parsed again and only its first statement is used:
           a space-separated list (none in the levels; every target is a single name).
  each target name T:
    "<Class>Name" -> the class part is ignored, the name is what follows '>'
    empty name (e.g. "<CAIHuman>") -> the active target's name (Spawner InitialCommand: the
                                      spawned object; 303 uses, all in spawners)
    "player"/"ActivePlayer"/"OtherPlayers" -> the player(s) (sender becomes the active player)
    otherwise -> every object with that name (case-insensitive hash, HASH_STRING_NOCASE;
                 several objects can share a name and all get it); if none, the first
                 lite object (CommandObject) with that name; if none, nothing happens
  if <message> is itself a valid command: it runs as a command with the first found object as
     its active target, and nothing is sent (12 uses: `msg player (add inner 1)` in m09-02)
  else each found object gets the message right away (ObjectMessageFn, MID_TRIGGER)
```

The receiver (`GameBase::TriggerMsg`) splits the message into statements again with ConParse and
calls `OnTrigger(sender, CParsedMsg)` once per statement. `CParsedMsg` tokens compare
case-insensitively (the hash uses `toupper`). Arguments follow the message word: `hidden 1`,
`goto Key05`, `inc 2`.

## Scheduler and timing

- **Synchronous messages.** `msg` calls the target's handler immediately, depth first. If that
  handler runs commands (a Trigger firing, an EventCounter reaching a value), they run inside it,
  before the next statement of the original string. A message sent this frame is handled this frame.
- **Pending table.** `delay`/`loop`/`repeat` go into a fixed table of 100 slots
  (`CMDMGR_MAX_PENDING_COMMANDS`), each taking the **first free slot**. The command text is cut to
  255 chars and an id to 15 (none in the levels are that long). If the table is full, the command
  runs immediately. A slot remembers the sender and active target that were current when it was
  queued.
- **Frame order** (`CServerMgr` update, then `CGameServerShell::Update`):
  1. the server shell: lite objects first (`LiteObjectMgr::Update`: CommandObject timelines), then
     `CCommandMgr::Update`;
  2. then the regular objects (`PreUpdateObjects`: triggers touched by the player, keyframers, AI…).
- **CCommandMgr::Update** walks the slots in index order. Each one does `delay -= frameTime`, and
  when `delay <= 0` it runs. A counted `repeat` decrements its count and a `loop` re-arms with a new
  random delay. Otherwise the slot is freed. Frame time is clamped to 0.2 s and scaled by the
  server time scale.
- So **a delay starts counting at the next command-manager tick after it was queued**:
  - queued during object updates (a trigger touched, a key reached) in frame N: first decrement in
    frame N+1. `delay 0` runs at the start of the next frame.
  - queued by a CommandObject event (lite update) in frame N: decremented in the same frame's
    command-manager tick, so `delay 0` runs in frame N.
  - queued from inside the tick (a pending command that queues another): if the new slot's index is
    higher than the current one, it is decremented in the same pass, otherwise in the next frame.
    Order depends on slot indices. A viewer that keeps a 100-slot table and walks it in index order
    reproduces this. A plain list gives the same result except in this same-tick corner case.
- `ABORT` removes only the first matching pending entry. Ids compare case-insensitively.

## Variables

`INT name value` declares, `ADD`/`SUB`/`SET` change, and `WHEN (expr) THEN (cmds)` runs now if the
expression is true, else registers a watch (32 slots) that fires once when a variable in it changes
and makes it true. The levels use them twice:

- m10-04 `StartupCommand`: `Int BitCounter 0;When (BitCounter == 4) Then (MSG BitsReleased Trigger;msg trigger0 trigger`.
  Nothing ever changes `BitCounter` (the bits count through the EventCounter `stabitcounter`), so the
  `WHEN` never fires. Because `;` splits inside parentheses, **`msg trigger0 trigger` runs at load**.
  `Trigger0` is the opening sequence (AI animations, fog ramps, `cruiserDO`), so this is what the
  level relies on.
- m09-02 key commands: `msg player (add inner 1)` / `(sub middle 1)` and others. No `INT` declares
  `inner`/`middle`/`outer`, so `ADD`/`SUB` fail (`GetVar` returns null) and have no effect. Each is
  the last statement of its string, so nothing else is dropped.

So the viewer needs no expression evaluator. It only has to split the m10-04 string the engine's
way. This settles the map's "Variables" open point.

## Per-class messages

Each class's `OnTrigger` falls through to its base class for words it doesn't know:
`GameBase` (VISIBLE/SOLID/HIDDEN/REMOVE), or `GameBaseLite` (REMOVE only) for lite objects.
A word nobody knows is ignored. "Tron" marks words found in `object.lto`'s token initialisers that
NOLF2 doesn't have. Words of one or two letters (`ON`, `1`, `0`) are too short for the string scan,
so their presence is inferred.

| Class | Messages (args) | Effect | Uses* |
|---|---|---|---|
| **GameBase** (all objects) | `VISIBLE 1/0`, `SOLID 1/0`, `HIDDEN 1/0` (also `TRUE`/`FALSE`), `REMOVE` | VISIBLE/SOLID set or clear the flag (SOLID also restores RAYHIT if the object had it). `HIDDEN 1` clears VISIBLE, SOLID and RAYHIT; `HIDDEN 0` restores whichever of the three the object had at its first message. `REMOVE` deletes the object (refused for the player). Without an argument, or with any other value, nothing changes. | — |
| **WorldModel** | `ATTACH [objs]`, `DETACH`, `ATTACHCLASS cls`, `DESTROY`, `ACTIVATE`; Tron `ATTACHSTANDINGON` | `DESTROY` only clears NeverDestroy, so it doesn't destroy anything by itself. Attach makes other objects ride along. | HIDDEN 3,995, VISIBLE 1,261, REMOVE 702, SOLID 108, DESTROY 12, ATTACH 10, DETACH 5 |
| **ActiveWorldModel** (doors, switches, Sliding/Rotating/Spinning WM) | `ACTIVATE`, `TRIGGER`, `ON`, `OFF`, `LOCK`, `UNLOCK`, `PAUSE`, `RESUME`, `SETPOWERONMULTIPLIER f`; Tron `ADDPSET`, `REMOVEPSET`, `INFOSTRING` | WorldModel's handler runs first. `TRIGGER` toggles: OFF→power on (after OffWaitTime), moving→reverse, ON→power off (only with TriggerOff, else it re-arms the on timers). Locked: without the key, plays the locked sound and runs `LockedCommand`, no move. `ON` only when off/powering off; `OFF` only when on/powering on. `PAUSE`/`RESUME` only while moving. | (#36) |
| **SpinningWorldModel** | as ActiveWorldModel | `ON`: spin up over PowerOnTime; `OFF`: spin down. | HIDDEN 124, ON 43, REMOVE 21, OFF 14, VISIBLE 9, DESTROY 7 |
| **KeyFramer** | `ON`, `OFF`, `PAUSE`, `RESUME`, `FORWARD`, `BACKWARD`/`REVERSE`, `TOGGLEDIR`, `GOTO key`, `MOVETO key [cmd]`, `TARGET obj`, `CLEARTARGET`, `TARGETOFFSET x y z`; Tron `RESETPATH` (not used in SP levels) | `ON`: if inactive, starts **from the first key** (last key if going backward); a no-op when active. Before its first update it only sets StartActive. `OFF`: stop (not "paused", so `RESUME` won't restart it, `ON` will, from the start). `PAUSE`: stop and remember. `RESUME`: continue where it paused. `ON` after `PAUSE` restarts from the start. `FORWARD`/`BACKWARD`/`TOGGLEDIR`: set the direction. `GOTO key`: resume and jump to the key, running its command. `MOVETO key [cmd]`: resume and travel to the key, then run cmd. `PAUSE`/`GOTO`/`MOVETO`/`TARGET*` received before the first update are deferred. Key names: `BaseKeyName` (any case) + `0`, `01`…`09`, `10`… | ON 896, OFF 322, PAUSE 169, RESUME 111, GOTO 31, REVERSE 6, MOVETO 5, FORWARD 4 |
| **SoundFX** | `ON`/`TRIGGER`, `OFF`, `KILL`, `TOGGLE` | `ON`: play (`PlaySound`). `OFF`: stop (loop or one-shot). `KILL`: stop. `TOGGLE`: stop if playing, else play. | ON 1,454, OFF 266, KILL 72 |
| **Group** | anything | Rebuilds the message as its words joined by spaces (parentheses and quotes are lost, 256 chars) and sends it to each `ObjectN` name (Tron: 50 slots) by name, with the group as sender. | HIDDEN 236, DISABLE 129, VISIBLE 107, TRIGGER 105, SPAWN 85, ENABLE 61, ON 60, LOCK 43, … |
| **Trigger** / NoPlayerTrigger | `TRIGGER`, `LOCK`, `UNLOCK` | `TRIGGER` fires it as if touched by the sender (activation count, delays: #30). `LOCK`/`UNLOCK` set Locked. Its commands run with sender = the toucher and active target = the trigger. | TRIGGER 2,667, UNLOCK 797, LOCK 771, `TIRGGER` 1 (typo, ignored) |
| **EventCounter** | `INC`/`INCREMENT [n]`, `DEC`/`DECREMENT [n]`, `LOCK`, `UNLOCK`; Tron `RESET`, `REPORT` | Each step (n ≥ 1) changes the count by one and runs `EventNIncToValCmd`/`DecToValCmd` for every event whose value equals the new count (sender and active target = the counter). Decrement stops at 0. Locked: ignored. **Tron `RESET`**: count = StartingValue, no commands (disassembly: `[this+0x40] = [this+0x3c]`). `REPORT` prints the count. | INC 151, INCREMENT 145, DECREMENT 48, **RESET 36**, DEC 9, LOCK 1 |
| **CommandObject** (lite) | `ON`/`START`, `OFF`/`STOP`/`ABORT`, `PAUSE`, `RESUME`, `LOCK`, `UNLOCK`, `REMOVE` | `ON`: if it has events and isn't locked, starts the timeline (not restarted if already running). Each lite update runs the events whose time (ms in `EventTnEm` = `"<ms>\|<cmd>"`) ≤ elapsed time. At the end: `FinishedCommand`, events re-armed, removed after `NumberOfActivations` runs. `OFF` stops without re-arming, so events already run won't run again on the next `ON` (ltjs). Reached by name only when no regular object has that name. | ON 238, OFF 26 |
| **Prop** | `ANIM a`, `ANIMLOOP a`, `ACTIVATE`, `REMOVE`, `DESTROY` | | (models) |
| **CAIHuman** (Character) | `HIDDEN 1/0` (hides the character, then GameBase), `REMOVE` (GameBase), `VISIBLE`; plus AI words (`GOALSCRIPT`, `TELEPORT`, `LISTENICON`…) | Only REMOVE/HIDDEN/VISIBLE are in scope. | REMOVE 220, HIDDEN 46, VISIBLE 4 (+ 1,170 AI words) |
| **Door** | ActiveWorldModel + `TRIGGERCLOSE` | | (#36) |
| **StartupCommand** | — | Runs `Command` once at its first update (sender and active target = itself), then removes itself. | 20 levels |

\* Message words sent to objects of that class in the 38 levels, counted with the engine tokenizer.
Targets are resolved by name per level. Messages to `player` and to names no object has (spawned
objects) aren't attributed to a class here.

The existing keyframer port (`tools/keyframer.py` `self_commands`) uses a paren-aware splitter and
accepts a `msg` with extra unparenthesized words. Neither difference changes any live-at-start
keyframer's self-commands: the one key command that splits differently (m06-03) sends only AI
messages.

## Validation against the levels

All command-bearing properties were found by scanning every string property for a verb. The
corpus is the charting survey's 16,448 strings, minus 30 ArchiveBin `CustomCmdName1`/`OnWithdraw1`
values that are numbers, not commands: 16,418 strings. Every string tokenizes, because the
tokenizer accepts any input. As commands:

| Outcome | Strings |
|---|---|
| Run (first statement valid) | 15,782 |
| AI mixed messages (`Initial`/`ActivateOn`/`ActivateOff`), split the AI's way | 599 |
| **Never run**: commented out: `*msg`/`*delay` 19, `xmsg` 8, `COMMENTOUT[…]` 3, `\\msg` 1, `(FR)msg` 1 | 32 |
| **Never run**: Spawner `InitialCommand` `addgoal …` without `msg` (m04-03; AI anyway) | 5 |

Inside the strings that run:

| Finding | Count |
|---|---|
| Statements skipped, unknown verb `)` (left over from `(…;)`) | 48 |
| Statements skipped, typos: `popcornkf off` (intro, `msg` missing), `m02sg …` (m02-02 BinaryBit), `senses 0` (AI) | 3 |
| Statement skipped, `msg worry4DO` with no message (intro) | 1 |
| Strings whose meaning depends on `;` splitting inside parentheses | 179 |
| Strings with CR/LF/tab separators | 931 |
| `abort` followed by more statements (rest dropped if the id isn't pending) | 59 |
| `msg` whose message is a command (`msg player (add …)`) | 12 |
| Message words that are typos and get ignored: `TIRGGER`, `FADEIN.5` (`(fadein.5)`, 18), `TALKLOCK0` | 20 |
| Target lists `(a b c)`, `RAND` p out of range, nested commands not valid, delayed command > 255 chars, id > 15 chars | 0 |

Executed verbs (statements that run, nested included): MSG 27,830, DELAY 3,707, ABORT 105, LOOPID 84,
RAND3 30, RAND2 20, DELAYID 13, RAND 8, ADD 6, SUB 6, LOOP 2, RAND4 2, RAND6 1, INT 1, WHEN 1.

## What this changes for the map

- The interpreter (#32) must use **the engine tokenizer**, not a paren-aware splitter: `;` and line
  breaks always end a statement. That includes the m10-04 startup command, which triggers `Trigger0`
  at load. It must also gate every string on its first statement, and stop a string at a failed
  `ABORT`.
- **Variables need no evaluator**: implement `INT`/`WHEN` minimally or not at all. The only `WHEN`
  never fires, and `ADD`/`SUB` touch undeclared variables.
- **EventCounter `RESET`** (Tron-only, 36 uses) belongs with the relays (#35): set the count back to
  StartingValue.
- `msg <CAIHuman> (…)` (303) only exists in Spawner `InitialCommand`, which is out of scope.
