# Keyframer paths in the level's blind object data

Research for #20 (map #19). Question: what is the layout of the blind object data section in DAT v85, and
how does a keyframer turn it into motion and sound?

## Answer

The blind object data section is a simple list of chunks, and every chunk in the retail levels is a
keyframer path. A keyframer's hidden `KeyDataIndex` property (a real, truncated to an integer) is the index
of its chunk. A chunk holds a key count followed by variable-length keys. Each key has a position, a
pitch/yaw/roll, a time delta, an optional sound and an optional command, and optional Bezier tangents.
`ExternalKeyFile` is a leftover editor property and the engine never reads it. The format is fully
tractable: all 2,135 keyframers in the 38 single-player levels parse, each consumes its chunk exactly,
and no chunk is left over.

Motion takes one of two modes. With `TotalPathTime > 0` the object moves at a constant speed along the
whole path, shaped by `Wavetype`, and the key times are ignored. With `TotalPathTime` = 0 the key time
deltas drive the motion. Segments are cubic Bezier when both ends have tangents, and linear otherwise.
Rotation slerps between keys. `Looping` wraps from the last key back to the first. Nothing ping-pongs
automatically: a reversal only happens through a command (`REVERSE`/`BACKWARD`/`TOGGLEDIR`), often one
sent by the keyframer's own keys. `ActiveSound` loops from the first controlled object while the
keyframer is active.

## File layout

The DAT v85 header (`tools/dat85.py` `load`) has six u32 section offsets after the version. The second
one, `blind_pos`, points to this section. Per ltjs `engine/runtime/world/src/world_blind_object_data.cpp`
(`CWorldBlindObjectData::Load`):

```
u32 numChunks
numChunks × {
    u32 size
    u32 id            // 0x6aaf0884 = KEYFRAMER_BLINDOBJECTID for every retail chunk
    u8  data[size]
}
```

The section ends exactly at the light-grid offset (`lgrid_pos`) in all 38 levels. `GetBlindObjectData(nNum, nId)`
indexes the chunk by `nNum` and checks that `nId` matches.

### Keyframer chunk (`data`)

Per ltjs `game/objectdll/objectshared/keyframer.cpp` (`CreateKeyList`) and `keydata.cpp`
(`KeyData::Copy`). Everything is little-endian:

```
u32 numKeys                       // the engine truncates it to u16
numKeys × {
    u16 control                   // bit0: prev tangent present, bit1: next tangent present
    u8  soundLen
    u8  commandLen
    f32 pos[3]                    // world space, same frame as object Pos
    f32 pitchYawRoll[3]           // radians, same convention as the object Rotation property
    f32 timeStamp                 // seconds since the previous key (the first key's is a start delay)
    f32 soundRadius
    char sound[soundLen]          // not NUL-terminated; non-empty sets SOUND_KEY
    char command[commandLen]      // not NUL-terminated; non-empty sets MESSAGE_KEY
    if control & 1: f32 prevTangent[3]   // relative to pos; BezierPrevCtrl = pos + v
    if control & 2: f32 nextTangent[3]   // relative to pos; BezierNextCtrl = pos + v
}
```

Every key also gets `POSITION_KEY`, from the `KeyData` constructor. Key *names* are not stored. A key is
addressed as `BaseKeyName` + index (`FindKey`: `"0"`, `"01"`…`"09"`, `"10"`…). That only matters for
`GOTO`/`MOVETO` commands.

### Linking an object to its chunk

`KeyFramer::ReadProps`: `KeyDataIndex` (hidden, `PF_HIDDEN`, real, default −1) → `(uint32)value`, or
`0xffffffff` if it is negative. On disk the values carry a +0.1 bias (`1.1`, `3.1`…). Truncate them, don't
round.

## Verified against the retail levels

I wrote a throwaway script over all 38 `extracted/worlds/retailsingleplayer/*.dat`, using `tools/dat85.py`
for objects plus the layout above:

| Check | Result |
|---|---|
| Chunks / `KeyFramer` objects | 2,135 / 2,135; only `KeyFramer` has `KeyDataIndex` |
| Chunk ids | all `0x6aaf0884` |
| Indices | all in range, no two keyframers share one, no chunk unused |
| Bytes consumed per chunk | exact for every chunk (179,216 keys) |
| Section end == `lgrid_pos` | 38/38 |
| Keys per path | 2 to 851 |
| `control` | 0: 178,043; 3: 987; 1: 115; 2: 71 |
| Sound keys / command keys | 129 / 813 (19 sound names are a single space, i.e. effectively none) |
| `ExternalKeyFile` non-empty | 1,306 (unused by the engine, see above) |

There are 147 live-at-start keyframers (`StartActive`):

