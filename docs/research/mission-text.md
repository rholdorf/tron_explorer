# Mission text and transmissions

Ticket #50 (map #28). Question: how does Tron 2.0 put `MISSIONTEXT` (277 messages) and `TRANSMISSION`
(171) on screen? That covers syntax, string tables, font, position, colour, timing, fades, typing, sound,
what happens when a second one arrives, and whether they block anything. It also asks which font and
texture files exist in `extracted/`.

## Answer

- **Both are player messages with one number, a string id** in `cres.dll`'s Windows string table. Every
  one of the 448 uses is `msg player (missiontext <id>)` or `msg player (transmission <id>)` with exactly
  two words. Neither one blocks input or pauses anything.
- **MISSIONTEXT** draws a typed "terminal" block in the upper left.
  - Placement: at (100, 132) in 640×480 units, Tw Cen MT 14 px, orange (255, 155, 0) with a drop shadow.
  - Typing: letters appear one every 0.015 s, while `type.wav` loops. Each line break costs 0.25 s and
    plays `enter.wav`. Lines fill downwards.
  - Hold and fade: the whole block stays 3 s after the last letter, then fades out linearly over 2 s.
  - A new MISSIONTEXT replaces the current one at once, even mid-typing. There is no queue.
- **TRANSMISSION** is not drawn by the `CHUDTransmission` item the ltjs code suggests.
  - In Tron, a plain transmission goes to the **announcement message queue**: one centred line at the top,
    with its bottom edge at (320, 80). It uses Tw Cen MT 14 px in light blue (90, 199, 255).
  - Timing: 1 s fade-in, 4 s hold, 0.5 s linear fade-out, so 5.5 s in all.
  - Stacking: at most 2 are on screen, stacked upwards. A third pushes the oldest out at once.
  - Each one plays the `msgfadeout` sound (`interface/snd/msgfadeout.wav`).
- **Strings carry inline colour markup** `<color r g b>`. The engine parses it.
  - The tag recolours the text from that point on. The alpha still follows the fade.
  - Any other `<…>` is literal text.
  - 214 of the 230 mission-text strings and 138 of the 141 transmission strings use it.
  - Transmissions read `MESSAGE:` in the queue's blue, then `<color 165 223 255>` for the body.
- **Everything needed is in `extracted/`**:
  - the strings (`cres.dll`)
  - the layout values (`attributes/layout.txt`)
  - the font: the `twcenmt_.ttf` source TTF, plus the game's own pre-rendered pages
    `interface/fonts/twencen_20_000.dtx` / `_001.dtx` with their `.ffa`/`.ffb` descriptions
  - the three sounds (`interface/snd/type.wav`, `enter.wav`, `msgfadeout.wav`)

  The only file missing is `interface/snd/transmission.wav`, which only the unused multiplayer path plays.
- **Three ids have no string**: MISSIONTEXT 6130 (m01-01), TRANSMISSION 5355 (m05-04) and 5316 (m09-03).
  The game loads an empty string. The empty mission text replaces any current one with nothing. The
  empty transmission takes a queue slot and still plays its sound.

## What the viewer must do

| Message | Uses (strings) | Game behaviour to reproduce |
|---|---:|---|
| `missiontext <id>` | 277 (230 ids, 229 resolve) | Restart a typed text block: Tw Cen MT 14, base colour (255,155,0), `<color>` runs, black shadow +2,+2 px. Letters at 0.015 s, +0.25 s per `\n`; `type.wav` loops while typing (stopped at each `\n`), `enter.wav` at each `\n`; hold 3 s, linear fade 2 s. Position (100,132), lines downwards, no wrap. |
| `transmission <id>` | 171 (141 ids, 139 resolve) | Add a line to a 2-slot queue: centred on x = 320, bottom at y = 80, newest at the bottom, older ones pushed up; Tw Cen MT 14, base colour (90,199,255), `<color>` runs, wrap at 400; alpha 0→1 over 1 s, hold 4 s, 1→0 over 0.5 s. Play `msgfadeout.wav` once. A third message reuses the oldest slot at once. |
| `missiontext 0` | 0 | (Engine: clears the block. Not in the data.) |
| `transmission <id> 1` (ActivePlayerComm) | 0 | (Multiplayer path to `CHUDTransmission`. Not in the data.) |

All positions and sizes are in 640×480 units, scaled by **screen width / 640 on both axes**
(`GetXRatio`). The game was 4:3. On a 16:9 screen this stretches the layout's vertical placement; see
"Open points".

On-screen time of a mission text is `0.015·letters + 0.25·linebreaks + 3 + 2` seconds: 5.0 / 6.1 / 13.7 s
(min / median / max over the 230 strings). The longest string has 397 visible letters and 12 lines. A
transmission always lasts 5.5 s.

