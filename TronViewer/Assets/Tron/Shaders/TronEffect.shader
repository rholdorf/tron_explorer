// ClientFX effects drawn by the engine's sprite and particle paths (drawparticles.cpp): texture x vertex
// colour, no lighting, no fog (FLAG_FOGDISABLE), Z test without Z write, both faces, the texture clamped.
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

            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST;
                float _SrcBlend, _DstBlend;
            CBUFFER_END

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
            };

            v2f vert (appdata v)
            {
                v2f o;
                o.pos = TransformObjectToHClip(v.vertex.xyz);
                o.color = v.color;
                o.uv = v.uv;
                return o;
            }

            half4 frag (v2f i) : SV_Target
            {
                float4 c = SAMPLE_TEXTURE2D(_MainTex, sampler_trilinear_clamp, i.uv) * i.color;
                return half4(TargetColor(c.rgb), c.a);
            }
            ENDHLSL
        }
    }
}
