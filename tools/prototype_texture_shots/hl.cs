var on = ON; var key = "KEY"; int n = 0;
foreach (var r in UnityEngine.Object.FindObjectsByType<UnityEngine.Renderer>(UnityEngine.FindObjectsSortMode.None))
  foreach (var m in r.sharedMaterials) {
    if (m == null || m.name.Replace('\\', '/').ToLowerInvariant() != key) continue;
    var t = Tron.DtxLoader.Load(m.name);
    if (on) { m.SetTexture("_MainTex", UnityEngine.Texture2D.whiteTexture); m.SetFloat("_Fullbright", 1); }
    else { if (t != null) m.SetTexture("_MainTex", t.tex); m.SetFloat("_Fullbright", t != null && t.fullbright ? 1 : 0); }
    n++;
  }
return n;