### Where the messages are

| | Uses | Run inside `delay` | Sources | Levels |
|---|---:|---:|---|---|
| MISSIONTEXT | 277 | 210 | Trigger 181, Dialogue 48, KeyFramer 28, GameStartPoint 11, NoPlayerTrigger 5, EventCounter 3, CommandObject 1 | 31 of 38 (most: m03-01 28, m02-01 22, m01-02 16, m02-04 16) |
| TRANSMISSION | 171 | 3 (+5 in `loopid`) | Trigger 141, EventCounter 20, Dialogue 8, NoPlayerTrigger 1, SlidingSwitch 1 | 31 of 38 (most: m02-01, m03-01, m09-01 12 each) |

Overlaps, counted per command string:
- **Mission texts:** 21 strings send more than one mission text, in 47 successive pairs. In 46 of those
  pairs, the next text arrives before the previous one has faded; the gaps run from 1 to 9 s, with a
  median of 2 s. In none of them does it arrive while the previous one is still typing. So the
  replacement rule shapes the designed sequences, e.g. m01-01 "Scanning …" ×2 → "Code Alert".
- **Transmissions:** no string sends two.
- **Both kinds:** 5 strings send one of each. The two use different screen areas.

Also counted alongside: `objective add|remove|completed <id>` (101 uses). These are the HUD objectives,
which are out of scope.

## Engine details

### Server (`object.lto`, ltjs `playerobj.cpp`)

- Registration: `MISSIONTEXT <text id>` (`0x102ccd64`) and `TRANSMISSION <transmission id>
  [ActivePlayerComm]` (`0x102cce44`). Tron has no `[TeamNumber]`, unlike ltjs line 709.
  `WorldProperties` also registers `TRANSMISSION <id> <optional: sound id>` (`0x102ecf88`), but no level
  sends it there.
- MISSIONTEXT handler `0x10073d30` (player `OnTrigger` compare at `0x100718fb`). It needs 2 words. It
  sends `MID_PLAYER_INFOCHANGE` (0x67) with `IC_MISSION_TEXT_ID` (0xd), two zero bytes and
  `(float)atol(id)`, guaranteed. This matches ltjs `HandleMissionTextMessage` (lines 1935–1951).
- TRANSMISSION handler `0x10073360` (compare at `0x10071798`). It needs 2 words. `ActivePlayerComm` is
  read only when there are exactly 3 words; then the active player's client id is looked up.
  - With a player, it sends message **0x7b**: client id, string id, 0.
  - Otherwise, it sends message **0x7f**: string id, 0. That is every use in the data.
  - ltjs instead always sends `MID_PLAYER_TRANSMISSION` with a team byte (lines 1723–1764).

### Client (`cshell.dll`)

- **0x67 / IC 0xd**: the game shell's `UpdatePlayerStats` (`CTronInterfaceMgr` vtable slot 35
  `0x100a65b0`) falls through to the base `0x100bf800`. IC 0xd (`0x100bfafd`) calls
  `g_pMissionText->Start((int)amount)` (`0x1015a3d0`) when amount > 0, otherwise `Clear`. This is ltjs
  `interfacemgr.cpp` lines 2518–2525.
  - `Start` loads the string (`LoadTempString` `0x100cd8d0`: `LoadStringA` from the `cres_hinstance`
    module into a 2048-byte buffer, empty on failure). It sets the text, resets the `CTimedText`
    (`0x1017b600`), and starts and shows it.
- **0x7f** (game client shell `OnMessage`, jump table at `0x100a69f6`, case `0x100a6ecf`): reads the id
  and a second u32.
  - It plays the sound bute `msgfadeout` (`0x100f0c60`).
  - If the id ≠ 0, it calls `AddMessage(LoadTempString(id), 4)` on the object at `0x102715b0`. That is
    a `CHUDAnnouncementMsgQueue`: vtable `0x101ed12c`, constructed at `0x100a3d33` into
    `CTronHUDMgr+0x11254`.
  - If the second value ≠ 0, it also adds string 3822, "%1!d! build points added to version number".
    The player handler always sends 0 there.
- **0x7b** (interface manager, case `0x100bf3de`): this is the only path to `CHUDTransmission`.
  - It plays a Dialogue sound or `Interface\Snd\transmission.wav`.
  - It shows the text with the `[Transmission]` layout (27 px, yellow (255,255,90), centre (320,360),
    4 s + 1 s fade) and copies it to the chat queue.
  - Nothing in the data takes this path.
