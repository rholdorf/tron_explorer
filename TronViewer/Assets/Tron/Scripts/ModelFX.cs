using System;

namespace Tron
{
    // An effect that shows a model, as ModelFXRenderer draws it: whether it shows, where, its clip time, lit
    // or full bright, and where its nodes and sockets go once drawn. Colour and scale are the effect's.
    public interface IFxModelView
    {
        FxEffect Effect { get; }
        bool Shown { get; }
        LTVec ModelPos { get; }
        LTQuat ModelRot { get; }
        float AnimTime { get; }
        bool NoLight { get; }
        FxModel.NodeTransform Nodes { set; }
    }

    // The LTBModel effect as the game plays it (ltjs clientfxdll/ltbmodelfx.cpp; docs/research/clientfx-types.md
    // on research/clientfx-types): one model object, created with the effect at its parent's rotation turned
    // to Normal (offset in those axes), then placed by the base rules each update and turned by Facing:
    // ParentAlign keeps the parent's rotation turned to Normal, CameraFacing the camera's, AlongNormal keeps
    // what the base gives (the parent's: the normal is lost, ltjs as written). RotateAdd (degrees per second)
    // builds a spin on top of the facing. Ck scales the model's lights and fades its lit passes (R, G, B, A
    // of the base), Sk its size. Its clip (AniName, else animation 0) plays without looping and restarts
    // once done; OverrideAniLength stretches it over AniLength (the key's lifespan when 0); SyncToKey scrubs
    // it with the key's time, SyncToModelAnim drives the key's time from it. With smooth shutdown the effect
    // waits for the clip to finish. Pos and Rot are the model object's: effects linked to it follow them.
    // Plain C#, no Unity, so tools/tests/test_model_fx.py compiles it with .NET.
    public sealed class FxModel : FxEffect, IFxModelView
    {
        public const int CameraFacing = 0, AlongNormal = 1, ParentAlign = 2;

        public delegate bool NodeTransform(string name, bool socket, out LTVec pos, out LTQuat rot);

        readonly ClientFXMgr mgr;
        // The clip's length in ms (the main tracker's GetCurAnimLength); < 0 when the model has none.
        readonly int animMs;
        int facing;
        bool rotate, syncToKey, syncToModelAnim, overrideLength;
        float rate = 1;
        LTQuat normalRot, spin = new LTQuat(0, 0, 0, 1);
        bool playDone;

        // Where its clip is (s) and how fast it runs.
        public float AnimTime { get; private set; }
        public float AnimRate => rate;
        public bool HasAnim => animMs >= 0;
        // Its model's nodes and sockets in the level, as last drawn (ModelFXRenderer); none until then.
        public NodeTransform Nodes { get; set; }

        // animLength: the clip's length (s), negative for a model with no clip.
        public FxModel(ClientFXMgr mgr, float animLength)
        {
            this.mgr = mgr;
            animMs = animLength < 0 ? -1 : (int)Math.Round(animLength * 1000);
            playDone = animMs < 0;
        }

        protected override void OnInit()
        {
            var k = Key;
            facing = (int)k.Num("Facing", 0);
            syncToKey = k.Num("SyncToKey") != 0;
            syncToModelAnim = !syncToKey && k.Num("SyncToModelAnim") != 0;
            overrideLength = k.Num("OverrideAniLength") != 0;
            rotate = k.RotateAdd.x != 0 || k.RotateAdd.y != 0 || k.RotateAdd.z != 0;
            // ParseProperties: a zero normal is the z axis.
            var n = k.Vec("Normal", new LTVec(0, 0, 1));
            n = n.Length() * n.Length() > 1e-6f ? n / n.Length() : new LTVec(0, 0, 1);
            var r = n.y == 1 || n.y == -1 ? new LTVec(1, 0, 0).Cross(n) : new LTVec(0, 1, 0).Cross(n);
            normalRot = LTQuat.FromForwardUp(n, n.Cross(r));
            Rot = CreateRot * normalRot;
            Pos = CreatePos + Rot.Rotate(k.Offset);
            AnimTime = 0;
            if (overrideLength)
            {
                float len = k.Num("AniLength") < 1e-6f ? k.Lifespan : k.Num("AniLength");
                rate = Math.Abs(len) >= 1e-6f && animMs > 0 ? animMs * 0.001f / len : 0;
            }
        }

        protected override void OnBeginUpdate()
        {
            if (animMs <= 0) return;
            if (syncToModelAnim)
            {
                int t = (int)(AnimTime * 1000) % animMs;
                Elapsed = t * Key.Lifespan / animMs;
            }
            else if (syncToKey)
            {
                // ResetAnim, then the time the key's place in its life gives (the last ms left out).
                float lifespan = Key.Lifespan;
                float wrapped = lifespan > 0 ? (float)(Elapsed / lifespan % 1.0) : 0;
                AnimTime = (uint)(wrapped * (animMs - 1)) / 1000f;
                playDone = false;
            }
        }

        protected override void OnUpdate(float dt)
        {
            // The clip restarts once it has played (the main tracker doesn't loop). Not while shutting down:
            // ltjs restarts it there too and then asks whether it has finished, so a clip of more than one
            // key would never let the effect go (one-shot fades like M08_EnergyWall_FadeOut would blink on
            // forever); the viewer lets it finish.
            if (!syncToKey && playDone && animMs >= 0 && !ShuttingDown)
            {
                AnimTime = 0;
                playDone = false;
            }
            if (Parent != null && facing == ParentAlign) Rot = rotate ? Parent.Rot : Parent.Rot * normalRot;
            if (rotate)
            {
                LTVec r = spin.Right(), u = spin.Up(), f = spin.Forward();
                var basis = facing == CameraFacing ? mgr.CameraRot : Rot;
                const float rad = (float)(Math.PI / 180);
                spin = LTQuat.AxisAngle(r, Key.RotateAdd.x * dt * rad) * spin;
                spin = LTQuat.AxisAngle(u, Key.RotateAdd.y * dt * rad) * spin;
                spin = LTQuat.AxisAngle(f, Key.RotateAdd.z * dt * rad) * spin;
                Rot = basis * spin * normalRot;
            }
            else if (facing == CameraFacing) Rot = mgr.CameraRot * normalRot;
        }

        // The engine's own frame on the model: its main tracker runs at its rate and stops at the end.
        public override void EngineUpdate(float dt)
        {
            if (animMs < 0 || playDone) return;
            AnimTime += dt * rate;
            if (AnimTime * 1000 >= animMs)
            {
                AnimTime = animMs / 1000f;
                playDone = true;
            }
        }

        public override bool IsFinishedShuttingDown => syncToKey || playDone;

        FxEffect IFxModelView.Effect => this;
        bool IFxModelView.Shown => Visible;
        LTVec IFxModelView.ModelPos => Pos;
        LTQuat IFxModelView.ModelRot => Rot;
        bool IFxModelView.NoLight => false;

        public override bool Attachment(string name, bool socket, out LTVec pos, out LTQuat rot)
        {
            if (Nodes != null) return Nodes(name, socket, out pos, out rot);
            pos = default;
            rot = default;
            return false;
        }
    }
}
