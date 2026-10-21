using System;

namespace Tron
{
    // The viewer's random sources. A capture (-shots, -frames) seeds them and fixes the frame time, so two runs
    // draw the same frames and faithful mode can be checked pixel for pixel (#92); otherwise each is seeded by
    // the clock, as before.
    public static class ViewerRandom
    {
        static Random seeds;

        public static void Seed(int seed)
        {
            seeds = new Random(seed);
            UnityEngine.Random.InitState(seed);
        }

        public static Random New() => seeds != null ? new Random(seeds.Next()) : new Random();

        public static Func<double> NextDouble() => New().NextDouble;
    }
}
