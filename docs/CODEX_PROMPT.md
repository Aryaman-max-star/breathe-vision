# CODEX BRIEF: BREATHE Vision website

You are taking over the marketing website for **BREATHE Vision**, a hardware startup project built at the Junction 2026 hackathon (Espoo, Finland, 13 to 15 Nov 2026). A working version already exists in this folder. Your job is to turn it into the best possible version of itself: more beautiful, more cinematic, more convincing, faster and fully responsive, while keeping every fact honest.

Read this whole brief before writing code. Then work in the order given in section 14.

---

## 1. What is in this folder

```
breathe-site/
├── index.html                         # current site, editable source (CSS + JS inline, assets referenced by path)
├── assets/
│   ├── video/hero-scan-loop.mp4       # 10 s seamless loop, 1280x720, H.264 (cyan scanner line sweeping across a 6-cell EV module, ping-pong loop)
│   ├── video/hero-poster.jpg          # first frame of the video, used as poster
│   ├── img/module-studio.jpg          # photoreal render: 6-cell prismatic EV module, studio light, copper rim light
│   ├── img/case-a-swollen-cell.jpg    # same module, cell 3 swollen, warm light (Case A)
│   ├── img/case-b-thermal.jpg         # same module rendered as a false-colour thermal image, hot on the left end (Case B)
│   ├── img/cell-healthy-vs-swollen.jpg# two prismatic cells side by side, right one bulging (exaggerated)
│   ├── img/station-render.jpg         # photoreal render of OUR real prototype rig (printed frame, 4 cells, white screen, Arduino USB Camera, UNO Q, Modulinos)
│   ├── img/station-lineart.png        # white line drawing of the rig on transparent background
│   └── 3d/module.glb, 3d/station.glb  # glTF models of the EV module and of our rig (units: 1 unit = 100 mm)
└── docs/
    ├── CODEX_PROMPT.md                # this brief
    └── current-published-single-file.html  # the same site with every asset embedded as base64 (reference only, do not edit)
```

All images and the video are **renders made in Blender**, not photographs. The footer must keep saying so until the team supplies real photos (section 11).

---

## 2. The product (get every detail right)

**One line:** BREATHE Vision is a service-bay check station that measures swelling of every cell in an EV battery module to a fraction of a millimetre, tells you whether chemistry or heat caused it, recommends a cell-specific action, and stores the result in the pack's battery record.

**Why it matters**
- A lithium-ion cell grows (swells) before it fails. Today that growth is checked by eye, if at all.
- Swelling comes from gas generation (electrolyte breakdown), SEI layer growth and lithium plating. Overcharging, cold or fast charging and heat make it worse. (Source: "Swelling Mechanisms, Diagnostic Applications, and Mitigation Strategies in Lithium-Ion Batteries", Batteries, MDPI, 11(10):356.)
- Lithium-ion cells perform and last best between **15 and 35 °C**. Calendar ageing roughly **doubles at 35 °C versus 25 °C** because SEI growth roughly doubles per 10 °C. (Sources: batterydesign.net thermal management page; Review of battery thermal management systems in electric vehicles, Renewable and Sustainable Energy Reviews, 2024.)
- From **18 February 2027**, EU Battery Regulation (EU) 2023/1542 (Article 77) requires a **digital battery passport** for every EV battery, LMT battery and industrial battery above 2 kWh placed on the EU market, and it must stay up to date through the battery's life.

**How the station works (the real prototype)**
1. **Scan:** the module slides into a holder. A side-on Arduino USB Camera (4K, Sony IMX376, ring light off) sits about 20 cm in front of the holder and looks along the tops of the cells against a white screen. Focus and exposure are locked. One scan averages **30 frames**.
2. **Measure:** for every pixel column, the top edge of each cell is found with sub-pixel precision. Hundreds of columns give each cell one precise height, compared with its own baseline and with its neighbours.
3. **Diagnose:** rules plus an anomaly model (Isolation Forest) run **on the Arduino UNO Q itself** (edge AI, no cloud needed). Cases: SWELL (one cell grows), WATCH, THERMAL (whole module warm, geometry unchanged), RESEAT (cell not seated), MISSING, OBSTRUCTED / LIGHTING / CAMERA MOVED (station fault), OK.
4. **Act and record:** a cell-specific service action appears on the station (LED matrix, buzzer), and every scan is written to **PostgreSQL on Aiven**, linked to the pack ID for its battery passport.

