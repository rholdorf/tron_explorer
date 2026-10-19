using System;
using System.Collections.Generic;

// Head tracking: the model nodes a character turns toward what it looks at (ltjs game/shared trackednode*.cpp,
// trackednodecontext.cpp; the groups are modelbutes.txt [TrackingNodesN], a skeleton's LookAtTrackingNodes).
// Plain C#, no Unity, so tools/tests/test_tracked_nodes.py compiles it with .NET; ModelAnimator turns the bones.
namespace Tron
{
    // A rotation and a position: the basis vectors as columns (right, up, forward) and the translation.
    public struct LTFrame
    {
        public LTVec R, U, F, T;

        public LTFrame(LTVec r, LTVec u, LTVec f, LTVec t) { R = r; U = u; F = f; T = t; }

        public static LTFrame Identity => new LTFrame(new LTVec(1, 0, 0), new LTVec(0, 1, 0), new LTVec(0, 0, 1), default);

        // The rotation times v (Apply3x3).
        public LTVec Rotate(LTVec v) => R * v.x + U * v.y + F * v.z;
        // The rotation's transpose times v.
        public LTVec Unrotate(LTVec v) => new LTVec(Dot(R, v), Dot(U, v), Dot(F, v));
        // The inverse of a rotation and translation, applied to the point p.
        public LTVec InverseApply(LTVec p) => Unrotate(p - T);
        public LTVec Apply(LTVec p) => Rotate(p) + T;

        // a * b (3x3 and translation).
        public static LTFrame operator *(LTFrame a, LTFrame b) => new LTFrame(a.Rotate(b.R), a.Rotate(b.U), a.Rotate(b.F), a.Apply(b.T));

        public static float Dot(LTVec a, LTVec b) => a.x * b.x + a.y * b.y + a.z * b.z;
    }

    // One tracked node (CTrackedNode, TrackedNodeControlFn). Its constraint space has +z along its cone axis
    // (m_mInvTargetTransform's rows: the axes right, up, forward); its look is kept there between frames.
    public sealed class TrackedNode
    {
        public readonly string Name;
        // m_mInvTargetTransform: the rows.
        readonly LTVec rowR, rowU, rowF;
        readonly float tanXDiscomfort, tanYDiscomfort, tanXThreshold, tanYThreshold, maxAngVel;
        public TrackedNode Child;   // the next node of the group, nearer the tip (its parent waits while it's comfortable)
        public TrackedNode Mimic;   // a cloned node copies this one's orientation

        public bool Enabled { get; private set; }
        // Whether Update turns it: on, and its Mimic (if any) on.
        public bool Turning => Enabled && (Mimic == null || Mimic.Enabled);
        public bool InDiscomfort { get; private set; }
        public bool AtMaxThreshold { get; private set; }
        public bool LookingAtTarget { get; private set; }
        bool autoDisable, sync = true;
        bool trackAnimation;   // TRACK_ANIMATION: the offset in the animation's space, else a world position
        LTVec animOffset;
        LTVec actualUp = new LTVec(0, 1, 0), actualRight = new LTVec(1, 0, 0), actualForward = new LTVec(0, 0, 1);
        LTVec alignUp = new LTVec(0, 1, 0);

        // CTrackedNodeMgr::SetNodeConstraints: angles in radians; the cone axis and up default to +y and -x.
        public TrackedNode(string name, LTVec? axis, LTVec? up, float discomfortX, float discomfortY, float maxX, float maxY,
                           float maxAngVel)
        {
            Name = name;
            var f = Normalized(axis ?? new LTVec(0, 1, 0));
            var u = Normalized(up ?? new LTVec(-1, 0, 0));
            if (LTFrame.Dot(u, f) > 0.99f)
            {
                u = new LTVec(0, 1, 0);
                if (LTFrame.Dot(u, f) > 0.99f) u = new LTVec(0, 0, -1);
            }
            var r = f.Cross(u);
            u = r.Cross(f);
            rowR = Normalized(r);
            rowU = Normalized(u);
            rowF = f;
            float Clamp(float v, float hi) => Math.Min(Math.Max(v, 0), hi);
            float limit = 89 * (float)Math.PI / 180;
            maxX = Clamp(maxX, limit);
            maxY = Clamp(maxY, limit);
            tanXDiscomfort = (float)Math.Tan(Clamp(discomfortX, maxX));
            tanYDiscomfort = (float)Math.Tan(Clamp(discomfortY, maxY));
            tanXThreshold = (float)Math.Tan(maxX);
            tanYThreshold = (float)Math.Tan(maxY);
            this.maxAngVel = Math.Abs(maxAngVel);
        }

        // A node whose orientation copies `of`'s (LinkNodeOrientation); its own constraint space is the identity
        // (CTrackedNode's, never constrained).
        public static TrackedNode Clone(string name, TrackedNode of) => new TrackedNode(name, of);

