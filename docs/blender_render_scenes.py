import bpy, bmesh, math, sys, os
from mathutils import Vector

SCENE = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "hero"
OUT = "/home/claude/cad/render/out"
os.makedirs(OUT, exist_ok=True)
S = 0.01  # 1 mm = 0.01 units

# ---------------- reset ----------------
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = int(os.environ.get("SAMPLES", "64"))
sc.cycles.use_adaptive_sampling = True
sc.cycles.adaptive_threshold = 0.03
sc.cycles.use_denoising = True
try:
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
except Exception:
    pass
sc.cycles.max_bounces = 6
sc.render.resolution_x = int(os.environ.get("RX", "1600"))
sc.render.resolution_y = int(os.environ.get("RY", "1000"))
sc.render.film_transparent = False
sc.view_settings.view_transform = "AgX"
sc.view_settings.look = "AgX - Medium High Contrast"
sc.render.image_settings.file_format = "JPEG"
sc.render.image_settings.quality = 88

world = bpy.data.worlds.new("w"); sc.world = world; world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.004, 0.005, 0.006, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0

# ---------------- materials ----------------
def mat(name, color, rough=0.4, metal=0.0, coat=0.0, aniso=0.0, emit=None, emit_strength=0.0, sss=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if coat: b.inputs["Coat Weight"].default_value = coat
    if aniso: b.inputs["Anisotropic"].default_value = aniso
    if sss:
        b.inputs["Subsurface Weight"].default_value = sss
        b.inputs["Subsurface Radius"].default_value = (0.3, 0.3, 0.3)
        b.inputs["Subsurface Scale"].default_value = 0.02
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = emit_strength
    return m

M = dict(
    wrap=mat("wrap", (0.012, 0.07, 0.25), 0.3, coat=0.4),
    alu=mat("alu", (0.70, 0.71, 0.73), 0.38, 1.0, aniso=0.6),
    lid=mat("lid", (0.42, 0.43, 0.45), 0.5, 1.0),
    alu_dark=mat("alu_dark", (0.03, 0.032, 0.035), 0.42, 1.0),
    nickel=mat("nickel", (0.72, 0.70, 0.66), 0.22, 1.0),
    copper=mat("copper", (0.93, 0.55, 0.35), 0.25, 1.0),
    steel=mat("steel", (0.55, 0.56, 0.58), 0.35, 1.0),
    label=mat("label", (0.55, 0.56, 0.57), 0.55),
    vent=mat("vent", (0.25, 0.26, 0.27), 0.35, 1.0),
    floor=mat("floor", (0.012, 0.013, 0.015), 0.38),
    pla_light=mat("pla_light", (0.36, 0.37, 0.37), 0.45, sss=0.05),
    pla_white=mat("pla_white", (0.86, 0.86, 0.84), 0.38, sss=0.08),
    pla_dark=mat("pla_dark", (0.025, 0.027, 0.03), 0.45),
    pcb=mat("pcb", (0.01, 0.20, 0.17), 0.30, coat=0.4),
    chip=mat("chip", (0.01, 0.01, 0.012), 0.35),
    gold=mat("gold", (1.0, 0.76, 0.33), 0.25, 1.0),
    black_plastic=mat("black_plastic", (0.008, 0.008, 0.009), 0.32, coat=0.2),
    glass=mat("glass", (0.02, 0.02, 0.03), 0.02, coat=1.0),
    led=mat("led", (0.9, 0.9, 1.0), 0.3, emit=(0.6, 0.8, 1.0), emit_strength=3.0),
    white_conn=mat("white_conn", (0.85, 0.84, 0.80), 0.45),
)

def link(o, m):
    o.data.materials.clear(); o.data.materials.append(m); return o

def cube(name, x0, x1, y0, y1, z0, z1, m, bevel=0.0, seg=3):
    bpy.ops.mesh.primitive_cube_add(size=1, location=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    o = bpy.context.object; o.name = name; o.scale = (x1 - x0, y1 - y0, z1 - z0)
    bpy.ops.object.transform_apply(scale=True)
    if bevel:
        b = o.modifiers.new("bev", "BEVEL"); b.width = bevel; b.segments = seg; b.limit_method = "ANGLE"
    bpy.ops.object.shade_smooth() if bevel else None
    return link(o, m)

def cyl(name, x, y, z0, h, r, m, verts=48, axis="Z"):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=h)
    o = bpy.context.object; o.name = name
    if axis == "Z": o.location = (x, y, z0 + h / 2)
    elif axis == "Y":
        o.rotation_euler = (math.radians(90), 0, 0); o.location = (x, y + h / 2, z0)
    bpy.ops.object.shade_smooth()
    return link(o, m)

def area(name, loc, target, size, energy, color=(1, 1, 1), shape="RECTANGLE", sy=None):
    l = bpy.data.lights.new(name, "AREA"); l.energy = energy; l.color = color; l.shape = shape
    l.size = size; l.size_y = sy or size
    o = bpy.data.objects.new(name, l); sc.collection.objects.link(o); o.location = loc
    d = Vector(target) - Vector(loc); o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return o

def camera(loc, target, lens=50, fstop=None, focus=None):
    c = bpy.data.cameras.new("cam"); c.lens = lens
    o = bpy.data.objects.new("cam", c); sc.collection.objects.link(o); o.location = loc
    d = Vector(target) - Vector(loc); o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    if fstop:
        c.dof.use_dof = True; c.dof.aperture_fstop = fstop
        c.dof.focus_distance = focus or d.length
    sc.camera = o; return o

def floor(z=0.0, size=60):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, z)); return link(bpy.context.object, M["floor"])