**Hardware in the prototype:** Arduino UNO Q (Qualcomm Linux side + STM32 MCU), Arduino USB Camera (TPX00246) on its own base on the table, at least 20 cm from the holder (autofocus minimum), lens about 48 to 65 mm above the table, Modulino Thermo (air temperature, humidity, dew point), Modulino Knob (start scan, long press = calibrate), Modulino Buzzer (alerts). Everything sits on a 3D-printed open frame 157 x 163 mm (Bambu Lab P2S).

**Demo module (scaled mock):** four printed cells 18 x 30 x 42 mm in a thin-walled 4-slot holder. One fault cell is **0.6 mm taller (42.6 mm)**: invisible to the eye, about 7 to 9 pixels to the camera. **Detection target: 0.25 mm.** Hairdryer warming demonstrates the THERMAL case (printed cells expand only about 0.03 to 0.09 mm for a 10 to 30 K rise, so a uniform rise with a temperature jump is heat, not swelling).

**The two failure modes the site must explain**
- **Case A, irregular chemical reaction:** one cell grows on its own (plating, gas). Neighbours stay at built height. Verdict: `SWELL / cell 3 / +0.60 mm`. Action: isolate and replace cell 3, test cells 2 and 4, review its charge history for cold fast charging.
- **Case B, uneven heat distribution:** a blocked cooling channel or poor thermal pad heats one side. All cells move a little together, temperature is up, no single outlier. Verdict: `THERMAL / geometry unchanged / +0.03 mm`. Action: let the module cool below 35 °C and rescan; inspect the cooling path on the hot side.

**Vision (roadmap)**
- NOW: the service-bay check for EV service centres and battery repairers.
- NEXT: a cross-brand battery health dataset (which cells, conditions and charging habits lead to swelling).
- THEN: become a leading **European battery manufacturer**, designing cells from years of real-world evidence.

**Team:** Jugaadenberg. Aryaman Banerjee (Mechanical Engineering with Management, University of Manchester; Engine & Drivetrain Engineer, Manchester Stinger Formula Student). Vaibhavi Shetty (Computer Science; HV Safety Engineer, Formula Student).

**Hackathon context:** Arduino challenge "The Green European Renaissance" (edge AI on the UNO Q), Best Use of Aiven, OpenAI Best Use of Codex. Arduino Project Hub post tag: "Junction Finland 2026".

---

## 3. Honesty rules (non-negotiable)

- Never invent customers, testimonials, press logos, partners, funding, certifications, prices, accuracy figures or "used by" claims. Alloyed shows "As featured in"; we have nothing to show there, so leave it out or replace it with "Built at Junction 2026" and the challenge tracks.
- Every performance number on the page must come from section 2. Label demo numbers as coming from the **scaled demo module**.
- Renders stay labelled as renders. Real-EV imagery is illustrative; our prototype is the printed rig.
- No real brand logos (Arduino, Aiven, OpenAI) as images. Plain text names are fine.
- The pilot form has no backend: keep the honest note, or wire it to a real service only if the team gives you one (section 12).

---

## 4. Design direction

**Reference:** alloyed.com (metal additive manufacturing). Take its feel, not its content: a full-screen looping video opener with a huge short headline, near-black canvas, generous whitespace, confident short statements, a "One technology stack" style section with a technical illustration and a list of layers, numbered "how to work with us" steps, crisp footer.

**Mood:** a precision instrument at night. Graphite black, cool steel, one warm copper light (copper is the anode current collector inside every cell, so it is our signature colour). Heat colours (amber to red) appear only where heat is the subject.

**Current tokens (keep, refine if you have a better reason):**
```css
--ink:#050607;  --panel:#0C0E10;  --line:rgba(255,255,255,.09);
--text:#EDEFF1; --muted:#8B939A;  --copper:#D9935E;
--ion:#7FD4FF;  --ok:#5FD39B;     --warn:#F2B544;  --bad:#F2604A;
fonts: Geist (display + body, weights 300 to 700), Geist Mono (data, units, labels)
background: #050607 with a 26 px dot grid (rgba(255,255,255,.055)) and a faint copper glow top right
```
- Headings: sentence case, weight 500, letter-spacing -0.035em, line-height 1.02. H1 clamp(52px, 9vw, 148px).
- Units and measurements always in Geist Mono with tabular numbers (0.25 mm, +0.60 mm, 30 frames).
- Eyebrows: mono, 12 px, uppercase, 0.14em tracking, copper.
- Buttons: pill. Primary white on black in the nav; copper for the main call to action.
- One bold idea per section; everything around it stays quiet.

