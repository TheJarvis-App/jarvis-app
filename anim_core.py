"""Character motion for Jarvis, solved in plain Python: a script of actions ("walk to the door", "open it", "sit on
the chair and eat") becomes, for every frame, what each control of the rig does.

Why it's built this way: a local model can't write believable bone keys, and two keyframes on a whole character
aren't motion. Here motion comes from how bodies move: footsteps are planned on the real ground (each foot lands
flat on a tread, never on a step's edge) and stay planted while the body passes over them; the pelvis bobs, sways
and twists with the steps and is lowered whenever a leg couldn't reach; heels roll and toes bend; arms swing against
the legs; hands reach for real points (a door handle that is itself moving, a sandwich, a cup) and things in a hand
move with it. Blender's IK then bends knees and elbows to meet those targets, so the saved .blend stays an
editable rig, not baked bones.

The same file runs in the engine (tests, planning) and inside Blender (blender_character.py feeds it ray-cast
ground heights and writes what it returns as keys). No bpy, no mathutils: its small matrix maths is below.

    result = solve(script, ground=lambda x, y, z: 0.0)
    result["actors"]["man"]["bones"]["foot_ik.L"][frame] -> ((x, y, z) location, (w, x, y, z) rotation)

Coordinates: metres, Z up. yaw 0 faces -Y; positive yaw turns left (counter-clockwise seen from above).
"""
import math
import random

import anim_library as lib

FPS = lib.FPS


# ---------- small vector / matrix maths ----------

def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def length(a):
    return math.sqrt(dot(a, a))


def norm(a):
    n = length(a)
    return (a[0] / n, a[1] / n, a[2] / n) if n > 1e-12 else (0.0, 0.0, 0.0)


def lerp(a, b, t):
    if isinstance(a, (int, float)):
        return a + (b - a) * t
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(len(a)))


def dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def smooth(t):
    """Smoothstep: eases in and out, flat at both ends."""
    t = clamp(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def smoother(t):
    t = clamp(t, 0.0, 1.0)
    return t * t * t * (t * (6 * t - 15) + 10)


def ease_out(t):
    t = clamp(t, 0.0, 1.0)
    return 1 - (1 - t) ** 3


def ease_in(t):
    t = clamp(t, 0.0, 1.0)
    return t ** 3


def wrap(angle):
    """An angle in radians, wrapped to (-pi, pi]."""
    return math.atan2(math.sin(angle), math.cos(angle))


def mat_mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def mat_vec(m, v):
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2], m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])


def transpose(m):
    return tuple(tuple(m[j][i] for j in range(3)) for i in range(3))


IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def rot_axis(axis, angle):
    x, y, z = norm(axis)
    c, s = math.cos(angle), math.sin(angle)
    C = 1 - c
    return ((c + x * x * C, x * y * C - z * s, x * z * C + y * s),
            (y * x * C + z * s, c + y * y * C, y * z * C - x * s),
            (z * x * C - y * s, z * y * C + x * s, c + z * z * C))


def rot_z(angle):
    return rot_axis((0, 0, 1), angle)


def columns(x, y, z):
    """The rotation whose columns are the axes x, y, z."""
    return ((x[0], y[0], z[0]), (x[1], y[1], z[1]), (x[2], y[2], z[2]))


def col(m, j):
    return (m[0][j], m[1][j], m[2][j])


