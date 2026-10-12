"""LithTech Jupiter render style (.ltb, D3D file type 5, version 3) parser, and the subset the viewer's
model shader can draw.

Layout (d3d_renderstyle.cpp Load_LTBData, the RenderStyle_Packer's raw MSVC structs; see
docs/research/render-styles.md on branch research/render-styles):
  LTB_Header (20 bytes)  u8 fileType = 5, pad, u16 version = 3, ...
  u32 totalSize, u32 styleCount (always 1 in Tron)
  per style: u32 size, LightingMaterial (4 x float4 ambient/diffuse/emissive/specular + f32 power),
             u32 passCount, per pass: RenderPassOp (532 bytes), u8 hasD3DPass
Tron's files have no trailing RSD3DOptions (unlike ltjs's loader).
"""
import struct

# RenderPassOp: 4 x TextureStageOps (120 bytes) then the pass states.
STAGE = struct.Struct("<11I I16f I I")       # TextureParam, ColorOp/Arg1/Arg2, AlphaOp/Arg1/Arg2,
                                             # UVSource, UAddress, VAddress, TexFilter, UVTransform_Enable,
                                             # matrix, ProjectTexCoord, TexCoordCount
PASS_TAIL = struct.Struct("<5I I 3I I I 2f")  # Blend, ZBuffer, Cull, TextureFactor, AlphaRef, DynamicLight,
                                              # ZBufferTest, AlphaTest, FillMode, bUseBumpEnvMap,
                                              # BumpEnvMapStage, scale, offset
assert STAGE.size == 120 and STAGE.size * 4 + PASS_TAIL.size == 532

# Engine enums (ltrenderstyle.h); ColorOp 19 is the packer's MODULATETEXALPHA = D3DTOP_BLENDTEXTUREALPHA.
BLEND = {0: "opaque", 1: "add", 2: "saturate", 3: "alpha", 4: "mod_srccolor", 5: "mod_dstcolor",
         6: "mul_srccol_dstcol", 7: "mul_srccol_one", 8: "mul_srcalpha_zero", 9: "mul_srcalpha_one",
         10: "mul_dstcol_zero"}

# The model shader's stage operations (TronModel.shader), one code space for color and alpha.
OP_DISABLE, OP_SEL1, OP_SEL2, OP_MOD, OP_MOD2X, OP_BLEND_CUR_A, OP_BLEND_TF_A, OP_ADD, OP_BLEND_TEX_A = range(9)
COLOR_OPS = {0: OP_DISABLE, 1: OP_SEL1, 2: OP_SEL2, 3: OP_MOD, 4: OP_MOD2X, 5: OP_BLEND_CUR_A, 6: OP_BLEND_TF_A,
             7: OP_ADD, 19: OP_BLEND_TEX_A}
ALPHA_OPS = {0: OP_DISABLE, 1: OP_SEL1, 2: OP_SEL2, 3: OP_MOD, 4: OP_BLEND_CUR_A, 5: OP_BLEND_TF_A, 6: OP_ADD,
             10: OP_BLEND_TEX_A}
# Stage arguments: 0 CURRENT, 1 DIFFUSE, 2 TEXTURE, 3 TFACTOR (same codes in the shader).
UV_SETS = {0: 0, 6: 1, 9: 1}   # UV set 1 -> 0; camera/world-space reflection -> 1 (identical without a UV transform)
# Unity BlendMode factors per engine blend mode.
# (renderstylelookuptables.cpp: MOD_SRCCOLOR = SRCCOLOR, INVSRCCOLOR; MUL_SRCCOL_DSTCOL = SRCCOLOR, DESTCOLOR)
UNITY_BLEND = {"opaque": (1, 0), "alpha": (5, 10), "add": (1, 1), "mul_srcalpha_one": (5, 1),
               "saturate": (8, 1), "mul_srccol_one": (3, 1), "mul_srcalpha_zero": (5, 0),
               "mod_srccolor": (3, 6), "mul_srccol_dstcol": (3, 2)}
# Unity CompareFunction for the alpha test enum (0 none, 1 LESS, 2 LESSEQUAL, 3 GREATER, 4 GREATEREQUAL, ...).
UNITY_CMP = {1: 2, 2: 4, 3: 5, 4: 7, 5: 3, 6: 6}
ZFUNC = {0: 8, **UNITY_CMP}
IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)   # ZBufferTestMode uses the same enum, 0 = always


class Stage:
    pass


class Pass:
    pass


class Style:
    pass


