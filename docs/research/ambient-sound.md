# How the engine plays ambient sounds

Research for #21 (map #19). Question: what rules does the engine use to play the level's ambient sounds,
and how does the viewer reproduce them with Unity's `AudioSource`? The sounds covered are `SoundFX` that start
on, `SoundButeFX`, and the `ActiveSound` of active keyframers.

## Answer in brief

- **Falloff is linear in "LT volume", not in gain.** Inside `InnerRadius` the sound plays at full volume.
  Between the radii, the LT volume is `Volume × (1 − (d − inner)/(outer − inner))`. At `OuterRadius` and beyond
  it is 0. After that, the retail `SndDrv.dll` maps LT volume to DirectSound millibels with a steep power curve:
  halfway between the radii is −8.7 dB, and 80% of the way out is −31 dB.
- **`Ambient` = not positioned.** The sound is centred in the head with no pan and no front/back loss. Only the
  distance from the listener changes its volume, using the same linear falloff.
  `Ambient = 0` means a positioned 3D sound: panned, with the same falloff.
- **Voices**: 32 software voices, plus up to 30 hardware 3D voices when hardware is available. The engine sorts
  sounds by `Priority`, then by `Volume/100 / distance`. Sounds farther than `1.5 × OuterRadius` hold no voice,
  but their timeline keeps running.
- **`SoundButeFX`** plays its first sound right away. It then waits `U(MinDelay, MaxDelay)` seconds, counted
  from the *start* of the last play, and (`WaitUntilFinished`) also waits for that sound to end. Each play picks a
  random `PathN` file from the soundbute. The soundbute's own `Volume` and `Pitch` are **ignored** (always 100
  and 1.0).
- **`ActiveSound`**: a looping 3D sound attached to the keyframer's first target object.
  `OuterRadius = SoundRadius`, `InnerRadius = 0.25 × SoundRadius`, volume 100, priority 1.
- **In Unity**: use `spatialBlend = 1` for 3D sounds and `spatialBlend = 0` for `Ambient` sounds. Set
  `AudioSource.volume` every frame from the formula below, keep Unity's own rolloff flat, and set `dopplerLevel = 0`.

Tron 2.0's retail binaries agree with ltjs in every rule checked below, with one exception: the volume curve.
ltjs replaced the original LT-volume-to-dB curve with a plain `20·log10(v/127)`. Retail `SndDrv.dll` still
uses the original curve.

## Sources

- ltjs (NOLF2 game code plus the Jupiter engine):
  - `game/objectdll/objectshared/serversoundfx.cpp` (`SoundFX`)
  - `soundbutefx.cpp`
  - `keyframer.cpp`
  - `game/shared/soundmgr.cpp` (`CGameSoundMgr`, `FillPSIFromButeOrParams`)
  - `game/shared/soundbutemgr.cpp`
  - `engine/sdk/inc/ltbasedefs.h` (`PLAYSOUND_*`, `PlaySoundInfo`)
  - `engine/runtime/sound/src/soundmgr.cpp` (`CSoundMgr::PlaySound`, `Update`, `CompareSoundInstances`)
  - `soundinstance.cpp` (`PreUpdatePositionalSound`, `CAmbientSoundInstance` / `C3DSoundInstance::UpdateOutput`)
  - `soundbuffer.h`
  - `sys/s_dx8/s_dx8.cpp`. The current file and the original import at commit `9f5176f61f` are both used for
    `CONVERT_LIN_VOL_TO_LOG_VOL`.
  - `game/clientshelldll/clientshellshared/gameclientshell.cpp` (`InitSound`) and `profilemgr.{h,cpp}` (defaults)
- Retail, disassembled with `objdump -d --x86-asm-syntax=intel`:
  - `/Users/rui/src/tron/SndDrv.dll`
  - `/Users/rui/src/tron/Lithtech.exe`
  - `extracted/object.lto`
- Data:
  - `export/levels/retailsingleplayer/*/level.json`
  - `extracted/attributes/soundbutes.txt`
  - `extracted/snd/**.wav`

## Retail checks (where Tron could differ from ltjs)

