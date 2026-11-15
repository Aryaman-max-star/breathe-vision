"""Step-by-step calibration wizard for people who have never calibrated anything.

It tells the user exactly what to do with their hands, offers one action at a time (dashboard
button or a short press on the knob), and explains every result in plain words.

The wizard does no measuring itself: it calls the functions in `ops` (provided by main.py):
    focus() -> dict            geometry() -> dict           baseline_reset() -> dict
    baseline_add() -> dict     baseline_finish() -> dict    scale(slot) -> dict
    test_scan() -> dict (classified result)                 sim(action, slot) (simulator only)
    is_synthetic() -> bool
"""
from __future__ import annotations

ROUNDS = 8          # baseline: 8 rounds x 4 pictures = 32 scans
PER_ROUND = 4
SCALE_REPS = 3      # fault cell measured 3 times per slot
STEP_NAMES = {"focus": 1, "geometry": 2, "baseline": 3, "scale": 4, "check": 5}
WORKING = {
    "focus": "Sharpening the picture… about 1 minute. Don't touch anything.",
    "geometry": "Learning the layout… up to a minute. Don't touch anything.",
    "baseline": "Taking 4 pictures… about 10 seconds. Hands away.",
    "finish": "Working out the noise level and training the AI… a few seconds.",
    "scale": "Measuring… a few seconds. Hands away.",
    "check": "Test scan… a few seconds. Hands away.",
}