- **Announcement queue**: layout `[AnnouncementMessageQueue]`, read at `0x101543f0`: BasePos (320,80),
  Font 0, FontSize 14, MessageTime 4, MessageFade 0.5, Width 400, MaxMessages 2, MaxHistory 2,
  TextColor (90,199,255).
  - `AddMessage(text, type)` (`0x10154580`) copies the format and takes the colour from a per-type table.
    Type 4 is `TextColor`, written at `0x10154568`.
  - It centres the text and sets Tron's extra `MsgCreate` float to 1.0.
  - It then calls the base `CHUDMessageQueue::AddMessage`: take the oldest of the 2 active messages,
    recreate it with the new text, and append it (ltjs `hudmessagequeue.cpp` `AddMessage`, line 226).
- **Tron's `CHUDMessage`** (`Create` `0x1017a5e0`, `Update` `0x1017ab10`, `SetAlpha` `0x1017aa00`) has three times, each multiplied
  by the console variable `MessageDuration` (1.0 in `autoexec.cfg`).
  - The extra one (`+0xdc`, here 1.0) is a **fade-in**: alpha = min(t / fadeIn, 1).
  - Display ends at fadeIn + duration. After that, alpha = 1 − (t − fadeIn − duration) / fade, and the
    message hides at 0.
  - ltjs has no fade-in. `[Miscellaneous]` has no `MessageMinimumTime`/`Fade`, so no minimum applies.
- **MissionText layout**: `[MissionText]`, read at `0x1015a5c0` with the same keys as ltjs
  `hudmissiontext.cpp` `UpdateLayout`:
  - Font 0, FontSize 14, TextColor (255,155,0), NumLines 1, LetterDelay 0.015, LineDelay 0.2,
    LineScrollTime 0.25, FadeDelay 3.0, FadeTime 2.0, Pos (100,132)
  - TypeSound `interface\snd\type.wav`, ScrollSound `interface\snd\enter.wav`
  - There is no `Width` entry, so the wrap width is 0 = no wrapping (ltjs
    `cuiformattedpolystring_impl.cpp` line 461). The strings break lines with `\n` themselves.
- **CTimedText** (ltjs `timedtext.cpp`):
  - Typing: each visible letter takes `LetterDelay`. `\n` takes no time itself.
  - Line breaks: with `NumLines 1`, every new line takes the "scroll" branch. It costs `LineScrollTime`
    (0.25 s), kills the looping type sound and plays the scroll sound once. The type sound restarts on
    the next letter.
  - End: after the last letter, `FadeDelay`, then alpha falls linearly over `FadeTime`.
  - Shadow: each frame the text is drawn black at the same alpha, offset (+2, +2), then in colour.
    `TIMED_TEXT_FADE_TOP_LINE` is off.
  - Tron reads the length with the poly string's `GetLength` (vtable `+0x54`, `Lithtech.exe`
    `0x55d730`), which counts displayed characters. So colour tags take no typing time.
  - Time is client time. The block pauses while a menu is up (`PostPlayingState` → `Pause`) and is
    cleared on level exit (`CTronInterfaceMgr::OnExitWorld`).
- **Video check** (`reference/video/1-2.mp4`, a 1080p capture of a 4:3 game pillarboxed to x 240–1680).
  It shows m01-01's `missiontext 6129` and the intro/m01-01 transmissions 5430/5431.
  - Mission text: the text starts at x = 465 = 240 + 100·2.25. Lines arrive about every 0.7–0.9 s, as
    the formula predicts. The fade starts 3 s after the last line.
  - Unlike the ltjs scroll code, **the block never moves up**: lines stack downwards from y ≈ 132.
  - Transmission: the line is centred on x = 960 and spans y ≈ 155–178 (69–79 in 640 units). So the
    queue is **bottom-justified** at y = 80. It fades in over about 1 s.

### The colour markup (`Lithtech.exe`)

- The formatted poly string's override of vtable slot 36 (`ApplyColors(start, count)`) is `0x560fb0`.
  The base is `0x55bae0`. `SetColors` (`0x55afd0`) stores the colour and calls slot 36.
  - When the source text (`+0x90`) is longer than the displayed text (`+0x14`), the override walks the
    source.
  - At each `<color ` (UTF-16 constant `0x5c1e00`, compared over 7 characters), it parses three decimal
    numbers with `0x5612d0`. The result is `(current alpha) | r<<16 | g<<8 | b`. It then skips to `>`.
  - Every following glyph's 4 vertices take that colour. Glyphs before the first tag take the string's
    colour.
- So `SetColor(alpha | base)` during a fade keeps the tag colours and changes only alpha.
- Malformed tags are tolerated. `<color 255 255 255 >` works, because the parser skips to `>`. A
  doubled `<<color …>` shows a literal `<`.