# ---------------- realistic EV module ----------------
CT, CL, CH = 0.27, 1.48, 0.93   # cell thickness (x), length (y), wrap height (z) in units (x100 mm)
PADT = 0.012

def swell_mesh(o, amount):
    """push the two large faces (+x/-x) and lid outward with a smooth dome profile"""
    me = o.data
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=14, use_grid_fill=True)
    cx = sum(v.co.x for v in bm.verts) / len(bm.verts)
    xs = [v.co.x for v in bm.verts]; ys = [v.co.y for v in bm.verts]; zs = [v.co.z for v in bm.verts]
    xmin, xmax, ymin, ymax, zmin, zmax = min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)
    for v in bm.verts:
        fy = math.sin(math.pi * (v.co.y - ymin) / (ymax - ymin))
        fz = math.sin(math.pi * (v.co.z - zmin) / (zmax - zmin))
        side = (v.co.x - cx) / ((xmax - xmin) / 2)
        v.co.x += amount * side * fy * max(fz, 0) ** 0.8
        if v.co.z > zmax - 1e-6:
            fx = math.cos(math.pi / 2 * side)
            v.co.z += 0.0 * fy * fx
    bm.to_mesh(me); bm.free(); me.update()

def build_module(n=6, swollen=None, swell=0.03):
    xs = []
    total = n * CT + (n - 1) * PADT
    x0 = -total / 2
    zb = 0.06  # sits on cooling plate
    # cooling plate with coolant ports
    cube("coldplate", x0 - 0.10, x0 + total + 0.10, -CL / 2 - 0.08, CL / 2 + 0.08, 0.0, zb, M["alu"], bevel=0.006)
    for yy in (-0.35, 0.35):
        cyl("port", x0 - 0.10 - 0.08, yy, zb / 2 - 0.0, 0.08, 0.022, M["alu"], axis="Z").rotation_euler = (0, math.radians(90), 0)
    for i in range(n):
        x = x0 + i * (CT + PADT); xs.append(x + CT / 2)
        body = cube(f"cell{i}", x, x + CT, -CL / 2, CL / 2, zb, zb + CH, M["wrap"], bevel=0.012 if swollen != i else 0.0)
        if swollen == i:
            swell_mesh(body, swell)
            b = body.modifiers.new("bev", "BEVEL"); b.width = 0.01; b.segments = 2; b.limit_method = "ANGLE"
            bpy.ops.object.shade_smooth()
        lid_z = zb + CH
        cube(f"lid{i}", x + 0.004, x + CT - 0.004, -CL / 2 + 0.004, CL / 2 - 0.004, lid_z - 0.004, lid_z + 0.012, M["lid"], bevel=0.004)
        # white side label
        cube(f"lab{i}", x + 0.06, x + CT - 0.06, -CL / 2 - 0.0015, -CL / 2 + 0.0005, zb + 0.36, zb + 0.52, M["label"])
        # terminals
        for ty, m in ((-0.52, M["alu"]), (0.52, M["copper"])):
            cube(f"term{i}", x + 0.035, x + CT - 0.035, ty - 0.12, ty + 0.12, lid_z + 0.012, lid_z + 0.045, m, bevel=0.006)
        # vent
        cyl(f"vent{i}", x + CT / 2, 0.0, lid_z + 0.012, 0.004, 0.055, M["vent"])
        # compression pad
        if i < n - 1:
            cube(f"pad{i}", x + CT, x + CT + PADT, -CL / 2 + 0.03, CL / 2 - 0.03, zb + 0.02, zb + CH - 0.02, M["alu_dark"])
    # busbars (series: alternate ends)
    for i in range(n - 1):
        ty = -0.52 if i % 2 == 0 else 0.52
        xa, xb = xs[i] - 0.09, xs[i + 1] + 0.09
        top = zb + CH + 0.045
        cube(f"bus{i}", xa, xb, ty - 0.10, ty + 0.10, top, top + 0.012, M["nickel"], bevel=0.004)
    # end plates and steel straps
    for xe in (x0 - 0.06, x0 + total):
        cube("endplate", xe, xe + 0.06, -CL / 2 - 0.03, CL / 2 + 0.03, zb, zb + CH + 0.03, M["alu_dark"], bevel=0.008)
    for zz in (zb + 0.18, zb + CH - 0.22):
        for yy in (-CL / 2 - 0.035, CL / 2 + 0.005):
            cube("strap", x0 - 0.065, x0 + total + 0.065, yy, yy + 0.03, zz, zz + 0.07, M["steel"], bevel=0.004)
    return xs, total

