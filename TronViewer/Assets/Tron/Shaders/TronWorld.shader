// Reproduces the LithTech Jupiter fixed-function world shaders (d3d_rendershader_gouraud.cpp):
//   base    = texture * vertexColor * 2          (Saturate=1 -> D3DTOP_MODULATE2X; vertex color = baked lighting)
//   fullbright DTX: lerp(lit, texture, texture.a) (d3d_rendershader_gouraud_fullbright.cpp)
//   glow pass (_LTGlowPass): fullbright -> texture.rgb * texture.a, everything else black
//   envmap  = (texture ADDSIGNED env) * diffuse  (EnvMapAdd=1; EnvMapAlpha masks env by texture alpha)
//   detail  = (texture ADDSIGNED detail) * diffuse
// plus D3D linear fog. Math is done in gamma space like the original, then converted
// to linear for the sRGB render target (textures are uploaded as linear = raw values).
Shader "Tron/World"
{
    Properties
    {
        _MainTex ("Texture", 2D) = "white" {}
        _EnvTex ("Env Map", 2D) = "gray" {}
        _DetailTex ("Detail", 2D) = "gray" {}
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
        Tags { "RenderType"="Opaque" "Queue"="Geometry" }
        Pass
        {
            Blend [_SrcBlend] [_DstBlend]
            ZWrite [_ZWrite]
            ZTest [_ZTest]
            Cull [_Cull]

            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _MainTex, _EnvTex, _DetailTex;
            float4 _MainTex_ST;
            float _UseEnv, _EnvAlpha, _UseDetail, _Cutoff, _Alpha, _Fullbright, _NoFog;
            float4 _DetailScale, _UVScroll;

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
                float4 color : COLOR;
            };

            struct v2f
            {
                float4 pos : SV_POSITION;
                float2 uv : TEXCOORD0;
                float2 envuv : TEXCOORD1;
                float2 detuv : TEXCOORD2;
                float fog : TEXCOORD3;
                float4 color : COLOR;
            };

            v2f vert (appdata v)
            {
                v2f o;
                o.pos = UnityObjectToClipPos(v.vertex);
                o.uv = v.uv + _UVScroll.xy * _Time.y;
                float2 d = v.uv * _DetailScale.xy;
                o.detuv = float2(d.x * _DetailScale.z - d.y * _DetailScale.w, d.x * _DetailScale.w + d.y * _DetailScale.z);
                // Sphere-ish env map from the camera-space normal (d3d_SetEnvMapTransform)
                float3 vn = normalize(mul((float3x3)UNITY_MATRIX_IT_MV, v.normal));
                o.envuv = vn.xy * float2(0.5, -0.5) + 0.5;
                float3 viewPos = UnityObjectToViewPos(v.vertex);
                // Fog is computed in LithTech units: distance is divided by the world scale.
                float dist = -viewPos.z / _LTFogParams.w;
                o.fog = _LTFogParams.z > 0 && _NoFog == 0 ? saturate((_LTFogParams.y - dist) / max(_LTFogParams.y - _LTFogParams.x, 1e-3)) : 1;
                o.color = v.color;
                return o;
            }

            fixed4 frag (v2f i) : SV_Target
            {
                fixed4 tex = tex2D(_MainTex, i.uv);
                if (_Cutoff > 0 && tex.a < _Cutoff) discard;
                fixed3 c = tex.rgb;
                if (_UseEnv > 0)
                {
                    fixed3 env = tex2D(_EnvTex, i.envuv).rgb - 0.5;
                    c = saturate(c + env * (_EnvAlpha > 0 ? tex.a : 1));
                }
                if (_UseDetail > 0)
                    c = saturate(c + tex2D(_DetailTex, i.detuv).rgb - 0.5);
                float a = (_Fullbright > 0 ? 1 : tex.a) * i.color.a * _Alpha;
                if (_LTGlowPass > 0)
                {
                    // Glow buffer is kept in gamma space; fogged towards black like ScreenGlowFog.
                    fixed3 g = _Fullbright > 0 ? tex.rgb * tex.a : 0;
                    return fixed4(g, a);
                }
                fixed3 lit = c * i.color.rgb * max(_LTSaturate, 1);
                c = _Fullbright > 0 ? lerp(lit, tex.rgb, tex.a) : lit;
                c = lerp(_LTFogColor.rgb, saturate(c), i.fog);
                return fixed4(GammaToLinearSpace(c), a);
            }
            ENDCG
        }
    }
}