def load(path):
    with open(path, "rb") as f:
        d = f.read()
    file_type, version = struct.unpack_from("<BxH", d, 0)
    if file_type != 5:
        raise ValueError(f"not a render style (type {file_type})")
    if version != 3:
        raise ValueError(f"render style version {version} not supported")
    p = 20
    _total, n_styles = struct.unpack_from("<2I", d, p)
    p += 8
    if n_styles < 1:
        raise ValueError("no styles")
    _size, = struct.unpack_from("<I", d, p)
    p += 4
    s = Style()
    v = struct.unpack_from("<17f", d, p)
    p += 68
    s.ambient, s.diffuse, s.emissive, s.specular, s.power = v[0:4], v[4:8], v[8:12], v[12:16], v[16]
    n_passes, = struct.unpack_from("<I", d, p)
    p += 4
    s.passes = []
    for _ in range(n_passes):
        ps = Pass()
        ps.stages = []
        for _k in range(4):
            f = STAGE.unpack_from(d, p)
            p += STAGE.size
            st = Stage()
            (st.texture, st.color_op, st.color_arg1, st.color_arg2, st.alpha_op, st.alpha_arg1, st.alpha_arg2,
             st.uv_source, st.u_address, st.v_address, st.filter, st.uv_transform) = f[:12]
            st.uv_matrix = f[12:28]
            ps.stages.append(st)
        t = PASS_TAIL.unpack_from(d, p)
        p += PASS_TAIL.size
        (ps.blend, ps.zbuffer, ps.cull, ps.tfactor, ps.alpha_ref, ps.lit, ps.ztest, ps.alpha_test, ps.fill,
         ps.bump) = t[:10]
        ps.has_d3d = d[p]
        p += 1
        s.passes.append(ps)
    return s


def default_style():
    """CD3DRenderStyle::SetDefaults: what a piece draws with when its instance slot is empty."""
    s = Style()
    s.ambient, s.diffuse, s.emissive, s.specular, s.power = (1, 1, 1, 1), (.8, .8, .8, 1), (0, 0, 0, 1), (0, 0, 0, 1), 20
    ps = Pass()
    ps.stages = []
    for k in range(4):
        st = Stage()
        st.texture, st.color_op, st.color_arg1, st.color_arg2 = (1, 3, 2, 1) if k == 0 else (0, 0, 0, 0)
        st.alpha_op, st.alpha_arg1, st.alpha_arg2 = (3, 2, 1) if k == 0 else (0, 0, 0)
        st.uv_source = st.u_address = st.v_address = st.uv_transform = 0
        st.filter = 2
        ps.stages.append(st)
    (ps.blend, ps.zbuffer, ps.cull, ps.tfactor, ps.alpha_ref, ps.lit, ps.ztest, ps.alpha_test, ps.fill,
     ps.bump, ps.has_d3d) = (0, 0, 1, 0x80808080, 128, 1, 2, 0, 1, 0, 0)
    s.passes = [ps]
    return s


def _stages(ps, where):
    """The pass's active texture stages (cascade until the first disabled color op), as shader
    vectors (colorOp, colorArg1, colorArg2, textureSlot), (alphaOp, alphaArg1, alphaArg2, uvSet),
    flattened to 16 numbers."""
    out = []
    for i, st in enumerate(ps.stages):
        if st.color_op == 0:
            break
        if i >= 2:
            raise ValueError(f"{where}: more than 2 texture stages")
        if st.color_op not in COLOR_OPS or st.alpha_op not in ALPHA_OPS:
            raise ValueError(f"{where}: stage {i} op color {st.color_op} alpha {st.alpha_op} not supported")
        args = (st.color_arg1, st.color_arg2, st.alpha_arg1, st.alpha_arg2)
        if any(a > 3 for a in args):
            raise ValueError(f"{where}: stage {i} argument {args} not supported")
        if st.texture > 2:
            raise ValueError(f"{where}: stage {i} texture param {st.texture:#x} not supported")
        # An identity texture matrix on a stored UV set changes nothing (thorn_corruption stores one).
        transform = st.uv_transform and not (st.uv_source == 0 and getattr(st, "uv_matrix", None) == IDENTITY)
        if st.uv_source not in UV_SETS or transform:
            raise ValueError(f"{where}: stage {i} uv source {st.uv_source} (transform {st.uv_transform}) "
                             f"not supported")
        out.append([[COLOR_OPS[st.color_op], st.color_arg1, st.color_arg2, st.texture],
                    [ALPHA_OPS[st.alpha_op], st.alpha_arg1, st.alpha_arg2, UV_SETS[st.uv_source]]])
    while len(out) < 2:
        out.append([[0, 0, 0, 0], [0, 0, 0, 0]])
    return [x for st in out for v in st for x in v]   # flat: 2 stages x 2 vectors x 4