def studio_lights(scale=1.0, warm=True):
    area("key", (-4 * scale, -5 * scale, 5 * scale), (0, 0, 0.4), 4 * scale, 950 * scale ** 2, (1.0, 0.96, 0.92))
    area("rim", (3.5 * scale, 4.5 * scale, 2.5 * scale), (0, 0, 0.5), 2.5 * scale, 1800 * scale ** 2, (1.0, 0.58, 0.32) if warm else (0.6, 0.8, 1.0))
    area("fill", (5 * scale, -3 * scale, 1.5 * scale), (0, 0, 0.4), 3 * scale, 380 * scale ** 2, (0.55, 0.72, 1.0))
    area("top", (0, 0, 7 * scale), (0, 0, 0), 6 * scale, 40 * scale ** 2, (1, 1, 1))

def thermal_materials(xs, total):
    """replace materials with an ironbow false-colour heat map: hot on the -x end"""
    m = bpy.data.materials.new("thermal"); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); em = nt.nodes.new("ShaderNodeEmission"); em.inputs[1].default_value = 0.85
    geo = nt.nodes.new("ShaderNodeNewGeometry"); sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    mr = nt.nodes.new("ShaderNodeMapRange"); mr.inputs[1].default_value = -total / 2 - 0.1; mr.inputs[2].default_value = total / 2 + 0.1
    mr.inputs[3].default_value = 0.80; mr.inputs[4].default_value = 0.10
    noise = nt.nodes.new("ShaderNodeTexNoise"); noise.inputs["Scale"].default_value = 3.0
    mix = nt.nodes.new("ShaderNodeMath"); mix.operation = "MULTIPLY_ADD"; mix.inputs[1].default_value = 0.12
    zf = nt.nodes.new("ShaderNodeMath"); zf.operation = "MULTIPLY"; zf.inputs[1].default_value = 0.10
    add = nt.nodes.new("ShaderNodeMath"); add.operation = "ADD"
    ramp = nt.nodes.new("ShaderNodeValToRGB"); cr = ramp.color_ramp
    cols = [(0.0, (0.02, 0.0, 0.08)), (0.25, (0.25, 0.0, 0.45)), (0.5, (0.85, 0.12, 0.25)), (0.72, (1.0, 0.45, 0.02)), (0.9, (1.0, 0.85, 0.2)), (1.0, (1.0, 1.0, 0.8))]
    cr.elements[0].position, cr.elements[0].color = cols[0][0], (*cols[0][1], 1)
    cr.elements[1].position, cr.elements[1].color = cols[-1][0], (*cols[-1][1], 1)
    for p, c in cols[1:-1]:
        e = cr.elements.new(p); e.color = (*c, 1)
    L = nt.links
    L.new(geo.outputs["Position"], sep.inputs[0]); L.new(sep.outputs[0], mr.inputs[0])
    L.new(noise.outputs[0], mix.inputs[0]); L.new(mr.outputs[0], mix.inputs[2])
    L.new(sep.outputs[2], zf.inputs[0]); L.new(mix.outputs[0], add.inputs[0]); L.new(zf.outputs[0], add.inputs[1])
    L.new(add.outputs[0], ramp.inputs[0]); L.new(ramp.outputs[0], em.inputs[0]); L.new(em.outputs[0], out.inputs[0])
    for o in sc.objects:
        if o.type == "MESH" and o.name.split(".")[0] not in ("Plane",):
            o.data.materials.clear(); o.data.materials.append(m)

# ---------------- station (our printed rig) ----------------
def import_stl(path, m):
    bpy.ops.wm.stl_import(filepath=path)
    o = bpy.context.selected_objects[0]; o.scale = (S, S, S)
    bpy.ops.object.transform_apply(scale=True)
    bpy.ops.object.shade_auto_smooth(angle=math.radians(35)) if hasattr(bpy.ops.object, "shade_auto_smooth") else None
    return link(o, m)

