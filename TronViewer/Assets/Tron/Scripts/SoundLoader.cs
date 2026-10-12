using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

namespace Tron
{
    // 16-bit (or 8-bit) PCM samples of a WAV file, interleaved, as floats in [-1, 1].
    public class PcmWav
    {
        public int channels, sampleRate;
        public float[] samples;
        public int Frames => samples.Length / channels;
    }

    // Sound files as AudioClips, requested by the path the game uses ("Snd\amb\drone12.WAV"), read
    // synchronously like DtxLoader's textures. The exporter writes every file the levels name to
    // <export>/sounds/<path in lower case> as PCM WAV (MP3-in-WAV is decoded there), so this only reads PCM.
    // Soundbute names are resolved before this (a soundbute picks one of its files).
    public static class SoundLoader
    {
        static readonly Dictionary<string, AudioClip> cache = new Dictionary<string, AudioClip>();
        // Paths asked for since the last ClearCache that have no readable file.
        public static readonly SortedSet<string> Missing = new SortedSet<string>();
        public static string Root; // <export>/sounds

        public static void ClearCache()
        {
            foreach (var c in cache.Values) if (c) UnityEngine.Object.Destroy(c);
            cache.Clear();
            Missing.Clear();
        }

        // The clip for a sound file, or null (and the path in Missing) if it isn't in the export.
        public static AudioClip Load(string path)
        {
            if (string.IsNullOrWhiteSpace(path)) return null;
            path = DtxLoader.Normalize(path);
            if (cache.TryGetValue(path, out var cached)) return cached;
            AudioClip clip = null;
            try
            {
                var full = Path.Combine(Root ?? "", path);
                if (File.Exists(full))
                {
                    var wav = ReadWav(File.ReadAllBytes(full));
                    clip = AudioClip.Create(path, wav.Frames, wav.channels, wav.sampleRate, false);
                    clip.SetData(wav.samples, 0);
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning($"Sound {path}: {e.Message}");
                if (clip) UnityEngine.Object.Destroy(clip);
                clip = null;
            }
            if (!clip) Missing.Add(path);
            cache[path] = clip;
            return clip;
        }

        // RIFF WAVE with a PCM fmt chunk; other chunks (cue, LIST, FLLR...) are skipped.
        public static PcmWav ReadWav(byte[] b)
        {
            if (b.Length < 12 || Encoding.ASCII.GetString(b, 0, 4) != "RIFF" || Encoding.ASCII.GetString(b, 8, 4) != "WAVE")
                throw new InvalidDataException("not a RIFF WAVE file");
            int format = -1, channels = 0, rate = 0, bits = 0;
            for (int i = 12; i + 8 <= b.Length;)
            {
                var id = Encoding.ASCII.GetString(b, i, 4);
                int n = BitConverter.ToInt32(b, i + 4);
                int body = i + 8;
                if (n < 0 || body + n > b.Length) n = b.Length - body; // truncated last chunk
                if (id == "fmt ")
                {
                    format = BitConverter.ToUInt16(b, body);
                    channels = BitConverter.ToUInt16(b, body + 2);
                    rate = BitConverter.ToInt32(b, body + 4);
                    bits = BitConverter.ToUInt16(b, body + 14);
                }
                else if (id == "data")
                {
                    if (format != 1 || (bits != 16 && bits != 8) || channels < 1)
                        throw new InvalidDataException($"not 8/16-bit PCM (format {format}, {bits} bits, {channels} channels)");
                    int bytesPer = bits / 8;
                    int count = n / bytesPer / channels * channels;
                    var s = new float[count];
                    if (bits == 16)
                        for (int k = 0; k < count; k++) s[k] = (short)(b[body + 2 * k] | b[body + 2 * k + 1] << 8) / 32768f;
                    else
                        for (int k = 0; k < count; k++) s[k] = (b[body + k] - 128) / 128f;
                    return new PcmWav { channels = channels, sampleRate = rate, samples = s };
                }
                i = body + n + (n & 1);
            }
            throw new InvalidDataException("no data chunk");
        }
    }
}
