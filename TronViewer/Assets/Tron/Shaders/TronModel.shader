// LithTech Jupiter model pieces drawn with their render style (d3d_renderstatemgr.cpp
// SetRenderStyleStates): up to 2 fixed-function texture stages per pass, evaluated from material
// floats (tools/renderstyle.py compiles the style and refuses what this shader can't draw).
//   stage vector a = (colorOp, colorArg1, colorArg2, texture slot), b = (alphaOp, alphaArg1, alphaArg2, uv set)
//   ops:  0 disable, 1 SELECTARG1, 2 SELECTARG2, 3 MODULATE, 4 MODULATE2X, 5 BLENDCURRENTALPHA,
//         6 BLENDFACTORALPHA, 7 ADD, 8 BLENDTEXTUREALPHA
//   args: 0 CURRENT, 1 DIFFUSE, 2 TEXTURE, 3 TFACTOR; texture slot 1..2 = the piece's texture list
//   uv set: 0 = model UVs, 1 = camera-space reflection vector xy (D3DTSS_TCI_CAMERASPACEREFLECTIONVECTOR)
// A second pass that blends over an opaque first pass is folded in (exact, fog included). Each draw is
// fogged with the world fog color before blending, like D3D fixed-function fog on every model pass.
// Diffuse is the D3D lighting result for lit passes (emissive + material diffuse * light) and white for
// unlit ones. Until the light grid lands, the light is the vertex color x2 (neutral 128).
// The glow buffer draws the style's [GlowRSMap] replacement pass (black when unmapped).
Shader "Tron/Model"
{
    Properties
    {
        _Tex1 ("Texture 1", 2D) = "white" {}
        _Tex2 ("Texture 2", 2D) = "white" {}
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
        _TF0 ("Pass 0 texture factor", Vector) = (0.5,0.5,0.5,0.5)
        _TF1 ("Pass 1 texture factor", Vector) = (0.5,0.5,0.5,0.5)
        _TFG ("Glow texture factor", Vector) = (0,0,0,0)
        _P0 ("Pass 0 (lit, -, alpha test func, alpha ref)", Vector) = (1,0,0,0.5)
        _P1 ("Pass 1 (lit, blend over, alpha test func, alpha ref; lit < 0 = no pass)", Vector) = (-1,0,0,0.5)
        _PG ("Glow (lit, premultiply, alpha test func, alpha ref)", Vector) = (0,0,0,0.5)
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
        Pass
        {
            Blend [_SrcBlend] [_DstBlend]
            ZWrite [_ZWrite]
            ZTest [_ZTest]
            Cull [_Cull]

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.core/ShaderLibrary/Color.hlsl"

            TEXTURE2D(_Tex1); SAMPLER(sampler_Tex1);
            TEXTURE2D(_Tex2); SAMPLER(sampler_Tex2);

            CBUFFER_START(UnityPerMaterial)
                float4 _Tex1_ST, _Tex2_ST;
                float4 _S0a, _S0b, _S1a, _S1b, _T0a, _T0b, _T1a, _T1b, _G0a, _G0b, _G1a, _G1b;
                float4 _TF0, _TF1, _TFG, _P0, _P1, _PG;
                float4 _MatDiffuse, _MatEmissive, _MatAmbient;
                float _SrcBlend, _DstBlend, _ZWrite, _ZTest, _Cull;
            CBUFFER_END

            // Globals shared with Tron/World (set by TronExplorer).
            float4 _LTFogColor;
            float4 _LTFogParams;
            float _LTGlowPass;

            struct appdata
            {
                float4 vertex : POSITION;
                float3 normal : NORMAL;
                float2 uv : TEXCOORD0;
                float4 color : COLOR;
            };

            struct v2f
            {
                float4 pos : SV_POSITION;
                float2 uv : TEXCOORD0;
                float2 refl : TEXCOORD1;
                float fog : TEXCOORD2;
                float4 color : COLOR;
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
                float3 vn = normalize(TransformWorldToViewDir(TransformObjectToWorldNormal(v.normal)));
                o.refl = reflect(normalize(vpos), vn).xy;
                float dist = -vpos.z / _LTFogParams.w;
                o.fog = _LTFogParams.z > 0 ? saturate((_LTFogParams.y - dist) / max(_LTFogParams.y - _LTFogParams.x, 1e-3)) : 1;
                o.color = v.color;
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
                return lerp(a2, a1, texA);
            }

            float4 Stage(float4 sa, float4 sb, float4 cur, float4 dif, float4 tf, float2 uv, float2 refl)
            {
                float2 tc = sb.w > 0 ? refl : uv;
                float4 tex = sa.w == 1 ? SAMPLE_TEXTURE2D(_Tex1, sampler_Tex1, tc)
                           : sa.w == 2 ? SAMPLE_TEXTURE2D(_Tex2, sampler_Tex2, tc) : float4(1, 1, 1, 1);
                float3 c = Op(sa.x, Arg(sa.y, cur, dif, tex, tf), Arg(sa.z, cur, dif, tex, tf), cur.a, tex.a, tf.a).rgb;
                float a = sb.x == 0 ? cur.a : Op(sb.x, Arg(sb.y, cur, dif, tex, tf), Arg(sb.z, cur, dif, tex, tf), cur.a, tex.a, tf.a).a;
                return float4(c, a);
            }

            float4 EvalPass(float4 s0a, float4 s0b, float4 s1a, float4 s1b, float4 tf, float lit, v2f i)
            {
                // D3D lighting: emissive + material diffuse * light (ambient light arrives with the light grid).
                float4 dif = lit > 0 ? float4(saturate(_MatEmissive.rgb + _MatDiffuse.rgb * i.color.rgb * 2), _MatDiffuse.a) : 1;
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

            float4 frag (v2f i) : SV_Target
            {
                if (_LTGlowPass > 0)
                {
                    float4 g = EvalPass(_G0a, _G0b, _G1a, _G1b, _TFG, _PG.x, i);
                    if (!AlphaPass(g.a, _PG.z, _PG.w)) discard;
                    if (_PG.y > 0) g = float4(g.rgb * g.a, 1);
                    return g;
                }
                float4 c = EvalPass(_S0a, _S0b, _S1a, _S1b, _TF0, _P0.x, i);
                if (!AlphaPass(c.a, _P0.z, _P0.w)) discard;
                if (_P1.x >= 0)
                {
                    float4 c1 = EvalPass(_T0a, _T0b, _T1a, _T1b, _TF1, _P1.x, i);
                    if (AlphaPass(c1.a, _P1.z, _P1.w)) c.rgb = _P1.y > 0 ? lerp(c.rgb, c1.rgb, saturate(c1.a)) : c1.rgb;
                }
                c.rgb = lerp(_LTFogColor.rgb, saturate(c.rgb), i.fog);
                return float4(SRGBToLinear(c.rgb), saturate(c.a));
            }
            ENDHLSL
        }
    }
}