| Rule | Retail evidence | Same as ltjs? |
|---|---|---|
| LT volume → dB curve | `SndDrv.dll` `0x10005470` (`Set3DSampleVolume`; the same code appears at `0x10007518`, `0x10007e3f` and `0x10009277`): clamp to [1, 127], then `(1 − 1/v) × 1.0079365` (127/126 at `0x1000c570`), then `fsqrt(127.0)`, `_CIpow`, `× −10000.0` and `−10000 − …` | original curve, **not** ltjs's replacement |
| DS3D min/max distance | `SndDrv.dll` `0x100077d0`: `SetMinDistance(fMax)`, then `SetMaxDistance(fMax)` (vtable `+0x44`/`+0x40`) | yes. DS3D adds no attenuation, it only pans |
| Linear falloff, `outer + 0.01` | `Lithtech.exe` `0x4815d2`–`0x48162b`: `d² ≤ in²` → 1, `d² ≥ out²` → 0, otherwise `1 − (√d² − in)/(out − in)`. `0x4813e8`: `outer = prop + 0.01` | yes |
| Earshot and voice priority | `Lithtech.exe` `0x480ff9`–`0x48109f`: `pri = vol × 0.01 / d` (`d > 1`), `+ priority`. Earshot flag `0x10` when `d ≤ 1.5 × outer` and `vol > 0` | yes |
| `SoundFX::PlaySound` flags | `object.lto` `0x1022f58b`–`0x1022f67c`: `0x130` (GETHANDLE, TIME, REVERB), `\|4` loop, `\|8` attached, `\|0x40` when volume < 100, `\|0x80` when pitch ≠ 1, `\|1` ambient or `\|2` 3D; priority from the prop | yes |
| `SoundButeFX::Update` | `object.lto` `0x1022c1d0`: `PlaySoundFromPos(pos, bute, Outer, prio 0, 0x30 \| ambient, vol 100, pitch 1.0, Inner, class 0, 1.0)` | yes, plus one extra trailing arg (below) |
| Soundbute volume ignored | `object.lto` `0x100c4bdb`: `vol == 0x64 ? 0x64 : bute.Volume` | yes |
| `ActiveSound` | `object.lto` `0x1010b745`: `PlaySoundFromObject(obj, snd, SoundRadius, 1, 0x14, 100, 1.0, −1.0, 0, 1.0)` | yes |

Tron's `CGameSoundMgr::PlaySoundFromPos` and `PlaySoundFromObject` (`0x100c4ca0`, `0x100c4940`) take one more
float than NOLF2. When it is strictly between 0 and 1, it scales the volume (`0x100c4d55`). None of the
ambient callers uses it: they all pass 1.0.

## Formulas

`d` is the distance from the listener to the sound, in level units. The listener is the player object (its
position and its rotation).

### 1. Falloff scale (all three object types, ambient or 3D)

```
outer' = OuterRadius + 0.01
f(d) = 1                                  if d ≤ InnerRadius
     = 0                                  if d ≥ outer'
     = 1 − (d − InnerRadius)/(outer' − InnerRadius)  otherwise
```

The tests compare squared distances, so `InnerRadius > OuterRadius` is possible: one live ambient `SoundFX`
has it. The sound is then at full volume out to `InnerRadius`, but it holds no voice beyond `1.5 × OuterRadius`.

### 2. Volume pipeline (integer truncations matter at low volume)

```
Vol      = Volume prop if Volume < 100 (PLAYSOUND_CTRL_VOL), else 100   // SoundButeFX, ActiveSound: always 100
raw      = uint8(Vol × f(d))
V        = uint16(raw × classMult × master/100)          // game defaults: 0.75 × 75/100
v        = clamp(V × 127 / 100 (integer), 1, 127)
t        = (1 − 1/v) × 127/126
dB       = −100 × (1 − t^√127)                           // √127 ≈ 11.27; DSBVOLUME_MIN = −100 dB
gain     = 10^(dB/20)
```

At `master = 100` and `classMult = 1`, by fraction `f` of the falloff (Volume 100):

| f | 1 | .9 | .8 | .7 | .6 | .5 | .4 | .3 | .2 | .1 | 0 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dB | 0 | −1.0 | −2.3 | −3.9 | −5.8 | −8.7 | −12.9 | −19.1 | −31.0 | −59.0 | −100 |
| at game defaults (×0.5625) | −6.8 | −8.7 | −10.5 | −13.3 | −17.2 | −21.1 | −28.6 | −38.7 | −55.6 | −86.0 | −100 |

The defaults are `SoundVolume 75` and `defaultsoundmultiplier 0.75` (`profilemgr.h`). The user's
`autoexec.cfg` has the same values. Every sound here uses class 0, `DEFAULT_SOUND_CLASS`. The master value is
also written to the primary buffer through the same curve. Whether DirectSound applies that write is
unverified. For the ear check in Parallels, either set the game to 100 / 1.0, or apply 0.5625 in the viewer
*before* the curve.

### 3. Positioning

