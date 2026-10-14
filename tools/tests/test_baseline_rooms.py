"""Rooms and corridors (baseline.segment) on synthetic floor grids."""
import baseline


def grid(*rects):
    """Cells (x, z, 0) covering the given (x0, z0, x1, z1) rectangles, ends exclusive."""
    return {(x, z, 0) for x0, z0, x1, z1 in rects for x in range(x0, x1) for z in range(z0, z1)}


def neighbours(cells):
    return {c: [(c[0] + dx, c[1] + dz, 0) for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if (c[0] + dx, c[1] + dz, 0) in cells] for c in cells}


# Two 20 x 20 rooms joined by a corridor 3 cells wide and 10 long.
TWO_ROOMS = grid((0, 0, 20, 20), (20, 8, 30, 11), (30, 0, 50, 20))


def test_two_rooms_and_the_corridor_between_them():
    s = baseline.segment(neighbours(TWO_ROOMS), core=4)
    assert len(s.rooms) == 2
    assert len(s.corridors) == 1
    assert sorted(len(r) for r in s.rooms) == [400, 400]
    assert len(s.corridors[0]) == 30
    assert s.edges == {("c0", "r0"), ("c0", "r1")}


def test_a_door_splits_a_room_in_two():
    s = baseline.segment(neighbours(grid((0, 0, 41, 20))), core=4, doors={(20, z, 0) for z in range(20)})
    assert len(s.rooms) == 2
    assert s.corridors == []
    assert s.edges == {("r0", "r1")}


def test_a_narrow_space_alone_is_a_corridor():
    s = baseline.segment(neighbours(grid((0, 0, 40, 3))), core=4)
    assert s.rooms == []
    assert len(s.corridors) == 1


def test_a_corridor_into_nowhere_is_a_dead_end():
    s = baseline.segment(neighbours(grid((0, 0, 20, 20), (20, 8, 30, 11))), core=4)
    assert len(s.rooms) == 1 and len(s.corridors) == 1
    assert s.edges == {("c0", "r0")}


def test_width_is_measured_across_the_corridor():
    s = baseline.segment(neighbours(TWO_ROOMS), core=4)
    assert s.corridor_width(0) == 3


def test_a_pillar_does_not_split_a_room():
    hall = grid((0, 0, 40, 40)) - grid((18, 10, 22, 30))   # a 4 x 20 pillar in the middle
    s = baseline.segment(neighbours(hall), core=4)
    assert len(s.rooms) == 1
    assert s.corridors == []


def test_rooms_meeting_at_a_narrow_neck_stay_apart():
    # Two 20 x 20 rooms touching through a 5-cell opening (narrower than a room's 7-cell minimum width).
    s = baseline.segment(neighbours(grid((0, 0, 20, 20), (20, 8, 21, 13), (21, 0, 41, 20))), core=4)
    assert len(s.rooms) == 2


def test_scattered_small_obstacles_are_not_edges():
    pillars = {(x, z, 0) for x in range(3, 40, 6) for z in range(3, 40, 6)}
    s = baseline.segment(neighbours(grid((0, 0, 40, 40)) - pillars), core=4)
    assert len(s.rooms) == 1
    assert s.corridors == []


def test_a_long_thin_wall_still_separates():
    # Two corridors 3 cells wide side by side, split by a 1-cell wall open at one end: a U, not a room.
    u = grid((0, 0, 40, 3), (0, 4, 40, 7), (39, 3, 40, 4))
    s = baseline.segment(neighbours(u), core=4)
    assert s.rooms == []


def test_a_scrap_between_two_rooms_is_an_opening_not_a_corridor():
    s = baseline.segment(neighbours(grid((0, 0, 20, 20), (20, 9, 22, 10), (22, 0, 42, 20))), core=4)
    assert len(s.rooms) == 2
    assert s.corridors == []
    assert s.edges == {("r0", "r1")}