---

## 5. Page structure and copy (current, in order)

Keep this order unless you have a clearly better narrative. Copy below is approved; you may tighten it but keep the meaning and the numbers.

1. **Nav (fixed, transparent over video, turns solid on scroll):** logo "BREATHE" with a small animated battery icon; links Technology, Swelling, Diagnosis, Station, Vision; button "Get in touch".
2. **Opener (100svh video):** `hero-scan-loop.mp4`, desaturated (saturate .55, brightness .82), gradient to black at the bottom. H1 "Batteries breathe. / We listen." (two lines) Sub "The health check that sees a cell swell before anyone can." Buttons "Book a pilot", "Watch it happen". Small live chip "BREATHE Vision / ● scanning". Scroll chevron.
3. **Statement:** "Every EV cell physically swells and heats as it ages, yet no one tracks it cell by cell. BREATHE measures each cell’s mechanical swelling and heat build-up, catches a failing cell before it fails, and gives every battery a longer life, sparking a renaissance in EV technology." Four stats: 0.25 mm (detection target on our scaled demo module), 30 (frames per scan), 4 cases (swelling, heat, badly seated cell and bad image told apart), On device (decisions run on the Arduino UNO Q).
4. **One station:** line drawing + four layers that auto-cycle and expand on hover: Better sensing (Side camera), Better decisions (Arduino UNO Q), Better context (Modulino Thermo), Better records (Aiven PostgreSQL).
5. **Problem:** "Swelling is the warning nobody measures." Three facts: 18.02.2027 passport, 15 to 35 °C, 2x ageing.
6. **Close-up band:** full-width healthy vs swollen cell image with captions.
7. **Scroll story (centrepiece):** "How a cell starts to swell." Pinned section (620vh track) with a canvas cross-section of a prismatic cell and six steps that light up with scroll progress p:
   - 01 Healthy (ions shuttle cathode to anode, flat can)
   - 02 Plating, p 0.13 to 0.33 (silver dendrites grow from the anode face)
   - 03 SEI growth, p 0.30 to 0.50 (amber film thickens on the anode)
   - 04 Gas, p 0.46 to 0.66 (bubbles rise into the headspace)
   - 05 Swelling, p 0.62 to 0.82 (can bulges, live readout to +0.60 mm against an "as built" line)
   - 06 Heat, p 0.80 to 0.98 (orange glow, temperature readout climbs)
   HUD chips: STAGE, Δh, T, GAS. Progress bar on top.
8. **Two failures, two different fixes:** Case A and Case B cards (images, pins, verdict boxes, copy from section 2). Case B has a thermal colour scale 24 to 44 °C.
9. **How it sees:** "A silhouette, read to a fraction of a pixel." Canvas mock of the camera view (white screen, four dark cell silhouettes, copper edge points sweeping, fitted lines, cell 3 raised, pixel-zoom inset "edge fitted to ~0.05 px") + four steps Scan, Measure, Diagnose, Act and record.
10. **Station:** prototype render + spec list (Brain Arduino UNO Q; Camera Arduino USB Camera, 4K, side view; Frames per scan 30; Detection target 0.25 mm; Demo fault +0.60 mm; Air sensing T, RH, dew point; Records PostgreSQL on Aiven). Caption: "Prototype station built at Junction 2026. Printed frame 157 x 163 mm, scaled mock module."
11. **Roadmap:** NOW / NEXT / THEN (section 2).
12. **Pilot form:** name, company, work email, type (EV service centre, Battery repairer or recycler, Fleet operator, Carmaker or cell maker, Investor). Honest note that nothing is sent.
13. **Footer:** "BREATHE Vision. Built at Junction 2026, Espoo, by team Jugaadenberg." and "Images are renders. Figures are from a scaled demo module."

---

## 6. Improvements wanted (make it the best possible version)

Do these in priority order. Each one should feel deliberate, not decorative.

**P1. Opener**
- Keep the video. Add a subtle load sequence: headline words rise in with a 60 ms stagger, sub and buttons fade after, chip pulses.
- Add a soft parallax: the video scales from 1.08 to 1.0 and darkens slightly as the user scrolls past it.
- Mobile: serve the poster image if `prefers-reduced-data` or `saveData` is on; otherwise play the video muted, inline.