def board(x0, y0, w, d, z, kind):
    cube("pcb", x0 * S, (x0 + w) * S, y0 * S, (y0 + d) * S, z * S, (z + 1.6) * S, M["pcb"], bevel=0.0015)
    zt = (z + 1.6) * S
    if kind == "uno":
        cube("hdr", (x0 + 17) * S, (x0 + 66) * S, (y0 + 1.3) * S, (y0 + 3.8) * S, zt, zt + 0.085, M["chip"])
        cube("hdr", (x0 + 26) * S, (x0 + 66) * S, (y0 + 49.5) * S, (y0 + 52) * S, zt, zt + 0.085, M["chip"])
        for k in range(18):
            cube("pin", (x0 + 18 + k * 2.7) * S, (x0 + 18.7 + k * 2.7) * S, (y0 + 2.2) * S, (y0 + 2.9) * S, zt + 0.085, zt + 0.087, M["gold"])
        cube("soc", (x0 + 26) * S, (x0 + 40) * S, (y0 + 16) * S, (y0 + 30) * S, zt, zt + 0.014, M["steel"], bevel=0.001)
        cube("mcu", (x0 + 8) * S, (x0 + 15) * S, (y0 + 30) * S, (y0 + 37) * S, zt, zt + 0.01, M["chip"])
        cube("usbc", (x0 - 1.2) * S, (x0 + 7) * S, (y0 + 22.5) * S, (y0 + 31.5) * S, zt, zt + 0.032, M["steel"], bevel=0.008)
        for r in range(8):
            for c in range(13):
                cube("led", (x0 + 44 + c * 1.4) * S, (x0 + 44.7 + c * 1.4) * S, (y0 + 14 + r * 3.2) * S, (y0 + 14.7 + r * 3.2) * S, zt, zt + 0.004, M["white_conn"])
        cube("qwiic", (x0 + 60) * S, (x0 + 66) * S, (y0 + 40) * S, (y0 + 44.5) * S, zt, zt + 0.03, M["white_conn"])
    else:
        for xx in (x0 + 0.6, x0 + w - 5.1):
            cube("qwiic", xx * S, (xx + 4.5) * S, (y0 + 8.2) * S, (y0 + 17.2) * S, zt, zt + 0.029, M["white_conn"])
        if kind == "knob":
            cube("enc", (x0 + 14.5) * S, (x0 + 26.5) * S, (y0 + 6.7) * S, (y0 + 18.7) * S, zt, zt + 0.065, M["steel"])
            cyl("cap", (x0 + 20.5) * S, (y0 + 12.68) * S, zt + 0.065, 0.16, 0.075, M["black_plastic"], verts=64)
        if kind == "buzzer":
            cyl("buz", (x0 + 20.5) * S, (y0 + 12.68) * S, zt, 0.045, 0.06, M["black_plastic"])
        if kind == "thermo":
            cube("sens", (x0 + 19.5) * S, (x0 + 21.5) * S, (y0 + 11.7) * S, (y0 + 13.7) * S, zt, zt + 0.009, M["chip"])

def c920(cx, y0, y1, zc):
    w, h = 94 * S, 29 * S
    cube("cam_body", cx - w / 2, cx + w / 2, y0, y1, zc - h / 2, zc + h / 2, M["black_plastic"], bevel=0.05, seg=6)
    cyl("cam_ring", cx, y1 - 0.004, zc, 0.012, 0.085, M["steel"], axis="Y")
    cyl("cam_lens", cx, y1 + 0.002, zc, 0.012, 0.06, M["glass"], axis="Y")
    cyl("cam_led", cx - 0.30, y1 - 0.001, zc, 0.006, 0.012, M["led"], axis="Y")
    cyl("cam_led", cx + 0.30, y1 - 0.001, zc, 0.006, 0.012, M["led"], axis="Y")
    cube("clip", cx - 0.12, cx + 0.12, y0 + 0.05, y1 - 0.05, zc - h / 2 - 0.08, zc - h / 2 + 0.01, M["black_plastic"], bevel=0.02)


def arduino_cam(cx, cy, z0):
    """Arduino USB Camera (TPX00246), approximate: round ribbed puck with ring light on a block clip base. Faces +Y."""
    R, DEP = 39 * S, 30 * S
    bw, bd, bh = 62 * S, 28 * S, 16 * S
    dark = mat("cam_dark", (0.018, 0.019, 0.021), 0.45)
    cube("cam_base", cx - bw / 2, cx + bw / 2, cy - bd / 2, cy + bd / 2, z0, z0 + bh, dark, bevel=0.025, seg=4)
    logo = mat("cam_logo", (0.85, 0.87, 0.88), 0.5)
    for dx in (-0.045, 0.045):
        bpy.ops.mesh.primitive_torus_add(major_radius=0.042, minor_radius=0.007, location=(cx + dx, cy + bd / 2 + 0.002, z0 + bh / 2), rotation=(math.radians(90), 0, 0))
        link(bpy.context.object, logo)
    cyl("cam_neck", cx, cy, z0 + bh, 8 * S, 6.5 * S, mat("cam_neckm", (0.06, 0.06, 0.065), 0.3, metal=0.6))
    zc = z0 + bh + 8 * S + R - 0.02
    y0 = cy - DEP / 2
    cyl("cam_puck", cx, y0, zc, DEP, R, dark, verts=96, axis="Y")
    rib = mat("cam_rib", (0.025, 0.026, 0.028), 0.6)
    for i in range(64):
        a = 2 * math.pi * i / 64
        bpy.ops.mesh.primitive_cube_add(size=1, location=(cx + (R + 0.004) * math.cos(a), cy - 0.01, zc + (R + 0.004) * math.sin(a)), rotation=(0, -a, 0))
        o = bpy.context.object; o.scale = (0.012, DEP - 0.08, 0.016); link(o, rib)
    ring = mat("cam_ring", (0.92, 0.93, 0.95), 0.35, emit=(1.0, 0.98, 0.95), emit_strength=0.4, sss=0.2)
    cyl("cam_ringlight", cx, y0 + DEP, zc, 0.01, R - 0.012, ring, verts=96, axis="Y")
    cyl("cam_face", cx, y0 + DEP + 0.004, zc, 0.012, 26 * S, mat("cam_facem", (0.01, 0.01, 0.012), 0.15, coat=1.0), verts=96, axis="Y")
    fy = y0 + DEP + 0.016
    cube("cam_window", cx - 0.075, cx + 0.075, fy - 0.004, fy + 0.006, zc - 0.17, zc + 0.15, mat("cam_win", (0.04, 0.04, 0.05), 0.1, metal=0.3), bevel=0.07, seg=8)
    cyl("cam_shutter", cx, fy + 0.004, zc + 0.08, 0.012, 0.06, mat("cam_shut", (0.35, 0.35, 0.38), 0.5), axis="Y")
    cyl("cam_lensring", cx, fy + 0.004, zc - 0.07, 0.01, 0.06, M["steel"], axis="Y")
    cyl("cam_lens", cx, fy + 0.008, zc - 0.07, 0.01, 0.042, M["glass"], axis="Y")
    bpy.ops.object.text_add(location=(cx + 0.245, fy + 0.002, zc + 0.11), rotation=(math.radians(90), 0, math.radians(180)))
    t = bpy.context.object; t.data.body = "ARDUINO"; t.data.size = 0.034; link(t, logo)
    bpy.ops.object.text_add(location=(cx + 0.025, fy + 0.002, zc - 0.21), rotation=(math.radians(90), 0, math.radians(180)))
    t = bpy.context.object; t.data.body = "*"; t.data.size = 0.07; link(t, logo)
    return zc

