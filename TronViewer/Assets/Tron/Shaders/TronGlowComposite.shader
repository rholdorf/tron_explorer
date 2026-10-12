// Adds the blurred glow buffer (gamma values) to the screen, in gamma space under the Gamma color space.
Shader "Hidden/Tron/GlowComposite"
{
    Properties { _MainTex ("Glow", 2D) = "black" {} }
    SubShader
    {
        Tags { "Queue"="Overlay" "RenderType"="Transparent" }
        ZTest Always ZWrite Off Cull Off
        Blend One One
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            sampler2D _MainTex;
            struct appdata { float4 vertex : POSITION; float2 uv : TEXCOORD0; };
            struct v2f { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };
            v2f vert (appdata v) { v2f o; o.pos = UnityObjectToClipPos(v.vertex); o.uv = v.uv; return o; }
            fixed4 frag (v2f i) : SV_Target
            {
                fixed3 g = saturate(tex2D(_MainTex, i.uv).rgb);
            #ifdef UNITY_COLORSPACE_GAMMA
                return fixed4(g, 0);
            #else
                return fixed4(GammaToLinearSpace(g), 0);
            #endif
            }
            ENDCG
        }
    }
}