        TrackedNode(string name, TrackedNode mimic)
        {
            Name = name;
            Mimic = mimic;
            rowR = new LTVec(1, 0, 0);
            rowU = new LTVec(0, 1, 0);
            rowF = new LTVec(0, 0, 1);
        }

        // EnableTracking: a change syncs the look to the animation on the next update.
        public void Enable(bool on)
        {
            if (Enabled == on) return;
            Enabled = on;
            sync = true;
        }

        // SetTarget...: what it looks at, a point in the level.
        public void TargetWorld()
        {
            trackAnimation = false;
        }

        // The LookAt group going off (CTrackedNodeContext::EnableTrackingGroup): it looks back along the
        // animation (its cone axis, 100 units out) and turns itself off if it already looks there.
        public void ReleaseToAnimation()
        {
            autoDisable = true;
            trackAnimation = true;
            animOffset = new LTVec(rowF.x * 100, rowF.y * 100, rowF.z * 100);
        }

        // TrackedNodeControlFn: parent, the parent's frame; fromParent, the node's bind pose relative to its parent;
        // node, its animated frame (all in the level's space), replaced by the tracked one; target, the point
        // looked at; dt, the time since the last update. False, node untouched, while it is off.
        public bool Update(LTFrame parent, LTFrame fromParent, ref LTFrame node, LTVec target, float dt)
        {
            if (!Turning) return false;
            var binding = parent * fromParent;
            binding.T = node.T;
            if (Mimic != null)
            {
                actualForward = Mimic.actualForward;
                actualUp = Mimic.actualUp;
                actualRight = Mimic.actualRight;
                InDiscomfort = Mimic.InDiscomfort;
                AtMaxThreshold = Mimic.AtMaxThreshold;
                LookingAtTarget = Mimic.LookingAtTarget;
                node = Final(binding, node.T, Mimic, this);
            }
            else
            {
                if (sync)
                {
                    SyncOrientation(node, binding);
                    sync = false;
                }
                LTVec look;
                if (Child != null && !Child.InDiscomfort) look = actualForward;
                else
                {
                    look = FindLookDirection(binding, node, target, dt, out bool discomfort, out bool threshold, out bool lookingAt);
                    InDiscomfort = discomfort;
                    AtMaxThreshold = threshold;
                    LookingAtTarget = lookingAt;
                }
                // SetupFinalTransform.
                actualForward = look;
                actualRight = Normalized(actualForward.Cross(alignUp));
                actualUp = Normalized(actualRight.Cross(actualForward));
                node = Final(binding, node.T, this, this);
            }
            if (autoDisable)
            {
                if (LookingAtTarget) Enabled = false;
                autoDisable = false;
            }
            return true;
        }

        // The actual basis (in `blend`'s constraint space) back in the node's axes, then in the level through
        // binding * `global`'s InvTargetᵀ (a clone blends with its mimic's space and goes out through its own).
        LTFrame Final(LTFrame binding, LTVec pos, TrackedNode blend, TrackedNode global)
        {
            var r = blend.rowR; var u = blend.rowU; var f = blend.rowF;
            var bRight = actualRight * r.x + actualUp * u.x + actualForward * f.x;
            var bUp = actualRight * r.y + actualUp * u.y + actualForward * f.y;
            var bForward = bUp.Cross(bRight);
            var gr = global.rowR; var gu = global.rowU; var gf = global.rowF;
            LTVec ToGlobal(LTVec v) => binding.Rotate(gr * v.x + gu * v.y + gf * v.z);
            return new LTFrame(ToGlobal(bRight), ToGlobal(bUp), ToGlobal(bForward), pos);
        }

        void SyncOrientation(LTFrame anim, LTFrame binding)
        {
            // mInBinding = bindingᵀ anim; mInActual = InvTarget mInBinding: its columns.
            LTVec InActual(LTVec c)
            {
                var v = binding.Unrotate(c);
                return new LTVec(LTFrame.Dot(rowR, v), LTFrame.Dot(rowU, v), LTFrame.Dot(rowF, v));
            }
            var bR = InActual(anim.R); var bU = InActual(anim.U); var bF = InActual(anim.F);
            actualRight = bR * rowR.x + bU * rowR.y + bF * rowR.z;
            actualUp = bR * rowU.x + bU * rowU.y + bF * rowU.z;
            actualForward = actualUp.Cross(actualRight);
            // InvTarget's columns, weighted by its up row.
            var c0 = new LTVec(rowR.x, rowU.x, rowF.x);
            var c1 = new LTVec(rowR.y, rowU.y, rowF.y);
            var c2 = new LTVec(rowR.z, rowU.z, rowF.z);
            alignUp = c0 * rowU.x + c1 * rowU.y + c2 * rowU.z;
        }