# ---------------- scenes ----------------
if SCENE in ("hero", "caseA", "caseB"):
    swollen = 2 if SCENE == "caseA" else None
    xs, total = build_module(6, swollen=swollen, swell=0.06)
    floor()
    if SCENE == "caseB":
        thermal_materials(xs, total)
        sc.view_settings.view_transform = "Standard"; sc.view_settings.look = "None"
        camera((-2.9, -3.6, 2.55), (0.05, 0.05, 0.42), lens=46)
    else:
        studio_lights()
        camera((-2.9, -3.6, 2.4), (0.1, 0.05, 0.42), lens=52, fstop=4.0)
    if SCENE == "caseA":
        area("glow", (0.5, -1.5, 0.6), (xs[2], 0, 0.6), 0.6, 120, (1.0, 0.25, 0.12))

elif SCENE == "cell":
    for i, (xx, sw) in enumerate(((-0.42, 0), (0.42, 0.13))):
        bpy.ops.object.select_all(action="DESELECT")
        body = cube(f"c{i}", xx - CT, xx + CT, -0.55, 0.55, 0.0, 1.2, M["wrap"], bevel=0.0 if sw else 0.015)
        if sw:
            swell_mesh(body, sw)
            b = body.modifiers.new("bev", "BEVEL"); b.width = 0.01; b.segments = 2
            bpy.ops.object.shade_smooth()
        top = 1.2
        cube("lid", xx - CT + 0.005, xx + CT - 0.005, -0.545, 0.545, top - 0.004, top + 0.014, M["alu"], bevel=0.004)
        for ty, m in ((-0.33, M["alu"]), (0.33, M["copper"])):
            cube("t", xx - 0.12, xx + 0.12, ty - 0.09, ty + 0.09, top + 0.014, top + 0.06, m, bevel=0.008)
        cyl("v", xx, 0, top + 0.014, 0.004, 0.06, M["vent"])
        cube("lab", xx - CT + 0.1, xx + CT - 0.1, -0.5515, -0.549, 0.55, 0.72, M["label"])
    floor()
    studio_lights(0.8)
    area("redrim", (1.6, 1.2, 1.4), (0.42, 0, 0.8), 1.0, 380, (1.0, 0.3, 0.15))
    camera((0.0, -4.4, 1.9), (0.0, 0.0, 0.62), lens=50, fstop=8)

elif SCENE == "station":
    D = "/home/claude/cad/render/stl/"
    import_stl(D + "frame.stl", M["pla_light"])
    import_stl(D + "holder.stl", M["pla_dark"])
    for i in range(1, 5):
        import_stl(D + f"cell{i}.stl", M["pla_white"])
    board(4.0, 40.0, 68.58, 53.34, 2.4, "uno")
    board(112.0, 8.0, 41.0, 25.36, 2.4, "buzzer")
    board(112.0, 44.0, 41.0, 25.36, 2.4, "thermo")
    board(112.0, 80.0, 41.0, 25.36, 2.4, "knob")
    arduino_cam(90 * S, -105 * S, 0.0)
    floor()
    area("key", (-2.6, -3.0, 3.6), (0.8, 0.8, 0.2), 2.6, 380, (1.0, 0.96, 0.92))
    area("rim", (2.8, 3.6, 1.8), (0.8, 1.0, 0.3), 1.8, 700, (1.0, 0.58, 0.32))
    area("fill", (3.4, -1.6, 1.2), (0.8, 0.8, 0.2), 2.0, 160, (0.55, 0.72, 1.0))
    area("top", (0.8, 0.8, 4.5), (0.8, 0.8, 0), 4.0, 120)
    camera((float(os.environ.get("CX","3.6")), float(os.environ.get("CY","1.9")), float(os.environ.get("CZ","1.9"))), (float(os.environ.get("TX","0.9")), float(os.environ.get("TY","0.25")), 0.3), lens=float(os.environ.get("LENS","28")), fstop=8)