- **`Ambient = 1` (`PLAYSOUND_AMBIENT`).** This flag wins over `PLAYSOUND_3D` when both are set
  (`CSoundMgr::PlaySound`). An ambient `SoundButeFX` sets both, because the soundbute adds `PLAYSOUND_3D`.
  - With a 2D voice: pan stays at centre (64) and only the volume changes with distance.
  - With a 3D voice: the sample sits straight ahead at distance `d`. It is still not directional.
  - Either way, the sound depends only on how far the listener is, not on which way they face.
- **`Ambient = 0` (`PLAYSOUND_3D`).** Which path runs depends on whether a hardware 3D provider is present.
  - With a hardware 3D provider: DirectSound 3D pans it from the position relative to the listener.
    `min = max = outer` means DS3D adds no distance attenuation. Velocity feeds Doppler with distance factor
    1/64.
  - In the software path:
    - Volume: `vol × f(d) × front`, where `front = 1 − 0.25·max(0, listenerFront · n̂)` and `n̂` is the unit
      vector from the sound to the listener. A sound behind the listener loses up to 25%.
    - Pan: `pan = 64 + 64·(−listenerRight · n̂)`.

### 4. Pitch

`PitchShift ≠ 1` sets `PLAYSOUND_CTRL_PITCH`. The playback rate is `round(rate × PitchShift)` and the duration
is `duration / PitchShift`, so pitch and speed change together. The WAV `lith` chunk could add a random pitch
modulation (`RandomPitchMod`), but none of the referenced files has one. `SoundButeFX` and `ActiveSound` always
play at pitch 1.

### 5. Loop

- **`Loop = 1`.** The sample loops. If the WAV has a valid `cue ` point with an `ltxt` length, playback starts at
  0 and loops only the `[cue, cue+len]` region.
  - The live ambient drones have `cue = 0` and `len` equal to the whole file, so they loop all of it.
  - Three event files have partial regions: `lrglaserbeam`, `legacycode` and `occuluslaser`.
  - `ltxt len = 0` means "no region", so the whole file loops.
- **`Loop = 0`.** The sound plays once. The server then kills it after its duration (`SetNextUpdate(duration)`).
  `SoundButeFX` never loops (`BaseSFXObjSound` has `LoopSound = 0`).

### 6. Priority and voice limit

- Each sound has `modPri = Priority + (Vol/100)/max(d, 1)`, so the integer `Priority` always dominates. Sounds
  are sorted in decreasing order:
  - local sounds come first;
  - on equal `modPri`, a sound already playing beats one that isn't;
  - then the newest wins.
- From the top of the list, each sound within earshot (`d ≤ 1.5 × OuterRadius`) takes a free voice. If none is
  free, it steals the lowest-ranked voice of the same kind.
- Voices:
  - `MaxSWVoices` = 32 (2D). Ambient sounds use these.
  - `Max3DVoices` = 32, minus 2 when there are more than 2, capped by the hardware. Used only when a hardware 3D
    provider exists.
  - At most 255 sound instances.
- A silenced sound keeps its timer. When it gets a voice again, it resumes where its timeline is now.
- Priorities used:
  - `SoundFX`: its `Priority` prop (live: 456 × 0, 5 × 1, 7 × 3).
  - `SoundButeFX`: 0.
  - `ActiveSound`: 1 (`SOUNDPRIORITY_MISC_MEDIUM`).
- The busiest level, m03-01, has 59 live ambient sounds. That is more than the 32 voices.

### 7. `SoundButeFX` (all 38 have `StartOn = 1`, `NumPlays = −1` and `WaitUntilFinished = 1`)

The engine checks this every server frame:

```
if now − lastPlay ≥ delay and (not Wait or previous sound finished):
    lastPlay = now; delay = uniform(MinDelay, MaxDelay)
    file = weighted-random PathN of the soundbute   (no Weight keys in Tron: uniform)
    play at the object's position (not attached), Inner/Outer = props (if > −1, else soundbute's),
         Volume 100, pitch 1, priority 0, flags = soundbute flags | AMBIENT if Ambient
```

- `lastPlay` and `delay` start at 0, so the first sound plays at level start.
- The delay is measured from the *start* of the previous sound. With `WaitUntilFinished`, the next sound starts
  at `max(start + U(min, max), end of the previous one)`.
- `PlayChance` is 1.0 for all 7 soundbutes used (`BaseSFXObjSound`).
- The live soundbutes are `routerrands`, `blipandbleep_01`, `infected_ones_01`, `infected_ones_02`,
  `LCstaging_ones`, `kpad2_snds` and `City_oneoffs`.
  - All of them have `Parent = BaseSFXObjSound` (3D, no reverb, no loop).
  - `infected_ones_02` sets `Volume = 60`. **The engine ignores it.**