def _argb(v):
    return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255, (v >> 24) / 255]


def _state(ps):
    """A pass's hardware state as Unity material values."""
    return {
        "blend": UNITY_BLEND[BLEND[ps.blend]],
        "zwrite": int(ps.zbuffer == 0),
        "ztest": 8 if ps.zbuffer == 2 else ZFUNC[ps.ztest],
        "cull": {0: 0, 1: 2, 2: 1}[ps.cull],                           # D3D CCW culls back faces
    }


def _pass(ps, where, blend_over=0):
    return {
        "stages": _stages(ps, where),
        "tfactor": _argb(ps.tfactor),
        "lit": int(bool(ps.lit)),
        "blendOver": blend_over,
        "alphaTest": [UNITY_CMP.get(ps.alpha_test, 0), ps.alpha_ref / 255],
    }


def _check(s, name):
    if len(s.passes) > 2:
        raise ValueError(f"{name}: {len(s.passes)} passes")
    for i, ps in enumerate(s.passes):
        if ps.has_d3d or ps.bump or ps.fill != 1:
            raise ValueError(f"{name} pass {i}: shader pass, bump map or wireframe")
        if BLEND.get(ps.blend) not in UNITY_BLEND:
            raise ValueError(f"{name} pass {i}: blend {BLEND.get(ps.blend, ps.blend)} not supported")


def compile_style(s, name):
    """The shader description of a style, or ValueError when the model shader can't draw it: the
    lighting (its LightingMaterial) and one or two draws, each with its hardware state and the passes it evaluates.
    A second pass is folded into the first draw when that's exact: pass 0 opaque, pass 1 alpha-blended
    or opaque with the same Z and cull states (its alpha test then selects instead of discarding).
    Otherwise it needs the framebuffer and is a draw of its own after the first, with its own states
    (rendermodelpiecelist.cpp draws each pass of a piece in turn); each draw is fogged on its own."""
    _check(s, name)
    p0 = s.passes[0]
    out = {"lighting": {"ambient": list(s.ambient), "diffuse": list(s.diffuse), "emissive": list(s.emissive)}}
    draw = dict(_state(p0), passes=[_pass(p0, f"{name} pass 0")])
    out["draws"] = [draw]
    if len(s.passes) == 2:
        p1 = s.passes[1]
        if (BLEND[p0.blend] == "opaque" and BLEND[p1.blend] in ("opaque", "alpha") and p0.cull == p1.cull
                and p1.zbuffer == 0 and p0.zbuffer == 0 and p1.ztest in (0, 2) and p0.alpha_test == 0):
            draw["passes"].append(_pass(p1, f"{name} pass 1", int(BLEND[p1.blend] == "alpha")))
        else:
            out["draws"].append(dict(_state(p1), passes=[_pass(p1, f"{name} pass 1")]))
    return out


def compile_glow(s, name):
    """The passes a style is swapped for while drawing the screen-glow buffer ([GlowRSMap] in
    clientbutes.txt), with the state they need. One opaque or MUL_SRCALPHA_ZERO pass (premultiplied
    in the shader, blendOver 1) can be drawn over an opaque model's own state. Two alpha-blended
    passes with the same Z and cull fold into one premultiplied draw, Blend One OneMinusSrcAlpha
    (blendOver 2 on the first): over(over(dst, c0, a0), c1, a1) = c1 a1 + (1 - a1) a0 c0
    + (1 - a0)(1 - a1) dst. No other glow style is used."""
    _check(s, name)
    p0 = s.passes[0]
    if len(s.passes) == 1 and BLEND[p0.blend] in ("opaque", "mul_srcalpha_zero"):
        return dict(_state(p0), blend=UNITY_BLEND["opaque"],
                    passes=[_pass(p0, name, int(BLEND[p0.blend] == "mul_srcalpha_zero"))])
    if (len(s.passes) == 2 and all(BLEND[p.blend] == "alpha" for p in s.passes)
            and len({(p.zbuffer, p.ztest, p.cull) for p in s.passes}) == 1):
        return dict(_state(p0), blend=(1, 10),
                    passes=[_pass(p0, f"{name} pass 0", 2), _pass(s.passes[1], f"{name} pass 1", 1)])
    raise ValueError(f"{name}: glow style must be one opaque or MUL_SRCALPHA_ZERO pass, "
                     f"or two alpha-blended passes")


if __name__ == "__main__":
    import json
    import sys
    for path in sys.argv[1:]:
        st = load(path)
        try:
            print(path, json.dumps(compile_style(st, path)))
        except ValueError as e:
            print(path, "UNSUPPORTED:", e)