**P2. Interactive 3D (new section, after "One station" or replacing the line drawing on desktop)**
- Use Three.js (pinned version, loaded from a CDN such as cdnjs or jsDelivr) with `GLTFLoader` to show `assets/3d/station.glb` (and/or `module.glb`).
- Dark studio look: ACES or AgX-like tone mapping, one warm key light, copper rim light, cool fill, soft contact shadow under the model, slow auto-rotate, drag to orbit, no zoom on scroll (it hijacks page scrolling).
- Exploded view on scroll: frame, holder, cells, boards and camera separate vertically with labels (Side camera, Arduino UNO Q, Modulino Thermo, Knob, Buzzer, 4-slot holder, white screen) and reassemble as the user scrolls on.
- Fallback: show `station-lineart.png` when WebGL is unavailable or reduced motion is on.

**P3. Scroll story polish**
- Smoother easing between stages, a short caption overlay inside the canvas for each stage, and a mini "module view" in the corner that shows where in the module this cell sits.
- Make the cross-section feel more physical: subtle electrode texture, ion trails, bubbles that coalesce into the gas pocket, the can wall thickness visible, a dimension arrow with "+0.60 mm (demo scale)".
- Keyboard and reduced-motion support: arrow keys step through stages; with reduced motion show six static frames in a grid instead of the pinned scroll.

**P4. "Try the scan" interactive demo (new section, high impact)**
- A canvas or SVG camera view of four cells. Controls: a slider "Cell 3 growth (mm)" from 0.00 to 1.00, a toggle "Warm the module (+15 °C)", a toggle "Lift cell 2 (not seated)", a button "Block the view".
- Live output, using the real decision logic: threshold T_alarm = 0.25 mm, T_watch = 0.12 mm; thermal expansion Δh = 68e-6 x 42 mm x ΔT (show the tiny number); first alarm says RESEAT, second scan confirms SWELL. Show the verdict pill, the cell-specific action text and a fake scan time in ms.
- This lets judges and visitors feel the product. Label it "Simulation".

**P5. Battery passport section (new)**
- A card that looks like a digital battery record for `DEMO-PACK-001`: pack ID, chemistry placeholder, last scan time, per-cell heights as a small bar chart, status history timeline (OK, SWELL cell 3, replaced, OK), and "stored in PostgreSQL on Aiven". Clearly marked as example data.
- One line on the regulation: from 18 Feb 2027 the passport is mandatory for EV batteries in the EU.

**P6. Imagery and motion**
- Lazy-load every image below the fold (`loading="lazy"`, `decoding="async"`), use `<picture>` with AVIF/WebP plus JPEG fallback, and provide 800 / 1600 / 2400 widths via `srcset`.
- Subtle Ken Burns on the Case images on hover only. No auto-moving images elsewhere.
- Optional smooth scrolling (Lenis) only if it does not break the pinned story or anchor links; disable for reduced motion.
- Use GSAP + ScrollTrigger (pinned versions) if it simplifies the story and the exploded view; otherwise keep the vanilla requestAnimationFrame approach.

**P7. Team section (new, before the form)**
- Two people, roles and one line each (section 2). No photos unless supplied; use monogram tiles.

**P8. FAQ (new, short)**
- Is this used on real cars yet? (No, it is a hackathon prototype on a scaled module.)
- Why a camera and not a pressure sensor? (Non-contact, one camera covers every cell, works across brands.)
- Can it tell heat from swelling? (Yes, by the pattern across cells plus temperature context.)
- Where does the data go? (On-device decision, then PostgreSQL on Aiven, linked to the pack ID.)

**P9. Footer**
- Columns: Product (Technology, Swelling, Diagnosis, Station), Project (Junction 2026, Arduino Project Hub post link placeholder `#`, GitHub placeholder `#`), Contact (form anchor). Small battery mark. Copyright 2026.

---

## 7. Technical requirements

- Plain HTML, CSS and JavaScript is fine; a Vite + vanilla setup is fine if you need modules. Do not introduce a heavy framework unless it clearly helps. If you do move to a framework (Astro or Next.js static export), keep the output fully static.
- Pin every external library to an exact version. No `@latest`.
- Performance budget: first meaningful paint under 2.5 s on a mid-range laptop; total transfer under 6 MB on desktop, under 3 MB on mobile (poster instead of video if needed). Video stays under 2 MB.
- Accessibility: semantic landmarks, alt text on every image (keep the current ones), visible focus states, all canvases have `aria-label`, the story has a text equivalent, colour contrast at least 4.5:1 for body text, `prefers-reduced-motion` respected everywhere.
- Responsive: test at 375, 768, 1024, 1440 and 1920 px wide. The pinned story collapses to one active step above the canvas on mobile (already implemented).
- SEO and sharing: title "BREATHE Vision", meta description (one sentence from section 2), Open Graph and Twitter card using `module-studio.jpg`, favicon (simple battery mark in copper, SVG).
- No console errors. No layout shift when fonts load (use `font-display: swap` and size-adjusted fallbacks).
- Keep the site working as a single static folder so it can be hosted on GitHub Pages, Netlify or Vercel.

