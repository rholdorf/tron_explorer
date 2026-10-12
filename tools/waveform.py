"""The engine's wave shapes, shared by ActiveWorldModels (spinners' Waveform) and KeyFramers (Wavetype):
keyframer.cpp uses activeworldmodel.cpp's c_aWaveTypes, and both ReadProps match it with _stricmp."""

NAMES = ["Linear", "Sine", "SlowOff", "SlowOn"]   # AWM_WAVE_* / KFWAVE_*


def index(name):
    """The wave a prop names (any case), as an index into NAMES; Linear (0) when it names none."""
    return next((i for i, w in enumerate(NAMES) if w.lower() == name.lower()), 0)