- 137 loop: 105 have a closed path (last key equals first key) and 32 jump back to the start.
- 66 use velocity mode with `Linear`, 9 velocity with `Sine`, and 72 time mode. No retail keyframer uses `SlowOn`/`SlowOff`.
- 29 have Bezier segments, 74 rotate, and 73 only translate.
- 22 use `AlignToPath`, 75 `IgnoreOffsets`, 19 `PushObjects`, and none `TargetName`.
- In 30 the first key's `timeStamp` is not 0, which means a start delay in time mode.
- They control `WorldModel` 92, `Finder` 26, `SpecialFX` 20, `Optimizer` 17, `VolumeBrush` 8,
  `CAIHuman` 6, `Camera` 5 and `ScaleSprite` 3. In 114 of the 177 links the object sits exactly on the first key.
- **70 have command keys. 43 of those message themselves**: `PAUSE` 53, `GOTO` 8, `REVERSE` 6,
  `FORWARD` 4, `OFF` 2. The rest message other objects (`HIDDEN`, `TRIGGER`, `ON`/`OFF`, `LOCK`/`UNLOCK`,
  `RESUME`, `delay`…).
- 3 have sound keys, and all of their sound names are blank.

Tron's own `object.lto` contains `0x6aaf0884` at four sites (the get/free pairs in `CreateKeyList` and
`Load`). It also has the same property names (`KeyDataIndex`, `ExternalKeyFile`, `TotalPathTime`,
`Wavetype`…), the wave strings `Linear`/`Sine`/`SlowOff`/`SlowOn`, and the same command verbs. Together with
the exact byte match above, this shows the ltjs (NOLF2) code describes Tron's keyframer. I did not
disassemble `KeyData::Copy` itself, because the data match leaves no room for a different layout.

## How a keyframer moves (ltjs `keyframer.cpp`)

**Start.** On the first `Update`, `CreateKeyList` runs. It finds the objects named in `ObjectName`
(`;`-separated, each name can match several objects), reads the keys and builds `m_fRealTime` as the
running sum of `timeStamp` (`m_fEndTime` = the last key's). For each object it stores:
- `offset = objPos − key0.pos`;
- `rotOffset = objRot − key0.rot`. This is a **component-wise quaternion subtraction**, and the code
  comments that it has "no geometric meaning".

Then, if `StartActive` (or `StartPaused`) is set, it calls `GoActive`: time 0, current key = the first
key, direction forward. Nothing moves on that first frame.

**Each frame** (`Update`), it processes every key it has reached. In time mode that means
`realTime <= curTime`. In velocity mode it means `curPos` sits exactly on the key. Passing a key:
- sets the segment (`pos1` = that key, `pos2` = the next one);
- plays the key's sound (one-shot, at the key's position, `soundRadius`);
- runs its command through the command manager;
- pauses at a `MOVETO` destination, if one is set.

When the list runs out, it resets to the first key with `curTime = 0` and `curPos = key0.pos`. Without
`Looping` it then goes inactive (`m_bFinished`). With `Looping` it continues. The object teleports back
to key 0 because nothing interpolates across the wrap. Then `UpdateObjects` runs, and `curTime` advances
by the frame time (negative when the direction is backward).

**Position** (`CalcCurPos`):
- *Time mode* (`TotalPathTime <= 0`): `t = (curTime − pos1.realTime) / (pos2.realTime − pos1.realTime)`
  (0 if the range is under 0.001). Before the first key is reached (a delay at the start) there is no
  segment, so nothing moves.
- *Velocity mode* (`TotalPathTime > 0`): `CalculateVelocityInfo` sums the segment lengths. A Bezier
  segment's length is `Bezier_SegmentLength`, 20 chords; a linear one is the straight distance. Then
  `velocity = totalDistance / TotalPathTime`. Each frame:
  - `pathPct = clamp(curTime / TotalPathTime, 0, 1)`;
  - `moveDist = wave(velocity, pathPct) × frameTime`;
  - `t += moveDist / segmentLength`;
  - when `t >= 1` (or `pathPct >= 1`), the object snaps to `pos2` and `t` restarts at 0. The overshoot
    is clamped away.

  For Bezier segments the step is rescaled by the chord length actually covered, which approximates
  constant arc-length speed (a "TODO" in the source).
- Wave speed (`GetKFWaveValue`):
  - `Linear`: `v`;
  - `Sine`: `π/2 · v · sin(π·p)`;
  - `SlowOff`: `π/2 · v · cos(π/2·p)`;
  - `SlowOn`: `π/2 · v · sin(π/2·p) + 0.003·v`.

  Each one integrates to about the same total distance over the path.
- Bezier curve: `Bezier_Evaluate(pos1.pos, pos1.nextCtrl, pos2.prevCtrl, pos2.pos, t)`. It applies only
  when `pos1` has bit 1 **and** `pos2` has bit 0. Otherwise the segment is a lerp.