---

## 8. Things not to do

- Do not add stock photos, fake reviews, fake logos or fake statistics.
- Do not use purple-blue gradients, glassmorphism everywhere, emoji as icons or generic SaaS illustrations.
- Do not autoplay sound. Do not hijack scroll speed.
- Do not remove the scroll story or the two-case comparison; they are the heart of the pitch.
- Do not claim the product detects anything it does not (see section 2 for the exact cases).

---

## 9. Animation details already implemented (so you can extend them)

- `drawStory(t)` draws the cell cross-section on `#storyCanvas` from `storyP` (0 to 1), computed from the scroll position of `#storyTrack`. Effect ramps: plate 0.13 to 0.33, sei 0.30 to 0.50, gas 0.46 to 0.66, bulge 0.62 to 0.82, heat 0.80 to 0.98. HUD values: Δh = 0.6 x bulge mm, T = 25 + 33 x heat + 4 x bulge °C, GAS = gas x 100 %.
- `drawScope(t)` draws the camera view on `#scope` with a 4 s sweep.
- An IntersectionObserver only redraws canvases that are on screen. Reduced motion draws static frames.
- `.reveal` elements start offset only if they are below the fold at load, so the first screen is never empty.

---

## 10. Assets you can regenerate

The renders and video came from a Blender script (Cycles). If the team asks for new shots (for example a 3/4 hero of the rig, a top-down of the module, or a longer video), describe the shot and they can re-render. Keep new renders in the same lighting language: black floor with soft reflection, warm key, copper rim from behind, cool fill.

---

## 11. Real photos (when the team supplies them)

Expected: the printed station on a desk, the four cells and holder, the UNO Q with the Modulinos wired, the camera view on a laptop, and the team at Junction. When they arrive:
- Replace `station-render.jpg` in the Station section with the real photo and move the render to the 3D or technology section.
- Add a "From the hackathon" strip with 3 to 5 real photos.
- Update the footer note to "Some images are renders."

---

## 12. Optional integrations (only if the team provides credentials)

- Pilot form: Formspree, Netlify Forms or a small serverless function. Never put secrets in the client.
- Live data: a read-only endpoint that returns the latest scan for `DEMO-PACK-001` from the Aiven database, polled every 10 s, powering the passport card. Without an endpoint, keep the example data and label it.

---

## 13. Acceptance checklist

- [ ] Opener video loops seamlessly, poster shows instantly, headline readable on every frame.
- [ ] Scroll story runs at 60 fps on a laptop, all six stages reachable, works on mobile and with reduced motion.
- [ ] 3D station loads under 2 s after the section comes into view, orbit works, fallback image works.
- [ ] "Try the scan" produces the correct verdict for: growth 0.6 mm (RESEAT then SWELL), growth 0.15 mm (WATCH), warm only (THERMAL), lifted cell (RESEAT), blocked view (OBSTRUCTED), nothing (OK).
- [ ] Every number on the page matches section 2. No invented claims.
- [ ] Lighthouse: Performance ≥ 85 desktop, Accessibility ≥ 95, Best Practices ≥ 95, SEO ≥ 95.
- [ ] No console errors at 375, 768, 1440 px.
- [ ] Footer states that images are renders and figures come from a scaled demo module.

---

## 14. Work order

1. Run the current `index.html` locally (`npx serve .` or `python3 -m http.server`) and read the code.
2. Split CSS and JS into `css/site.css` and `js/` modules (story, scope, ui). Keep behaviour identical. Commit.
3. P1 opener polish. Commit.
4. P4 "Try the scan" (highest demo value). Commit.
5. P2 3D station with exploded view. Commit.
6. P3 story polish, P5 passport card, P7 team, P8 FAQ, P9 footer. Commit after each.
7. P6 performance and image pipeline, SEO, favicon. Commit.
8. Go through section 13 and fix everything that fails.

For each commit, write a one-line message and log the prompt you used in `docs/CODEX_LOG.md` (time, task, what changed). The team is entering the OpenAI "Best Use of Codex" challenge, so this log matters.