def quat(m):
    """(w, x, y, z) of a rotation matrix."""
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = (0.25 * s, (m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s)
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = ((m[2][1] - m[1][2]) / s, 0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s)
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = ((m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s)
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = ((m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s)
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def quat_mat(q):
    w, x, y, z = q
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


def slerp_mat(a, b, t):
    """Rotation between a and b (normalised quaternion interpolation: plenty for a blend of a few frames)."""
    qa, qb = quat(a), quat(b)
    if sum(qa[i] * qb[i] for i in range(4)) < 0:
        qb = tuple(-c for c in qb)
    q = tuple(qa[i] + (qb[i] - qa[i]) * t for i in range(4))
    n = math.sqrt(sum(c * c for c in q))
    return quat_mat(tuple(c / n for c in q))


def angle_between(a, b):
    return math.acos(clamp(dot(norm(a), norm(b)), -1.0, 1.0))


# A transform is (R, t): rotation matrix and translation.
def tf_mul(a, b):
    return (mat_mul(a[0], b[0]), add(mat_vec(a[0], b[1]), a[1]))


def tf_inv(a):
    rt = transpose(a[0])
    return (rt, mul(mat_vec(rt, a[1]), -1.0))


def tf_point(a, p):
    return add(mat_vec(a[0], p), a[1])


def forward(yaw):
    return (math.sin(yaw), -math.cos(yaw), 0.0)


def left(yaw):
    return (math.cos(yaw), math.sin(yaw), 0.0)


def yaw_of(direction):
    return math.atan2(direction[0], -direction[1])


# ---------- the rig, as anim_core sees it ----------

class Rig:
    """Rest frames of a skeleton (anim_library.skeleton()), exactly as Blender builds them: Y along the bone, Z the
    bone's roll axis, X = Y x Z."""

    def __init__(self, skel):
        self.skel = skel
        self.rest = {}
        for name, b in skel.items():
            y = norm(sub(b["tail"], b["head"]))
            z = sub(b["z"], mul(y, dot(b["z"], y)))
            z = norm(z)
            x = cross(y, z)
            self.rest[name] = (columns(x, y, z), tuple(b["head"]))
        self.length = {n: length(sub(b["tail"], b["head"])) for n, b in skel.items()}
        self.leg = self.length["thigh.L"] + self.length["shin.L"]
        self.arm = self.length["upper_arm.L"] + self.length["forearm.L"]
        hips = skel["hips"]["head"]
        self.hips_height = hips[2]
        self.hip_offset = {s: sub(skel[f"thigh.{s}"]["head"], hips) for s in "LR"}
        self.height = skel["head"]["tail"][2]

    def child(self, parent_world, name, basis_rot=IDENTITY):
        """World transform of bone `name` posed with `basis_rot`, its parent at `parent_world`."""
        parent = self.skel[name]["parent"]
        rel = tf_mul(tf_inv(self.rest[parent]), self.rest[name])
        return tf_mul(tf_mul(parent_world, rel), (basis_rot, (0.0, 0.0, 0.0)))

    def tail(self, world, name):
        return tf_point(world, (0.0, self.length[name], 0.0))

    def basis_under_root(self, root_world, name, world):
        """The local (basis) transform that puts control `name` (a child of root) at `world`."""
        return tf_mul(tf_mul(tf_inv(self.rest[name]), self.rest["root"]), tf_mul(tf_inv(root_world), world))

    def root_world(self, x, y, z, yaw):
        return (mat_mul(rot_z(yaw), self.rest["root"][0]), (x, y, z))

    def oriented(self, name, rot):
        """World rotation for bone `name` turned by `rot` from its rest orientation."""
        return mat_mul(rot, self.rest[name][0])


def local_rot(bend=0.0, twist=0.0, lean=0.0):
    """A vertical bone's own rotation (degrees): bend forward, twist left, lean right."""
    return mat_mul(mat_mul(rot_axis((0, 1, 0), math.radians(twist)), rot_axis((1, 0, 0), math.radians(bend))),
                   rot_axis((0, 0, 1), math.radians(lean)))


def body_rot(yaw, pitch=0.0, roll=0.0):
    """World rotation of the body: turned to `yaw` (radians), tipped forward by `pitch` and to the right by `roll`
    (degrees)."""
    return mat_mul(mat_mul(rot_z(yaw), rot_axis((1, 0, 0), math.radians(pitch))),
                   rot_axis((0, -1, 0), math.radians(roll)))


def foot_rot(yaw, pitch_deg):
    """World rotation of a foot turned to `yaw` with its heel raised by `pitch_deg` (negative: toes up)."""
    return mat_mul(rot_z(yaw), rot_axis((1, 0, 0), math.radians(pitch_deg)))


def ankle_from_contact(contact, yaw, pitch_deg):
    """Where the ankle is when the foot pivots on the ground at `contact` (ball when the heel is up, heel when the
    toes are up) by `pitch_deg`."""
    p = math.radians(pitch_deg)
    f = forward(yaw)
    rel = (-lib.BALL, lib.ANKLE) if pitch_deg >= 0 else (-lib.HEEL, lib.ANKLE)
    fwd_ = rel[0] * math.cos(p) + rel[1] * math.sin(p)
    up = -rel[0] * math.sin(p) + rel[1] * math.cos(p)
    return (contact[0] + f[0] * fwd_, contact[1] + f[1] * fwd_, contact[2] + up)


def contact_points(ankle, yaw, pitch_deg, toe_deg=0.0):
    """Heel, ball and toe tip of a foot posed at `ankle`, on the sole (world). The toes bend up by `toe_deg` at
    the ball (they stay flat on the ground while the heel rises)."""
    r = foot_rot(yaw, pitch_deg)
    pts = {k: add(ankle, mat_vec(r, (0.0, -d, -lib.ANKLE))) for k, d in (("heel", lib.HEEL), ("ball", lib.BALL))}
    toe_r = foot_rot(yaw, pitch_deg - toe_deg)
    pts["toe"] = add(pts["ball"], mat_vec(toe_r, (0.0, -(lib.TOE - lib.BALL), 0.0)))
    return pts


# ---------- doors ----------

class Door:
    """A hinged door: `hinge` (x, y, floor z), `u` from the hinge along the closed leaf to its free edge, `n_in`
    into the room it swings into."""

    def __init__(self, spec):
        self.id = spec["id"]
        self.hinge = tuple(spec["hinge"])
        self.u = norm((spec["u"][0], spec["u"][1], 0.0))
        self.n_in = norm((spec["n_in"][0], spec["n_in"][1], 0.0))
        self.width = spec["width"]
        self.height = spec.get("height", 2.2)
        self.thick = spec.get("thick", 0.06)
        self.sign = 1.0 if cross(self.u, self.n_in)[2] > 0 else -1.0
        d = lib.ACTIONS["door"]
        self.handle_h = spec.get("handle_height", d["handle_height"])
        self.handle_in = spec.get("handle_in", d["handle_in"])
        self.angles = {}   # frame -> degrees open
        self.start_angle = spec.get("angle", 0.0)

    def leaf_dir(self, a_deg):
        return mat_vec(rot_z(self.sign * math.radians(a_deg)), self.u)

    def face_normal(self, a_deg, inner=True):
        n = mat_vec(rot_z(self.sign * math.radians(a_deg)), self.n_in)
        return n if inner else mul(n, -1.0)

    def handle(self, a_deg, inner):
        """The handle's grip point on the inner (room) or outer face at `a_deg` open."""
        along = self.width - self.handle_in
        p = add(self.hinge, mul(self.leaf_dir(a_deg), along))
        p = add(p, mul(self.face_normal(a_deg, inner), self.thick / 2 + 0.045))
        return (p[0], p[1], self.hinge[2] + self.handle_h)

    def middle(self):
        return add(self.hinge, mul(self.u, self.width / 2))

    def blocks(self, a_deg, centre, radius):
        """Whether a body disc (`centre` xy, `radius`) overlaps the leaf at `a_deg`."""
        d = self.leaf_dir(a_deg)
        rel = (centre[0] - self.hinge[0], centre[1] - self.hinge[1], 0.0)
        along = clamp(dot(rel, d), 0.0, self.width)
        nearest = mul(d, along)
        return dist2(rel, nearest) < radius + self.thick / 2

    def angle_at(self, frame):
        best = None
        for f in sorted(self.angles):
            if f <= frame:
                best = self.angles[f]
            else:
                break
        return self.start_angle if best is None else best

    def set(self, frame, angle):
        self.angles[frame] = angle


# ---------- the solver ----------

class Problem(Exception):
    """A script that can't be carried out as asked (an unreachable seat, a door that isn't there)."""


class Actor:
    def __init__(self, spec, world):
        self.id = spec["id"]
        self.template = spec.get("template", "man")
        t = lib.CHARACTERS.get(self.template, lib.CHARACTERS["man"])
        self.height = spec.get("height", t["height"])
        self.rig = Rig(lib.skeleton(self.height, t["width"], t["hips"]))
        self.world = world
        self.rng = random.Random(spec.get("seed", 7) * 1013 + sum(map(ord, self.id)))
        self.yaw = math.radians(spec.get("heading", 0.0))
        x, y = spec["at"][:2]
        z = world.ground(x, y, spec["at"][2] if len(spec["at"]) > 2 else None)
        self.pos = (x, y, z)
        k = self.height / lib.REST_HEIGHT
        self.k = k
        self.feet = {s: self._stand_plant(s, self.pos, self.yaw) for s in "LR"}
        self.poses = []           # one dict per frame, from frame 0
        self.events = []
        self.holding = {"L": None, "R": None}
        self.seated = None
        self.hand_rel = {"L": self._rest_hand("L"), "R": self._rest_hand("R")}
        self.speed = 0.0
        self.stand_height = self.rig.hips_height - 0.012 * k
        self.pelvis_z = self.pos[2] + self.stand_height
        self.last_step_side = "R"
        self.start_frame = 0
        self.boundaries = []      # frames where one motion hands over to the next (crossfaded by _crossfade)

    def mark(self):
        if self.poses:
            self.boundaries.append(len(self.poses))

    # ----- positions -----
    def _stand_plant(self, side, at, yaw):
        s = 1.0 if side == "L" else -1.0
        lat = lib.STEP_WIDTH * self.k * s
        p = add(at, mul(left(yaw), lat))
        fyaw = yaw + s * math.radians(lib.TOE_OUT)
        z = self.world.foot_ground(p, fyaw)
        return {"x": p[0], "y": p[1], "z": z, "yaw": fyaw}

    def _rest_hand(self, side):
        """Relaxed hanging hand: (out, forward, up) from the shoulder joint."""
        return (0.035 * self.k, -0.02 * self.k, -0.515 * self.k)

    @property
    def frame(self):
        return self.start_frame + len(self.poses)

    @property
    def last(self):
        return self.poses[-1] if self.poses else None

    def time(self):
        return self.frame / FPS

    def event(self, what, **extra):
        self.events.append(dict(frame=self.frame, time=round(self.frame / FPS, 3), what=what, actor=self.id, **extra))

    # ----- the body for one frame -----
    def torso(self, pose):
        """World transforms of the torso bones and both shoulder joints for `pose` (cached on it)."""
        if "_fk" in pose:
            return pose["_fk"]
        rig = self.rig
        px, py, pz, yaw, pitch, roll = pose["pelvis"]
        hips_w = (rig.oriented("hips", body_rot(yaw, pitch, roll)), (px, py, pz))
        fk = {"hips": hips_w}
        parent = hips_w
        for name in ("spine", "chest", "neck", "head"):
            parent = rig.child(parent, name, local_rot(*pose[name]))
            fk[name] = parent
        for s in "LR":
            sh = rig.child(fk["chest"], f"shoulder.{s}", shoulder_rot(s, pose.get(f"shrug.{s}", 0.0)))
            fk[f"shoulder.{s}"] = sh
            fk[f"arm_root.{s}"] = rig.tail(sh, f"shoulder.{s}")
            fk[f"hip.{s}"] = tf_point(hips_w, mat_vec(transpose(rig.rest["hips"][0]), rig.hip_offset[s]))
        pose["_fk"] = fk
        return fk

    def body_yaw(self, pose):
        """Which way the upper body faces: the pelvis turned by the spine's and chest's twist."""
        return pose["pelvis"][3] + math.radians(pose["spine"][1] + pose["chest"][1])

    def hand_world(self, pose, side, rel):
        fk = self.torso(pose)
        s = 1.0 if side == "L" else -1.0
        yaw = self.body_yaw(pose)
        out, fwd, up = rel
        return add(add(add(fk[f"arm_root.{side}"], mul(left(yaw), out * s)), mul(forward(yaw), fwd)), (0, 0, up))

    def rel_of_hand(self, pose, side, world):
        fk = self.torso(pose)
        s = 1.0 if side == "L" else -1.0
        yaw = self.body_yaw(pose)
        d = sub(world, fk[f"arm_root.{side}"])
        return (dot(d, left(yaw)) * s, dot(d, forward(yaw)), d[2])

    def mouth(self, pose):
        fk = self.torso(pose)
        head = fk["head"]
        return tf_point(head, (0.0, 0.06 * self.k, 0.105 * self.k))   # the lips: the head bone's Z is forward

    def new_pose(self, root, pelvis, spine=(0, 0, 0), chest=(0, 0, 0), neck=(0, 0, 0), head=(0, 0, 0)):
        return {"root": root, "pelvis": pelvis, "spine": tuple(spine), "chest": tuple(chest), "neck": tuple(neck),
                "head": tuple(head)}

    def finish_pose(self, pose, hands=None, grips=None, look=None):
        """Fill in what an action didn't set: hands (relative positions blended from the last frame), feet from
        their plants, grips, poles; then the frame is appended."""
        for s in "LR":
            if f"foot.{s}" not in pose:
                p = self.feet[s]
                pose[f"foot.{s}"] = (p["x"], p["y"], p["z"] + lib.ANKLE * self.k, p["yaw"], 0.0)
                pose.setdefault(f"toe.{s}", 0.0)
            if f"hand.{s}" not in pose:
                rel = (hands or {}).get(s, self.hand_rel[s])
                pose[f"hand.{s}"] = self.hand_world(pose, s, rel)
            self.hand_rel[s] = self.rel_of_hand(pose, s, pose[f"hand.{s}"])
            pose.setdefault(f"grip.{s}", (grips or {}).get(s, 0.22))
            pose.setdefault(f"hrot_w.{s}", 0.0)
        if look is not None:
            pose["look"] = look
        self.poses.append(pose)
        return pose


def shoulder_rot(side, shrug):
    """A shoulder raised by `shrug` degrees. Its bone points out sideways with Z up, so a turn about its own X axis
    tips its tip up, on either side."""
    return rot_axis((1, 0, 0), math.radians(shrug))


class World:
    """What the solver knows of the scene: ground height (a function the caller gives: in Blender, ray casts on
    walkable surfaces), doors, props and seats."""

    def __init__(self, ground=None, doors=(), props=(), seats=(), tables=(), clearance=None):
        self._ground = ground or (lambda x, y, z=None: 0.0)
        # how far a point (at hip height over the ground there) is from the nearest wall or furniture: in Blender a
        # BVH of the scene's solids (doors excluded: they move); without one, open space everywhere
        self._clearance = clearance or (lambda x, y, z: 10.0)
        self.doors = {d["id"]: Door(d) for d in doors}
        self.props = {}
        for p in props:
            kind = lib.PROPS.get(p.get("kind"), lib.PROPS["box"])
            at = tuple(p["at"])
            self.props[p["id"]] = {"id": p["id"], "kind": p.get("kind", "box"), "spec": kind,
                                   "start": (rot_z(math.radians(p.get("yaw", 0.0))), at), "keys": {},
                                   "visible": {}}
        self.seats = {s["id"]: dict(s) for s in seats}
        self.tables = {t["id"]: dict(t) for t in tables}

    def clearance(self, x, y, z=None):
        z = self.ground(x, y, z) if z is None else z
        return min(self._clearance(x, y, z + 0.9), self._clearance(x, y, z + 0.35))

    def ground(self, x, y, z_hint=None):
        z = self._ground(x, y, z_hint)
        return 0.0 if z is None else z

    def foot_ground(self, ankle_xy, yaw, k=1.0):
        """The height a foot planted here stands at: the highest of heel, ball and toe (it rests on the highest)."""
        f = forward(yaw)
        zs = [self.ground(ankle_xy[0] + f[0] * d * k, ankle_xy[1] + f[1] * d * k, ankle_xy[2] if len(ankle_xy) > 2
                          else None) for d in (lib.HEEL, lib.BALL * 0.6, lib.TOE)]
        return max(zs)

    def foot_level(self, ankle_xy, yaw, z_hint=None, k=1.0):
        """Whether a foot here would stand flat (heel and toe on the same surface), and at which height."""
        f = forward(yaw)
        zs = [self.ground(ankle_xy[0] + f[0] * d * k, ankle_xy[1] + f[1] * d * k, z_hint)
              for d in (lib.HEEL - 0.015, 0.0, lib.BALL, lib.TOE + 0.05)]   # toes kept off a riser ahead
        return max(zs) - min(zs) < 0.02, max(zs)


# ---------- paths ----------

def _densify(points, step=0.03):
    """A polyline with corners rounded (people don't turn on a point) and points every `step` metres."""
    pts = [tuple(p[:2]) for p in points]
    out = [pts[0]]
    for p in pts[1:]:
        if dist2(p, out[-1]) > 1e-4:
            out.append(p)
    pts = out
    if len(pts) > 2:   # round each corner over up to 0.7 m either side
        rounded = [pts[0]]
        for i in range(1, len(pts) - 1):
            a, b, c = pts[i - 1], pts[i], pts[i + 1]
            r = min(0.7, dist2(a, b) / 2.2, dist2(b, c) / 2.2)
            p0 = lerp(b, a, r / max(dist2(a, b), 1e-9))
            p2 = lerp(b, c, r / max(dist2(b, c), 1e-9))
            for k in range(9):
                t = k / 8
                rounded.append(lerp(lerp(p0, b, t), lerp(b, p2, t), t))
        rounded.append(pts[-1])
        pts = rounded
    dense = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        n = max(1, int(dist2(a, b) / step))
        for k in range(1, n + 1):
            dense.append(lerp(a, b, k / n))
    s = [0.0]
    for a, b in zip(dense, dense[1:]):
        s.append(s[-1] + dist2(a, b))
    return dense, s


def _at(dense, s_list, s):
    """(point, tangent yaw) at arc length `s`."""
    if s <= 0:
        i = 0
    elif s >= s_list[-1]:
        i = len(s_list) - 2
    else:
        lo, hi = 0, len(s_list) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if s_list[mid] <= s:
                lo = mid
            else:
                hi = mid
        i = lo
    i = max(0, min(i, len(dense) - 2))
    seg = max(s_list[i + 1] - s_list[i], 1e-9)
    t = clamp((s - s_list[i]) / seg, 0.0, 1.0)
    p = lerp(dense[i], dense[i + 1], t)
    d = sub((dense[i + 1][0], dense[i + 1][1], 0), (dense[i][0], dense[i][1], 0))
    return p, yaw_of(d)


def _gauss(values, sigma):
    """Gaussian-smoothed copy of a list of numbers; the ends are held."""
    if sigma <= 0 or len(values) < 3:
        return list(values)
    r = int(sigma * 3)
    w = [math.exp(-(k * k) / (2 * sigma * sigma)) for k in range(-r, r + 1)]
    out = []
    n = len(values)
    for i in range(n):
        acc = tot = 0.0
        for k in range(-r, r + 1):
            j = clamp(i + k, 0, n - 1)
            acc += values[j] * w[k + r]
            tot += w[k + r]
        out.append(acc / tot)
    return out


# ---------- locomotion ----------

def _speed_profile(actor, dense, s_list, gait, v_max, stop, v_start):
    """Arc length at each frame: accelerating from `v_start`, slowing for corners and steps, stopping at the end
    when `stop`. Returns [s per frame], the last one exactly the path's length."""
    S = s_list[-1]
    if S < 1e-3:
        return [0.0]
    ds = 0.03
    n = max(2, int(S / ds) + 1)
    ss = [S * i / (n - 1) for i in range(n)]
    caps = []
    world = actor.world
    z_prev = None
    zs = []
    for s in ss:
        p, _ = _at(dense, s_list, s)
        z = world.ground(p[0], p[1], z_prev)
        zs.append(z)
        z_prev = z
    for i, s in enumerate(ss):
        cap = v_max
        # steps up or down within 0.7 m: slower, shorter steps
        lo, hi = max(0, i - int(0.7 / ds)), min(n, i + int(0.7 / ds))
        if max(zs[lo:hi]) - min(zs[lo:hi]) > 0.06:
            cap = min(cap, v_max * 0.72)
        # corners: tangent change over 0.6 m
        p0, y0 = _at(dense, s_list, max(0.0, s - 0.3))
        p1, y1 = _at(dense, s_list, min(S, s + 0.3))
        turn = abs(wrap(y1 - y0))
        if turn > 0.05:
            radius = 0.6 / turn
            cap = min(cap, max(0.45, math.sqrt(1.4 * radius)))
        caps.append(cap)
    caps = _gauss(caps, 6)
    a = gait["accel"] * actor.k ** 0.5
    v = [0.0] * n
    v[0] = min(caps[0], max(v_start, 0.0))
    for i in range(1, n):
        v[i] = min(caps[i], math.sqrt(v[i - 1] ** 2 + 2 * a * ds))
    if stop:
        v[-1] = 0.0
        for i in range(n - 2, -1, -1):
            v[i] = min(v[i], math.sqrt(v[i + 1] ** 2 + 2 * a * 1.1 * ds))
    t = [0.0]
    for i in range(1, n):
        avg = max((v[i] + v[i - 1]) / 2, 0.06)
        t.append(t[-1] + ds / avg)
    T = t[-1]
    frames = max(2, int(round(T * FPS)) + 1)
    out = []
    j = 0
    for f in range(frames):
        tf = min(T, f / FPS)
        while j < n - 2 and t[j + 1] < tf:
            j += 1
        seg = max(t[j + 1] - t[j], 1e-9)
        out.append(ss[j] + (ss[j + 1] - ss[j]) * clamp((tf - t[j]) / seg, 0, 1))
    out = _gauss(out, FPS * 0.12)   # softens the corners of the speed ramps (no jerk at the start of a step)
    out[0], out[-1] = 0.0, S
    for i in range(1, len(out)):    # never backwards
        out[i] = max(out[i], out[i - 1])
    return out


def locomote(actor, path, gait_kind="walk", stop=True, face=None, overlay=None, speed=None, settle=0.25,
             label="walk"):
    """Walk (or run) along `path` [(x, y), ...] from where the actor stands. `face`: a yaw (radians) or (x, y)
    point the body keeps facing instead of the way it goes (side steps). `overlay(pose, t, u)`: changes each frame
    (u runs 0..1 over the move) — a hand on a handle while walking through a door."""
    g = lib.gait(gait_kind)
    v_max = (speed or g["speed"]) * actor.k ** 0.5
    pts = [actor.pos[:2]] + [tuple(p[:2]) for p in path]
    dense, s_list = _densify(pts)
    S = s_list[-1]
    if S < 0.05:
        return
    if face is None and actor.speed < 0.2:
        # starting off far from the way one faces: turn on the spot first (a first step can't swing round 180)
        _, way = _at(dense, s_list, min(S, 0.6))
        if abs(wrap(way - actor.yaw)) > math.radians(70):
            turn(actor, way)
            pts = [actor.pos[:2]] + [tuple(p[:2]) for p in path]
            dense, s_list = _densify(pts)
            S = s_list[-1]
            if S < 0.05:
                return
    s_frames = _speed_profile(actor, dense, s_list, g, v_max, stop, actor.speed)
    n = len(s_frames)
    dt = 1.0 / FPS
    vel = [0.0] + [(s_frames[i] - s_frames[i - 1]) / dt for i in range(1, n)]
    vel[0] = vel[1] if n > 1 else 0.0

    def facing(i):
        s = s_frames[i]
        if face is not None:
            if isinstance(face, (int, float)):
                return float(face)
            p, _ = _at(dense, s_list, s)
            return yaw_of(sub((face[0], face[1], 0), (p[0], p[1], 0)))
        _, y = _at(dense, s_list, min(S, s + 0.25))
        return y

    # body yaw: follows the path, turning at a natural rate
    yaws = []
    y_prev = actor.yaw
    for i in range(n):
        target = facing(i)
        step = wrap(target - y_prev)
        lim = math.radians(240) * dt
        y_prev = y_prev + clamp(step, -lim, lim)
        yaws.append(y_prev)
    yaw_s = _gauss_angles(yaws, 2.0)

    # ----- footsteps -----
    k = actor.k
    plants = []   # (strike frame, side, plant dict)
    strike_side = "L" if actor.last_step_side == "R" else "R"
    # the first step: the foot on the side of the first turn, or the one behind
    first_yaw = yaw_s[min(n - 1, int(FPS * 0.5))]
    turn0 = wrap(first_yaw - actor.yaw)
    if abs(turn0) > 0.25:
        strike_side = "L" if turn0 > 0 else "R"
    f = 0.0
    lift0 = int(FPS * 0.1)
    t_strike = lift0 / FPS + 0.32
    feet_now = dict(actor.feet)
    last_strike_frame = {"L": -1, "R": -1}
    done_sides = set()
    z_hint = actor.pos[2]
    guard = 0
    while guard < 400:
        guard += 1
        fr = min(n - 1, int(round(t_strike * FPS)))
        s_now = s_frames[fr]
        v_now = max(vel[fr], 0.15)
        # starting and stopping take short steps at nearly the usual rhythm, not slow long ones
        c = lib.cadence(g, max(v_now, 0.6 * v_max) / k ** 0.5)
        L_step = v_now / c
        lead = (0.42 if gait_kind != "run" else 0.3) * L_step
        s_land = min(S, s_now + lead)
        ending = s_land >= S - 0.04 or fr >= n - 1
        if ending:
            s_land = S
        p, ty = _at(dense, s_list, s_land)
        yaw_f = yaws[fr] if face is not None else ty
        if ending:
            yaw_f = yaw_s[-1]
        side_sign = 1.0 if strike_side == "L" else -1.0
        variation = 1.0 + actor.rng.uniform(-0.03, 0.03)
        plant_xy = add((p[0], p[1], 0.0), mul(left(yaw_f), lib.STEP_WIDTH * k * side_sign * variation))
        fyaw = yaw_f + side_sign * math.radians(lib.TOE_OUT + actor.rng.uniform(-1.5, 1.5))
        plant_xy, z = _fit_tread(actor, plant_xy, fyaw, z_hint, s_land, S, dense, s_list, side_sign, yaw_f)
        z_hint = z
        plants.append((fr, strike_side, {"x": plant_xy[0], "y": plant_xy[1], "z": z, "yaw": fyaw}, c))
        last_strike_frame[strike_side] = fr
        feet_now[strike_side] = plants[-1][2]
        if ending:
            done_sides.add(strike_side)
            other = "R" if strike_side == "L" else "L"
            o = feet_now[other]
            want = actor._stand_plant(other, (p[0], p[1], z), yaw_s[-1])
            if other in done_sides or (dist2((o["x"], o["y"]), (want["x"], want["y"])) < 0.06 and
                                       abs(wrap(o["yaw"] - want["yaw"])) < 0.2):
                break
        strike_side = "R" if strike_side == "L" else "L"
        t_strike += max(0.28, 1.0 / c * (1.0 + actor.rng.uniform(-0.02, 0.02)))
    # frames until the last step has landed and the body has settled over the feet
    last_frame = max(n - 1, plants[-1][0] if plants else 0) + int(settle * FPS)
    _emit_locomotion(actor, g, gait_kind, dense, s_list, s_frames, yaw_s, plants, last_frame, lift0, overlay, k)
    actor.last_step_side = plants[-1][1] if plants else actor.last_step_side
    actor.speed = 0.0 if stop else vel[-1]


def _gauss_angles(values, sigma):
    unwrapped = [values[0]]
    for v in values[1:]:
        unwrapped.append(unwrapped[-1] + wrap(v - unwrapped[-1]))
    return _gauss(unwrapped, sigma)


def _fit_tread(actor, xy, fyaw, z_hint, s_land, S, dense, s_list, side_sign, yaw_path):
    """A plant where the whole foot stands flat: moved a little along the path off a step's edge when it would
    land on one."""
    world = actor.world
    ok, z = world.foot_level(xy, fyaw, z_hint, actor.k)
    if ok:
        return xy, z
    for shift in (-0.05, 0.05, -0.1, 0.1, -0.15, 0.15, -0.2, 0.2, -0.26, 0.26):
        s2 = clamp(s_land + shift, 0.0, S)
        p, _ = _at(dense, s_list, s2)
        cand = add((p[0], p[1], 0.0), mul(left(yaw_path), lib.STEP_WIDTH * actor.k * side_sign))
        ok, z2 = world.foot_level(cand, fyaw, z_hint, actor.k)
        if ok:
            return cand, z2
    return xy, z


def _emit_locomotion(actor, g, gait_kind, dense, s_list, s_frames, yaws, plants, last_frame, lift0, overlay, k):
    n = len(s_frames)
    duty = g["duty"]
    actor.mark()
    # each foot's timeline: [(strike frame, plant)], starting from where it stands now
    timeline = {"L": [(-10 ** 6, dict(actor.feet["L"]))], "R": [(-10 ** 6, dict(actor.feet["R"]))]}
    for fr, side, plant, _ in plants:
        timeline[side].append((fr, plant))
    strikes = [fr for fr, _, _, _ in plants]
    sides = [side for _, side, _, _ in plants]
    first_side = sides[0] if sides else "L"
    start_pelvis = actor.last["pelvis"][2] if actor.last else actor.pelvis_z

    def step_phase(f):
        """(continuous step count, index of the last strike before f)."""
        if not strikes or f < strikes[0]:
            lift = lift0
            first = strikes[0] if strikes else lift0 + 8
            return -1.0 + clamp((f - lift) / max(1, first - lift), 0, 1), -1
        i = 0
        while i + 1 < len(strikes) and strikes[i + 1] <= f:
            i += 1
        if i + 1 < len(strikes):
            return i + (f - strikes[i]) / max(1, strikes[i + 1] - strikes[i]), i
        return float(i) + min(1.0, (f - strikes[i]) / (FPS * 0.5)), i

    def foot_state(side, f):
        """(ankle position, yaw, pitch, toe bend, ground under this foot) of one foot at frame f."""
        tl = timeline[side]
        j = 0
        while j + 1 < len(tl) and tl[j + 1][0] <= f:
            j += 1
        cur_strike, plant = tl[j]
        nxt = tl[j + 1] if j + 1 < len(tl) else None
        heel = g["heel"]
        if nxt is not None:
            standing = cur_strike < -10 ** 5
            if standing:     # standing still before its first step
                if side == first_side:
                    toe_off = lift0
                else:        # the other foot leaves once the first has landed (walking) or just before (running)
                    first = strikes[0] if strikes else lift0 + 8
                    toe_off = first + int(round((duty - 0.5) * 2 * max(1, nxt[0] - first)))
                heel_off = toe_off - int(FPS * 0.12)
            else:            # stance lasts duty * stride: from this foot's last strike to its next
                stride = nxt[0] - cur_strike
                toe_off = cur_strike + int(round(duty * stride))
                heel_off = toe_off - max(int(FPS * 0.14), int(0.5 * duty * stride))   # heel rises from mid-stance
            if nxt[0] - toe_off < 4:
                toe_off = nxt[0] - 4
                heel_off = min(heel_off, toe_off - 2)
            lift = heel * (0.5 if standing else 1.0)
            if f >= toe_off:   # swinging
                u = clamp((f - toe_off) / max(1, nxt[0] - toe_off), 0, 1)
                return _swing(actor, g, plant, nxt[1], toe_off, nxt[0], f, lift, k) + (
                    lerp(plant["z"], nxt[1]["z"], smooth(u)),)
            if f >= heel_off:   # heel rising around the ball of the foot
                u = (f - heel_off) / max(1, toe_off - heel_off)
                pitch = lift * smooth(u)
                ball = _plant_point(plant, lib.BALL, k)
                return ankle_from_contact(ball, plant["yaw"], pitch), plant["yaw"], pitch, pitch, plant["z"]
        # flat stance, or rolling down onto the heel just after landing
        since = f - cur_strike
        roll = int(FPS * 0.1)
        if 0 <= since < roll and cur_strike > -10 ** 5:
            pitch = -12.0 * (1 - smooth(since / roll))
            heel_pt = _plant_point(plant, lib.HEEL, k)
            return ankle_from_contact(heel_pt, plant["yaw"], pitch), plant["yaw"], pitch, 0.0, plant["z"]
        return (plant["x"], plant["y"], plant["z"] + lib.ANKLE * k), plant["yaw"], 0.0, 0.0, plant["z"]

    total = last_frame + 1
    for f in range(1, total):
        i = min(f, n - 1)
        s = s_frames[i]
        p, _ = _at(dense, s_list, s)
        yaw = yaws[i]
        v = (s_frames[i] - s_frames[i - 1]) * FPS if i > 0 else 0.0
        a = ((s_frames[min(n - 1, i + 1)] - 2 * s_frames[i] + s_frames[max(0, i - 1)]) * FPS * FPS) if 0 < i < n - 1 \
            else 0.0
        amount = clamp(v / max(g["speed"] * 0.8, 0.1), 0.0, 1.0)
        psi, si = step_phase(f)
        frac = psi - math.floor(psi)
        side_i = sides[si] if 0 <= si < len(sides) else ("R" if first_side == "L" else "L")
        sgn = 1.0 if side_i == "L" else -1.0
        feet = {s_: foot_state(s_, f) for s_ in "LR"}
        # pelvis height: over the ground the feet stand on (not the lifted foot), bobbing with each step
        gz = (feet["L"][4] + feet["R"][4]) / 2
        if gait_kind == "run":
            bob = -g["bob"] * math.cos(2 * math.pi * (frac - 0.35)) * amount
        else:
            bob = -g["bob"] * math.cos(2 * math.pi * frac) * amount
        pz = gz + actor.stand_height - (0.02 if gait_kind != "run" else 0.07) * amount * k + bob * k
        if f < 6:
            pz = lerp(start_pelvis, pz, smooth(f / 6))
        # weight over the stance foot: zero at each strike, most at mid-stance (and onto the standing foot before
        # the very first step)
        sway = g["sway"] * k * math.sin(math.pi * frac) * sgn * (0.6 + 0.4 * amount)
        twist = g["twist"] * (-sgn) * math.cos(math.pi * frac) * amount
        roll = 2.5 * math.sin(math.pi * frac) * (1.0 if side_i == "L" else -1.0) * amount
        pitch = g["lean"] * amount + clamp(a, -2.0, 2.0) * 1.5
        root = (p[0], p[1], gz, yaw)
        pel_xy = add((p[0], p[1], 0.0), mul(left(yaw), sway))
        pose = actor.new_pose(root, (pel_xy[0], pel_xy[1], pz, yaw + math.radians(twist), pitch, roll),
                              spine=(pitch * 0.25, -twist * 0.45, -roll * 0.35),
                              chest=(-pitch * 0.15 + 0.6 * math.sin(f / FPS * 2 * math.pi * 0.24),
                                     -twist * 0.5, -roll * 0.25),
                              neck=(-pitch * 0.3, twist * 0.3, roll * 0.2),
                              head=(-pitch * 0.25, twist * 0.25, roll * 0.25))
        for s_ in "LR":
            ankle, fy, fp, toe, _ = feet[s_]
            pose[f"foot.{s_}"] = (ankle[0], ankle[1], ankle[2], fy, fp)
            pose[f"toe.{s_}"] = toe
        _reach_legs(actor, pose)
        # arms swing against the legs, lagging them a little
        A = g["arm"] * k * amount
        swing_l = -(1.0 if first_side == "L" else -1.0) * A * math.cos(math.pi * (psi - 0.08))
        hands = {}
        for s_, sw in (("L", swing_l), ("R", -swing_l)):
            base = actor._rest_hand(s_)
            fwd = 0.02 * k * amount + sw
            up = g["elbow"] * k * max(0.0, sw) / max(A, 1e-6) * amount if A > 0 else 0.0
            if gait_kind == "run":
                base = (0.06 * k, 0.12 * k, -0.33 * k)
            hands[s_] = (base[0] + 0.01 * abs(sw), base[1] + fwd, base[2] + up)
        blend_from = getattr(actor, "_blend_hands", None)
        if blend_from and f <= blend_from[1]:
            w = smooth(f / max(1, blend_from[1]))
            hands = {s_: lerp(blend_from[0][s_], hands[s_], w) for s_ in "LR"}
        for s_ in "LR":
            if actor.holding[s_]:
                hands[s_] = actor.hand_rel[s_]
        pose["_hands_rel"] = hands
        if overlay is not None:
            overlay(pose, f / FPS, clamp(f / max(1, total - 1), 0, 1))
        hands = pose.pop("_hands_rel")
        actor.finish_pose(pose, hands=hands)
    actor._blend_hands = None
    for side in "LR":
        actor.feet[side] = dict(timeline[side][-1][1])
    last = actor.last
    actor.pos = (last["root"][0], last["root"][1], last["root"][2])
    actor.yaw = yaws[-1]
    actor.pelvis_z = last["pelvis"][2]


def _plant_point(plant, along, k):
    f = forward(plant["yaw"])
    return (plant["x"] + f[0] * along * k, plant["y"] + f[1] * along * k, plant["z"])


def _swing(actor, g, start, end, f0, f1, f, heel, k):
    """A foot in the air from its toe-off at `start` to landing at `end`."""
    u = clamp((f - f0) / max(1, f1 - f0), 0.0, 1.0)
    ball0 = _plant_point(start, lib.BALL, k)
    a0 = ankle_from_contact(ball0, start["yaw"], heel)
    heel1 = _plant_point(end, lib.HEEL, k)
    a1 = ankle_from_contact(heel1, end["yaw"], -12.0)
    if end["z"] - start["z"] > 0.05:   # a step up: the foot rises first and only then goes forward over the edge
        h = smoother(clamp((u - 0.18) / 0.82, 0.0, 1.0))
        base = lerp(a0[2], a1[2], ease_out(clamp(u / 0.7, 0.0, 1.0)))
    else:
        h = smoother(u)
        base = lerp(a0[2], a1[2], smooth(u))
    xy = lerp(a0, a1, h)
    # clear whatever lies between (a step up), plus the gait's own clearance
    world = actor.world
    hi = max(start["z"], end["z"])
    for t in (0.25, 0.5, 0.75):
        q = lerp(a0, a1, t)
        hi = max(hi, world.ground(q[0], q[1], hi))
    clear = (hi - lerp(start["z"], end["z"], 0.5)) + g["clear"] * k
    z = base + max(0.0, clear) * math.sin(math.pi * u) ** 1.3
    yaw = start["yaw"] + wrap(end["yaw"] - start["yaw"]) * smooth(u)
    pitch = lerp(heel, -12.0, smooth(clamp(u * 1.6, 0, 1)))
    toe = heel * (1 - smooth(clamp(u * 2, 0, 1)))
    return (xy[0], xy[1], z), yaw, pitch, toe


def _reach_legs(actor, pose):
    """Lowers the pelvis until both ankles are within the legs' reach (a straight leg is never overstretched)."""
    rig = actor.rig
    limit = rig.leg * 0.985
    for s in "LR":   # a standing action leaves the feet where they're planted
        if f"foot.{s}" not in pose:
            p = actor.feet[s]
            pose[f"foot.{s}"] = (p["x"], p["y"], p["z"] + lib.ANKLE * actor.k, p["yaw"], 0.0)
            pose.setdefault(f"toe.{s}", 0.0)
    for _ in range(3):
        pose.pop("_fk", None)
        fk = actor.torso(pose)
        drop = 0.0
        for s in "LR":
            hip = fk[f"hip.{s}"]
            ankle = pose[f"foot.{s}"][:3]
            d = length(sub(hip, ankle))
            if d > limit:
                h = dist2(hip, ankle)
                want = math.sqrt(max(limit * limit - h * h, 0.01)) + ankle[2]
                drop = max(drop, hip[2] - want)
        if drop <= 1e-4:
            break
        px, py, pz, yaw, pitch, roll = pose["pelvis"]
        pose["pelvis"] = (px, py, pz - drop - 0.002, yaw, pitch, roll)
        pose["_drop"] = pose.get("_drop", 0.0) + drop + 0.002
    pose.pop("_fk", None)


# ---------- standing still, turning on the spot ----------

def idle(actor, seconds, look=None, hands=None, breathe=True, label="idle"):
    """Standing: breathing, weight drifting a little between the feet, an occasional glance."""
    n = max(1, int(round(seconds * FPS)))
    base = actor.last
    actor.mark()
    start_hands = dict(actor.hand_rel)
    yaw = actor.yaw
    gz = (actor.feet["L"]["z"] + actor.feet["R"]["z"]) / 2
    mid = ((actor.feet["L"]["x"] + actor.feet["R"]["x"]) / 2, (actor.feet["L"]["y"] + actor.feet["R"]["y"]) / 2)
    pz0 = base["pelvis"][2] if base else actor.pelvis_z
    phase = actor.rng.uniform(0, math.tau)
    for f in range(1, n + 1):
        t = f / FPS
        w = smooth(f / max(1, int(0.4 * FPS)))
        breath = math.sin(t * math.tau * lib.ACTIONS["idle"]["breath"] + phase) if breathe else 0.0
        shift = 0.012 * actor.k * math.sin(t * math.tau * 0.11 + phase)
        target_z = gz + actor.stand_height + 0.003 * breath
        pz = lerp(pz0, target_z, w)
        pel = add((mid[0], mid[1], 0.0), mul(left(yaw), shift))
        pose = actor.new_pose((mid[0], mid[1], gz, yaw), (pel[0], pel[1], pz, yaw, 1.0, -shift * 40),
                              spine=(0.5, 0, shift * 20), chest=(0.8 * breath - 0.5, 0, shift * 15),
                              neck=(0, 2.0 * math.sin(t * 0.37 + phase), 0), head=(0.5, 0, 0))
        _reach_legs(actor, pose)
        rel = {s: lerp(start_hands[s], (hands or {}).get(s, actor._rest_hand(s)), w) for s in "LR"}
        for s in "LR":
            if actor.holding[s]:
                rel[s] = start_hands[s]
        actor.finish_pose(pose, hands=rel, look=look)
    actor.pelvis_z = actor.last["pelvis"][2]
    actor.pos = (mid[0], mid[1], gz)


def turn(actor, target_yaw, label="turn"):
    """Turning on the spot with small steps: each foot lifts and is put down turned, the body turning between
    them — never a spin on planted feet."""
    delta = wrap(target_yaw - actor.yaw)
    if abs(delta) < math.radians(12):
        actor.yaw = actor.yaw + delta
        return
    actor.mark()
    n = max(1, int(math.ceil(abs(delta) / math.radians(lib.TURN_STEP))))
    step_t = lib.ACTIONS["turn"]["step"]
    lead = "L" if delta > 0 else "R"
    centre = ((actor.feet["L"]["x"] + actor.feet["R"]["x"]) / 2, (actor.feet["L"]["y"] + actor.feet["R"]["y"]) / 2,
              (actor.feet["L"]["z"] + actor.feet["R"]["z"]) / 2)
    moves = []
    for i in range(n):
        y_i = actor.yaw + delta * (i + 1) / n
        moves.append((lead, actor._stand_plant(lead, centre, y_i)))
        other = "R" if lead == "L" else "L"
        moves.append((other, actor._stand_plant(other, centre, y_i)))
    per = int(step_t * FPS)
    overlap = int(per * 0.35)
    total = per + (len(moves) - 1) * (per - overlap) + int(0.15 * FPS)
    yaw0 = actor.yaw
    start_hands = dict(actor.hand_rel)
    pz0 = actor.last["pelvis"][2] if actor.last else actor.pelvis_z
    starts = [k * (per - overlap) for k in range(len(moves))]
    feet_from = {s: dict(actor.feet[s]) for s in "LR"}
    for f in range(1, total + 1):
        u = smooth(f / total)
        yaw = yaw0 + delta * u
        pose_feet = {}
        for s in "LR":
            plant = feet_from[s]
            state = None
            for (side, dest), st in zip(moves, starts):
                if side != s:
                    continue
                if f < st:
                    break
                if f >= st + per:
                    plant = dest
                    continue
                v = (f - st) / per
                a0 = (plant["x"], plant["y"], plant["z"] + lib.ANKLE * actor.k)
                a1 = (dest["x"], dest["y"], dest["z"] + lib.ANKLE * actor.k)
                p = lerp(a0, a1, smoother(v))
                p = (p[0], p[1], lerp(a0[2], a1[2], smooth(v)) + 0.045 * actor.k * math.sin(math.pi * v))
                state = (p, plant["yaw"] + wrap(dest["yaw"] - plant["yaw"]) * smooth(v), 6.0 * math.sin(math.pi * v))
                break
            if state is None:
                state = ((plant["x"], plant["y"], plant["z"] + lib.ANKLE * actor.k), plant["yaw"], 0.0)
            pose_feet[s] = state
        dip = 0.012 * actor.k * math.sin(math.pi * clamp(f / total, 0, 1))
        pel_z = lerp(pz0, centre[2] + actor.stand_height, smooth(f / 6)) - dip
        pose = actor.new_pose((centre[0], centre[1], centre[2], yaw), (centre[0], centre[1], pel_z,
                                                                      yaw - math.radians(4) * math.copysign(1, delta)
                                                                      * math.sin(math.pi * u), 2.0, 0.0),
                              spine=(1, math.degrees(delta) * 0.06 * math.sin(math.pi * u), 0),
                              chest=(0.5, math.degrees(delta) * 0.06 * math.sin(math.pi * u), 0),
                              neck=(0, math.degrees(delta) * 0.08 * math.sin(math.pi * u), 0), head=(0, 0, 0))
        for s in "LR":
            p, fy, fp = pose_feet[s]
            pose[f"foot.{s}"] = (p[0], p[1], p[2], fy, fp)
            pose[f"toe.{s}"] = 0.0
        _reach_legs(actor, pose)
        rel = {s: lerp(start_hands[s], actor._rest_hand(s), smooth(f / max(1, int(0.3 * FPS)))) for s in "LR"}
        for s in "LR":
            if actor.holding[s]:
                rel[s] = start_hands[s]
        actor.finish_pose(pose, hands=rel)
    for side, dest in moves:
        actor.feet[side] = dict(dest)
    actor.yaw = yaw0 + delta
    actor.pelvis_z = actor.last["pelvis"][2]
    actor.pos = centre


# ---------- hands: reaching, holding, gestures ----------

def _hand_frame(fingers, palm):
    """World rotation of a hand bone whose fingers point along `fingers` with the palm facing `palm`."""
    y = norm(fingers)
    z = norm(sub(palm, mul(y, dot(palm, y))))
    return columns(cross(y, z), y, z)


def _hold_pose(actor, pose, side, prop_id, frame):
    """A held prop follows the hand: its world transform is the hand's, times the offset taken when it was
    grasped."""
    prop = actor.world.props[prop_id]
    hand = (pose[f"hrot.{side}"], pose[f"hand.{side}"])
    prop["keys"][frame] = tf_mul(hand, prop["offset"])


def _prop_world(world, prop_id, frame):
    prop = world.props[prop_id]
    best = prop["start"]
    for f in sorted(prop["keys"]):
        if f <= frame:
            best = prop["keys"][f]
        else:
            break
    return best


def gesture(actor, seconds, targets, look=None, grips=None, hrot=None, ease=0.35, keep_feet=True, body=None,
            label="gesture"):
    """Hands (and maybe the upper body) moving to targets over time while standing: `targets(t, pose)` -> {side:
    ("world"|"rel", point)} for each frame. `hrot(t, pose)` -> {side: rotation}; `body(t, pose)` changes the torso.
    Blends in from wherever the hands were over `ease` seconds."""
    n = max(1, int(round(seconds * FPS)))
    start_rel = dict(actor.hand_rel)
    start_grip = {s_: (actor.last or {}).get(f"grip.{s_}", 0.22) for s_ in "LR"}
    start_hrot = {s_: (actor.last or {}).get(f"hrot.{s_}") for s_ in "LR"}
    prev_rel = dict(start_rel)
    actor.mark()
    gz = (actor.feet["L"]["z"] + actor.feet["R"]["z"]) / 2
    mid = ((actor.feet["L"]["x"] + actor.feet["R"]["x"]) / 2, (actor.feet["L"]["y"] + actor.feet["R"]["y"]) / 2)
    yaw = actor.yaw
    last = actor.last
    pz0 = last["pelvis"][2] if last else actor.pelvis_z
    phase = actor.rng.uniform(0, math.tau)
    for f in range(1, n + 1):
        t = f / FPS
        breath = math.sin(t * math.tau * 0.24 + phase)
        pose = actor.new_pose((mid[0], mid[1], gz, yaw), (mid[0], mid[1], lerp(pz0, gz + actor.stand_height,
                                                                                 smooth(f / 8)), yaw, 1.5, 0.0),
                              spine=(1.0, 0, 0), chest=(0.7 * breath, 0, 0), neck=(0, 0, 0), head=(0, 0, 0))
        if body is not None:
            body(t, pose)
        _reach_legs(actor, pose)
        actor.torso(pose)
        want = targets(t, pose) or {}
        rel = {}
        w = smooth(t / ease) if ease > 0 else 1.0
        for s in "LR":
            kind, point = want.get(s, ("rel", actor._rest_hand(s)))
            r = actor.rel_of_hand(pose, s, point) if kind == "world" else point
            rel[s] = lerp(start_rel[s], r, w)
        _limit_reach(actor, pose, rel)
        for s in "LR":   # a hand never moves faster than a fast punch, whatever its target does
            d = sub(rel[s], prev_rel[s])
            cap = 0.12 * actor.k
            if length(d) > cap:
                rel[s] = add(prev_rel[s], mul(d, cap / length(d)))
            prev_rel[s] = rel[s]
        for s in "LR":
            pose[f"hand.{s}"] = actor.hand_world(pose, s, rel[s])
        if hrot is not None:
            for s, r in (hrot(t, pose) or {}).items():
                # a hand turns to a new hold over a fraction of a second, from however it was held
                was = start_hrot.get(s)
                pose[f"hrot.{s}"] = slerp_mat(was, r[0], smooth(t / 0.3)) if was is not None and t < 0.3 else r[0]
                pose[f"hrot_w.{s}"] = r[1]
        for s in "LR":
            if actor.holding[s]:
                pose[f"hrot_w.{s}"] = 1.0
                if pose.get(f"hrot.{s}") is None and last is not None and last.get(f"hrot.{s}") is not None:
                    pose[f"hrot.{s}"] = last[f"hrot.{s}"]
        g = grips(t, pose) if grips else {}
        gw = smooth(t / 0.2)   # a hand closes or opens over a fifth of a second, never in one frame
        for s in "LR":
            if s in g:
                pose[f"grip.{s}"] = lerp(start_grip[s], g[s], gw)
        actor.finish_pose(pose, look=look(t, pose) if callable(look) else look)
        for s in "LR":
            if actor.holding[s] and f"hrot.{s}" in pose:
                _hold_pose(actor, pose, s, actor.holding[s], actor.frame - 1)
    actor.pelvis_z = actor.last["pelvis"][2]


def _limit_reach(actor, pose, rel):
    """Keeps each hand within the arm's reach (98%): an IK chain asked for more snaps straight and drifts."""
    limit = actor.rig.arm * 0.97
    for s in "LR":
        d = length(rel[s])
        if d > limit:
            rel[s] = mul(rel[s], limit / d)


def grasp(actor, side, prop_id, frame=None):
    """From now on `prop_id` moves with the actor's `side` hand (the offset is measured at this frame)."""
    pose = actor.last
    prop = actor.world.props[prop_id]
    current = _prop_world(actor.world, prop_id, actor.frame - 1)
    hand = (pose.get(f"hrot.{side}") or actor.rig.oriented(f"hand.{side}", rot_z(actor.yaw)), pose[f"hand.{side}"])
    prop["offset"] = tf_mul(tf_inv(hand), current)
    actor.holding[side] = prop_id
    actor.event("grasp", prop=prop_id, hand=side)


def release(actor, side):
    prop_id = actor.holding[side]
    if prop_id:
        actor.holding[side] = None
        actor.event("release", prop=prop_id, hand=side)


# ---------- the door ----------

def _door_side(door, point):
    """+1 when `point` is on the room side the door swings into, -1 outside."""
    rel = sub((point[0], point[1], 0.0), (door.hinge[0], door.hinge[1], 0.0))
    return 1.0 if dot(rel, door.n_in) > 0 else -1.0


def _hand_for(actor, point, yaw):
    rel = sub((point[0], point[1], 0.0), (actor.pos[0], actor.pos[1], 0.0))
    return "L" if dot(rel, left(yaw)) > 0 else "R"


def _lever_grip(toward_door, leaf_dir):
    """How a hand holds a lever handle: on top of it, palm down, fingers wrapping toward the door (turned a little
    toward the hinge, where the lever points), thumb inward. That is within ~90 degrees of a hanging hand on either
    side, so blending into it never flips the wrist (palm-on-the-door with fingers to the hinge would be a thumb-down
    twist of nearly 180 degrees for one of the hands)."""
    fingers = norm(add(add(mul(toward_door, 1.0), mul(leaf_dir, -0.35)), (0.0, 0.0, -0.25)))
    palm = add((0.0, 0.0, -1.0), mul(toward_door, 0.3))
    return _hand_frame(fingers, palm)


def _reach_from(actor, xy, yaw, side, target, bend=4.2, twist=4.0, head=False):
    """How far `side`'s hand would have to reach to `target` for the actor standing at `xy` facing `yaw`, leaning
    in as _hold_lean does — measured on the real torso, not guessed."""
    gz = actor.world.ground(xy[0], xy[1], actor.pos[2])
    sign = 1.0 if side == "L" else -1.0
    pose = actor.new_pose((xy[0], xy[1], gz, yaw), (xy[0], xy[1], gz + actor.stand_height, yaw, 1.5, 0.0),
                          spine=(bend, -sign * twist, 0), chest=(bend * 0.67, -sign * twist * 0.75, 0))
    pose[f"shrug.{side}"] = 4.0
    if head:   # where the face is when leaning in and looking down at the hand: in front of the head bone
        fk = actor.torso(pose)
        return tf_point(fk["head"], (0.0, 0.1 * actor.k, 0.13 * actor.k))   # the head bone's Z is forward
    return length(sub(target, actor.torso(pose)[f"arm_root.{side}"]))


def _fits(actor, xy, yaw):
    """Whether both feet of someone standing at `xy` facing `yaw` would be flat on one surface."""
    for side in "LR":
        s = 1.0 if side == "L" else -1.0
        p = add((xy[0], xy[1], 0.0), mul(left(yaw), lib.STEP_WIDTH * actor.k * s))
        ok, _ = actor.world.foot_level(p, yaw + s * math.radians(lib.TOE_OUT), actor.pos[2], actor.k)
        if not ok:
            return False
    return True


def stand_near(actor, centre, gap=0.42, prefer=None, body=0.24):
    """Where to stand to use something at `centre`: `gap` metres from it, on the side facing the actor (or `prefer`,
    a yaw), backing off and trying the sides until the body (radius `body`) is clear of everything solid there —
    measured in the scene (World.clearance), so a table between never gets walked into. Returns (x, y, yaw facing
    it)."""
    k = actor.k
    world = actor.world
    base = yaw_of(sub((centre[0], centre[1], 0), (actor.pos[0], actor.pos[1], 0))) if prefer is None else prefer
    for extra in (0.0, 0.1, 0.2, 0.3, 0.45, 0.6):
        for turn_deg in (0, 35, -35, 70, -70, 110, -110, 180):
            y = base + math.radians(turn_deg)
            p = add((centre[0], centre[1], 0.0), mul(forward(y), -(gap + extra) * k))
            if world.clearance(p[0], p[1], None) >= body * k:
                return p[0], p[1], y
    p = add((centre[0], centre[1], 0.0), mul(forward(base), -gap * k))
    return p[0], p[1], base


def _hold_lean(pose, side, sign, w, bend=4.2, twist=4.0):
    """The torso of someone holding on to a door handle in front of them: leaning in a little, turned toward that
    hand, the shoulder raised. `w` blends it in over whatever the feet are doing."""
    if w <= 0:
        return
    for name, b, tw in (("spine", bend, twist), ("chest", bend * 0.67, twist * 0.75)):
        cur = pose[name]
        pose[name] = lerp(cur, (b, -sign * tw, cur[2]), w)
    pose[f"shrug.{side}"] = lerp(pose.get(f"shrug.{side}", 0.0), 4.0, w)
    pose.pop("_fk", None)


def open_door(actor, door_id, enter=True, label="open the door"):
    """From outside the door's swing: walk up to it, reach for the handle, press it, push the door open while
    stepping through, let go as it swings on, and (with `enter`) walk into the room. The door opens as far as the
    body needs before the body gets there."""
    world = actor.world
    door = world.doors.get(door_id)
    if door is None:
        raise Problem(f"there's no door called {door_id}")
    d = lib.ACTIONS["door"]
    mid = door.middle()
    inside_side = _door_side(door, actor.pos)
    if inside_side > 0:   # already inside: going out pulls the door — not built; say so instead of faking it
        raise Problem("the character is already on the side the door opens into")
    lateral = 0.06   # stand a little toward the handle side, so the swinging leaf clears the shoulder
    yaw_in = yaw_of(door.n_in)
    handle0 = door.handle(0.0, inner=False)
    # the farthest spot (so the leaf has room to swing) from which the hand reaches the handle comfortably, with
    # both feet flat on one tread of the steps
    approach = None
    for back in [x / 100 for x in range(60, 21, -2)]:
        cand = add(add(mid, mul(door.n_in, -back)), mul(door.u, lateral))
        hand = _hand_for(actor, handle0, yaw_in) if False else ("L" if dot(sub(handle0, cand), left(yaw_in)) > 0
                                                               else "R")
        if _reach_from(actor, cand, yaw_in, hand, handle0) < actor.rig.arm * 0.88 and _fits(actor, cand, yaw_in):
            approach = cand
            break
    if approach is None:
        raise Problem("there's nowhere in front of the door to stand and reach its handle")
    if dist2(actor.pos, approach) > 0.12:
        locomote(actor, [approach], "walk", stop=True, face=None)
    turn(actor, yaw_in)
    idle(actor, 0.15)
    side = _hand_for(actor, door.handle(0.0, inner=False), yaw_in)
    actor.event("reach handle", door=door_id, hand=side)
    sign = 1.0 if side == "L" else -1.0

    def handle_rot(a):
        return _lever_grip(door.face_normal(a, inner=True), door.leaf_dir(a))   # the door is beyond its outer face

    reach_t, unlatch_t = d["reach"], d["unlatch"]
    f_reach0 = actor.frame

    def reach_targets(t, pose):
        u = smooth(t / reach_t)
        h = door.handle(0.0, inner=False)
        if t > reach_t:   # pressing the lever down
            h = add(h, (0, 0, -0.03 * smooth((t - reach_t) / unlatch_t)))
        return {side: ("world", h)}

    def reach_body(t, pose):
        lean = 7.0 * smooth(t / reach_t)
        pose["spine"] = (lean * 0.6, -sign * 4.0 * smooth(t / reach_t), 0)
        pose["chest"] = (lean * 0.4, -sign * 3.0 * smooth(t / reach_t), 0)
        pose[f"shrug.{side}"] = 4.0 * smooth(t / reach_t)

    gesture(actor, reach_t + unlatch_t, reach_targets, look=door.handle(0.0, False),
            grips=lambda t, p: {side: 0.22 + 0.6 * smooth((t - reach_t * 0.7) / (reach_t * 0.3))},
            hrot=lambda t, p: {side: (handle_rot(0.0), smooth((t - reach_t * 0.4) / (reach_t * 0.6)))},
            ease=reach_t, body=reach_body)
    actor.event("grasp handle", door=door_id, hand=side)
    # push: the door's angle follows the hand while the body steps in; it must always stay ahead of the body
    push_t, release_at, open_to, swing_t = d["push"], d["release_at"], d["open"], d["swing"]
    through = add(mid, mul(door.n_in, 0.15))
    inside = add(add(mid, mul(door.n_in, d["inside"])), mul(door.u, lateral * 2))
    path = [through, inside] if enter else [add(mid, mul(door.n_in, -0.3))]
    radius = d["clearance"] * actor.k
    state = {"a": 0.0, "held": True, "released_at": None, "release_rel": None}
    f_push0 = actor.frame

    def overlay(pose, t, u):
        f = actor.frame
        body = pose["pelvis"][:2]
        # where the leaf must be: past the body (and a margin) whenever the body is in its sweep
        need = 0.0
        for a in range(0, int(open_to) + 1, 2):
            if not door.blocks(a, body, radius + 0.12):
                need = a
                break
        else:
            need = open_to
        sched = (release_at * smooth(t / push_t) if t <= push_t else
                 release_at + (open_to - release_at) * ease_out((t - push_t) / swing_t))
        a = max(state["a"], min(open_to, max(sched, need + 4.0 if need > 0 else 0.0)))
        state["a"] = a
        door.set(f, a)
        _hold_lean(pose, side, sign, 1.0 if state["held"] else 1 - smooth((t - state["released_at"]) / 0.45))
        fk = actor.torso(pose)
        far = length(sub(door.handle(a, inner=False), fk[f"arm_root.{side}"])) > actor.rig.arm * 0.98
        if state["held"] and (a >= release_at or t >= push_t or far):   # pushed, or out of the hand's reach
            state["why"] = {"angle": round(a, 1), "t": round(t, 2), "out_of_reach": far}
            state["held"] = False
            state["released_at"] = t
            state["release_rel"] = actor.hand_rel[side]   # where the hand really was: on the handle
            actor.event("release handle", door=door_id, hand=side, **state["why"])
        if state["held"]:   # the lever, pressed down at the end of the reach, comes back up as the door moves
            press = -0.03 * (1 - smooth(t / 0.3))
            pose[f"hand.{side}"] = add(door.handle(a, inner=False), (0.0, 0.0, press))
            pose[f"hrot.{side}"] = handle_rot(a)
            pose[f"hrot_w.{side}"] = 1.0
            pose[f"grip.{side}"] = 0.82
            pose["look"] = door.handle(a, False)
        else:
            w = smooth((t - state["released_at"]) / 0.45)
            if w < 1.0:
                rel_from = state["release_rel"]
                pose["_hands_rel"][side] = lerp(rel_from, pose["_hands_rel"][side], w)
                pose[f"hrot_w.{side}"] = 1.0 - w
                pose[f"hrot.{side}"] = handle_rot(a)
                pose[f"grip.{side}"] = lerp(0.82, 0.22, w)
            pose["look"] = None

    # hands start from the reach pose
    actor._blend_hands = (dict(actor.hand_rel), int(0.3 * FPS))
    locomote(actor, path, "slow", stop=True, overlay=overlay, settle=0.3)
    a = state["a"]
    f = actor.frame
    if a < open_to:   # the door swings on after the body has passed
        for k in range(1, int(swing_t * FPS) + 1):
            door.set(f + k, a + (open_to - a) * ease_out(k / (swing_t * FPS)))
    actor.event("door open", door=door_id)
    if enter:
        actor.event("entered", door=door_id)
    return side


def close_door(actor, door_id, label="close the door"):
    """From inside the room the door opened into: go round the open leaf's free end into the space behind it, take
    the inner handle and walk the door shut — the body follows the leaf round the hinge, so the leaf always moves
    away from the body and can never hit it; let go just before it closes and it swings shut on its own."""
    world = actor.world
    door = world.doors.get(door_id)
    if door is None:
        raise Problem(f"there's no door called {door_id}")
    d = lib.ACTIONS["door"]
    a_open = door.angle_at(actor.frame + 10 ** 6)
    if a_open < 20:
        raise Problem("the door is already closed")
    if _door_side(door, actor.pos) < 0:
        raise Problem("the character isn't on the side the door opened into")
    k = actor.k
    a_rel = d["close_release"]

    def place(phi, r):
        return add(door.hinge, mul(door.leaf_dir(phi), r))

    def tangent_yaw(phi):
        """Facing round the hinge toward the closed position."""
        return yaw_of(sub(door.leaf_dir(phi - 1.0), door.leaf_dir(phi)))

    def spot(a_door):
        """(body angle round the hinge, radius) behind the leaf at `a_door` from which the hand reaches the inner
        handle comfortably while the chest stays clear of the leaf."""
        h = door.handle(a_door, inner=True)
        for off in (22, 25, 19, 28, 16):   # the leaf at least a step ahead of the pelvis: the leading foot clears it
            for r in (1.15, 1.2, 1.1, 1.05, 1.0, 0.95, 0.9, 1.25):
                phi = a_door + off
                p = place(phi, r * k)
                yaw = tangent_yaw(phi)
                if world.clearance(p[0], p[1], door.hinge[2]) < 0.3 * k:
                    continue
                side = "L" if dot(sub(h, p), left(yaw)) > 0 else "R"
                if door.blocks(a_door, p, 0.27 * k):   # the chest and the swinging arm, facing round the hinge
                    continue
                face = _reach_from(actor, p, yaw, side, h, bend=5.0, twist=4.0, head=True)
                if door.blocks(a_door, face, 0.13 * k):   # leaning in to look at the handle: the head stays clear
                    continue
                if _reach_from(actor, p, yaw, side, h, bend=5.0, twist=4.0) < actor.rig.arm * 0.9:
                    return off, r * k, side
        raise Problem("there's no room behind the open door to stand and close it")

    off, r, side = spot(a_open)
    phi1 = a_open + off
    q1 = place(phi1, r)
    # round the leaf's free end, never through it
    # (arms swing ~0.3 m out from the body's centre: the route keeps that far from the leaf's free end)
    around = place(a_open - 14, door.width + 0.62 * k)
    behind = place(phi1 + 6, door.width + 0.5 * k)
    turn(actor, yaw_of(sub(around, (actor.pos[0], actor.pos[1], 0.0))))
    locomote(actor, [(around[0], around[1]), (behind[0], behind[1]), (q1[0], q1[1])], "slow", stop=True)
    yaw1 = tangent_yaw(phi1)
    turn(actor, yaw1)
    sign = 1.0 if side == "L" else -1.0

    def handle_rot(a):
        return _lever_grip(mul(door.face_normal(a, inner=True), -1.0), door.leaf_dir(a))   # beyond its inner face

    reach_t = d["reach"]
    actor.event("reach handle", door=door_id, hand=side)
    gesture(actor, reach_t, lambda t, p: {side: ("world", door.handle(a_open, inner=True))},
            look=door.handle(a_open, True),
            grips=lambda t, p: {side: 0.22 + 0.6 * smooth((t - reach_t * 0.7) / (reach_t * 0.3))},
            hrot=lambda t, p: {side: (handle_rot(a_open), smooth((t - reach_t * 0.4) / (reach_t * 0.6)))},
            ease=reach_t, body=lambda t, p: _hold_lean(p, side, sign, smooth(t / reach_t), bend=5.0, twist=4.0))
    actor.event("grasp handle", door=door_id, hand=side)
    shut_t = d["shut"]
    state = {"held": True, "release_rel": None, "released_at": None, "a": a_open, "a_released": None}

    def body_angle(pose):
        rel = sub((pose["pelvis"][0], pose["pelvis"][1], 0.0), (door.hinge[0], door.hinge[1], 0.0))
        return math.degrees(math.atan2(dot(rel, door.n_in), dot(rel, door.u)))   # 0 closed, 90 along n_in

    def overlay(pose, t, u):
        f = actor.frame
        if state["held"]:
            # the door goes where the body takes it: `off` degrees ahead of where the body really is, never back
            a = min(state["a"], clamp(body_angle(pose) - off, 0.0, a_open))
            _hold_lean(pose, side, sign, 1.0, bend=5.0, twist=4.0)
            fk = actor.torso(pose)
            far = length(sub(door.handle(a, inner=True), fk[f"arm_root.{side}"])) > actor.rig.arm * 0.98
            if a <= a_rel or far:
                state.update(held=False, released_at=t, a_released=a, release_rel=actor.hand_rel[side])
                actor.event("release handle", door=door_id, hand=side, angle=round(a, 1), out_of_reach=far)
        else:   # let go: it swings shut by itself, faster as it goes
            a = state["a_released"] * (1 - ease_in((t - state["released_at"]) / shut_t))
            _hold_lean(pose, side, sign, 1 - smooth((t - state["released_at"]) / 0.45), bend=5.0, twist=4.0)
        a = max(0.0, a)
        state["a"] = a
        door.set(f, a)
        if state["held"]:
            pose[f"hand.{side}"] = door.handle(a, inner=True)
            pose[f"hrot.{side}"] = handle_rot(a)
            pose[f"hrot_w.{side}"] = 1.0
            pose[f"grip.{side}"] = 0.82
            pose["look"] = door.handle(a, True)
        else:
            w = smooth((t - state["released_at"]) / 0.45)
            pose["_hands_rel"][side] = lerp(state["release_rel"], pose["_hands_rel"][side], w)
            pose[f"hrot_w.{side}"] = 1.0 - w
            pose[f"hrot.{side}"] = handle_rot(a)
            pose[f"grip.{side}"] = lerp(0.82, 0.22, w)
            pose["look"] = door.handle(a, True) if w < 1 else None

    actor._blend_hands = (dict(actor.hand_rel), int(0.2 * FPS))
    # the body walks round the hinge behind the leaf as it closes, as far as there's room (a wall the arc would
    # run into ends it early: then the door is let go sooner and swings the rest of the way by itself)
    phi_end = a_rel + off - 1.0
    phi = phi1
    while phi > phi_end:
        nxt = place(phi - 2.0, r)
        if world.clearance(nxt[0], nxt[1], door.hinge[2]) < 0.3 * k:
            phi_end = phi
            break
        phi -= 2.0
    a_rel = max(a_rel, phi_end - off + 1.0)
    arc = [place(lerp(phi1, phi_end, i / 6), r) for i in range(1, 7)]
    locomote(actor, [(p[0], p[1]) for p in arc], "slow", stop=True, overlay=overlay, settle=shut_t + 0.5)
    f = actor.frame
    if state["held"]:   # the walk ended with the hand still on it: let go now
        state["a_released"] = state["a"]
        actor.event("release handle", door=door_id, hand=side)
    if state["a"] > 0.0:   # whatever is left of the swing after the body has stopped
        start = state["a"]
        n = max(2, int(shut_t * FPS))
        for kf in range(1, n + 1):
            door.set(f + kf - 1, start * (1 - ease_in(kf / n)))
    door.set(f + int(shut_t * FPS) + 1, 0.0)
    actor.event("door closed", door=door_id)
    return side


# ---------- sitting, standing ----------

def sit(actor, seat_id, label="sit down"):
    """Walk to the front of the seat, turn round, and lower onto it: hips back and down, chest leaning forward to
    stay balanced, hands finding the thighs, then upright."""
    world = actor.world
    seat = world.seats.get(seat_id)
    if seat is None:
        raise Problem(f"there's no seat called {seat_id}")
    d = lib.ACTIONS["sit"]
    k = actor.k
    facing = math.radians(seat.get("facing", 0.0))
    # stand in front of the seat with one's back to it (a clear spot: a chair at a table has the table in front)
    fx, fy, _ = stand_near(actor, seat["at"], 0.4, prefer=facing + math.pi)
    front = (fx, fy)
    if dist2(actor.pos, front) > 0.12:
        locomote(actor, [front], "walk", stop=True)
    turn(actor, facing)
    seat_h = seat.get("height", lib.SEAT_HEIGHT)
    seat_xy = (seat["at"][0], seat["at"][1])
    gz = (actor.feet["L"]["z"] + actor.feet["R"]["z"]) / 2
    # the feet move a little closer to the seat so the shins are near vertical when seated
    for s in "LR":
        p = actor._stand_plant(s, add((seat_xy[0], seat_xy[1], gz), mul(forward(facing), 0.33 * k)), facing)
        _step_foot(actor, s, p, 0.35)
    start = actor.last["pelvis"]
    yaw = facing
    sit_pel = add((seat_xy[0], seat_xy[1], 0.0), mul(forward(facing), d["seat_depth"] * k))
    sit_z = seat["at"][2] + seat_h + 0.095 * k if len(seat["at"]) > 2 else gz + seat_h + 0.095 * k
    n = int(d["down"] * FPS)
    actor.mark()
    start_rel = dict(actor.hand_rel)
    on_thigh = (-0.06 * k, 0.24 * k, -0.42 * k)
    actor.event("sitting down", seat=seat_id)
    for f in range(1, n + 1):
        u = f / n
        down = smoother(u)
        lean = d["lean"] * math.sin(math.pi * min(1.0, u * 1.15))   # forward going down, upright once seated
        x = lerp(start[0], sit_pel[0], smooth(u * 1.3))
        y = lerp(start[1], sit_pel[1], smooth(u * 1.3))
        z = lerp(start[2], sit_z, down)
        pose = actor.new_pose((seat_xy[0], seat_xy[1], gz, yaw), (x, y, z, yaw, lean * 0.55 + 4 * down, 0.0),
                              spine=(lean * 0.25, 0, 0), chest=(lean * 0.2, 0, 0), neck=(-lean * 0.35, 0, 0),
                              head=(-lean * 0.25, 0, 0))
        rel = {s: lerp(start_rel[s], on_thigh, smooth(u * 1.4)) for s in "LR"}
        actor.finish_pose(pose, hands=rel)
    actor.seated = seat_id
    actor.pelvis_z = sit_z
    actor.event("seated", seat=seat_id)


def stand_up(actor, label="stand up"):
    if not actor.seated:
        return
    d = lib.ACTIONS["sit"]
    k = actor.k
    seat = actor.world.seats[actor.seated]
    facing = math.radians(seat.get("facing", 0.0))
    gz = (actor.feet["L"]["z"] + actor.feet["R"]["z"]) / 2
    mid = ((actor.feet["L"]["x"] + actor.feet["R"]["x"]) / 2, (actor.feet["L"]["y"] + actor.feet["R"]["y"]) / 2)
    start = actor.last["pelvis"]
    n = int(d["up"] * FPS)
    actor.mark()
    start_rel = dict(actor.hand_rel)
    actor.event("standing up", seat=actor.seated)
    for f in range(1, n + 1):
        u = f / n
        up = smoother(clamp((u - 0.2) / 0.8, 0, 1))
        lean = d["lean"] * math.sin(math.pi * min(1.0, u * 1.1)) * 1.1
        stand = add((mid[0], mid[1], 0.0), mul(forward(facing), -0.02 * k))
        x = lerp(start[0], stand[0], smooth(u * 1.2))
        y = lerp(start[1], stand[1], smooth(u * 1.2))
        z = lerp(start[2], gz + actor.stand_height, up)
        pose = actor.new_pose((mid[0], mid[1], gz, facing), (x, y, z, facing, lean * 0.6 + 4 * (1 - up), 0.0),
                              spine=(lean * 0.25, 0, 0), chest=(lean * 0.2, 0, 0), neck=(-lean * 0.3, 0, 0),
                              head=(-lean * 0.2, 0, 0))
        _reach_legs(actor, pose)
        rel = {s: lerp(start_rel[s], actor._rest_hand(s), smooth(u)) for s in "LR"}
        for s in "LR":
            if actor.holding[s]:
                rel[s] = start_rel[s]
        actor.finish_pose(pose, hands=rel)
    actor.seated = None
    actor.pelvis_z = actor.last["pelvis"][2]
    actor.pos = (mid[0], mid[1], gz)
    actor.yaw = facing
    actor.event("standing", seat=None)


def _step_foot(actor, side, dest, seconds):
    """One foot picked up and put down at `dest` while the other stays (shuffling into place)."""
    n = max(2, int(seconds * FPS))
    src = dict(actor.feet[side])
    actor.mark()
    last = actor.last
    start_rel = dict(actor.hand_rel)
    for f in range(1, n + 1):
        v = f / n
        a0 = (src["x"], src["y"], src["z"] + lib.ANKLE * actor.k)
        a1 = (dest["x"], dest["y"], dest["z"] + lib.ANKLE * actor.k)
        p = lerp(a0, a1, smoother(v))
        p = (p[0], p[1], lerp(a0[2], a1[2], smooth(v)) + 0.04 * actor.k * math.sin(math.pi * v))
        pel = last["pelvis"] if last else (actor.pos[0], actor.pos[1], actor.pelvis_z, actor.yaw, 0, 0)
        other = actor.feet["R" if side == "L" else "L"]
        mid = lerp((src["x"], src["y"]), (dest["x"], dest["y"]), smooth(v))
        cx, cy = (mid[0] + other["x"]) / 2, (mid[1] + other["y"]) / 2
        pose = actor.new_pose((cx, cy, other["z"], actor.yaw), (lerp(pel[0], cx, smooth(v)), lerp(pel[1], cy, smooth(v)),
                                                                 pel[2], actor.yaw, 1.5, 0.0),
                              spine=(1, 0, 0), chest=(0.5, 0, 0))
        pose[f"foot.{side}"] = (p[0], p[1], p[2], src["yaw"] + wrap(dest["yaw"] - src["yaw"]) * smooth(v),
                                5 * math.sin(math.pi * v))
        pose[f"toe.{side}"] = 0.0
        _reach_legs(actor, pose)
        actor.finish_pose(pose, hands=start_rel)
    actor.feet[side] = dict(dest)
    actor.pelvis_z = actor.last["pelvis"][2]


# ---------- eating, drinking, phone, picking things up ----------

def _seated_body(actor, base):
    """While seated: the pelvis stays on the seat; the chest leans in toward what the hands do."""
    def body(t, pose):
        pose["pelvis"] = base
        pose["root"] = actor.last["root"]
    return body


def _reach_for(actor, side, point, seconds, look=None, body=None, grip_to=0.75, rot=None):
    gesture(actor, seconds, lambda t, p: {side: ("world", point)}, look=look or point,
            grips=lambda t, p: {side: 0.22 + (grip_to - 0.22) * smooth((t - seconds * 0.65) / (seconds * 0.35))},
            hrot=(lambda t, p: {side: (rot, smooth((t - seconds * 0.3) / (seconds * 0.7)))}) if rot else None,
            ease=seconds, body=body)


def eat(actor, prop_id, side="R", bites=None, drink=False, label="eat"):
    """Reach for the food (or drink) in front of the actor, pick it up, bring it to the mouth for a few bites (sips)
    with the head meeting it, put it back where it was and let go."""
    world = actor.world
    prop = world.props.get(prop_id)
    if prop is None:
        raise Problem(f"there's no {prop_id} here")
    d = lib.ACTIONS["drink" if drink else "eat"]
    start = _prop_world(world, prop_id, actor.frame - 1)
    home = start[1]
    base = actor.last["pelvis"]
    body = _seated_body(actor, base) if actor.seated else None
    yaw = actor.yaw
    k = actor.k
    s = 1.0 if side == "L" else -1.0
    # how the hand meets it: from above-behind, palm toward it, fingers forward
    grip_rot = _hand_frame(add(forward(yaw), (0, 0, -0.5)), add(mul(left(yaw), -s), (0, 0, -0.3)))
    grip_point = add(home, mul(forward(yaw), -0.03))
    grip_point = (grip_point[0], grip_point[1], home[2] + 0.02)
    lean_body = (lambda t, p: (body(t, p) if body else None, p.update(spine=(9.0, -s * 4, 0),
                                                                          chest=(5.0, -s * 3, 0))))
    holder = next((h for h in "LR" if actor.holding[h] == prop_id), None)
    if holder is not None:   # already in hand (picked up before): drink from it as it's held
        side = holder
        s = 1.0 if side == "L" else -1.0
        grip_rot = actor.last.get(f"hrot.{side}") or grip_rot
    else:
        actor.event("reach", prop=prop_id, hand=side)
        _reach_for(actor, side, grip_point, d["reach"], body=lean_body, rot=grip_rot)
        grasp(actor, side, prop_id)
    count = bites or (d.get("bites", 1) if not drink else 1)
    for i in range(count):
        def to_mouth(t, p, i=i):
            mouth = actor.mouth(p)
            prop_ = world.props[prop_id]
            spec = prop_["spec"]
            bite_local = spec["mouth"] or (0, 0, 0)
            r = p.get(f"hrot.{side}", grip_rot)
            want = sub(mouth, mat_vec(r, add(prop_["offset"][1], mat_vec(prop_["offset"][0], bite_local))))
            if drink:
                want = add(want, (0, 0, -0.01))
            return {side: ("world", want)}

        def lift_rot(t, p, phase="lift"):
            tilt = math.radians(d.get("tilt", 0.0)) * (smooth(t / d["lift"]) if phase == "lift" else 1.0)
            r = mat_mul(rot_axis(left(yaw), -tilt if drink else -0.4 * smooth(t / d["lift"])), grip_rot)
            return {side: (r, 1.0)}

        def head_meets(t, p):
            if body:
                body(t, p)
            p["neck"] = (6.0 if not drink else -d.get("head_back", 10.0) * smooth(t / d["lift"]), 0, 0)
            p["head"] = (6.0 if not drink else -4.0, 0, 0)
            p["spine"] = (4.0, 0, 0)

        actor.event("bite" if not drink else "sip", prop=prop_id, n=i + 1)
        gesture(actor, d["lift"], to_mouth, hrot=lift_rot, grips=lambda t, p: {side: 0.8}, ease=d["lift"],
                body=head_meets, look=None)
        hold = d.get("bite", d.get("sip", 1.0))

        def chew_head(t, p):
            head_meets(t, p)
            p["head"] = (6.0 + 3.0 * math.sin(t * math.tau * 2.6), 0, 0)

        gesture(actor, hold, to_mouth, hrot=lambda t, p: lift_rot(d["lift"], p), grips=lambda t, p: {side: 0.8},
                ease=0.0, body=chew_head if not drink else head_meets)
        if i + 1 < count:   # lowered a little while chewing
            rest = add(home, (0, 0, 0.18))
            gesture(actor, d.get("chew", 0.8), lambda t, p: {side: ("world", rest)},
                    hrot=lambda t, p: {side: (grip_rot, 1.0)}, grips=lambda t, p: {side: 0.8}, ease=0.5,
                    body=(lambda t, p: (body(t, p) if body else None,
                                        p.update(head=(2 + 2.5 * math.sin(t * math.tau * 2.4), 0, 0)))))
    # put it back where it was
    actor.event("put back", prop=prop_id)
    _reach_for(actor, side, grip_point, d["put"] if "put" in d else d["lower"], body=lean_body, rot=grip_rot,
               grip_to=0.8)
    prop["keys"][actor.frame - 1] = (start[0], home)
    release(actor, side)
    gesture(actor, 0.6, lambda t, p: {side: ("rel", actor._rest_hand(side) if not actor.seated
                                             else (-0.06 * k, 0.24 * k, -0.42 * k))},
            grips=lambda t, p: {side: lerp(0.8, 0.22, smooth(t / 0.3))},
            hrot=lambda t, p: {side: (grip_rot, 1 - smooth(t / 0.4))}, ease=0.6, body=body)


def drink(actor, prop_id, side="R"):
    return eat(actor, prop_id, side=side, drink=True)


def pick_up(actor, prop_id, label="pick it up"):
    """Bend the knees (feet planted), reach with the hand(s), grasp, rise holding it."""
    world = actor.world
    prop = world.props.get(prop_id)
    if prop is None:
        raise Problem(f"there's no {prop_id} here")
    d = lib.ACTIONS["pick_up"]
    k = actor.k
    where = _prop_world(world, prop_id, actor.frame - 1)[1]
    sx, sy, yaw = stand_near(actor, where, 0.3)
    if dist2(actor.pos, (sx, sy)) > 0.12:
        locomote(actor, [(sx, sy)], "walk", stop=True)
    turn(actor, yaw)
    two = prop["spec"]["hands"] == 2
    size = prop["spec"]["size"]
    gz = (actor.feet["L"]["z"] + actor.feet["R"]["z"]) / 2
    low = where[2] - gz < 0.6
    pel = actor.last["pelvis"]
    # how far to bend: from the ground, a squat; from a table, as far over it as the hand needs to get there
    bend = 32.0
    if not low:
        for bend in (12.0, 20.0, 28.0, 36.0, 44.0):
            test = actor.new_pose(actor.last["root"], (pel[0], pel[1], pel[2] - 0.08 * k, yaw, bend, 0.0),
                                  spine=(12, 0, 0), chest=(8, 0, 0))
            if length(sub(where, actor.torso(test)["arm_root.R"])) < actor.rig.arm * 0.93:
                break

    def crouch(t, p, amount=None):
        u = smooth(t / d["crouch"]) if amount is None else amount
        drop = (0.32 if low else 0.08) * k * u
        p["pelvis"] = (pel[0] - forward(yaw)[0] * 0.08 * u, pel[1] - forward(yaw)[1] * 0.08 * u, pel[2] - drop, yaw,
                       bend * u, 0.0)
        p["spine"] = (12 * u, 0, 0)
        p["chest"] = (8 * u, 0, 0)
        p["neck"] = (-14 * u, 0, 0)

    def targets(t, p):
        out = {}
        sides = ("L", "R") if two else ("R",)
        for s in sides:
            sg = 1.0 if s == "L" else -1.0
            side_pt = add(where, mul(left(yaw), sg * (size[0] / 2 + 0.03 if two else 0.0)))
            out[s] = ("world", (side_pt[0], side_pt[1], where[2] + (size[2] * 0.4 if two else 0.03)))
        return out

    def rot_for(s):
        sg = 1.0 if s == "L" else -1.0
        return (_hand_frame(add(forward(yaw), (0, 0, -0.6)), mul(left(yaw), -sg)) if two else
                _hand_frame(add(forward(yaw), (0, 0, -0.8)), (0, 0, -1)))

    sides = ("L", "R") if two else ("R",)
    actor.event("reach", prop=prop_id)
    gesture(actor, d["crouch"], targets, body=crouch, look=where,
            grips=lambda t, p: {s: 0.22 + 0.5 * smooth((t - d["crouch"] * 0.7) / (d["crouch"] * 0.3)) for s in sides},
            hrot=lambda t, p: {s: (rot_for(s), smooth(t / d["crouch"])) for s in sides}, ease=d["crouch"])
    for s in sides:
        grasp(actor, s, prop_id) if s == sides[0] else None
    if two:   # the second hand holds it too (the prop follows the first)
        actor.holding["L"] = prop_id
    carry = {s: (0.0 * k, 0.32 * k, -0.36 * k) for s in "LR"} if two else {"R": (0.03 * k, 0.12 * k, -0.5 * k)}

    def rise(t, p):
        crouch(t, p, amount=1 - smoother(t / d["rise"]))

    def carry_t(t, p):
        out = {}
        for s in sides:
            rel = carry[s]
            if two:
                sg = 1.0 if s == "L" else -1.0
                rel = (-(size[0] / 2 + 0.03) * 1.0 + 0.17 * k, 0.34 * k, -0.38 * k)
            out[s] = ("rel", rel)
        return out

    gesture(actor, d["rise"], carry_t, body=rise, grips=lambda t, p: {s: 0.75 for s in sides},
            hrot=lambda t, p: {s: (rot_for(s), 1.0) for s in sides}, ease=d["rise"])
    actor.event("holding", prop=prop_id)


def put_down(actor, at=None, label="put it down"):
    """Bend down and set what's held on the ground (or a surface at `at`), let go and straighten up."""
    held = actor.holding["R"] or actor.holding["L"]
    if not held:
        raise Problem("the character isn't holding anything")
    world = actor.world
    d = lib.ACTIONS["put_down"]
    k = actor.k
    yaw = actor.yaw
    target = at or add((actor.pos[0], actor.pos[1], 0.0), mul(forward(yaw), 0.42 * k))
    gz = world.ground(target[0], target[1], actor.pos[2])
    prop = world.props[held]
    two = prop["spec"]["hands"] == 2
    size = prop["spec"]["size"]
    z = (target[2] if len(target) > 2 else gz) + size[2] / 2
    pel = actor.last["pelvis"]
    low = z - gz < 0.6
    sides = [s for s in "LR" if actor.holding[s]]
    lead = sides[0] if actor.holding["R"] != held else "R"

    def crouch(t, p, amount=None):
        u = smooth(t / d["crouch"]) if amount is None else amount
        drop = (0.32 if low else 0.08) * k * u
        p["pelvis"] = (pel[0], pel[1], pel[2] - drop, yaw, (32 if low else 12) * u, 0.0)
        p["spine"] = (12 * u, 0, 0)
        p["chest"] = (8 * u, 0, 0)

    start_world = _prop_world(world, held, actor.frame - 1)
    # the hand that the prop follows goes to where the prop must end up
    holder = "R" if actor.holding["R"] == held and "offset" in prop else lead
    off = prop["offset"]

    def targets(t, p):
        u = smooth(t / d["crouch"])
        r = p.get(f"hrot.{holder}") or actor.last.get(f"hrot.{holder}")
        dest_centre = (target[0], target[1], z)
        cur = lerp(start_world[1], dest_centre, u)
        hand = sub(cur, mat_vec(r, off[1])) if r else cur
        out = {holder: ("world", hand)}
        for s in sides:
            if s != holder:
                sg = 1.0 if s == "L" else -1.0
                out[s] = ("world", add(cur, mul(left(yaw), sg * (size[0] / 2 + 0.03))))
        return out

    last = actor.last
    gesture(actor, d["crouch"], targets, body=crouch,
            hrot=lambda t, p: {s: (last.get(f"hrot.{s}") or IDENTITY, 1.0) for s in sides},
            grips=lambda t, p: {s: 0.75 for s in sides}, ease=0.0)
    for s in sides:
        actor.holding[s] = None
    prop["keys"][actor.frame - 1] = (start_world[0], (target[0], target[1], z))
    actor.event("release", prop=held)

    def rise(t, p):
        crouch(t, p, amount=1 - smoother(t / d["rise"]))

    gesture(actor, d["rise"], lambda t, p: {}, body=rise, grips=lambda t, p: {s: 0.22 for s in "LR"},
            hrot=lambda t, p: {s: (last.get(f"hrot.{s}") or IDENTITY, 1 - smooth(t / 0.4)) for s in sides},
            ease=d["rise"])


def wave(actor, side="R", at=None, label="wave"):
    d = lib.ACTIONS["wave"]
    k = actor.k
    total = d["raise"] + d["wave"] * 2 * d["waves"] + d["lower"]
    s = 1.0 if side == "L" else -1.0

    def targets(t, p):
        up = (0.24 * k, 0.12 * k, 0.32 * k)
        if t < d["raise"]:
            return {side: ("rel", up)}
        if t < total - d["lower"]:
            w = math.sin((t - d["raise"]) / d["wave"] * math.pi)
            return {side: ("rel", (up[0] + 0.1 * k * w, up[1], up[2] - 0.015 * k * abs(w)))}
        return {side: ("rel", actor._rest_hand(side))}

    def hand_rot(t, p):
        yaw = actor.body_yaw(p)
        w = math.sin((t - d["raise"]) / d["wave"] * math.pi) if d["raise"] < t < total - d["lower"] else 0.0
        fingers = add((0, 0, 1), mul(left(yaw), s * (0.25 + 0.35 * w)))
        palm = forward(yaw)
        weight = smooth(t / d["raise"]) * (1 - smooth((t - (total - d["lower"])) / d["lower"]))
        return {side: (_hand_frame(fingers, palm), weight)}

    def body(t, p):
        p["chest"] = (0, s * 3 * math.sin(t * 6), -s * 3)
        p[f"shrug.{side}"] = 6 * smooth(t / d["raise"]) * (1 - smooth((t - (total - d["lower"])) / d["lower"]))

    actor.event("wave", hand=side)
    look = (lambda t, p: at) if at else None
    gesture(actor, total, targets, hrot=hand_rot, body=body, look=look,
            grips=lambda t, p: {side: 0.05}, ease=d["raise"])


def point_at(actor, target, side=None, label="point"):
    d = lib.ACTIONS["point"]
    k = actor.k
    side = side or _hand_for(actor, target, actor.yaw)
    total = d["raise"] + d["hold"] + d["lower"]

    def targets(t, p):
        if t < d["raise"] + d["hold"]:
            fk = actor.torso(p)
            sh = fk[f"arm_root.{side}"]
            dirn = norm(sub(target, sh))
            return {side: ("world", add(sh, mul(dirn, actor.rig.arm * 0.95)))}
        return {side: ("rel", actor._rest_hand(side))}

    def hand_rot(t, p):
        fk = actor.torso(p)
        dirn = norm(sub(target, fk[f"arm_root.{side}"]))
        w = smooth(t / d["raise"]) * (1 - smooth((t - d["raise"] - d["hold"]) / d["lower"]))
        return {side: (_hand_frame(dirn, (0, 0, -1)), w)}

    actor.event("point", hand=side)
    gesture(actor, total, targets, hrot=hand_rot, look=target, grips=lambda t, p: {side: 0.1}, ease=d["raise"])


def talk(actor, seconds, at=None, label="talk"):
    """Talking: hands rising to gesture in turn, head nodding and tilting, weight shifting."""
    k = actor.k
    g = lib.ACTIONS["talk"]["gesture"]
    phase = actor.rng.uniform(0, 3)

    def targets(t, p):
        out = {}
        for i, s in enumerate("RL"):
            w = max(0.0, math.sin((t + phase + i * 1.3) / (g * 2) * math.tau))
            out[s] = ("rel", lerp(actor._rest_hand(s), (0.02 * k, 0.28 * k, -0.3 * k + 0.05 * k * math.sin(t * 5 + i)),
                                  w * (0.6 if i else 1.0)))
        return out

    def body(t, p):
        p["head"] = (3 * math.sin(t * 3.1 + phase), 5 * math.sin(t * 1.3), 3 * math.sin(t * 0.9))
        p["neck"] = (2 * math.sin(t * 2.3), 3 * math.sin(t * 0.7 + 1), 0)
        p["chest"] = (1 + math.sin(t * 1.5), 2 * math.sin(t * 0.8), 0)

    actor.event("talk")
    gesture(actor, seconds, targets, body=body, look=(lambda t, p: at) if at else None,
            grips=lambda t, p: {"L": 0.15, "R": 0.15}, ease=0.5)


def phone(actor, seconds=4.0, prop_id=None, label="phone call"):
    """Take the phone from the pocket, hold it to the ear and talk (the other hand gesturing), put it away."""
    d = lib.ACTIONS["phone"]
    k = actor.k
    side = "R"
    world = actor.world
    if prop_id is None or prop_id not in world.props:
        raise Problem("there's no phone to use")
    prop = world.props[prop_id]
    pocket = (0.03 * k, 0.02 * k, -0.62 * k)
    gesture(actor, d["take"], lambda t, p: {side: ("rel", pocket)}, grips=lambda t, p: {side: 0.7 * smooth(t / 0.6)},
            ease=d["take"])
    # the phone appears in the hand at the pocket
    pose = actor.last
    yaw = actor.body_yaw(pose)
    r = _hand_frame((0, 0, 1), mul(left(yaw), 1.0))
    pose[f"hrot.{side}"] = r
    prop["keys"][actor.frame - 1] = (r, pose[f"hand.{side}"])
    prop["visible"][actor.frame - 1] = True
    if actor.frame - 2 >= 0:
        prop["visible"].setdefault(0, False)
    grasp(actor, side, prop_id)

    def ear(t, p):
        fk = actor.torso(p)
        head = fk["head"]
        e = tf_point(head, (-0.11 * k, 0.07 * k, 0.0))   # beside the right ear
        return {side: ("world", add(e, (0, 0, -0.07 * k))), "L": ("rel", actor._rest_hand("L"))}

    def ear_rot(t, p):
        yaw_ = actor.body_yaw(p)
        return {side: (_hand_frame((0, 0, 1), mul(left(yaw_), 1.0)), 1.0)}

    def head_tilt(t, p):
        p["head"] = (2 * math.sin(t * 2.2), 3 * math.sin(t * 0.9), -6)
        p["neck"] = (0, 0, -3)

    gesture(actor, d["raise"], ear, hrot=ear_rot, body=head_tilt, grips=lambda t, p: {side: 0.7}, ease=d["raise"])
    actor.event("on the phone")

    def talking(t, p):
        out = ear(t, p)
        w = max(0.0, math.sin(t / 1.6 * math.tau))
        out["L"] = ("rel", lerp(actor._rest_hand("L"), (0.04 * k, 0.26 * k, -0.3 * k), w))
        return out

    gesture(actor, max(1.0, seconds), talking, hrot=ear_rot, body=head_tilt, grips=lambda t, p: {side: 0.7, "L": 0.2},
            ease=0.2)
    gesture(actor, d["lower"], lambda t, p: {side: ("rel", pocket)}, hrot=ear_rot, grips=lambda t, p: {side: 0.7},
            ease=d["lower"])
    release(actor, side)
    prop["visible"][actor.frame - 1] = False
    gesture(actor, d["put"], lambda t, p: {}, grips=lambda t, p: {side: 0.22}, ease=d["put"],
            hrot=lambda t, p: {side: (ear_rot(t, p)[side][0], 1 - smooth(t / 0.3))})


def jump(actor, distance=0.0, label="jump"):
    """Crouch, swing the arms and spring up (forward by `distance`), tuck the feet in the air, land on both feet
    with the knees absorbing it and stand up again."""
    d = lib.ACTIONS["jump"]
    k = actor.k
    yaw = actor.yaw
    g = 9.81
    h = d["height"] * k
    flight = 2 * math.sqrt(2 * h / g)
    fl = {s: dict(actor.feet[s]) for s in "LR"}
    land = {s: dict(fl[s], x=fl[s]["x"] + forward(yaw)[0] * distance, y=fl[s]["y"] + forward(yaw)[1] * distance)
            for s in "LR"}
    for s in "LR":
        land[s]["z"] = actor.world.foot_ground((land[s]["x"], land[s]["y"], fl[s]["z"]), land[s]["yaw"], k)
    pel = actor.last["pelvis"] if actor.last else (actor.pos[0], actor.pos[1], actor.pelvis_z, yaw, 0, 0)
    stand = pel[2]
    actor.mark()
    phases = [("crouch", d["crouch"]), ("push", d["push"]), ("air", flight), ("land", d["land"]),
              ("recover", d["recover"])]
    actor.event("jump")
    start_rel = dict(actor.hand_rel)
    gz_land = (land["L"]["z"] + land["R"]["z"]) / 2
    for name, dur in phases:
        n = max(2, int(round(dur * FPS)))
        for f in range(1, n + 1):
            u = f / n
            if name == "crouch":
                dz, x_off, lean, arms = -d["dip"] * k * smooth(u), 0.0, 18 * smooth(u), -0.18 * smooth(u)
                feet = fl
                fz = {s: 0.0 for s in "LR"}
            elif name == "push":
                dz, x_off, lean, arms = -d["dip"] * k * (1 - smooth(u)) + 0.06 * k * u, 0.0, 18 * (1 - u), \
                    -0.18 + 0.5 * smooth(u)
                feet = fl
                fz = {s: 0.0 for s in "LR"}
            elif name == "air":
                tt = u * flight
                dz = 0.06 * k + (math.sqrt(2 * g * h) * tt - 0.5 * g * tt * tt)
                x_off, lean, arms = distance * u, 4.0, 0.32 - 0.25 * u
                feet = None
                fz = {s: 0.12 * k * math.sin(math.pi * u) for s in "LR"}
            elif name == "land":
                dz, x_off, lean, arms = -d["dip"] * k * math.sin(math.pi * u * 0.9), distance, 14 * math.sin(
                    math.pi * u), 0.07 * (1 - u)
                feet = land
                fz = {s: 0.0 for s in "LR"}
            else:
                dz, x_off, lean, arms = -0.02 * k * (1 - smooth(u)), distance, 2 * (1 - u), 0.0
                feet = land
                fz = {s: 0.0 for s in "LR"}
            base_z = stand if name in ("crouch", "push") else (lerp(stand, stand + gz_land - fl["L"]["z"], u)
                                                                if name == "air" else stand + gz_land - fl["L"]["z"])
            centre = add((pel[0], pel[1], 0.0), mul(forward(yaw), x_off))
            pose = actor.new_pose((centre[0], centre[1], gz_land if name in ("land", "recover") else fl["L"]["z"], yaw),
                                  (centre[0], centre[1], base_z + dz, yaw, lean * 0.6, 0.0),
                                  spine=(lean * 0.3, 0, 0), chest=(lean * 0.15, 0, 0), neck=(-lean * 0.35, 0, 0))
            for s in "LR":
                if feet is not None:
                    p = feet[s]
                    pose[f"foot.{s}"] = (p["x"], p["y"], p["z"] + lib.ANKLE * k, p["yaw"], 0.0)
                else:   # in the air: the feet follow the body, tucked a little
                    a = lerp((fl[s]["x"], fl[s]["y"], fl[s]["z"]), (land[s]["x"], land[s]["y"], land[s]["z"]), u)
                    pose[f"foot.{s}"] = (a[0], a[1], a[2] + lib.ANKLE * k + dz - 0.06 * k + fz[s], fl[s]["yaw"],
                                         10.0 * math.sin(math.pi * u))
                pose[f"toe.{s}"] = 0.0
            _reach_legs(actor, pose)
            rel = {s: (actor._rest_hand(s)[0] + 0.03, actor._rest_hand(s)[1] + arms * k * 1.4,
                       actor._rest_hand(s)[2] + max(0.0, arms) * 0.8 * k) for s in "LR"}
            if name == "crouch":
                rel = {s: lerp(start_rel[s], rel[s], smooth(u)) for s in "LR"}
            actor.finish_pose(pose, hands=rel)
        if name == "push":
            actor.event("take off")
        if name == "air":
            actor.event("land")
    for s in "LR":
        actor.feet[s] = land[s]
    actor.pos = (actor.last["root"][0], actor.last["root"][1], gz_land)
    actor.pelvis_z = actor.last["pelvis"][2]


def dance(actor, seconds=6.0, label="dance"):
    """Dancing on the beat: stepping side to side (real steps, weight moving onto each foot), hips swaying, arms
    swinging up in turn, head bobbing; each bar a little different."""
    beat = lib.ACTIONS["dance"]["beat"]
    k = actor.k
    yaw = actor.yaw
    centre = ((actor.feet["L"]["x"] + actor.feet["R"]["x"]) / 2, (actor.feet["L"]["y"] + actor.feet["R"]["y"]) / 2,
              (actor.feet["L"]["z"] + actor.feet["R"]["z"]) / 2)
    beats = max(2, int(seconds / beat))
    actor.mark()
    actor.event("dance")
    start_rel = dict(actor.hand_rel)
    for b in range(beats):
        side = "L" if b % 2 == 0 else "R"
        sg = 1.0 if side == "L" else -1.0
        out = 0.16 * k * (1 + 0.25 * actor.rng.uniform(-1, 1))
        dest_c = add(centre, mul(left(yaw), sg * out * 0.5))
        dest = actor._stand_plant(side, add(dest_c, mul(left(yaw), sg * out * 0.5)), yaw)
        other = "R" if side == "L" else "L"
        n = int(beat * FPS)
        src = dict(actor.feet[side])
        pel0 = actor.last["pelvis"] if actor.last else (centre[0], centre[1], actor.pelvis_z, yaw, 0, 0)
        style = b // 4 % 3
        for f in range(1, n + 1):
            v = f / n
            p0 = (src["x"], src["y"], src["z"] + lib.ANKLE * k)
            p1 = (dest["x"], dest["y"], dest["z"] + lib.ANKLE * k)
            p = lerp(p0, p1, smoother(min(1.0, v * 1.6)))
            p = (p[0], p[1], p[2] + 0.06 * k * math.sin(math.pi * min(1.0, v * 1.6)))
            sway = sg * 0.05 * k * smooth(v)
            bounce = -0.035 * k * abs(math.sin(math.pi * v))
            pc = add(centre, mul(left(yaw), sway))
            pose = actor.new_pose((centre[0], centre[1], centre[2], yaw),
                                  (lerp(pel0[0], pc[0], smooth(v)), lerp(pel0[1], pc[1], smooth(v)),
                                   centre[2] + actor.stand_height - 0.03 * k + bounce, yaw + math.radians(sg * 8 *
                                                                                                          smooth(v)),
                                   3.0, -sg * 6 * math.sin(math.pi * v)),
                                  spine=(2, -sg * 6 * smooth(v), sg * 4 * math.sin(math.pi * v)),
                                  chest=(1, -sg * 4, sg * 3), neck=(4 * math.sin(math.pi * v * 2), 0, 0),
                                  head=(3 * math.sin(math.pi * v * 2), sg * 6, -sg * 4))
            pose[f"foot.{side}"] = (p[0], p[1], p[2], src["yaw"], 8 * math.sin(math.pi * min(1.0, v * 1.6)))
            pose[f"toe.{side}"] = 0.0
            o = actor.feet[other]
            pose[f"foot.{other}"] = (o["x"], o["y"], o["z"] + lib.ANKLE * k, o["yaw"], 0.0)
            pose[f"toe.{other}"] = 0.0
            _reach_legs(actor, pose)
            up_side = side if style != 1 else other
            rel = {}
            for s in "LR":
                lift = (0.45 if s == up_side else 0.15) * math.sin(math.pi * v) if style != 2 else 0.25 * abs(
                    math.sin(math.pi * (v + (0.5 if s == "L" else 0))))
                rel[s] = (0.12 * k + 0.08 * k * lift, 0.18 * k, -0.35 * k + lift * 0.45 * k)
            if b == 0:
                rel = {s: lerp(start_rel[s], rel[s], smooth(v)) for s in "LR"}
            actor.finish_pose(pose, hands=rel, grips={"L": 0.5, "R": 0.5})
        actor.feet[side] = dest
        centre = ((actor.feet["L"]["x"] + actor.feet["R"]["x"]) / 2, (actor.feet["L"]["y"] + actor.feet["R"]["y"]) / 2,
                  centre[2])
    actor.pos = centre
    actor.pelvis_z = actor.last["pelvis"][2]


def handshake(actor, other, label="shake hands"):
    """Two actors already facing each other: both right hands meet half way and shake. Both timelines are filled
    from the later of their two current frames."""
    d = lib.ACTIONS["handshake"]
    start = max(actor.frame, other.frame)
    for a in (actor, other):
        if a.frame < start:
            idle(a, (start - a.frame) / FPS)
    meet = lerp(actor.hand_world(actor.last, "R", (0.0, 0.32, -0.3)), other.hand_world(other.last, "R",
                                                                                      (0.0, 0.32, -0.3)), 0.5)
    total = d["reach"] + d["shake"] * 2 * d["shakes"] + d["release"]
    for a in (actor, other):
        def targets(t, p, a=a):
            if t < d["reach"]:
                return {"R": ("world", meet)}
            if t < total - d["release"]:
                return {"R": ("world", add(meet, (0, 0, 0.04 * math.sin((t - d["reach"]) / d["shake"] * math.pi))))}
            return {"R": ("rel", a._rest_hand("R"))}
        a.event("handshake", partner=other.id if a is actor else actor.id)
        gesture(a, total, targets, look=lambda t, p, a=a: (other if a is actor else actor).torso(
            (other if a is actor else actor).last)["head"][1] if (other if a is actor else actor).last else None,
            grips=lambda t, p: {"R": 0.75 if d["reach"] * 0.8 < t < total - d["release"] else 0.22}, ease=d["reach"])


def fight(actor, seconds=4.0, label="fight"):
    """A boxer's guard (fists by the chin, knees soft, weight on the balls of the feet) with jabs and crosses in
    turn: the punching hand drives out from the shoulder as the hips and chest turn into it, the other stays up."""
    k = actor.k
    beat = 0.45
    rng = actor.rng
    combo = [rng.choice("LR") for _ in range(int(seconds / beat))]
    guard = {"L": (-0.08 * k, 0.24 * k, 0.02 * k), "R": (-0.08 * k, 0.2 * k, -0.01 * k)}
    actor.event("fight")

    def targets(t, p):
        i = int(t / beat)
        u = (t % beat) / beat
        out = {s_: ("rel", guard[s_]) for s_ in "LR"}
        if i < len(combo):
            s_ = combo[i]
            ext = math.sin(math.pi * min(1.0, u * 1.6)) if u < 0.65 else 0.0
            g = guard[s_]
            out[s_] = ("rel", (g[0] + 0.06 * k * ext, g[1] + 0.3 * k * ext, g[2] + 0.04 * k * ext))
        return out

    def body(t, p):
        i = int(t / beat)
        u = (t % beat) / beat
        s_ = combo[i] if i < len(combo) else "L"
        turn = (12.0 if s_ == "R" else -8.0) * math.sin(math.pi * min(1.0, u * 1.6))
        p["pelvis"] = (p["pelvis"][0], p["pelvis"][1], p["pelvis"][2] - 0.06 * k + 0.012 * k * math.sin(t * 9),
                       p["pelvis"][3] + math.radians(turn * 0.4), 6.0, 0.0)
        p["spine"] = (6.0, turn * 0.5, 0)
        p["chest"] = (4.0, turn * 0.6, 0)
        p["neck"] = (-6.0, -turn * 0.3, 0)
        p["head"] = (-4.0, -turn * 0.3, 0)

    gesture(actor, seconds, targets, body=body, grips=lambda t, p: {"L": 0.95, "R": 0.95}, ease=0.35)
    idle(actor, 0.4)


def work(actor, seconds=4.0, label="work"):
    """Working with the hands: typing at a surface when seated (hands low in front, small quick moves, head
    down to the screen), hammering when standing (the hand rising and striking down on a beat)."""
    k = actor.k
    actor.event("work")
    if actor.seated:
        def targets(t, p):
            return {s_: ("rel", (-0.04 * k, 0.33 * k, -0.33 * k + 0.012 * k * abs(math.sin(t * 11 + (1.7 if s_ == "L"
                                                                                                     else 0)))))
                    for s_ in "LR"}

        def body(t, p):
            p["spine"] = (8.0, 0, 0)
            p["neck"] = (12.0, 2 * math.sin(t * 0.8), 0)
            p["head"] = (6.0, 0, 0)
        gesture(actor, seconds, targets, body=_combine(_seated_body(actor, actor.last["pelvis"]), body),
                grips=lambda t, p: {"L": 0.3, "R": 0.3}, ease=0.5)
    else:
        def targets(t, p):
            u = (t % 0.7) / 0.7
            lift = smooth(u / 0.6) if u < 0.6 else 1.0 - ease_in((u - 0.6) / 0.4)   # raise, then strike down
            return {"R": ("rel", (0.02 * k, 0.32 * k, -0.42 * k + 0.32 * k * max(0.0, lift))),
                    "L": ("rel", (0.0, 0.3 * k, -0.45 * k))}

        def body(t, p):
            p["spine"] = (14.0, -4.0, 0)
            p["chest"] = (6.0, -3.0, 0)
            p["neck"] = (10.0, 0, 0)
        gesture(actor, seconds, targets, body=body, grips=lambda t, p: {"R": 0.9, "L": 0.6}, ease=0.5)


def _combine(*fns):
    def body(t, p):
        for f in fns:
            f(t, p)
    return body


# ---------- the script ----------

ACTION_NAMES = ("walk", "run", "walk_to", "turn", "face", "idle", "wait", "open_door", "enter", "close_door",
                "sit", "stand", "eat", "drink", "pick_up", "put_down", "carry", "wave", "point", "talk", "phone",
                "jump", "dance", "handshake", "fight", "work")


def solve(script, ground=None, seed=7, clearance=None):
    """Every actor's frames for `script`: {"fps", "frames", "actors": {id: {"poses", "bones", "events"}},
    "doors": {id: {frame: angle}}, "props": {id: {frame: (R, t)}}, "timeline": [...]}."""
    world = World(ground, script.get("doors", ()), script.get("props", ()), script.get("seats", ()),
                  script.get("tables", ()), clearance)
    actors = {}
    for spec in script.get("actors", ()):
        actors[spec["id"]] = Actor(dict(spec, seed=spec.get("seed", seed)), world)
    timeline = []
    for item in script.get("script", ()):
        actor = actors.get(item.get("actor") or next(iter(actors), None))
        if actor is None:
            raise Problem("the script has no character to animate")
        if item.get("after"):
            other = actors.get(item["after"])
            if other is not None and other.frame > actor.frame:
                idle(actor, (other.frame - actor.frame) / FPS)
        if not actor.poses:   # a moment of standing before anything, so the first frame is a settled pose
            idle(actor, 0.25)
        f0 = actor.frame
        _run(actor, actors, world, item)
        timeline.append({"actor": actor.id, "do": item["do"], "start": f0, "end": actor.frame,
                         "label": item.get("label") or item["do"]})
    end = max([a.frame for a in actors.values()] + [0])
    end = max(end, max([max(d.angles) + 1 for d in world.doors.values() if d.angles] + [0]))
    for a in actors.values():   # everyone stands (breathing) until the last one finishes
        if a.frame < end + int(0.6 * FPS):
            idle(a, (end + int(0.6 * FPS) - a.frame) / FPS)
    frames = max(a.frame for a in actors.values()) if actors else end
    out = {"fps": FPS, "frames": frames, "actors": {}, "doors": {}, "props": {}, "timeline": timeline}
    for a in actors.values():
        _crossfade(a)
        _smooth_pelvis(a)
        _slew_grips(a)
        bones, influences = compose(a)
        out["actors"][a.id] = {"template": a.template, "height": a.height, "bones": bones, "influences": influences,
                               "events": a.events, "poses": a.poses}
    for d in world.doors.values():
        out["doors"][d.id] = {f: d.angle_at(f) for f in range(frames)} if d.angles else {}
    for pid, p in world.props.items():
        out["props"][pid] = {"start": p["start"], "keys": dict(p["keys"]), "visible": dict(p["visible"]),
                             "kind": p["kind"]}
    return out


def _run(actor, actors, world, item):
    do = item["do"]
    if do in ("walk", "walk_to", "run"):
        path = item.get("path") or [item["to"]]
        locomote(actor, path, "run" if do == "run" else item.get("gait", "walk"), stop=item.get("stop", True),
                 speed=item.get("speed"))
        if item.get("face") is not None:
            turn(actor, math.radians(item["face"]))
    elif do in ("turn", "face"):
        if "yaw" in item:
            turn(actor, math.radians(item["yaw"]))
        else:
            t = item["toward"]
            turn(actor, yaw_of(sub((t[0], t[1], 0), (actor.pos[0], actor.pos[1], 0))))
    elif do in ("idle", "wait"):
        idle(actor, item.get("seconds", 1.0), look=item.get("look"))
    elif do in ("open_door", "enter"):
        open_door(actor, item["door"], enter=item.get("enter", True))
    elif do == "close_door":
        close_door(actor, item["door"])
    elif do == "sit":
        sit(actor, item["seat"])
    elif do == "stand":
        stand_up(actor)
    elif do == "eat":
        eat(actor, item["prop"], bites=item.get("bites"))
    elif do == "drink":
        drink(actor, item["prop"])
    elif do == "pick_up":
        pick_up(actor, item["prop"])
    elif do == "put_down":
        put_down(actor, item.get("at"))
    elif do == "carry":
        if not (actor.holding["L"] or actor.holding["R"]):
            pick_up(actor, item["prop"])
        locomote(actor, item.get("path") or [item["to"]], "slow")
    elif do == "wave":
        wave(actor, item.get("hand", "R"), at=item.get("at"))
    elif do == "point":
        point_at(actor, tuple(item["at"]))
    elif do == "talk":
        talk(actor, item.get("seconds", 3.0), at=item.get("at"))
    elif do == "phone":
        phone(actor, item.get("seconds", 4.0), item.get("prop"))
    elif do == "jump":
        jump(actor, item.get("distance", 0.0))
    elif do == "dance":
        dance(actor, item.get("seconds", 6.0))
    elif do == "fight":
        fight(actor, item.get("seconds", 4.0))
    elif do == "work":
        work(actor, item.get("seconds", 4.0))
    elif do == "handshake":
        other = actors.get(item.get("with"))
        if other is None:
            raise Problem("a handshake needs a second character")
        handshake(actor, other)
    else:
        raise Problem(f"I don't know how to animate “{do}”")


_FADE_TORSO = ("spine", "chest", "neck", "head")


def _crossfade(actor, seconds=0.3):
    """Where one motion hands over to the next (a walk ending, a reach starting), the body must not jump. The
    frame after a boundary is predicted from the two before it (the motion keeps its velocity); the gap between that
    and what the new motion says is added back and decays smoothly to nothing — so values and velocities stay
    continuous and nothing snaps. Feet are left alone (they are planted), and so is a hand holding on to something
    on both sides of the boundary (it must stay on the handle)."""
    poses = actor.poses
    window = max(2, int(seconds * FPS))
    for b in sorted(set(actor.boundaries)):
        if b < 2 or b >= len(poses):
            continue
        p0, p1, p2 = poses[b - 2], poses[b - 1], poses[b]
        fades = {}

        def gap(key, index=None, angle=False):
            a0 = p0[key] if index is None else p0[key][index]
            a1 = p1[key] if index is None else p1[key][index]
            a2 = p2[key] if index is None else p2[key][index]
            if angle:
                predicted = a1 + wrap(a1 - a0)
                return wrap(predicted - a2)
            return 2 * a1 - a0 - a2

        for i in range(6):
            fades[("pelvis", i)] = gap("pelvis", i, angle=(i == 3))
        for i in range(4):
            fades[("root", i)] = gap("root", i, angle=(i == 3))
        for name in _FADE_TORSO:
            for i in range(3):
                fades[(name, i)] = gap(name, i)
        for s in "LR":
            held = p1.get(f"hrot_w.{s}", 0.0) > 0.5 and p2.get(f"hrot_w.{s}", 0.0) > 0.5
            if not held:
                for i in range(3):
                    fades[(f"hand.{s}", i)] = gap(f"hand.{s}", i)
        # a gap the size of normal motion isn't a jump: only fade real discontinuities
        limits = {"pelvis": (0.004, math.radians(0.6)), "root": (0.004, math.radians(0.6))}
        for j in range(window):
            if b + j >= len(poses):
                break
            w = 1.0 - smooth(j / window)
            pose = poses[b + j]
            for (key, i), g in fades.items():
                lim = limits.get(key, (0.004, 0.4))
                small = lim[1] if (key in ("pelvis", "root") and i == 3) or key in _FADE_TORSO else lim[0]
                if abs(g) <= small:
                    continue
                values = list(pose[key])
                values[i] += g * w
                pose[key] = tuple(values)
            pose.pop("_fk", None)
            _reach_legs(actor, pose)


def _smooth_pelvis(actor):
    """A light low-pass over the pelvis height (never above what the legs can reach) and over head look-at weight,
    so no frame jumps."""
    # Where a leg couldn't reach, _reach_legs lowered the pelvis just there: a sharp dip. Spread each lowering over
    # the frames around it (widen, then smooth) so the body sinks into it and rises out of it; the spread is never
    # less than what was needed, and the legs are checked again after.
    poses = actor.poses
    drops = [p.pop("_drop", 0.0) for p in poses]
    base = [p["pelvis"][2] + d for p, d in zip(poses, drops)]
    wide = [max(drops[max(0, i - 4):i + 5]) for i in range(len(drops))]
    spread = [max(a, b) for a, b in zip(_gauss(wide, 2.5), drops)]
    zs = _gauss([b - d for b, d in zip(base, spread)], 1.0)
    for p, z in zip(poses, zs):
        px, py, _, yaw, pitch, roll = p["pelvis"]
        p["pelvis"] = (px, py, z, yaw, pitch, roll)
        p.pop("_fk", None)
        _reach_legs(actor, p)
        p.pop("_drop", None)
    # look-at targets fade in and out instead of switching: the weight is smoothed, and frames without a target
    # borrow the nearest one (before or after), so the fade-in already looks where the look is going
    _fill_nearest(actor.poses, "look")
    w = [1.0 if p.get("_had_look") else 0.0 for p in actor.poses]
    for p, wi in zip(actor.poses, _gauss(w, FPS * 0.15)):
        p["look_w"] = wi
    # a hand control keeps the last (or next) orientation it was given while nothing needs it (influence 0), so it
    # never flips between a grasp's orientation and a default one
    for s in "LR":
        _fill_rotations(actor.poses, f"hrot.{s}")


def _slew_grips(actor, per_frame=0.09):
    """Fingers close and open at a hand's pace: no grip changes more than `per_frame` between two frames (an
    action ending with a fist and the next one relaxed would otherwise flick them open in one frame)."""
    for s in "LR":
        prev = None
        for p in actor.poses:
            g = p.get(f"grip.{s}", 0.22)
            if prev is not None:
                g = clamp(g, prev - per_frame, prev + per_frame)
            p[f"grip.{s}"] = g
            prev = g


def _fill_rotations(poses, key):
    """Frames without the rotation `key` turn smoothly from the one before the gap to the one after it (held at
    the ends), so the control never flips — even while nothing uses it."""
    known = [i for i, p in enumerate(poses) if p.get(key) is not None]
    if not known:
        return
    for i in range(known[0]):
        poses[i][key] = poses[known[0]][key]
    for i in range(known[-1] + 1, len(poses)):
        poses[i][key] = poses[known[-1]][key]
    for a, b in zip(known, known[1:]):
        if b - a > 1:
            ra, rb = poses[a][key], poses[b][key]
            for i in range(a + 1, b):
                poses[i][key] = slerp_mat(ra, rb, smooth((i - a) / (b - a)))


def _fill_nearest(poses, key):
    """Frames without `key` take the nearest frame's value; `_had_<key>` remembers which frames really had one."""
    had = [p.get(key) is not None for p in poses]
    if key == "look":
        for p, h in zip(poses, had):
            p["_had_look"] = h
    if not any(had):
        return
    prev = None
    nearest = [None] * len(poses)
    dist = [10 ** 9] * len(poses)
    for i, p in enumerate(poses):
        if had[i]:
            prev = i
        if prev is not None:
            nearest[i], dist[i] = prev, i - prev
    nxt = None
    for i in range(len(poses) - 1, -1, -1):
        if had[i]:
            nxt = i
        if nxt is not None and nxt - i < dist[i]:
            nearest[i], dist[i] = nxt, nxt - i
    for i, p in enumerate(poses):
        if not had[i] and nearest[i] is not None:
            p[key] = poses[nearest[i]][key]


def _look(actor, pose):
    """Neck and head turned toward pose["look"] (weighted), within what a neck can do."""
    target = pose.get("look")
    w = pose.get("look_w", 0.0)
    if target is None or w <= 0.01:
        return
    fk = actor.torso(pose)
    chest_rot = fk["chest"][0]
    head_pos = fk["head"][1]
    d = sub(tuple(target), head_pos)
    # direction in the chest's frame: its Z is forward, X left, Y up
    local = mat_vec(transpose(chest_rot), d)
    yaw = math.degrees(math.atan2(local[0], local[2]))
    pitch = math.degrees(math.atan2(local[1], math.hypot(local[0], local[2])))
    yaw = clamp(yaw, -70, 70) * w
    pitch = clamp(pitch, -28, 25) * w
    nb, nt, nl = pose["neck"]
    hb, ht, hl = pose["head"]
    pose["neck"] = (nb - pitch * 0.4, nt + yaw * 0.45, nl)
    pose["head"] = (hb - pitch * 0.6, ht + yaw * 0.55, hl)
    pose.pop("_fk", None)


def compose(actor):
    """Per-frame bone transforms for Blender: {bone: [(location, quaternion) per frame]} for the controls and the
    FK bones, and {constraint: [influence per frame]}."""
    rig = actor.rig
    bones = {n: [] for n in lib.CONTROLS + lib.FK_BONES}
    infl = {"hand_rot.L": [], "hand_rot.R": []}
    for pose in actor.poses:
        pose.pop("_fk", None)
        _look(actor, pose)
        fk = actor.torso(pose)
        rx, ry, rz, ryaw = pose["root"]
        root_w = rig.root_world(rx, ry, rz, ryaw)
        root_basis = tf_mul(tf_inv(rig.rest["root"]), root_w)
        bones["root"].append((root_basis[1], quat(root_basis[0])))
        hb = rig.basis_under_root(root_w, "hips", fk["hips"])
        bones["hips"].append((hb[1], quat(hb[0])))
        for name in ("spine", "chest", "neck", "head"):
            bones[name].append(((0.0, 0.0, 0.0), quat(local_rot(*pose[name]))))
        for s in "LR":
            bones[f"shoulder.{s}"].append(((0.0, 0.0, 0.0), quat(shoulder_rot(s, pose.get(f"shrug.{s}", 0.0)))))
            x, y, z, fyaw, fpitch = pose[f"foot.{s}"]
            fw = (rig.oriented(f"foot_ik.{s}", foot_rot(fyaw, fpitch)), (x, y, z))
            # foot_rot is relative to yaw 0 facing -Y: the rest foot already points that way
            fb = rig.basis_under_root(root_w, f"foot_ik.{s}", fw)
            bones[f"foot_ik.{s}"].append((fb[1], quat(fb[0])))
            bones[f"toe.{s}"].append(((0.0, 0.0, 0.0), quat(rot_axis((1, 0, 0), math.radians(pose.get(f"toe.{s}",
                                                                                                       0.0))))))
            hand = pose[f"hand.{s}"]
            hr = pose.get(f"hrot.{s}")
            hw = (hr if hr is not None else rig.oriented(f"hand_ik.{s}", rot_z(actor.body_yaw(pose))), tuple(hand))
            hb_ = rig.basis_under_root(root_w, f"hand_ik.{s}", hw)
            bones[f"hand_ik.{s}"].append((hb_[1], quat(hb_[0])))
            infl[f"hand_rot.{s}"].append(clamp(pose.get(f"hrot_w.{s}", 0.0), 0.0, 1.0))
            # poles: knees forward over the foot, elbows back and out
            hip = fk[f"hip.{s}"]
            ankle = (x, y, z)
            knee_p = add(add(lerp(hip, ankle, 0.5), mul(forward(fyaw), 0.6 * actor.k)),
                         mul(left(fyaw), (0.04 if s == "L" else -0.04) * actor.k))
            kw = (rig.rest[f"knee_pole.{s}"][0], knee_p)
            kb = rig.basis_under_root(root_w, f"knee_pole.{s}", kw)
            bones[f"knee_pole.{s}"].append((kb[1], quat(kb[0])))
            sh = fk[f"arm_root.{s}"]
            byaw = actor.body_yaw(pose)
            side = 1.0 if s == "L" else -1.0
            elbow = pose.get(f"elbow.{s}") or add(add(add(sh, mul(left(byaw), 0.28 * side * actor.k)),
                                                      mul(forward(byaw), -0.45 * actor.k)), (0, 0, -0.22 * actor.k))
            ew = (rig.rest[f"elbow_pole.{s}"][0], elbow)
            eb = rig.basis_under_root(root_w, f"elbow_pole.{s}", ew)
            bones[f"elbow_pole.{s}"].append((eb[1], quat(eb[0])))
            g = clamp(pose.get(f"grip.{s}", 0.22), 0.0, 1.0)
            bones[f"fingers1.{s}"].append(((0.0, 0.0, 0.0), quat(rot_axis((1, 0, 0), math.radians(70 * g)))))
            bones[f"fingers2.{s}"].append(((0.0, 0.0, 0.0), quat(rot_axis((1, 0, 0), math.radians(80 * g)))))
            bones[f"thumb1.{s}"].append(((0.0, 0.0, 0.0), quat(rot_axis((1, 0, 0), math.radians(25 * g)))))
            bones[f"thumb2.{s}"].append(((0.0, 0.0, 0.0), quat(rot_axis((1, 0, 0), math.radians(35 * g)))))
            # the wrist trails the arm's swing a little when the hand is free
            bones[f"hand.{s}"].append(((0.0, 0.0, 0.0), quat(rot_axis((1, 0, 0), math.radians(-8.0)))))
    return bones, infl


# ---------- checks that need no Blender ----------

def foot_slide(result, actor_id, threshold=0.004):
    """Planted feet that move: for each foot, the largest drift of its contact point (heel, ball or the whole
    sole) over frames where it should be planted (flat on the ground: pitch 0 and the ankle at plant height)."""
    poses = result["actors"][actor_id]["poses"]
    worst = 0.0
    for s in "LR":
        prev = None
        for p in poses:
            x, y, z, yaw, pitch = p[f"foot.{s}"]
            if abs(pitch) < 0.5:
                if prev is not None and abs(prev[3] - pitch) < 0.5:
                    worst = max(worst, dist2((x, y), prev[:2]))
                prev = (x, y, z, pitch)
            else:
                prev = None
    return worst


def contact_heights(result, actor_id, ground):
    """(lowest, highest) gap between a foot's lowest contact point and the ground, over frames where the foot is
    meant to be on it."""
    poses = result["actors"][actor_id]["poses"]
    lo, hi = 1e9, -1e9
    for p in poses:
        for s in "LR":
            x, y, z, yaw, pitch = p[f"foot.{s}"]
            pts = contact_points((x, y, z), yaw, pitch, p.get(f"toe.{s}", 0.0))
            low = min(pts.values(), key=lambda q: q[2])
            g = ground(low[0], low[1], low[2])
            gap = low[2] - g
            if abs(pitch) < 0.5 or gap < 0.02:
                lo = min(lo, gap)
                hi = max(hi, gap if abs(pitch) < 0.5 else lo)
    return lo, hi


def max_jump(result, actor_id):
    """The largest frame-to-frame change of any control position (m) and FK rotation (degrees): snapping."""
    bones = result["actors"][actor_id]["bones"]
    worst_pos, worst_rot, where = 0.0, 0.0, None
    for name, frames in bones.items():
        for i in range(1, len(frames)):
            (l0, q0), (l1, q1) = frames[i - 1], frames[i]
            dp = length(sub(l1, l0))
            dq = abs(sum(a * b for a, b in zip(q0, q1)))
            ang = math.degrees(2 * math.acos(clamp(dq, -1.0, 1.0)))
            if dp > worst_pos:
                worst_pos, where = dp, (name, i)
            worst_rot = max(worst_rot, ang)
    return worst_pos, worst_rot, where
