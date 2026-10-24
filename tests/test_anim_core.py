"""Character motion solved in plain Python (anim_core.py): a man walks up the villa's entrance steps, opens the front
door, walks in and closes it behind him — measured frame by frame, no Blender needed."""
import math

import pytest

import anim_core as ac


def ground(x, y, z=None):
    """The villa's entrance as blender_build plans it: lawn at 0, two steps, the floor inside at 0.55."""
    if -7 <= x <= 7 and -4.5 <= y <= 4.5:
        return 0.55
    if -1.1 <= x <= 1.1 and -4.9 <= y < -4.5:
        return 0.35
    if -1.1 <= x <= 1.1 and -5.3 <= y < -4.9:
        return 0.175
    return 0.0


DOOR = {"id": "front", "hinge": [-0.54, -4.375, 0.55], "u": [1, 0], "n_in": [0, 1], "width": 1.08, "height": 2.2}
SCRIPT = {"actors": [{"id": "man", "at": [0.0, -11.0], "heading": 180}], "doors": [DOOR],
          "script": [{"actor": "man", "do": "open_door", "door": "front"},
                     {"actor": "man", "do": "close_door", "door": "front"}]}


@pytest.fixture(scope="module")
def solved():
    return ac.solve(SCRIPT, ground)


def _held(solved):
    """Frames between each "grasp handle" and the "release handle" after it."""
    frames, start = [], None
    for e in solved["actors"]["man"]["events"]:
        if e["what"] == "grasp handle":
            start = e["frame"]
        elif e["what"] == "release handle" and start is not None:
            frames += range(start, e["frame"])
            start = None
    return frames


def test_the_door_sequence_happens_in_the_order_asked(solved):
    events = [e["what"] for e in solved["actors"]["man"]["events"]]
    order = ["reach handle", "grasp handle", "release handle", "door open", "entered", "reach handle",
             "grasp handle", "release handle", "door closed"]
    it = iter(events)
    assert all(any(e == want for e in it) for want in order), events
    frames = [e["frame"] for e in solved["actors"]["man"]["events"]]
    assert frames == sorted(frames)


def test_planted_feet_never_slide_and_never_sink_into_the_steps(solved):
    assert ac.foot_slide(solved, "man") < 0.001
    lowest, _ = ac.contact_heights(solved, "man", ground)
    assert lowest > -0.015


def test_the_door_opens_wide_enough_never_touches_the_body_and_ends_shut(solved):
    angles = solved["doors"]["front"]
    assert max(angles.values()) >= 80 and angles[max(angles)] == 0.0
    door = ac.Door(DOOR)
    poses = solved["actors"]["man"]["poses"]
    assert not [f for f, p in enumerate(poses) if door.blocks(angles.get(f, 0.0), p["pelvis"][:2], 0.17)]
    steps = [abs(angles[f] - angles[f - 1]) for f in range(1, len(angles))]
    assert max(steps) < 7.0   # no frame where the leaf jumps


def test_the_hand_is_on_the_moving_handle_whenever_it_holds_it(solved):
    poses = solved["actors"]["man"]["poses"]
    door = ac.Door(DOOR)
    angles = solved["doors"]["front"]
    held = _held(solved)
    assert len(held) > 30   # pushing it open and walking it shut, not a touch
    for f in held:
        side = "L" if poses[f].get("hrot_w.L", 0) > poses[f].get("hrot_w.R", 0) else "R"
        hand = poses[f][f"hand.{side}"]
        near = min(ac.length(ac.sub(hand, door.handle(angles.get(f, 0.0), inner))) for inner in (True, False))
        assert near < 0.035, (f, near)


def test_closing_the_door_follows_the_body_round_the_hinge(solved):
    """While the hand holds it shut-wards, the door's angle is set by where the body is, never by a clock."""
    poses = solved["actors"]["man"]["poses"]
    angles = solved["doors"]["front"]
    closing = [f for f in _held(solved) if f > 300]
    assert closing
    door = ac.Door(DOOR)

    def body_angle(p):
        rel = ac.sub((p["pelvis"][0], p["pelvis"][1], 0.0), (door.hinge[0], door.hinge[1], 0.0))
        return math.degrees(math.atan2(ac.dot(rel, door.n_in), ac.dot(rel, door.u)))

    leads = [body_angle(poses[f]) - angles[f] for f in closing[5:]]
    assert max(leads) - min(leads) < 8.0 and min(leads) > 5.0   # a steady lead: the body stays behind the leaf
    assert all(angles[a] >= angles[b] for a, b in zip(closing, closing[1:]))   # never swings back open


def test_one_motion_hands_over_to_the_next_without_snapping(solved):
    _, worst_rot, where = ac.max_jump(solved, "man")
    assert worst_rot < 25.0, where
    poses = solved["actors"]["man"]["poses"]

    def accel(f, key):
        a0, a1, a2 = (poses[f + d]["pelvis"][:3] if key == "pelvis" else poses[f + d][key] for d in (-1, 0, 1))
        return ac.length(tuple(a2[i] - 2 * a1[i] + a0[i] for i in range(3))) * ac.FPS
    walking = sorted(accel(f, "pelvis") for f in range(1, len(poses) - 1))
    assert walking[int(len(walking) * 0.99)] < 0.45   # no jitter: m/s of velocity change per frame
    assert walking[-1] < 1.0


def test_a_door_that_isnt_there_is_a_problem_not_a_fake_animation():
    script = dict(SCRIPT, script=[{"actor": "man", "do": "open_door", "door": "back"}])
    with pytest.raises(ac.Problem):
        ac.solve(script, ground)


def test_a_wall_where_the_closing_walk_would_end_stops_it_and_the_door_swings_shut_on_its_own():
    wall_x = 0.45   # the villa's inner wall, a little nearer the door than in blender_build's plan

    def clearance(x, y, z):
        return abs(x - wall_x) if -4.25 < y < 0.0 else 10.0
    solved = ac.solve(SCRIPT, ground, clearance=clearance)
    poses = solved["actors"]["man"]["poses"]
    world = ac.World(ground, [DOOR], clearance=clearance)
    assert min(world.clearance(p["pelvis"][0], p["pelvis"][1]) for p in poses) > 0.25
    angles = solved["doors"]["front"]
    assert angles[max(angles)] == 0.0
