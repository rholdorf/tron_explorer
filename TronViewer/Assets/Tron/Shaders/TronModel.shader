// LithTech Jupiter model pieces drawn with their render style (d3d_renderstatemgr.cpp
// SetRenderStyleStates): up to 2 fixed-function texture stages per pass, evaluated from material
// floats (tools/renderstyle.py compiles the style and refuses what this shader can't draw).
//   stage vector a = (colorOp, colorArg1, colorArg2, texture slot), b = (alphaOp, alphaArg1, alphaArg2, uv set)
//   ops:  0 disable, 1 SELECTARG1, 2 SELECTARG2, 3 MODULATE, 4 MODULATE2X, 5 BLENDCURRENTALPHA,
//         6 BLENDFACTORALPHA, 7 ADD, 8 BLENDTEXTUREALPHA, 9 DOTPRODUCT3
//   args: 0 CURRENT, 1 DIFFUSE, 2 TEXTURE, 3 TFACTOR; texture slot 1..3 = the piece's texture list
//   uv set: 0 = model UVs, 1 = camera-space reflection vector xy (D3DTSS_TCI_CAMERASPACEREFLECTIONVECTOR)
// A second pass that blends over an opaque first pass is folded in (exact, fog included); one that needs
// the framebuffer is a later draw of the piece with its own material (LevelBuilder.CreateModelMaterials).
// Each draw is fogged with the world fog color before blending, like D3D fixed-function fog on every
// model pass. A draw with no main pass (_P0.x < 0) only draws into the glow buffer, one with no glow
// pass (_PG.x < 0) only into the frame.
// Diffuse is the D3D fixed-function lighting result for lit passes and white for unlit ones, per vertex:
// emissive + material ambient * ambient light + sum of material diffuse * light * max(0, N.L), saturated.
// The ambient light and up to 4 directional lights are per instance (ModelLighting.cs, set through a
// MaterialPropertyBlock): the light grid sample, the static object lights and the sun; a dynamic light is a
// D3D point light, attenuated per vertex. An effect model's
// colour scales them (AddAmbientAndScale) and its alpha the material alpha (RenderPieceList(fAlpha)), as
// _LTTransparency = 1 - alpha.
// The glow buffer draws the style's [GlowRSMap] replacement pass (black when unmapped); two alpha-blended
// glow passes fold into one premultiplied draw (_PG.y = 2, second pass in _H*, Blend One OneMinusSrcAlpha).
// Glow draws are fogged towards black with the glow fog (_LTFogParams holds ScreenGlowFog* then).
Shader "Tron/Model"
{
    Properties
    {
        _Tex1 ("Texture 1", 2D) = "white" {}
        _Tex2 ("Texture 2", 2D) = "white" {}
        _Tex3 ("Texture 3", 2D) = "white" {}
        _S0a ("Pass 0 stage 0 color", Vector) = (0,0,0,0)
        _S0b ("Pass 0 stage 0 alpha", Vector) = (0,0,0,0)
        _S1a ("Pass 0 stage 1 color", Vector) = (0,0,0,0)
        _S1b ("Pass 0 stage 1 alpha", Vector) = (0,0,0,0)
        _T0a ("Pass 1 stage 0 color", Vector) = (0,0,0,0)
        _T0b ("Pass 1 stage 0 alpha", Vector) = (0,0,0,0)
        _T1a ("Pass 1 stage 1 color", Vector) = (0,0,0,0)
        _T1b ("Pass 1 stage 1 alpha", Vector) = (0,0,0,0)
        _G0a ("Glow stage 0 color", Vector) = (0,0,0,0)
        _G0b ("Glow stage 0 alpha", Vector) = (0,0,0,0)
        _G1a ("Glow stage 1 color", Vector) = (0,0,0,0)
        _G1b ("Glow stage 1 alpha", Vector) = (0,0,0,0)
        _H0a ("Glow pass 1 stage 0 color", Vector) = (0,0,0,0)
        _H0b ("Glow pass 1 stage 0 alpha", Vector) = (0,0,0,0)
        _H1a ("Glow pass 1 stage 1 color", Vector) = (0,0,0,0)
        _H1b ("Glow pass 1 stage 1 alpha", Vector) = (0,0,0,0)
        _TF0 ("Pass 0 texture factor", Vector) = (0.5,0.5,0.5,0.5)
        _TF1 ("Pass 1 texture factor", Vector) = (0.5,0.5,0.5,0.5)
        _TFG ("Glow texture factor", Vector) = (0,0,0,0)
        _TFH ("Glow pass 1 texture factor", Vector) = (0,0,0,0)
        _P0 ("Pass 0 (lit, -, alpha test func, alpha ref; lit < 0 = glow only)", Vector) = (1,0,0,0.5)
        _P1 ("Pass 1 (lit, blend over, alpha test func, alpha ref; lit < 0 = no pass)", Vector) = (-1,0,0,0.5)
        _PG ("Glow (lit, 1 premultiply / 2 two passes, alpha test func, alpha ref; lit < 0 = no glow)", Vector) = (0,0,0,0.5)
        _PH ("Glow pass 1 (lit, -, alpha test func, alpha ref)", Vector) = (0,0,0,0.5)
        _MatDiffuse ("Material diffuse", Vector) = (1,1,1,1)
        _MatEmissive ("Material emissive", Vector) = (0,0,0,1)
        _MatAmbient ("Material ambient", Vector) = (0,0,0,1)
        _SrcBlend ("Src", Float) = 1
        _DstBlend ("Dst", Float) = 0
        _ZWrite ("ZWrite", Float) = 1
        _ZTest ("ZTest", Float) = 4
        _Cull ("Cull", Float) = 2
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" "Queue"="Geometry" "RenderPipeline"="UniversalPipeline" }
        HLSLINCLUDE
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.core/ShaderLibrary/Color.hlsl"
            #include "TronColor.hlsl"

            // PROTOTYPE (#99): world normal for URP's DepthNormals prepass (SSAO reads it).
            half4 PackDN(float3 n)
            {
            #if defined(_GBUFFER_NORMALS_OCT)
                float2 o = PackNormalOctQuadEncode(normalize(n));
                return half4(PackFloat2To888(saturate(o * 0.5 + 0.5)), 0);
            #else
                return half4(normalize(n), 0);
            #endif
            }
            // PROTOTYPE (#99): -proto-ssao sets _LTAO = 1 while the main camera draws; the AO texture is URP's.
            TEXTURE2D_X(_ScreenSpaceOcclusionTexture);
            float _LTAO;
            float SampleAO(float4 pos)
            {
                if (_LTAO <= 0) return 1;
                return SAMPLE_TEXTURE2D_X(_ScreenSpaceOcclusionTexture, sampler_LinearClamp, GetNormalizedScreenSpaceUV(pos)).x;
            }

            TEXTURE2D(_Tex1); SAMPLER(sampler_Tex1);
            TEXTURE2D(_Tex2); SAMPLER(sampler_Tex2);
            TEXTURE2D(_Tex3); SAMPLER(sampler_Tex3);

            CBUFFER_START(UnityPerMaterial)
                float4 _Tex1_ST, _Tex2_ST, _Tex3_ST;
                float4 _S0a, _S0b, _S1a, _S1b, _T0a, _T0b, _T1a, _T1b, _G0a, _G0b, _G1a, _G1b, _H0a, _H0b, _H1a, _H1b;
                float4 _TF0, _TF1, _TFG, _TFH, _P0, _P1, _PG, _PH;
                float4 _MatDiffuse, _MatEmissive, _MatAmbient;
                float _SrcBlend, _DstBlend, _ZWrite, _ZTest, _Cull;
            CBUFFER_END

            // Globals shared with Tron/World (set by TronExplorer).
            float4 _LTFogColor;
            float4 _LTFogParams;
            float _LTGlowPass;

            // Per instance (MaterialPropertyBlock, LevelBuilder.BuildModels), 0-1: the D3D ambient light and
            // directional lights (xyz = direction the light travels, world space; unused lights are black), or
            // point lights (w = 1: xyz = where it is in the world, the color's w its range).
            float4 _LTAmbient;
            float4 _LTLightDir[4];
            float4 _LTLightColor[4];
            float _LTTransparency;

            struct appdata
            {
                float4 vertex : POSITION;
                float3 normal : NORMAL;
                float2 uv : TEXCOORD0;
            };

            struct v2f
            {
                float4 pos : SV_POSITION;
                float2 uv : TEXCOORD0;
                float2 refl : TEXCOORD1;
                float fog : TEXCOORD2;
                float4 lit : TEXCOORD3;
            };

            v2f vert (appdata v)
            {
                v2f o;
                float3 wpos = TransformObjectToWorld(v.vertex.xyz);
                o.pos = TransformWorldToHClip(wpos);
                o.uv = v.uv;
                // Camera-space reflection of the eye vector; x and y are the same in D3D's left-handed
                // view space and Unity's right-handed one. Used unscaled as u, v (no texture transform).
                float3 vpos = TransformWorldToView(wpos);
                float3 wn = TransformObjectToWorldNormal(v.normal);
                float3 vn = normalize(TransformWorldToViewDir(wn));
                o.refl = reflect(normalize(vpos), vn).xy;
                float dist = -vpos.z / _LTFogParams.w;
                o.fog = _LTFogParams.z > 0 ? saturate((_LTFogParams.y - dist) / max(_LTFogParams.y - _LTFogParams.x, 1e-3)) : 1;
                // D3D lighting (D3DRS_LIGHTING, material colors, no vertex color), Gouraud like the device.
                float3 light = 0;
                [unroll] for (int k = 0; k < 4; k++)
                {
                    float4 ld = _LTLightDir[k];
                    float3 l = -ld.xyz;
                    float att = 1;
                    if (ld.w > 0)
                    {
                        // A D3D point light (a dynamic light): attenuation 1 / (1 + 19 (d / range)^2), none
                        // beyond its range.
                        float3 v = ld.xyz - wpos;
                        float d = length(v), q = d / _LTLightColor[k].w;
                        l = v / max(d, 1e-6);
                        att = d < _LTLightColor[k].w ? 1 / (1 + 19 * q * q) : 0;
                    }
                    light += _LTLightColor[k].rgb * att * max(0, dot(wn, l));
                }
                o.lit = float4(saturate(_MatEmissive.rgb + _MatAmbient.rgb * _LTAmbient.rgb + _MatDiffuse.rgb * light),
                               _MatDiffuse.a * (1 - _LTTransparency));
                return o;
            }

            float4 Arg(float a, float4 cur, float4 dif, float4 tex, float4 tf)
            {
                return a == 0 ? cur : a == 1 ? dif : a == 2 ? tex : tf;
            }

            // D3DTEXTUREOP on 4 channels; the caller keeps rgb from the color op and a from the alpha op.
            float4 Op(float op, float4 a1, float4 a2, float curA, float texA, float tfA)
            {
                if (op == 1) return a1;
                if (op == 2) return a2;
                if (op == 3) return a1 * a2;
                if (op == 4) return saturate(2 * a1 * a2);
                if (op == 5) return lerp(a2, a1, curA);
                if (op == 6) return lerp(a2, a1, tfA);
                if (op == 7) return saturate(a1 + a2);
                if (op == 9) return saturate(4 * dot(a1.rgb - 0.5, a2.rgb - 0.5)).xxxx;
                return lerp(a2, a1, texA);
            }

            float4 Stage(float4 sa, float4 sb, float4 cur, float4 dif, float4 tf, float2 uv, float2 refl)
            {
                float2 tc = sb.w > 0 ? refl : uv;
                float4 tex = sa.w == 1 ? SAMPLE_TEXTURE2D(_Tex1, sampler_Tex1, tc)
                           : sa.w == 2 ? SAMPLE_TEXTURE2D(_Tex2, sampler_Tex2, tc)
                           : sa.w == 3 ? SAMPLE_TEXTURE2D(_Tex3, sampler_Tex3, tc) : float4(1, 1, 1, 1);
                float3 c = Op(sa.x, Arg(sa.y, cur, dif, tex, tf), Arg(sa.z, cur, dif, tex, tf), cur.a, tex.a, tf.a).rgb;
                float a = sb.x == 0 ? cur.a : Op(sb.x, Arg(sb.y, cur, dif, tex, tf), Arg(sb.z, cur, dif, tex, tf), cur.a, tex.a, tf.a).a;
                return float4(c, a);
            }

            float4 EvalPass(float4 s0a, float4 s0b, float4 s1a, float4 s1b, float4 tf, float lit, v2f i)
            {
                float4 dif = lit > 0 ? i.lit : 1;
                float4 cur = dif;
                if (s0a.x > 0) cur = Stage(s0a, s0b, cur, dif, tf, i.uv, i.refl);
                if (s0a.x > 0 && s1a.x > 0) cur = Stage(s1a, s1b, cur, dif, tf, i.uv, i.refl);
                return cur;
            }

            // D3DRS_ALPHAFUNC on the 8-bit alpha, Unity CompareFunction codes (0 = no test).
            bool AlphaPass(float a, float func, float ref)
            {
                float x = round(saturate(a) * 255), r = round(ref * 255);
                return func == 0 || func == 8 || (func == 2 && x < r) || (func == 3 && x == r) || (func == 4 && x <= r)
                    || (func == 5 && x > r) || (func == 6 && x != r) || (func == 7 && x >= r);
            }

            struct v2fDN { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float3 n : TEXCOORD1; };
            v2fDN vertDN (appdata v)
            {
                v2fDN o;
                o.pos = TransformObjectToHClip(v.vertex.xyz);
                o.uv = v.uv;
                o.n = TransformObjectToWorldNormal(v.normal);
                return o;
            }
            half4 fragDN (v2fDN i) : SV_Target
            {
                if (_P0.x < 0 || _SrcBlend != 1 || _DstBlend != 0 || _ZWrite == 0 || _LTTransparency > 0) discard;
                if (_P0.z != 0)
                {
                    v2f f = (v2f)0; f.uv = i.uv; f.lit = 1;
                    if (!AlphaPass(EvalPass(_S0a, _S0b, _S1a, _S1b, _TF0, _P0.x, f).a, _P0.z, _P0.w)) discard;
                }
                return PackDN(i.n);
            }

            float4 frag (v2f i) : SV_Target
            {
                if (_LTGlowPass > 0)
                {
                    if (_PG.x < 0) discard;
                    float4 g = EvalPass(_G0a, _G0b, _G1a, _G1b, _TFG, _PG.x, i);
                    bool pass0 = AlphaPass(g.a, _PG.z, _PG.w);
                    if (_PG.y == 2)
                    {
                        // over(over(dst, g, a0), g1, a1) = g1 a1 + (1 - a1) a0 g + (1 - a0)(1 - a1) dst
                        float4 g1 = EvalPass(_H0a, _H0b, _H1a, _H1b, _TFH, _PH.x, i);
                        bool pass1 = AlphaPass(g1.a, _PH.z, _PH.w);
                        if (!pass0 && !pass1) discard;
                        float a0 = pass0 ? saturate(g.a) : 0, a1 = pass1 ? saturate(g1.a) : 0;
                        return float4(lerp(g.rgb * a0, g1.rgb, a1) * i.fog, 1 - (1 - a0) * (1 - a1));
                    }
                    if (!pass0) discard;
                    if (_PG.y > 0) g = float4(g.rgb * g.a, 1);
                    return float4(g.rgb * i.fog, g.a);
                }
                if (_P0.x < 0) discard;
                i.lit.rgb *= SampleAO(i.pos); // PROTOTYPE (#99): occludes the D3D lighting only (lit passes)
                float4 c = EvalPass(_S0a, _S0b, _S1a, _S1b, _TF0, _P0.x, i);
                if (!AlphaPass(c.a, _P0.z, _P0.w)) discard;
                if (_P1.x >= 0)
                {
                    float4 c1 = EvalPass(_T0a, _T0b, _T1a, _T1b, _TF1, _P1.x, i);
                    if (AlphaPass(c1.a, _P1.z, _P1.w)) c.rgb = _P1.y > 0 ? lerp(c.rgb, c1.rgb, saturate(c1.a)) : c1.rgb;
                }
                c.rgb = lerp(_LTFogColor.rgb, saturate(c.rgb), i.fog);
                return float4(TargetColor(c.rgb), saturate(c.a));
            }
        ENDHLSL
        Pass
        {
            Blend [_SrcBlend] [_DstBlend]
            ZWrite [_ZWrite]
            ZTest [_ZTest]
            Cull [_Cull]

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            ENDHLSL
        }
        // PROTOTYPE (#99)
        Pass
        {
            Name "DepthNormalsOnly"
            Tags { "LightMode"="DepthNormalsOnly" }
            ZWrite On
            Cull [_Cull]
            HLSLPROGRAM
            #pragma vertex vertDN
            #pragma fragment fragDN
            #pragma multi_compile_fragment _ _GBUFFER_NORMALS_OCT
            ENDHLSL
        }
    }
}