`soundbutes.txt` entry format (`CHierarchicalButeMgr`):

```
[Name]
Parent  = "BaseSFXObjSound"   // missing keys are inherited from the parent chain
Path0   = "Snd\amb\1_router2_01.WAV"   // Path0..N, read until the first missing index
Weight0 = 1                   // optional, default 1
InnerRadius, OuterRadius, Pitch, Volume (0–100), Priority (0/1/2), PlaysoundLocal, PlayClientLocal,
LoopSound, AllowReverb, PlayOnce, PlayChance, LipSync, MinDelay, MaxDelay
```

### 8. KeyFramer `ActiveSound`

`GoActive` starts the sound. For live keyframers that means at start, because `StartActive` calls it.
`GoInactive` kills it.

```
PlaySoundFromObject(first object of the keyframer's ObjectName list, ActiveSound,
                    outer = SoundRadius, priority 1, GETHANDLE|LOOP)
→ 3D | REVERB | ATTACHED, inner = 0.25 × SoundRadius (only when SoundRadius > 0), volume 100, pitch 1
```

- `PLAYSOUND_ATTACHED` makes the sound follow the target world model as it moves.
- The 30 live ones are all looping keyframers, with `SoundRadius` 1000 (17), 10000 (7), 30000 (3), 1500 (2)
  and 900 (1).
- With `SoundRadius = 0` the sound would be inaudible: its earshot is 0.015. No live keyframer has that.
- Key sounds (`SOUND_KEY`, played with `PlaySoundFromPos` when a key is passed) are separate. The 21 in-level
  `Key` objects have no `SoundName`. The external `.ltc` key files are not extracted and were not checked.

### Ignored for the viewer

- **`Filter`**: only 3 sounds use one (`Gen_big`). It is an EAX/DX8 filter that needs `SoundFilters 1`, and the
  user's cfg has 0.
- **`PLAYSOUND_REVERB`**: global EAX reverb, hardware only.
- **`PlayAttached` on `SoundFX`**: 2 sounds. They attach to the `SoundFX` object itself, which never moves.

## Mapping to Unity `AudioSource`

| Engine | Unity |
|---|---|
| clip | the WAV (16-bit PCM; 47 are MP3-in-WAV and need decoding at export) |
| `Loop` / `ActiveSound` | `loop = true`, `Play()` at start. If a partial cue region is ever needed, use an intro clip followed by a looped clip, or `timeSamples` wrap (none of the live ambient files needs it) |
| `Loop = 0` `SoundFX` | `PlayOneShot`-style, once |
| `SoundButeFX` | a component with the timer from §7, `PlayOneShot` / a new clip per play, `loop = false` |
| `PitchShift` | `pitch` (changes speed too, like the engine) |
| `Ambient = 1` | `spatialBlend = 0`. Volume set from the script |
| `Ambient = 0`, `ActiveSound` | `spatialBlend = 1`, `rolloffMode = Custom` with a **flat curve at 1** (or `Linear` with `minDistance` ≥ any `OuterRadius`), so Unity only pans. Volume set from the script |
| falloff and volume curve | every frame: `AudioSource.volume = gain` from §1–2, using the distance to the `AudioListener` in level units. Do it in script rather than with a baked custom rolloff curve: the curve is nonlinear in the *product* `Volume × f × master`, and the script also covers the 2D ambient sources, where Unity's rolloff doesn't apply. Optional: multiply by the software path's 25% behind-listener loss (§3) |
| `ActiveSound` attachment | parent the `AudioSource` to the target world model's GameObject |
| Doppler | `dopplerLevel = 0` (the software path has none, and the sources are static or slow) |
| `Priority` | `priority = 128 − 32 × Priority` (0 → 128; `ActiveSound` 1 → 96; 3 → 32). Lower is more important in Unity |
| earshot | stop or pause nothing: give zero volume beyond `OuterRadius` (`f = 0`) and let Unity virtualise. Unity's virtual voices keep their playback position, like the engine's timer |
| voice limit | `AudioSettings` real voices = 32 (Unity's default), the engine's software voice count. Unity drops the least important and least audible first, which is close to the engine's `Priority + vol/d` order |
| mute (M) | `AudioListener.volume = 0` (or `AudioListener.pause`) |

## Open

- The listener is the player *object* position (`m_bListenerInClient`), not the camera eye. In a free-fly viewer
  the camera is the reasonable stand-in.
- Hardware vs software 3D path in the user's Parallels VM: no hardware DS3D is likely, so the software 2D pan
  path is the one to match by ear.
- Key sounds in external `.ltc` key files are unchecked.
