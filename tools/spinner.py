"""Spinners: SpinningWorldModels, which keep rotating their world model while they are on.

Engine rules (ltjs spinningworldmodel.cpp / activeworldmodel.cpp, checked against retail object.lto):
- ReadProps (0x1022a680): each non-zero RotationAngles axis is seconds per full turn; the final angular
  velocity is 2*pi / RotationAngles (rad/s, sign kept).
- StartOn: SetPowerOn at creation; one that starts off waits for ON (ticket #33: SpinnerMotion.cs runs
  the on / off state machine, ActiveWorldModel::OnTrigger / HandleTriggerMsg). UpdatePowerOn (0x1022ab60) ramps each axis' velocity over
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
    """Every spinner with a speed, from a level's objects (dat85): world model name, obj (its index in
    the level's objects, its command-manager id), startOn, final velocity per axis (rad/s,
    pitch/yaw/roll), PowerOnTime and PowerOffTime (s; ActiveWorldModel::PostReadProp: 0 takes
    PowerOnTime), waveform (index into waveform.NAMES) and the props of the on / off state machine:
    triggerOff, locked, forceMove, forceMoveOn, forceMoveOff, moveDelay, onWaitTime, offWaitTime."""
    out = []
    for i, o in enumerate(objects):
        p = o["props"]
        if o["class"] != CLASS:
            continue
        angles = p.get("RotationAngles", [0.0, 5.0, 0.0])
        velocity = [2 * math.pi / a if a else 0.0 for a in angles]
        if not any(velocity):
            continue
        power_on = float(p.get("PowerOnTime", 1.0))
        power_off = float(p.get("PowerOffTime", 0.0))
        out.append({"worldModel": p.get("Name", ""), "obj": i, "startOn": bool(p.get("StartOn", False)),
                    "velocity": velocity, "powerOnTime": power_on,
                    "powerOffTime": power_off if power_off > 0 else power_on,
                    "waveform": waveform.index(p.get("Waveform", "Linear")),
                    "triggerOff": bool(p.get("TriggerOff", False)), "locked": bool(p.get("Locked", False)),
                    "forceMove": bool(p.get("ForceMove", False)), "forceMoveOn": bool(p.get("ForceMoveOn", False)),
                    "forceMoveOff": bool(p.get("ForceMoveOff", False)),
                    "moveDelay": float(p.get("MoveDelay", 0.0)), "onWaitTime": float(p.get("OnWaitTime", 0.0)),
                    "offWaitTime": float(p.get("OffWaitTime", 0.0))})
    return out