        LTVec FindLookDirection(LTFrame binding, LTFrame anim, LTVec target, float dt, out bool discomfort, out bool threshold,
                                out bool lookingAt)
        {
            lookingAt = discomfort = threshold = false;
            var local = trackAnimation ? binding.InverseApply(anim.Apply(animOffset)) : binding.InverseApply(target);
            if (LTFrame.Dot(local, local) < 0.01f) return actualForward;
            var t = new LTVec(LTFrame.Dot(rowR, local), LTFrame.Dot(rowU, local), LTFrame.Dot(rowF, local));
            if (LTFrame.Dot(t, t) < 0.01f) return actualForward;
            t = Normalized(t);
            if (t.z < 0)
            {
                t.z = -t.z;
                discomfort = threshold = true;
            }
            t = Constrained(t, tanXThreshold, tanYThreshold, out bool outOfBounds);
            t = ConstrainToMaxAngularVel(dt, actualForward, t, out lookingAt);
            if (lookingAt) threshold = threshold || outOfBounds;
            discomfort = discomfort || outOfBounds || IsInDiscomfort(t);
            return t;
        }

        LTVec ConstrainToMaxAngularVel(float dt, LTVec current, LTVec goal, out bool lookingAt)
        {
            float cosAngle = LTFrame.Dot(goal, current);
            float max = Math.Min(maxAngVel * dt, (float)Math.PI);
            float cosMax = (float)Math.Cos(max);
            if (cosAngle >= cosMax)
            {
                lookingAt = true;
                return goal;
            }
            lookingAt = false;
            var right = Normalized(current - (goal - current) / (cosAngle - 1));
            return current * cosMax + right * (float)Math.Sin(max);
        }

        bool IsInDiscomfort(LTVec look)
        {
            if (tanXDiscomfort < 0.01f || tanYDiscomfort < 0.01f) return true;
            Constrained(look, tanXDiscomfort, tanYDiscomfort, out bool d);
            return d;
        }

        // FindConstrainedVector: the look kept inside the ellipse of half-widths w, h one unit along +z.
        public static LTVec Constrained(LTVec t, float w, float h, out bool outOfBounds)
        {
            outOfBounds = false;
            float x = t.x, y = t.y;
            if (h < 0.001f)
            {
                float cz = 1 / (float)Math.Sqrt(w * w + 1);
                float mag = (float)Math.Sqrt(x * x + t.z * t.z);
                if (mag < 0.001f) { outOfBounds = true; return new LTVec(0, 0, 1); }
                float bz = t.z / mag;
                if (bz > cz) return new LTVec(x / mag, 0, bz);
                outOfBounds = true;
                return new LTVec(x < 0 ? -w * cz : w * cz, 0, cz);
            }
            if (w < 0.001f)
            {
                float cz = 1 / (float)Math.Sqrt(h * h + 1);
                float mag = (float)Math.Sqrt(y * y + t.z * t.z);
                if (mag < 0.001f) { outOfBounds = true; return new LTVec(0, 0, 1); }
                float bz = t.z / mag;
                if (bz > cz) return new LTVec(0, y / mag, bz);
                outOfBounds = true;
                return new LTVec(0, y < 0 ? -h * cz : h * cz, cz);
            }
            if (t.z > 0.99f) return t;
            var n = t.Cross(new LTVec(0, 0, 1));
            float a = (Sqr(n.y * h) + Sqr(n.x * w)) / Sqr(h);
            float b = 2 * n.y * n.z;
            float c = Sqr(n.z) - Sqr(n.x * w);
            float ySign = y < 0 ? -1 : 1;
            float disc = b * b - 4 * a * c;
            float ey = (-b + ySign * (float)Math.Sqrt(Math.Max(0, disc))) / (2 * a);
            float xSign = x < 0 ? -1 : 1;
            float ex = xSign * (float)Math.Sqrt(Math.Max(0, 1 - Sqr(ey / h)) * Sqr(w));
            var final = Normalized(new LTVec(ex, ey, 1));
            if (final.z < t.z) return t;
            outOfBounds = true;
            return final;
        }

        static float Sqr(float v) => v * v;

        static LTVec Normalized(LTVec v)
        {
            float l = v.Length();
            return l > 0 ? v / l : v;
        }
    }

    // A character's LookAt group (CTrackedNodeContext for kTrack_LookAt): its nodes in the order the model
    // evaluates them, parents first.
    public sealed class LookAtGroup
    {
        public readonly List<TrackedNode> Nodes = new List<TrackedNode>();
        public bool Active { get; private set; }

        // SetActiveTrackingGroup(LookAt) / (None).
        public void SetActive(bool on)
        {
            if (on == Active) return;
            Active = on;
            foreach (var n in Nodes)
            {
                if (on)
                {
                    n.TargetWorld();
                    n.Enable(true);
                }
                else n.ReleaseToAnimation();
            }
        }
    }
}
