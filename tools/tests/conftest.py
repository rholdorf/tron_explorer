import glob
import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

EXTRACTED = os.environ.get("TRON_EXTRACTED", "/Users/rui/src/pg/tron_explorer/extracted")
SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "..", "TronViewer", "Assets", "Tron", "Scripts")


CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net{version}</TargetFramework>
    <AssemblyName>driver</AssemblyName>
    <LangVersion>latest</LangVersion>
    <Nullable>disable</Nullable>
    <ImplicitUsings>disable</ImplicitUsings>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
    <InvariantGlobalization>true</InvariantGlobalization>
    <NoWarn>$(NoWarn);CS0162;CS0168;CS0169;CS0219;CS0414;CS0649;CS8981</NoWarn>
  </PropertyGroup>
  <ItemGroup>
{items}
  </ItemGroup>
</Project>
"""


def cs_driver(tmp_path_factory, name, source, *scripts):
    """Compiles a C# driver (its source text) with the viewer's scripts (file names under Scripts/) with the
    .NET SDK, skipping the test without one. Returns a function that runs the driver on its stdin text and
    returns its stdout."""
    dotnet = shutil.which("dotnet")
    if not dotnet:
        pytest.skip(".NET SDK (dotnet) not installed")
    sdks = subprocess.run([dotnet, "--list-sdks"], capture_output=True, text=True).stdout.split()
    if not sdks:
        pytest.skip(".NET SDK (dotnet) has no SDK installed")
    version = ".".join(sdks[0].split(".")[:2])
    d = tmp_path_factory.mktemp(name)
    (d / "Driver.cs").write_text(source)
    files = ["Driver.cs", *(os.path.join(SCRIPTS, f) for f in scripts)]
    items = "\n".join(f'    <Compile Include="{f}" />' for f in files)
    (d / "driver.csproj").write_text(CSPROJ.format(version=version, items=items))
    r = subprocess.run([dotnet, "build", str(d / "driver.csproj"), "-c", "Release", "-o", str(d / "out"),
                        "-nologo", "-v", "q"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    dll = str(d / "out" / "driver.dll")
    return lambda text: subprocess.run([dotnet, dll], input=text, capture_output=True, text=True, check=True).stdout


@pytest.fixture(scope="session")
def extracted():
    if not os.path.isdir(os.path.join(EXTRACTED, "worlds")):
        pytest.skip(f"game data not found at {EXTRACTED} (set TRON_EXTRACTED)")
    return EXTRACTED


@pytest.fixture(scope="session")
def world(extracted):
    """Loads (and caches) a level by its path under worlds/, without .dat."""
    import dat85
    cache = {}

    def load(name):
        if name not in cache:
            cache[name] = dat85.load(os.path.join(extracted, "worlds", name + ".dat"))
        return cache[name]
    return load


PROP = re.compile(r"(?i)((?<!custom)(command|cmd)\d*$|^EventT\d+E\d+$|^(Initial|ActivateOn|ActivateOff|"
                  r"OnWithdraw\d*|OnActivate|OnOptimize)$)")


def level_commands(w):
    """(class, property, command string) for every command string in a loaded level."""
    import keyframer
    out = []
    for o in w.objects:
        for k, v in o["props"].items():
            if not isinstance(v, str) or not PROP.search(k):
                continue
            if re.fullmatch(r"(?i)EventT\d+E\d+", k):
                v = v.split("|", 1)[1] if "|" in v else ""
            if v.strip() and v.strip() != "<none>" and not re.fullmatch(r"[\d.\s-]+", v):
                out.append((o["class"], k, v))
        if o["class"] == "KeyFramer":
            index = o["props"].get("KeyDataIndex", -1.0)
            if 0 <= index < len(w.blind):
                out += [("KeyFramer", "key", k["command"]) for k in keyframer.read_keys(w.blind[int(index)][1])
                        if k["command"].strip()]
    return out


@pytest.fixture(scope="session")
def corpus(extracted):
    """Every command string in the 38 single-player levels: (level, class, property, string). Every
    non-empty string property the engine reads as a command (a name ending in Command / Cmd with an
    optional number, not CustomCmd*; CommandObject events EventTnEm, the part after '|'; AI Initial /
    ActivateOn / ActivateOff; ArchiveBin OnWithdrawN; Optimizer OnActivate / OnOptimize), and every
    KeyFramer key command. "<none>" (the editor's empty value) and numbers aren't commands."""
    import dat85
    out = []
    for f in sorted(glob.glob(os.path.join(extracted, "worlds", "retailsingleplayer", "*.dat"))):
        name = os.path.basename(f)[:-4]
        out += [(name, *c) for c in level_commands(dat85.load(f))]
    return out
