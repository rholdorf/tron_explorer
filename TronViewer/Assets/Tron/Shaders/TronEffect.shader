// ClientFX effects drawn by the engine's sprite and particle paths (drawparticles.cpp): texture x vertex
// colour, no lighting, Z test without Z write, both faces, the texture clamped. No fog (FLAG_FOGDISABLE)
// unless _Fog: then D3D linear fog by the world's fog distances towards _FogColor, or the world's fog colour
// when its a is 1 (d3d_GetBlendStates: additive towards black, multiply towards white). DrawPrim effects
// (lightning, trails) repeat their texture (_Wrap) and may test alpha > 0 (_AlphaGreater).
// Blend by the effect's mode: Additive ONE ONE, Multiply ZERO SRCCOLOR, None SRCALPHA INVSRCALPHA. Gamma
// space like the other Tron shaders. Never drawn into the glow buffer (the renderer gives the main camera
// only).
Shader "Tron/Effect"
{
    Properties
    {
        _MainTex ("Texture", 2D) = "white" {}
        _SrcBlend ("Src", Float) = 1
        _DstBlend ("Dst", Float) = 1
        _Fog ("Fogged", Float) = 0
        _FogColor ("Fog color (a = 1: the world's)", Vector) = (0, 0, 0, 0)
        _Wrap ("Repeat the texture", Float) = 0
        _AlphaGreater ("Alpha test: alpha > 0", Float) = 0
    }
    SubShader
    {
        Tags { "RenderType"="Transparent" "Queue"="Transparent" "RenderPipeline"="UniversalPipeline" "IgnoreProjector"="True" }
        Pass
        {
            Blend [_SrcBlend] [_DstBlend]
            ZWrite Off
            ZTest LEqual
            Cull Off

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.core/ShaderLibrary/Color.hlsl"
            #include "TronColor.hlsl"

            TEXTURE2D(_MainTex);
            SamplerState sampler_trilinear_clamp;
            SamplerState sampler_trilinear_repeat;

            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST;
                float _SrcBlend, _DstBlend, _Fog, _Wrap, _AlphaGreater;
                float4 _FogColor;
            CBUFFER_END
            float4 _LTFogColor;
            float4 _LTFogParams;

            struct appdata
            {
                float4 vertex : POSITION;
                float4 color : COLOR;
                float2 uv : TEXCOORD0;
            };

            struct v2f
            {
                float4 pos : SV_POSITION;
                float4 color : COLOR;
                float2 uv : TEXCOORD0;
                float fog : TEXCOORD1;
            };

            v2f vert (appdata v)
            {
                v2f o;
                o.pos = TransformObjectToHClip(v.vertex.xyz);
                o.color = v.color;
                o.uv = v.uv;
                // Fog is computed in LithTech units: distance is divided by the world scale.
                float dist = -TransformWorldToView(TransformObjectToWorld(v.vertex.xyz)).z / _LTFogParams.w;
                o.fog = _LTFogParams.z > 0 && _Fog > 0 ? saturate((_LTFogParams.y - dist) / max(_LTFogParams.y - _LTFogParams.x, 1e-3)) : 1;
                return o;
            }

            half4 frag (v2f i) : SV_Target
            {
                float4 t = _Wrap > 0 ? SAMPLE_TEXTURE2D(_MainTex, sampler_trilinear_repeat, i.uv)
                                     : SAMPLE_TEXTURE2D(_MainTex, sampler_trilinear_clamp, i.uv);
                float4 c = t * i.color;
                if (_AlphaGreater > 0 && c.a <= 0) discard;
                c.rgb = lerp(_FogColor.a > 0 ? _LTFogColor.rgb : _FogColor.rgb, c.rgb, i.fog);
                return half4(TargetColor(c.rgb), c.a);
            }
            ENDHLSL
        }
    }
}