**Rotation** (`UpdateObjects`): `slerp(pos1.rot, pos2.rot, t)`, or exactly `pos2.rot` at a key.
- With `AlignToPath`: the object faces the frame's movement direction (up = +Y), then pitch and roll
  are lerped from the keys' PYR.
- With a `TargetName`: the object faces the target plus `TargetOffset` (unused in the live-at-start set).
- Unless `IgnoreOffsets` is set or there is a target, `rotOffset` is added back component-wise.

**Position of each object:**
- `curPos + offset`. The offset is **not** rotated with the path, so the object translates rigidly and
  spins about its own origin.
- With `IgnoreOffsets` set, the object's origin goes onto the path itself.
- With `PushObjects`, it uses `MoveObject`, which pushes whatever is in the way; otherwise it uses `SetObjectPos`.

**ActiveSound** (`GoActive`): `PlaySoundFromObject(firstControlledObject, ActiveSound, SoundRadius
(default 1000), PLAYSOUND_LOOP)`. The sound follows the first object in the `ObjectName` list. It is
killed in `GoInActive`, which runs at the end of a non-looping path, on `OFF`, and on `PAUSE` (`Pause`
calls `GoInActive`). `RESUME` calls `GoActive(false)`, which restarts the sound.

## Parser sketch

```python
KEYFRAMER_BLINDOBJECTID = 0x6aaf0884

def read_blind_objects(data, blind_pos):
    """[(id, bytes)] in file order; index = KeyDataIndex."""
    n, = struct.unpack_from("<I", data, blind_pos); p = blind_pos + 4
    chunks = []
    for _ in range(n):
        size, cid = struct.unpack_from("<II", data, p); p += 8
        chunks.append((cid, data[p:p + size])); p += size
    return chunks

def read_keyframer_keys(blob):
    n, = struct.unpack_from("<I", blob, 0); p = 4
    keys, t = [], 0.0
    for _ in range(n & 0xffff):
        ctrl, sl, cl = struct.unpack_from("<HBB", blob, p); p += 4
        pos = struct.unpack_from("<3f", blob, p); p += 12
        pyr = struct.unpack_from("<3f", blob, p); p += 12
        dt, srad = struct.unpack_from("<2f", blob, p); p += 8
        snd = blob[p:p + sl].decode("latin1").strip(); p += sl
        cmd = blob[p:p + cl].decode("latin1"); p += cl
        prev = nxt = None
        if ctrl & 1: prev = add(pos, struct.unpack_from("<3f", blob, p)); p += 12
        if ctrl & 2: nxt = add(pos, struct.unpack_from("<3f", blob, p)); p += 12
        t += dt
        keys.append(dict(pos=pos, pyr=pyr, time=t, sound=snd, sound_radius=srad,
                         command=cmd, bez_prev=prev, bez_next=nxt))
    assert p == len(blob)
    return keys

# in dat85.load: w.blind = read_blind_objects(data, blind_pos)
# per KeyFramer: idx = int(props["KeyDataIndex"])  (truncate; -1 = none)
#                cid, blob = w.blind[idx]; assert cid == KEYFRAMER_BLINDOBJECTID
```

The export would put `keys` (absolute `time`, positions, PYR, absolute Bezier controls, and command
strings for the self-addressed verbs) on the keyframer object in `level.json`. In Unity, positions go
through the same LithTech→Unity conversion as object `Pos`, and PYR uses `LevelData.Rotation`'s
convention.

## Consequences for the map (#19)

- The format is not a blocker: it is simple and fully verified.
- **Self-addressed key commands are part of the motion.** 43 of the 147 live-at-start keyframers message
  themselves from their own keys, mostly `PAUSE`, plus `GOTO`/`REVERSE`/`FORWARD`/`OFF`. Ping-pong paths
  are built this way. A faithful "living level" needs the keyframer to handle commands addressed to
  itself (`PAUSE`, `RESUME`, `OFF`, `FORWARD`, `BACKWARD`/`REVERSE`, `TOGGLEDIR`, `GOTO`). Commands to
  other objects stay out of scope (behavior map). A self-`PAUSE` with nothing in scope to `RESUME` it
  leaves the keyframer stopped, as in the game until something triggers it.
- Key sounds don't matter at start: all 3 live keyframers with sound keys have blank names.
- About 70 live keyframers move non-world-model objects (`Finder`, `Optimizer`, `SpecialFX`, AI,
  `Camera`, `VolumeBrush`…). The map's destination talks about world models, so the task ticket should
  decide which classes it moves.

## Sources

- ltjs (bibendovsky/ltjs): `engine/runtime/world/src/world_blind_object_data.cpp`;
  `game/objectdll/objectshared/keyframer.cpp`, `keyframer.h`, `keydata.cpp`, `keydata.h`;
  `engine/sdk/inc/ltbeziercurve.h`.
- Retail data: `extracted/worlds/retailsingleplayer/*.dat` (38), `extracted/object.lto` (string and
  constant search).