elif SCENE == "video":
    xs, total = build_module(6)
    floor()
    studio_lights()
    sc.render.fps = 24; sc.frame_start = 1; sc.frame_end = int(os.environ.get("FRAMES", "120"))
    top = 0.06 + CH + 0.045 + 0.012
    # laser welding head: emissive spot + beam + flickering point light, moving along the busbar line
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.012, location=(xs[0], -0.52, top + 0.004))
    spot = bpy.context.object; link(spot, mat("spark", (1, 0.6, 0.3), 0.5, emit=(1.0, 0.55, 0.2), emit_strength=180))
    bpy.ops.mesh.primitive_cylinder_add(radius=0.004, depth=0.9, location=(xs[0], -0.52, top + 0.45))
    beam = bpy.context.object; link(beam, mat("beam", (1, 0.5, 0.2), 0.5, emit=(1.0, 0.45, 0.15), emit_strength=25))
    pl = bpy.data.lights.new("weld", "POINT"); pl.color = (1.0, 0.55, 0.25); pl.shadow_soft_size = 0.01
    plo = bpy.data.objects.new("weld", pl); sc.collection.objects.link(plo)
    F = sc.frame_end
    for f in range(1, F + 1):
        t = (f - 1) / (F - 1)
        x = xs[0] - 0.05 + t * (xs[-1] - xs[0] + 0.1)
        for o, z in ((spot, top + 0.004), (beam, top + 0.45), (plo, top + 0.05)):
            o.location = (x, -0.52, z); o.keyframe_insert("location", frame=f)
        pl.energy = 60 + 45 * abs(math.sin(f * 2.3) * math.cos(f * 0.7)); pl.keyframe_insert("energy", frame=f)
    # slow cinematic dolly, low over the top, shallow depth of field following the weld
    cam = camera((xs[0] - 0.9, -2.0, 1.55), (xs[0], -0.52, top), lens=70, fstop=2.2)
    tgt = bpy.data.objects.new("tgt", None); sc.collection.objects.link(tgt)
    cam.data.dof.focus_object = tgt
    tc = cam.constraints.new("TRACK_TO"); tc.target = tgt; tc.track_axis = "TRACK_NEGATIVE_Z"; tc.up_axis = "UP_Y"
    for f in (1, F):
        t = (f - 1) / (F - 1)
        tgt.location = (xs[0] - 0.05 + t * (xs[-1] - xs[0] + 0.1), -0.52, top); tgt.keyframe_insert("location", frame=f)
        cam.location = (-1.35 + t * 2.1, -2.05 + t * 0.15, 1.45 - t * 0.12); cam.keyframe_insert("location", frame=f)
    for o in (tgt, cam):
        for fc in o.animation_data.action.fcurves if hasattr(o.animation_data.action, "fcurves") else []:
            for k in fc.keyframe_points: k.interpolation = "LINEAR"
    sc.view_settings.exposure = -0.7
    os.makedirs(f"{OUT}/frames", exist_ok=True)
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = f"{OUT}/frames/f_"
    bpy.ops.render.render(animation=True)
    print("rendered video frames"); raise SystemExit

