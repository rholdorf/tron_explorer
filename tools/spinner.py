"""Spinners: SpinningWorldModels that start on and keep rotating their world model.

Engine rules (ltjs spinningworldmodel.cpp / activeworldmodel.cpp, checked against retail object.lto):
- ReadProps (0x1022a680): each non-zero RotationAngles axis is seconds per full turn; the final angular
  velocity is 2*pi / RotationAngles (rad/s, sign kept).
- StartOn: SetPowerOn at creation. UpdatePowerOn (0x1022ab60) ramps each axis' velocity over
  PowerOnTime: v += GetWaveformValue(final / PowerOnTime, t / PowerOnTime) * frameTime, done when
  v >= |final| or t > PowerOnTime (then v = final). Retail compares with |final| where ltjs uses final,
  so a negative speed ramps up like a positive one instead of starting at full speed.
- The angles (pitch, yaw, roll) accumulate from 0 and the world model is set to
  Rotation * LTRotation(pitch, yaw, roll) * ~Rotation about its position (CalculateNewPosRot): it spins
  on the axes of its own frame. RotationPoint, which would move the pivot, is empty in every level.
- A spinner blocked by an object stops (TestObjectCollision) unless ForceMove: that reacts to the
  player, so the viewer doesn't do it.
"""
import math

import waveform

CLASS = "SpinningWorldModel"


def spinners(objects):
    """Spinners that start on, from a level's objects (dat85): world model name, final velocity per
    axis (rad/s, pitch/yaw/roll), PowerOnTime (s) and waveform (index into waveform.NAMES)."""
    out = []
    for o in objects:
        p = o["props"]
        if o["class"] != CLASS or not p.get("StartOn", False):
            continue
        angles = p.get("RotationAngles", [0.0, 5.0, 0.0])
        velocity = [2 * math.pi / a if a else 0.0 for a in angles]
        if not any(velocity):
            continue
        out.append({"worldModel": p.get("Name", ""), "velocity": velocity,
                    "powerOnTime": float(p.get("PowerOnTime", 100.0)),
                    "waveform": waveform.index(p.get("Waveform", "Linear"))})
    return out
