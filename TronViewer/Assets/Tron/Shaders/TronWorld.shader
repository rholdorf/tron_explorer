// Reproduces the LithTech Jupiter fixed-function world shaders (d3d_rendershader_gouraud.cpp):
//   base    = texture * vertexColor * 2          (Saturate=1 -> D3DTOP_MODULATE2X; vertex color = baked lighting)
//   fullbright DTX: lerp(lit, texture, texture.a) (d3d_rendershader_gouraud_fullbright.cpp)
//   glow pass (_LTGlowPass): fullbright -> texture.rgb * texture.a, everything else black
//   envmap  = (texture ADDSIGNED env) * diffuse  (EnvMapAdd=1; EnvMapAlpha masks env by texture alpha)
//   detail  = (texture ADDSIGNED detail) * diffuse
//   lightmap (shader lightmap_texture, d3d_rendershader_lightmap.cpp): the game draws the lightmap,
//            then the texture pass with blend DESTCOLOR/SRCCOLOR (= 2 * dst * src with Saturate) and
//            fog color 0x808080, so fog = 2 * lerp(fog, lm, f) * lerp(0.5, tex, f); fullbright adds a
//            SRCALPHA/INVSRCALPHA pass of the (grey-fogged) texture. Reproduced here in one pass.
// plus D3D linear fog. Math is done in gamma space like the original, then converted
// to linear with the exact sRGB curve, so the sRGB render target stores the gamma value unchanged
// (textures are uploaded as linear = raw values).
Shader "Tron/World"
{
    Properties
    {
        _MainTex ("Texture", 2D) = "white" {}
        _EnvTex ("Env Map", 2D) = "gray" {}
        _DetailTex ("Detail", 2D) = "gray" {}
        _LightmapTex ("Lightmap atlas (uv2)", 2D) = "gray" {}
        _UseLightmap ("Use Lightmap", Float) = 0
        _UseEnv ("Use Env", Float) = 0
        _EnvAlpha ("Env Map masked by alpha", Float) = 0
        _UseDetail ("Use Detail", Float) = 0
        _DetailScale ("Detail scale/angle (sx, sy, cos, sin)", Vector) = (1,1,1,0)
        _Cutoff ("Alpha ref (0 = off)", Float) = 0
        _Alpha ("Object alpha", Float) = 1
        _UVScroll ("UV scroll (u/s, v/s)", Vector) = (0,0,0,0)
        _Fullbright ("DTX fullbright (alpha = self-illum/glow mask)", Float) = 0
        _SrcBlend ("Src", Float) = 1
        _DstBlend ("Dst", Float) = 0
        _ZWrite ("ZWrite", Float) = 1
        _ZTest ("ZTest", Float) = 4
        _NoFog ("Fog disabled (FLAG_FOGDISABLE)", Float) = 0
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

            TEXTURE2D(_MainTex); SAMPLER(sampler_MainTex);
            TEXTURE2D(_EnvTex); SAMPLER(sampler_EnvTex);
            TEXTURE2D(_DetailTex); SAMPLER(sampler_DetailTex);
            TEXTURE2D(_LightmapTex); SAMPLER(sampler_LightmapTex);

            // Every material property lives in UnityPerMaterial so the SRP Batcher can batch draws.
            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST;
                float4 _DetailScale, _UVScroll;
                float _UseEnv, _EnvAlpha, _UseDetail, _Cutoff, _Alpha, _Fullbright, _NoFog, _UseLightmap;
                float _SrcBlend, _DstBlend, _ZWrite, _ZTest, _Cull;
            CBUFFER_END

            // Set globally per camera by TronExplorer: color (gamma 0-1), x=near, y=far, z=enabled
            float4 _LTFogColor;
            float4 _LTFogParams;
            float _LTSaturate;   // 1 or 2 (console var "Saturate")
            float _LTGlowPass;   // 1 while rendering the screen-glow buffer

            struct appdata
            {
                float4 vertex : POSITION;
                float3 normal : NORMAL;
                float2 uv : TEXCOORD0;
                float2 uv2 : TEXCOORD1;
                float4 color : COLOR;
            };

            struct v2f
            {
                float4 pos : SV_POSITION;
                float2 uv : TEXCOORD0;
                float2 envuv : TEXCOORD1;
                float2 detuv : TEXCOORD2;
                float fog : TEXCOORD3;
                float2 lmuv : TEXCOORD4;
                float4 color : COLOR;
            };

            v2f vert (appdata v)
            {
                v2f o;
                float3 wpos = TransformObjectToWorld(v.vertex.xyz);
                o.pos = TransformWorldToHClip(wpos);
                o.uv = v.uv + _UVScroll.xy * _Time.y;
                float2 d = v.uv * _DetailScale.xy;
                o.detuv = float2(d.x * _DetailScale.z - d.y * _DetailScale.w, d.x * _DetailScale.w + d.y * _DetailScale.z);
                // d3d_SetEnvMapTransform: per-vertex D3DTSS_TCI_CAMERASPACEREFLECTIONVECTOR, rotated to
                // world space by m_mWorldEnvMap (camera basis), then uv = R.xy * (-0.5 / EnvScale) + 0.5
                // with EnvScale 1. Level geometry is in LithTech world axes, so Unity world space matches.
                float3 r = reflect(normalize(wpos - GetCameraPositionWS()), TransformObjectToWorldNormal(v.normal));
                o.envuv = r.xy * -0.5 + 0.5;
                float3 viewPos = TransformWorldToView(wpos);
                // Fog is computed in LithTech units: distance is divided by the world scale.
                float dist = -viewPos.z / _LTFogParams.w;
                o.fog = _LTFogParams.z > 0 && _NoFog == 0 ? saturate((_LTFogParams.y - dist) / max(_LTFogParams.y - _LTFogParams.x, 1e-3)) : 1;
                o.color = v.color;
                o.lmuv = v.uv2;
                return o;
            }

            float4 frag (v2f i) : SV_Target
            {
                float4 tex = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, i.uv);
                if (_Cutoff > 0 && tex.a < _Cutoff) discard;
                float3 c = tex.rgb;
                if (_UseEnv > 0)
                {
                    float3 env = SAMPLE_TEXTURE2D(_EnvTex, sampler_EnvTex, i.envuv).rgb - 0.5;
                    c = saturate(c + env * (_EnvAlpha > 0 ? tex.a : 1));
                }
                if (_UseDetail > 0)
                    c = saturate(c + SAMPLE_TEXTURE2D(_DetailTex, sampler_DetailTex, i.detuv).rgb - 0.5);
                float a = (_Fullbright > 0 ? 1 : tex.a) * i.color.a * _Alpha;
                if (_LTGlowPass > 0)
                {
                    // Glow buffer is kept in gamma space; fogged towards black like ScreenGlowFog.
                    float3 g = _Fullbright > 0 ? tex.rgb * tex.a : 0;
                    return float4(g, a);
                }
                float sat = max(_LTSaturate, 1);
                if (_UseLightmap > 0)
                {
                    // Multipass: lightmap fogged to the fog color, texture fogged to 1/Saturate.
                    float3 lm = lerp(_LTFogColor.rgb, SAMPLE_TEXTURE2D(_LightmapTex, sampler_LightmapTex, i.lmuv).rgb, i.fog);
                    float3 texPass = lerp(1 / sat, c, i.fog);
                    c = saturate(lm * texPass * sat);
                    if (_Fullbright > 0) c = lerp(c, lerp(1 / sat, tex.rgb, i.fog), tex.a);
                    return float4(SRGBToLinear(c), a);
                }
                float3 lit = c * i.color.rgb * sat;
                c = _Fullbright > 0 ? lerp(lit, tex.rgb, tex.a) : lit;
                c = lerp(_LTFogColor.rgb, saturate(c), i.fog);
                return float4(SRGBToLinear(c), a);
            }
            ENDHLSL
        }
    }
}