elif SCENE == "scan":
    xs, total = build_module(6)
    floor()
    studio_lights()
    sc.render.fps = 24; sc.frame_start = 1; sc.frame_end = int(os.environ.get("FRAMES", "120"))
    top = 0.06 + CH + 0.045 + 0.012
    F = sc.frame_end
    # scanner: a thin projected line (narrow area light with low spread) + a faint fading light sheet
    ln = bpy.data.lights.new("scanline", "AREA"); ln.shape = "RECTANGLE"; ln.size = 0.006; ln.size_y = CL + 0.5
    ln.spread = math.radians(6); ln.energy = 260; ln.color = (0.62, 0.88, 1.0)
    lno = bpy.data.objects.new("scanline", ln); sc.collection.objects.link(lno)
    sheet_m = bpy.data.materials.new("sheet"); sheet_m.use_nodes = True; sheet_m.blend_method = "BLEND" if hasattr(sheet_m, "blend_method") else None
    nt = sheet_m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); mix = nt.nodes.new("ShaderNodeMixShader")
    tr = nt.nodes.new("ShaderNodeBsdfTransparent"); em = nt.nodes.new("ShaderNodeEmission")
    em.inputs[0].default_value = (0.62, 0.88, 1.0, 1); em.inputs[1].default_value = 6.0
    tc = nt.nodes.new("ShaderNodeTexCoord"); sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    mr = nt.nodes.new("ShaderNodeMapRange"); mr.inputs[1].default_value = 0.0; mr.inputs[2].default_value = 1.0
    mr.inputs[3].default_value = 0.22; mr.inputs[4].default_value = 0.0
    L = nt.links
    L.new(tc.outputs["Generated"], sep.inputs[0]); L.new(sep.outputs[2], mr.inputs[0])
    L.new(mr.outputs[0], mix.inputs[0]); L.new(tr.outputs[0], mix.inputs[1]); L.new(em.outputs[0], mix.inputs[2]); L.new(mix.outputs[0], out.inputs[0])
    bpy.ops.mesh.primitive_plane_add(size=1)
    sheet = bpy.context.object; sheet.scale = (CL + 0.3, 0.55, 1); sheet.rotation_euler = (math.radians(90), 0, math.radians(90))
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    sheet.data.materials.append(sheet_m)
    for f in range(1, F + 1):
        t = (f - 1) / (F - 1)
        x = xs[0] - CT * 0.8 + t * (xs[-1] - xs[0] + CT * 1.6)
        lno.location = (x, 0, top + 0.55); lno.rotation_euler = (0, 0, math.radians(90)); lno.keyframe_insert("location", frame=f); lno.keyframe_insert("rotation_euler", frame=f)
        sheet.location = (x, 0, top + 0.27); sheet.keyframe_insert("location", frame=f)
    cam = camera((xs[0] - 0.9, -2.0, 1.55), (xs[0], -0.52, top), lens=70, fstop=2.2)
    tgt = bpy.data.objects.new("tgt", None); sc.collection.objects.link(tgt)
    cam.data.dof.focus_object = tgt
    tcn = cam.constraints.new("TRACK_TO"); tcn.target = tgt; tcn.track_axis = "TRACK_NEGATIVE_Z"; tcn.up_axis = "UP_Y"
    for f in (1, F):
        t = (f - 1) / (F - 1)
        tgt.location = (xs[0] - 0.05 + t * (xs[-1] - xs[0] + 0.1), -0.30, top); tgt.keyframe_insert("location", frame=f)
        cam.location = (-1.35 + t * 2.1, -2.05 + t * 0.15, 1.45 - t * 0.12); cam.keyframe_insert("location", frame=f)
    sc.view_settings.exposure = -0.7
    os.makedirs(f"{OUT}/scanframes", exist_ok=True)
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = f"{OUT}/scanframes/f_"
    bpy.ops.render.render(animation=True)
    print("rendered scan frames"); raise SystemExit

