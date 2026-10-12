namespace Tron
{
    // How the engine carries an object standing on a moving world model (ltjs moveobject.cpp). Plain
    // System math over LTVec/LTQuat, so tools/tests/test_riding.py compiles it with Mono.
    public static class Riding
    {
        // Where a rider at `rider` ends up when the world model it stands on goes from (fromPos, fromRot) to
        // (toPos, toRot). MoveObject offsets it by the world model's move; RotateWorldModel turns its
        // position about the world model's position by toRot x fromRot^-1. Only the position: the rider's
        // own rotation (the player's view) is not turned.
        public static LTVec Carry(LTVec rider, LTVec fromPos, LTQuat fromRot, LTVec toPos, LTQuat toRot)
        {
            return toPos + (toRot * fromRot.Conjugate()).Rotate(rider - fromPos);
        }
    }
}