class Wizard:
    def __init__(self, ops):
        self.ops = ops
        self.reset()

    # ------------------------------------------------------------------ state
    def reset(self):
        self.active = False
        self.step = "prepare"
        self.round = 0              # baseline rounds done
        self.slot = 1               # scale: current slot
        self.rep = 0                # scale: measurements done in this slot
        self.result = None          # {"ok": bool, "text": str}
        self.working = None
        self.summary = {}

    def start(self):
        self.reset()
        self.active = True
        return self.screen()

    def cancel(self):
        self.reset()
        return self.screen()

    # ---------------------------------------------------------------- actions
    def act(self):
        """Do whatever the big button on the current screen says."""
        if not self.active:
            return self.start()
        s = self.step
        try:
            if s == "prepare":
                self.step, self.result = "focus", None
            elif s == "focus":
                self._run("focus", self._focus)
            elif s == "geometry":
                self._run("geometry", self._geometry)
            elif s == "baseline":
                self._run("baseline", self._baseline_round)
            elif s == "scale":
                self._run("scale", self._scale)
            elif s == "check":
                self._run("check", self._check)
            elif s == "done":
                self.reset()
        except Exception as e:  # noqa: BLE001
            self.working = None
            self.result = {"ok": False, "text": f"Something went wrong: {e}. Press the button to try again."}
        return self.screen()

    def skip(self):
        """Scale step only: skip this slot (its scale is taken from the slots that were measured)."""
        if self.step == "scale":
            self.result = {"ok": True, "text": f"Slot {self.slot} skipped. Put the normal cell back in slot {self.slot}."}
            self._next_slot()
        elif self.step == "focus":
            self.step, self.result = "geometry", {"ok": True, "text": "Focus skipped."}
        return self.screen()

    def _run(self, kind, fn):
        self.working = WORKING[kind]
        try:
            fn()
        finally:
            self.working = None

    def _sim(self, action, slot=0):
        if self.ops.is_synthetic():
            self.ops.sim(action, slot)

    # -------------------------------------------------------------- the steps
    def _focus(self):
        r = self.ops.focus()
        note = r.get("note", "") or ""
        if "ignores manual focus" in note:
            text = "This camera focuses by itself. That's fine."
        elif "closer than the lens can focus" in note:
            text = "Focus set, but the cells may be a little close for this camera. That's OK."
        else:
            text = "✓ Focus set."
        self.result = {"ok": True, "text": text}
        self.step = "geometry"

    def _geometry(self):
        r = self.ops.geometry()
        problems = []
        for w in r.get("warnings", []) or []:
            if "too close to the cell tops" in w:
                problems.append("The lens is level with the cell tops. Raise the camera so the lens is a few mm "
                                "ABOVE the cells (or clearly below them), then press Retry.")
            elif "screen edges not found" in w:
                problems.append("I can't see the whole orange screen. Turn or move the camera back so the full "
                                "width of the screen is in the picture (use Camera placement), then Retry.")
            elif "usable columns" in w:
                slot = w.split(":")[0].replace("slot", "").strip()
                problems.append(f"Slot {slot} is hard to see. Check nothing in front of it blocks the view "
                                "(cables, the hub, a hand) and that the cell is pushed down, then Retry.")
            elif "fit error" in w:
                problems.append("The picture doesn't match the expected layout. Check all four cells are in their "
                                "slots, nothing is in front of them, and the camera points at the screen. Then Retry.")
            else:
                problems.append(w)
        if problems:
            self.result = {"ok": False, "text": " ".join(problems)}
            return                                          # stay on this step: the button becomes "Retry"
        self.summary["lens_z"] = round(r["cam"]["Zc"], 1) if r.get("cam") else None
        self.result = {"ok": True, "text": "✓ I can see the screen and all four cells clearly."}
        self.ops.baseline_reset()
        self.round = 0
        self.step = "baseline"

    def _baseline_round(self):
        if self.round > 0:
            self._sim("reseat")
        low = set()
        for _ in range(PER_ROUND):
            r = self.ops.baseline_add()
            if not r.get("ok"):
                self.result = {"ok": False, "text": r.get("error", "Could not take a picture.") + " Press the button to try again."}
                return
            for i, c in enumerate(r.get("edge_conf") or []):
                if c is not None and c < 0.6:
                    low.add(i + 1)
        self.round += 1
        if low:
            self.result = {"ok": True, "text": (f"Round {self.round} done, but slot(s) {sorted(low)} look a bit unclear "
                                               "(dim or blurry). Check nothing shines on the cell tops and the screen "
                                               "is evenly lit. You can carry on.")}
        else:
            self.result = {"ok": True, "text": f"✓ Round {self.round} of {ROUNDS} done."}
        if self.round >= ROUNDS:
            self.working = WORKING["finish"]
            r = self.ops.baseline_finish()
            if not r.get("ok"):
                self.result = {"ok": False, "text": r.get("error", "Could not finish.")}
                return
            # what matters is how much ONE cell varies compared with its three neighbours (all four settling
            # together, or the camera shifting slightly, cancels out in the measurement)
            sig = r.get("sigma_rel_mm")
            if sig is None:
                sig = max(r.get("sigma_reseat_mm") or [0])
            alarm = r.get("t_alarm_mm")
            self.summary.update(sigma=round(sig, 3), alarm=alarm, ai=r.get("ai_text", ""))
            if sig <= 0.06:
                quality = "excellent"
            elif sig <= 0.12:
                quality = "good"
            elif sig <= 0.20:
                quality = ("acceptable: the 0.6 mm cell is still clearly caught, smaller swellings less so. Pushing "
                           "the cells down more consistently would improve it")
            else:
                self.result = {"ok": False, "text": (
                    f"The cells vary too much compared with each other ({sig:.2f} mm; it should be under 0.2 mm), "
                    "so a 0.6 mm cell couldn't be told apart reliably. Push each cell straight down until it stops, "
                    "the same way every time, and check nothing is stuck under a cell. "
                    "Press the button to redo this step from round 1.")}
                self.ops.baseline_reset()
                self.round = 0
                return
            self.result = {"ok": True, "text": (f"✓ Normal cells learned. Cell-to-cell variation {sig:.2f} mm ({quality}). "
                                               f"A cell will be flagged as swollen from {alarm} mm. {r.get('ai_text', '')}")}
            self.step, self.slot, self.rep = "scale", 1, 0

    def _scale(self):
        if self.rep == 0:
            if self.slot > 1:
                self._sim("normal")
            self._sim("fault", self.slot)
        else:
            self._sim("reseat")
        r = self.ops.scale(self.slot)
        if not r.get("ok"):
            err = r.get("error", "")
            if "only" in err and "higher" in err:
                text = (f"I don't see a taller cell in slot {self.slot}. Make sure the TALLER cell (42.6 mm) is in "
                        f"slot {self.slot}, pushed fully down, and the other three slots have normal cells. Then Measure again.")
            elif "edge was not found" in err:
                text = "Something blocked the view. Hands away, then Measure again."
            else:
                text = err + " Measure again."
            self.result = {"ok": False, "text": text}
            return
        self.rep += 1
        rel, k = r.get("raw_rel_mm"), r.get("k_scale")
        neigh = max(abs(x) for x in (r.get("others_mm") or [0]))
        ok_n = neigh < 0.1
        self.result = {"ok": ok_n, "text": (
            ("✓ " if ok_n else "") + f"Slot {self.slot}, try {self.rep}: the taller cell measured +{rel:.2f} mm (it is really +0.60)."
            + ("" if ok_n else f" The other slots moved by {neigh:.2f} mm, more than expected: check they are pushed down."))}
        if self.rep >= SCALE_REPS:
            self._next_slot()

    def _next_slot(self):
        self.rep = 0
        if self.slot >= 4:
            self.step = "check"
        else:
            self.slot += 1

    def _check(self):
        self._sim("normal")
        r = self.ops.test_scan()
        v = r.get("verdict")
        if v == "OK":
            self.result = {"ok": True, "text": "✓ Test scan: OK. The station is calibrated and ready."}
            self.step = "done"
        elif v == "RESEAT" or v == "SWELL" or v == "WATCH":
            self.result = {"ok": False, "text": (f"Test scan says {v} for slot(s) {r.get('verdict_slots')}. Make sure the "
                                                "fault cell is out and every cell is pushed fully down, then press Test scan again.")}
        else:
            self.result = {"ok": False, "text": f"Test scan says {v}: {r.get('reason', '')}. {r.get('action', '')} Then press Test scan again."}

    # ---------------------------------------------------------------- display
    def screen(self) -> dict:
        s, slot = self.step, self.slot
        scr = {"active": self.active, "step": s, "step_no": STEP_NAMES.get(s), "steps_total": 5,
               "working": self.working, "result": self.result, "slot": None, "progress": None,
               "can_skip": False, "summary": self.summary}
        if not self.active:
            scr.update(title="Calibration", do=["Calibration teaches the station what normal cells look like and how "
                                                "big 0.6 mm is. Do it once after setting up (about 20 minutes)."],
                       button="Start calibration")
            return scr
        if s == "prepare":
            scr.update(title="Get ready", button="I'm ready, start", do=[
                "Put the 4 NORMAL cells (42.0 mm) in slots 1, 2, 3 and 4. Keep the TALLER fault cell (42.6 mm) aside for now.",
                "Push each cell firmly and straight down into its slot.",
                "Place the camera with the Camera placement panel until it shows ✅ (if you haven't yet).",
                "Set the room lights the way they will be during the demo.",
                "While a step is running: keep hands, heads and cables out of the camera's view."])
        elif s == "focus":
            scr.update(title="Sharpen the picture", button="Retry" if self._failed() else "Sharpen",
                       do=["Don't touch anything.", "Press the button. It takes about 1 minute."], can_skip=True)
        elif s == "geometry":
            scr.update(title="Learn the layout", button="Retry" if self._failed() else "Learn layout",
                       do=["Don't touch anything.",
                           "Press the button. The station finds the screen, the four cells and exactly where the camera is (up to a minute)."])
        elif s == "baseline":
            if self.round == 0:
                do = ["Hands away from the cells.", "Press the button: it takes 4 pictures (about 10 seconds)."]
            else:
                do = ["Lift ALL FOUR cells a few millimetres and push each one firmly back down. "
                      "(This shows the station how much a cell can vary when it is put back.)",
                      "Hands away, then press the button."]
            scr.update(title=f"Learn what normal cells look like: round {self.round + 1} of {ROUNDS}",
                       button="Take 4 pictures", do=do, progress=[self.round, ROUNDS])
        elif s == "scale":
            if self.rep == 0:
                do = []
                if slot > 1:
                    do.append(f"Take the taller cell out of slot {slot - 1} and put the NORMAL cell back into slot {slot - 1}.")
                do += [f"Take the normal cell OUT of slot {slot} and put it aside.",
                       f"Put the TALLER fault cell (42.6 mm) into slot {slot} and push it firmly down.",
                       "Hands away, then press Measure."]
            else:
                do = [f"Lift the taller cell in slot {slot} slightly and push it firmly back down.",
                      "Hands away, then press Measure."]
            scr.update(title=f"Show it what 0.6 mm looks like: slot {slot}, try {self.rep + 1} of {SCALE_REPS}",
                       button="Measure", do=do, slot=slot, can_skip=True,
                       progress=[(slot - 1) * SCALE_REPS + self.rep, 4 * SCALE_REPS])
        elif s == "check":
            scr.update(title="Final test", button="Test scan", do=[
                "Take the taller cell out of slot 4 and put the NORMAL cell back in.",
                "All four NORMAL cells in place, pushed down. Hands away.",
                "Press Test scan. It should say OK."])
        elif s == "done":
            sm = self.summary
            scr.update(title="Calibration complete ✓", button="Close", do=[
                f"Cell-to-cell variation: {sm.get('sigma', '–')} mm. A cell is flagged as swollen from {sm.get('alarm', '–')} mm.",
                "Scan any time: SCAN button on the dashboard, or a short press on the knob.",
                "If the camera gets knocked: use Camera placement, or Re-anchor."])
        return scr

    def _failed(self):
        return bool(self.result and not self.result.get("ok"))
