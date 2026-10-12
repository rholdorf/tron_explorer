#ifndef TRON_COLOR_INCLUDED
#define TRON_COLOR_INCLUDED

// Tron shaders do their math in gamma space, like the D3D fixed-function pipeline. Under the Gamma
// color space the render target takes those values as-is and blending happens in gamma space, as
// in the game; under Linear they are converted so an sRGB target stores the same gamma value.
float3 TargetColor(float3 gammaColor)
{
#ifdef UNITY_COLORSPACE_GAMMA
    return gammaColor;
#else
    return SRGBToLinear(gammaColor);
#endif
}

#endif
