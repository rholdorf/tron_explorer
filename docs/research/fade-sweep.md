# Fade-outs and the fade-ins that follow them

Research for #38 (map #28). Question: for each single-player level, which player fade-outs are followed by
a fade-in that comes through what the viewer runs? Which ones leave the screen black, and why? How long is
the screen black between a fade-out and its fade-in, so we can pick the safety net's delay?

## Answer

85 objects hold a player fade-out (`msg player (fadeout ...)`), in 33 of the 38 levels. m05-03, m06-03,
m08-01, m10-01 and m11-01 have none.

- **27 never run in the viewer**: 26 are in `Dialogue` objects and 1 is in m10-04's `DisplayTimer`.
- **58 are in triggers** (fired directly in the sweep):
  - **28** fade back in through relays alone.
  - **4** fade back in only through IONode `CINEACTIVATE` (new in #38): m02-03 `SIPauseTR`, m02-04
    `S1PauseTR`, m07-02 `SIPauseTR` and m10-04 `Fade2TR`, the black screen in the ticket.
  - **14** fade out just before the level exit (`SceneFinEnd` / `exit trigger`). The game loads the next
    level. The viewer counts the exit and stays black.
  - **11** wait for a fade-in from a cutscene camera's `CleanupCommand` or a dialogue's `FinishedCommand`.
    Most are the "skip" pattern: `FadeTR` fades out, and `SceneIntroEnd` (run by the camera) fades in and
    locks `FadeTR`.
  - **1** is commented out (intro `Fade2TR`, `COMMENTOUT[...]`).

So without a safety net, **25 trigger fade-outs in 21 levels** would leave the viewer black: the 14 level
ends and the 11 camera or dialogue waits. Many of them are reached only from a camera or a dialogue, so
the viewer never fires them in practice.

**Gaps.** Measured from the end of the fade-out to the start of the fade-in, over the 32 fade-outs that
fade back in. The longest is 3.7 s (m01-01 `ExitTrigger`), then 3.5 s (fin `Fade1TR`) and 3.0 s (m02-01
`HitGroundTR`). Everything else is 1.6 s or less. The safety net waits **10 s**, almost three times the
longest gap, and also waits while a pending command holds a fade-in.

| Level | Fade-outs | Fade-in follows (viewer) | Via IONode (new) | Level end: fade-out, then exit | Fade-in from a camera or dialogue | In dialogue / timer (not run) |
|---|---|---|---|---|---|---|
| fin | 1 | 1 |  |  |  |  |
| intro | 2 |  |  |  | 1 (Fade1TR) | 1 commented out (Fade2TR) |
| m01-01 | 3 | 1 |  | 1 (SFPauseTR) |  | 1 |
| m01-02 | 3 | 1 |  | 1 (S2PauseTR) |  | 1 |
| m02-01 | 13 | 11 |  |  |  | 2 |
| m02-02 | 2 |  |  |  | 1 (FadeTR) | 1 |
| m02-03 | 3 | 1 | 1 (SIPauseTR) |  |  | 1 |
| m02-04 | 4 | 1 | 1 (S1PauseTR) | 1 (SEPauseTR) |  | 1 |
| m03-01 | 1 |  |  |  |  | 1 |
| m04-01 | 3 | 1 |  | 1 (SFPauseTR) |  | 1 |
| m04-02 | 1 |  |  |  |  | 1 |
| m04-03 | 2 | 1 |  |  |  | 1 |
| m05-01 | 2 |  |  | 1 (SFPauseTR) | 1 (FadeTR) |  |
| m05-02 | 3 |  |  |  | 2 (FadeTR, Fade3TR) | 1 |
| m05-04 | 3 | 1 |  | 1 (S1PauseTR) |  | 1 |
| m06-01 | 6 | 3 |  | 1 (SFPauseTR) |  | 2 |
| m06-02 | 3 | 1 |  |  | 1 (FadeTR) | 1 |
| m06-03cin | 1 |  |  | 1 (Fade1TR) |  |  |
| m06-04 | 1 |  |  |  |  | 1 |
| m07-01cin | 4 | 2 |  | 1 (Fade3TR) |  | 1 |
| m07-02 | 2 |  | 1 (SIPauseTR) |  |  | 1 |
| m07-02cin | 2 |  |  | 1 (SIPauseTR) | 1 (Fade1TR) |  |
| m07-03 | 2 |  |  |  | 1 (IONodeM07-03ADialogueClean00) | 1 |
| m07-04 | 2 | 1 |  |  | 1 (FadeTR) |  |
| m09-01 | 1 |  |  |  |  | 1 |
| m09-02 | 3 | 1 |  | 1 (SEPauseTR) |  | 1 |
| m09-02cin | 1 |  |  | 1 (Fade1TR) |  |  |
| m09-03 | 1 |  |  |  |  | 1 |
| m09-03cin | 2 |  |  | 1 (Fade2TR) | 1 (Fade1TR) |  |
| m10-02 | 1 |  |  |  |  | 1 |
| m10-03 | 1 |  |  |  |  | 1 |
| m10-03cin | 2 | 1 |  | 1 (Fade2TR) |  |  |
| m10-04 | 4 |  | 1 (Fade2TR) |  | 1 (Fade1TR) | 2 |

m02-04 `SEPauseTR` fades in and then fades out again at 8 s, before the exit, so it counts as a level end.
m07-03 `IONodeM07-03ADialogueClean00` runs its fade-out after the commands that fade in, so the screen ends
black until `SceneIntroStart`'s camera.

## IONode in Tron's `object.lto`

- `IONode::OnTrigger` is at `0x10022960`, vtable `0x10284ccc`. Its tokens are `ACTIVATE`, `ADDPSET`,
  `REMOVEPSET`, `INFOSTRING`, `CINEACTIVATE` and `CINEDEACTIVATE`.
- **`CINEACTIVATE`** calls vtable `+0x64` = `0x10022ff0` with no checks, then the base `OnTrigger`.
  `0x10022ff0` sets state 6. If `TriggerCommand` is set and `IsValidCmd` passes, it runs `Process(cmd,
  node, NULL)` right away; if not, it prints `IONode::Trigger - ERROR - Invalid command`. Then it changes
  the node's look, which the viewer doesn't show. There is no once-only gate.
- **`CINEDEACTIVATE`** sets state 8 (the closing look) and runs no command.
- **`ACTIVATE`** (the player's use) first requires the sender to be a character with the node's permission
  sets, facing the node within a dot-product limit. Then it calls the same `0x10022ff0`. If a check fails,
  it plays `IONodeInvalidPSet` and runs `InvalidPSetCommand`. The viewer's use only reaches doors and
  switches. The one `ACTIVATE` the levels send (m07-02 `bogusionode`) comes from an AI node.

## Method

- Every string prop matching `msg player (fadeout ...)` in the 38 `retailsingleplayer` worlds, grouped by
  the object that holds it.
- Trigger holders: the relays' Mono driver (`tools/tests/test_relays.py`) loads the level as the viewer
  joins it: relays, groups, IONodes, startup and start-point commands, the player away from every trigger,
  and frames of 0.1 s. It runs the trigger's `CommandN` strings and then 60 s of frames. Fade messages to
  the player (time ≥ 0.1) that a baseline run without the trigger doesn't produce count as following the
  fade-out. The run is repeated with IONodes deaf to tell the new IONode fade-ins apart.
- For the ones left black, the classification (level end, or a fade-in from a camera or dialogue) comes
  from reading who fires the next fade-in in the level's props.
- Not covered: keyframer key commands and door or switch commands are not fired by the sweep. Spot checks
  of the 11 camera or dialogue cases found their fade-ins in `Camera` `CleanupCommand`s or `Dialogue`
  `FinishedCommand`s, never in a keyframer.