- Tag colours in mission texts (by count): (255,155,0) 157, (255,255,255) 123, (165,233,255) 62,
  (255,110,0) 57, (90,199,255) 55, (155,251,123) 41, (43,170,0) 35, (200,200,200) 32, (191,255,0) 28,
  (255,255,0) 25, and 7 rarer colours.
- Transmissions use (165,223,255) 135 times. (255,255,0), (255,0,0) and (0,255,0) appear once each.

### Files in `extracted/`

| What | File | How to read |
|---|---|---|
| Strings | `cres.dll` | PE resources, type 6 (RT_STRING): block `n` holds ids `16(n−1)…16n−1`, each a u16 length + UTF-16LE text. 5,001 strings, ids 2–22511. No other copy (`worlds/*.txt` are resource lists, not text). |
| Layout | `attributes/layout.txt` | ButeMgr text: `[MissionText]`, `[AnnouncementMessageQueue]`, `[Transmission]`, `[Fonts]`. |
| Font 0 | `interface/fonts/twencen_20.ffb` (+ `.ffa`) | `.ffa` is a text S-expression: `TTFResource TWCENMT_.TTF`, `PointSize 20`, 256×256 pages, glyphs in alpha, `SpacingHorizontal 1`, `SpacingVertical 3`, `SpaceWidth 5`, a char map. `.ffb` is its binary form (not decoded). |
| Font pages | `interface/fonts/twencen_20_000.dtx`, `_001.dtx` | 256×256 DTX, glyph coverage in alpha (`tools/dtx.py` reads them). |
| Source TTF | `interface/fonts/twcenmt_.ttf` | Tw Cen MT. The game renders it at 20 pt and scales it to the char height (14·xratio). |
| Sounds | `interface/snd/type.wav` (1.73 s, looped), `enter.wav` (0.04 s), `msgfadeout.wav` (2.2 s) | 44.1 kHz mono PCM. `msgfadeout` is a `BaseLocalSound` bute (`attributes/soundbutes.txt`). |
| Missing | `interface/snd/transmission.wav` | Only the 0x7b path plays it. |

## Open points

- The drop-shadow alpha of the announcement queue: ltjs `CHUDMessage::Render` uses 0xBF black at
  (+2, +2). Tron's `CHUDMessage` render was not traced.
- Why the mission-text block doesn't scroll in the game, although the time is spent. The video is
  clear about it. The viewer should copy the video, not the ltjs scroll code.
- 16:9: the game scales both axes by width / 640, so its y positions assume 480 visible lines. The
  viewer has to choose between pillarboxing the HUD to 4:3 and anchoring it by width.

## Method

- Data: the corpus of the 16,418 command strings in the 38 `retailsingleplayer` levels (`tools/tests/conftest.py`), walked with
  `tools/commands.py` into nested `msg`/`delay`/`loop` bodies; each `missiontext` / `transmission` counted
  with its source class, target and delay offset. All targets are `player`.
- Strings: a small PE resource reader over `extracted/cres.dll` (RT_STRING blocks); colour tags and line
  counts per id from that.
- ltjs (`bibendovsky/ltjs`, raw files): `objectshared/playerobj.cpp`;
  `clientshellshared/hudmissiontext.cpp/.h`, `hudtransmission.cpp/.h`, `hudmessage.cpp/.h`,
  `hudmessagequeue.cpp/.h`, `timedtext.cpp/.h`, `hudmgr.cpp/.h`, `interfacemgr.cpp`, `layoutmgr.cpp`,
  `clientutilities.cpp`; `tron/tronhudmgr.cpp`, `troninterfacemgr.cpp`;
  `engine/runtime/ui/src/cuiformattedpolystring_impl.cpp`, `engine/sdk/inc/cuipolystring.h`.
- Tron retail: `extracted/object.lto`, `extracted/cshell.dll` and the GOG install's `Lithtech.exe`
  (`/Users/rui/src/tron`), disassembled with `objdump -d --x86-asm-syntax=intel`.
  - Tokens and handlers were traced as in `player-messages.md`.
  - The client message switches were decoded from their byte index tables (`0x100a7108`, `0x100bf608`).
  - HUD objects were identified by their MSVC RTTI vtables (`.?AVCHUDAnnouncementMsgQueue@@` → vtable
    `0x101ed12c`).
  - The layout keys come from the string pushes in each `UpdateLayout`.
- Video: `reference/video/1-2.mp4` (1080p60), frames sampled with `ffmpeg`. Line timing comes from
  pixel counts per text line band at 10 fps.
