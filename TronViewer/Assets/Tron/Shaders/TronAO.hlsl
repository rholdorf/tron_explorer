#ifndef TRON_AO_INCLUDED
#define TRON_AO_INCLUDED

// Remaster ssao (#99): URP's SSAO, computed on the main camera from the DepthNormals prepass, occludes the lit
// term of Tron/World and Tron/Model. _LTAO is 1 only while the main camera draws with ssao on; at 0 nothing is
// sampled, so faithful pixels can't change.

TEXTURE2D_X(_ScreenSpaceOcclusionTexture);
float _LTAO;

float SampleAO(float4 positionCS)
{
    if (_LTAO <= 0) return 1;
    return SAMPLE_TEXTURE2D_X(_ScreenSpaceOcclusionTexture, sampler_LinearClamp, GetNormalizedScreenSpaceUV(positionCS)).x;
}

// A world normal as URP's DepthNormals prepass stores it.
half4 PackDepthNormal(float3 n)
{
#if defined(_GBUFFER_NORMALS_OCT)
    float2 o = PackNormalOctQuadEncode(normalize(n));
    return half4(PackFloat2To888(saturate(o * 0.5 + 0.5)), 0);
#else
    return half4(normalize(n), 0);
#endif
}

#endif