elif SCENE == "scanvideo":
    xs, total = build_module(6)
    floor()
    studio_lights()
    sc.render.fps = 24; sc.frame_start = 1; sc.frame_end = int(os.environ.get("FRAMES", "120"))
    top = 0.06 + CH + 0.012
    CYAN = (0.45, 0.85, 1.0)
    X0, X1 = xs[0] - CT / 2 - 0.12, xs[-1] + CT / 2 + 0.12
    head_z = top + 0.75
    # scanner head: dark bar with a glowing slit
    YL = CL / 2 + 0.1
    head = cube("head", -0.03, 0.03, -YL + 0.1, YL - 0.1, head_z, head_z + 0.05, M["black_plastic"], bevel=0.008)
    slit = cube("slit", -0.004, 0.004, -YL + 0.15, YL - 0.15, head_z - 0.002, head_z + 0.001, mat("slitm", CYAN, 0.5, emit=CYAN, emit_strength=60))
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, (top + head_z) / 2), rotation=(0, math.pi / 2, 0))
    sheet = bpy.context.object; sheet.name = "sheet"; sheet.scale = (head_z - top, CL, 1)
    vm = bpy.data.materials.new("sheetmat"); vm.use_nodes = True; nt = vm.node_tree; nt.nodes.clear()
    o_ = nt.nodes.new("ShaderNodeOutputMaterial"); ve = nt.nodes.new("ShaderNodeEmission"); tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    ad = nt.nodes.new("ShaderNodeAddShader"); tc_ = nt.nodes.new("ShaderNodeTexCoord"); sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    mr = nt.nodes.new("ShaderNodeMapRange"); mr.inputs[1].default_value = 0.0; mr.inputs[2].default_value = 1.0
    mr.inputs[3].default_value = 0.0; mr.inputs[4].default_value = float(os.environ.get("VOL","0.5"))
    pw = nt.nodes.new("ShaderNodeMath"); pw.operation = "POWER"; pw.inputs[1].default_value = 3.0
    ve.inputs[0].default_value = (*CYAN, 1)
    nt.links.new(tc_.outputs["Generated"], sep.inputs[0])
    nt.links.new(sep.outputs[0], mr.inputs[0])
    nt.links.new(mr.outputs[0], pw.inputs[0]); nt.links.new(pw.outputs[0], ve.inputs[1])
    nt.links.new(ve.outputs[0], ad.inputs[0]); nt.links.new(tr.outputs[0], ad.inputs[1])
    nt.links.new(ad.outputs[0], o_.inputs["Surface"])
    sheet.data.materials.append(vm)
    sheet.visible_shadow = False; sheet.visible_diffuse = False; sheet.visible_glossy = False
    l = bpy.data.lights.new("scanl", "AREA"); l.shape = "RECTANGLE"; l.size = 0.006; l.size_y = 2 * YL; l.energy = float(os.environ.get("LE","3000")); l.color = CYAN; l.spread = math.radians(2.5)
    lo = bpy.data.objects.new("scanl", l); sc.collection.objects.link(lo); lo.location = (0, 0, head_z - 0.01)
    lz = 0.06 + CH
    beamline = cube("beamline", -0.0012, 0.0012, -CL / 2, CL / 2, lz - 0.001, lz + 0.075, mat("linem", CYAN, 0.5, emit=CYAN, emit_strength=float(os.environ.get("LINE","40"))))
    beamline.visible_shadow = False
    F = sc.frame_end
    parts = (head, slit, sheet, lo, beamline)
    xa, xb = xs[0] - CT / 2 - 0.05, xs[-1] + CT / 2 + 0.05
    for f in range(1, F + 1):
        t = (f - 1) / (F - 1); e = 0.5 - 0.5 * math.cos(math.pi * t)
        x = xa + (xb - xa) * e
        for o in parts:
            o.location.x = x; o.keyframe_insert("location", frame=f)
    cam = camera((xs[0] - 0.9, -2.0, 1.55), (0, 0, top), lens=58, fstop=2.8)
    tgt = bpy.data.objects.new("tgt", None); sc.collection.objects.link(tgt)
    cam.data.dof.focus_object = tgt
    tc = cam.constraints.new("TRACK_TO"); tc.target = tgt; tc.track_axis = "TRACK_NEGATIVE_Z"; tc.up_axis = "UP_Y"
    for f in (1, F):
        t = (f - 1) / (F - 1)
        tgt.location = (-0.35 + 0.7 * t, -0.15 + 0.3 * t, top); tgt.keyframe_insert("location", frame=f)
        cam.location = (-1.55 + 1.9 * t, -2.25 + 0.2 * t, 1.35 - 0.1 * t); cam.keyframe_insert("location", frame=f)
    sc.view_settings.exposure = -0.8
    if os.environ.get("STILL"):
        sc.frame_set(int(os.environ["STILL"])); sc.render.filepath = f"{OUT}/scan_test.jpg"
        bpy.ops.render.render(write_still=True); print("rendered still"); raise SystemExit
    os.makedirs(f"{OUT}/scanframes", exist_ok=True)
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = f"{OUT}/scanframes/f_"
    bpy.ops.render.render(animation=True)
    print("rendered scan frames"); raise SystemExit

elif SCENE == "lineart":
    D = "/home/claude/cad/render/stl/"
    blk = mat("blk", (0.0, 0.0, 0.0), 1.0)
    for n in ["frame", "holder", "cell1", "cell2", "cell3", "cell4"]:
        import_stl(D + n + ".stl", blk)
    board(4.0, 40.0, 68.58, 53.34, 2.4, "uno"); board(112.0, 8.0, 41.0, 25.36, 2.4, "buzzer")
    board(112.0, 44.0, 41.0, 25.36, 2.4, "thermo"); board(112.0, 80.0, 41.0, 25.36, 2.4, "knob")
    arduino_cam(90 * S, -105 * S, 0.0)
    for o in sc.objects:
        if o.type == "MESH":
            o.data.materials.clear(); o.data.materials.append(blk)
    world.node_tree.nodes["Background"].inputs[0].default_value = (0, 0, 0, 1)
    sc.render.use_freestyle = True; sc.render.line_thickness_mode = "ABSOLUTE"; sc.render.line_thickness = 1.1
    fs = sc.view_layers[0].freestyle_settings
    lset = fs.linesets.new("L") if len(fs.linesets) == 0 else fs.linesets[0]
    if lset.linestyle is None: lset.linestyle = bpy.data.linestyles.new("LS")
    lset.select_by_visibility = True; lset.select_silhouette = True; lset.select_border = True; lset.select_crease = True
    ls = lset.linestyle
    ls.color = (0.85, 0.87, 0.9); ls.thickness = 1.1
    sc.view_layers[0].freestyle_settings.crease_angle = math.radians(140)
    sc.view_settings.view_transform = "Standard"; sc.view_settings.look = "None"
    sc.cycles.samples = 4
    camera((3.5, 1.9, 2.1), (0.88, 0.3, 0.25), lens=30)

if os.environ.get("GLB"):
    bpy.ops.export_scene.gltf(filepath=os.environ["GLB"], export_format="GLB", use_selection=False, export_apply=True)
    print("exported glb"); raise SystemExit
sc.view_settings.exposure = {"hero": -0.7, "caseA": -0.7, "station": -0.6, "cell": -0.3}.get(SCENE, 0.0)
sc.render.filepath = f"{OUT}/{SCENE}.jpg"
bpy.ops.render.render(write_still=True)
print("rendered", SCENE)
