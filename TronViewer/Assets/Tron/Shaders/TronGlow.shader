// Screen glow (screenglowmgr.cpp): separable gaussian blur of the glow buffer, then additive composite.
Shader "Hidden/Tron/GlowBlur"
{
    Properties { _MainTex ("Glow", 2D) = "black" {} }
    SubShader
    {
        ZTest Always ZWrite Off Cull Off
        Pass
        {
            CGPROGRAM
            #pragma vertex vert_img
            #pragma fragment frag
            #include "UnityCG.cginc"
            sampler2D _MainTex;
            float4 _MainTex_TexelSize;
            float4 _GlowDir;          // xy = texel step direction * uvScale
            float _GlowOffsets[64];   // MaxGlowTaps: remaster's resampled filter has 48
            float _GlowWeights[64];
            int _GlowTaps;
            fixed4 frag (v2f_img i) : SV_Target
            {
                float3 acc = 0;
                for (int k = 0; k < _GlowTaps; k++)
                    acc += tex2D(_MainTex, i.uv + _GlowDir.xy * _MainTex_TexelSize.xy * _GlowOffsets[k]).rgb * _GlowWeights[k];
                return fixed4(acc, 1);
            }
            ENDCG
        }
    }
}
