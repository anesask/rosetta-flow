"""Scripted shop-floor quality assistant for Example Präzision AG: a policy-correct dialogue manager over the plant
systems. Identifiers and measured values are taken from the requester's text only when they literally appear in it,
so a misread never puts a number into the trace that nobody said."""

from __future__ import annotations

import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, create_model

from rosetta_flow.gen.domains.manufacturing import policy
from rosetta_flow.gen.domains.manufacturing.scenarios import FAMILY
from rosetta_flow.gen.domains.manufacturing.world import plausible_reading
from rosetta_flow.gen.numbers import as_float, number_tokens, number_values
from rosetta_flow.gen.scripted import ScriptedAgent, plain_dashes

_IDS = {
    "work_order_id": (re.compile(r"\bWO[-\s]?(\d{5})\b", re.IGNORECASE), "WO-"),
    "lot_id": (re.compile(r"\bL[-\s]?(\d{4})\b", re.IGNORECASE), "L-"),
    "machine_id": (re.compile(r"\bMC[-\s]?(\d{2})\b", re.IGNORECASE), "MC-"),
    "gauge_id": (re.compile(r"\bMM[-\s]?(\d{4})\b", re.IGNORECASE), "MM-"),
}


class RequestRead(BaseModel):
    """What the assistant understands from one message of plant staff."""

    model_config = ConfigDict(extra="forbid")

    topic: Literal["measurement", "release", "restart", "other"]
    work_order_id: str | None
    lot_id: str | None
    machine_id: str | None
    gauge_id: str | None
    measured_mm: str | None
    unit_number: int | None
    characteristic_words: str | None
    pushes_back: bool


READ_INSTRUCTION = (
    "You analyse messages from staff of a Swiss machining plant to its quality assistant. Read the latest message in "
    "the context of the conversation and fill the fields. topic: measurement (a measured value to judge), release "
    "(whether a lot may ship), restart (whether a machine may continue after a stop or tool problem), else other. "
    "Identifiers only if written in the message: work orders look like WO-24017, lots like L-4417, machines like "
    "MC-03, gauges like MM-0231; else null. measured_mm: the measured value exactly as written, else null. "
    "unit_number: the number of the measured part or unit if given. characteristic_words: the feature measured in "
    "the writer's words (e.g. Bohrung, alésage, length). pushes_back: they disagree with or want to bypass a "
    "decision the assistant already explained."
)


class PlantAgent(ScriptedAgent):
    NOTES: ClassVar[dict[str, tuple[str, ...]]] = {
        "drawing": (
            "{wo} runs part {part} on drawing rev {rev}; judging against rev {rev}, not the latest.",
            "Q2: limits come from the work order's revision ({rev}).",
            "Looking up drawing {part} rev {rev} from the work order.",
        ),
        "gauge": (
            "Q1: checking calibration of {gauge} before using the value.",
            "Value {value} mm from {gauge}. Gauge status first.",
        ),
        "gauge_invalid": (
            "{gauge} is {status}. The value cannot be used; asking for a re-measurement, nothing recorded.",
            "Q1: {gauge} {status}, no verdict on this measurement.",
        ),
        "inside": ("{value} mm is within {lower} to {upper} mm. Recording as pass.",),
        "outside": (
            "{value} mm is outside {lower} to {upper} mm. Q3: record fail, NCR, hold, disposition request.",
            "Out of tolerance ({value} vs {lower}..{upper}). Starting the NCR path.",
        ),
        "scope": (
            "Last passing inspection at unit {last}; NCR scope units {first} to {to}.",
            "Scope from {first} (after last pass {last}) to {to}.",
        ),
        "lot": ("Checking lot {lot} in ERP before saying anything about shipping.",),
        "ncr": (
            "Lot on hold under {ncr}. Q4: only an approved use_as_is allows a release.",
            "Reading {ncr} for the disposition and approval.",
        ),
        "machine": (
            "Checking today's events and tool life on {machine}.",
            "Q5/Q6: stop duration and tool life on {machine} first.",
        ),
        "restart_actions": (
            "Stop {stop} min, worn tools {worn}. Requesting what the policy needs before the next part.",
        ),
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.topic: str | None = None
        self.known: dict[str, Any] = {}
        self.wo: dict[str, Any] | None = None
        self.drawing: dict[str, Any] | None = None
        self.char: dict[str, Any] | None = None
        self.outcome: str | None = None
        self.summary: dict[str, Any] = {}

    # entry point

    def respond(self, customer_text: str, customer_done: bool = False) -> str:
        if customer_done and self.outcome:
            return self.say("thank the colleague briefly and close the conversation")
        text = plain_dashes(customer_text)
        read = self.read(RequestRead, READ_INSTRUCTION, text)
        self._learn(read, text)
        if self.topic is None:
            self.topic = self._topic(read)
        if self.outcome is None:
            return {"measurement": self._measurement, "release": self._release, "restart": self._restart}[self.topic]()
        if read and read.pushes_back:
            return self.say(
                "explain calmly that this decision is not the assistant's to change: the policy requires it, and "
                "only the quality engineer can decide a disposition or approve a release",
                **self.summary,
            )
        return self.say(
            "briefly say the matter stands as already explained and ask if there is anything else; do not confirm "
            "anything the colleague reports doing, the systems have not shown it",
            **self.summary,
        )

    def _must(self, name: str, **args: Any) -> tuple[str, Any]:
        """A call that cannot fail in a consistent world; if it does, the run is dropped, not kept half-done."""
        status, result = self.tool(name, **args)
        if status != "ok":
            raise RuntimeError(f"{name} failed unexpectedly: {result}")
        return status, result

    # understanding the requester

    def _learn(self, read: RequestRead | None, text: str) -> None:
        for key, (rx, prefix) in _IDS.items():
            if m := rx.search(text):
                self.known[key] = f"{prefix}{m.group(1)}"
        values = number_values(text)
        written = {as_float(tok.group()) for tok in number_tokens(text)}  # exact, number_values rounds to cents
        given = next(number_tokens(read.measured_mm), None) if read and read.measured_mm else None  # "44,94 mm"
        if given and (v := as_float(given.group())) is not None and v in written:
            self.known["measured_mm"] = v
        if read and read.unit_number and float(read.unit_number) in values:
            self.known["unit"] = read.unit_number
        if read and read.characteristic_words:
            self.known["characteristic_words"] = read.characteristic_words

    def _topic(self, read: RequestRead | None) -> str:
        # What the message contains decides; the model's topic label only breaks ties (it called measurements
        # "release" questions in the pilot and the agent then asked for a lot number nobody had).
        if "measured_mm" in self.known or "gauge_id" in self.known:
            return "measurement"
        if "lot_id" in self.known:
            return "release"
        if "machine_id" in self.known and "work_order_id" not in self.known:
            return "restart"
        if read and read.topic != "other":
            return read.topic
        return FAMILY[self.scenario.intent]

    def _ask(self, missing: list[str], **facts: Any) -> str:
        known = {k: v for k, v in self.known.items() if k != "characteristic_words"}
        return self.say(
            "ask only for the missing information, in one short question, and say why it is needed; do not ask "
            "again for anything already known",
            missing=missing,
            already_known=known,
            **facts,
        )

    def _pick_characteristic(self) -> dict[str, Any] | None:
        assert self.drawing is not None
        chars = self.drawing["characteristics"]
        ids = tuple(c["id"] for c in chars)
        model = create_model(
            "CharacteristicRead",
            __config__=ConfigDict(extra="forbid"),
            characteristic=(Literal[ids] | None, ...),  # type: ignore[valid-type]
        )
        listing = "; ".join(f"{c['id']} = {c['name']}" for c in chars)
        read = self.read(
            model,
            f"The plant colleague measured a feature of this part. Drawing characteristics: {listing}. Pick the id "
            "of the characteristic they measured, or null if the conversation does not make it clear.",
            str(self.known.get("characteristic_words") or ""),
        )
        chosen = getattr(read, "characteristic", None) if read else None
        # A 45 mm reading cannot be the 12 mm bore: the mapper once guessed that and the agent opened an NCR on the
        # wrong characteristic, a wrong verdict the checker cannot see. Plausibility by value decides instead.
        value = self.known.get("measured_mm")
        plausible = [c for c in chars if value is None or plausible_reading(value, c)]
        picked = next((c for c in plausible if c["id"] == chosen), None)
        return picked or (plausible[0] if len(plausible) == 1 else None)

    # measurement (Q1, Q2, Q3)

    def _measurement(self) -> str:
        k = self.known
        missing = [
            n
            for n, key in (
                ("work order number", "work_order_id"),
                ("measured value in mm", "measured_mm"),
                ("gauge id", "gauge_id"),
            )
            if key not in k
        ]
        if missing:
            return self._ask(missing)
        if self.wo is None:
            status, wo = self.tool("get_work_order", work_order_id=k["work_order_id"])
            if status != "ok":
                k.pop("work_order_id")
                return self._ask(["work order number"], problem=f"{wo}")
            self.wo = wo
        wo = self.wo
        if self.drawing is None:
            self.note("drawing", wo=wo["work_order_id"], part=wo["part_no"], rev=wo["drawing_revision"])
            _, self.drawing = self._must("get_drawing", part_no=wo["part_no"], revision=wo["drawing_revision"])
        if self.char is None and (char := self._pick_characteristic()) is not None:
            self.char = char
        missing = ([] if self.char else ["which characteristic was measured"]) + (
            [] if "unit" in k else ["unit number"]
        )
        if missing:
            names = [c["name"] for c in self.drawing["characteristics"]] if not self.char else None
            return self._ask(missing, characteristics_on_drawing=names) if names else self._ask(missing)
        c, value, unit = self.char, k["measured_mm"], k["unit"]
        if unit > wo["qty_made"]:
            k.pop("unit")
            return self._ask(["unit number"], problem=f"only {wo['qty_made']} units made so far")

        self.note("gauge", gauge=k["gauge_id"], value=value)
        status, gauge = self.tool("get_gauge_status", gauge_id=k["gauge_id"])
        if status != "ok":
            k.pop("gauge_id")
            return self._ask(["gauge id"], problem=f"{gauge}")
        facts: dict[str, Any] = {
            "work_order_id": wo["work_order_id"],
            "characteristic": c["name"],
            "measured_mm": value,
            "unit": unit,
            "gauge_id": gauge["gauge_id"],
        }
        if gauge["status"] != "valid":
            self.note("gauge_invalid", gauge=gauge["gauge_id"], status=gauge["status"])
            _, task = self._must(
                "request_remeasurement",
                work_order_id=wo["work_order_id"],
                characteristic=c["id"],
                unit=unit,
                reason=f"gauge {gauge['gauge_id']} {gauge['status']}",
            )
            self.outcome = "remeasure"
            self.summary = facts | {"gauge_status": gauge["status"], "task_id": task["task_id"]}
            why = (
                "the gauge is blocked (give the reason from the note)"
                if gauge["status"] == "blocked"
                else "the gauge's calibration expired (give the due date it missed)"
            )
            extra = (
                {"gauge_note": gauge["note"]} if gauge.get("note") else {"calibration_due": gauge["calibration_due"]}
            )
            return self.say(
                f"say the measurement cannot be used because {why}; nothing was recorded or decided; a "
                "re-measurement with a calibrated gauge was requested (task id)",
                **self.summary,
                **extra,
            )

        facts |= {"lower_mm": c["lower_mm"], "upper_mm": c["upper_mm"], "drawing_revision": self.drawing["revision"]}
        if self.drawing["revision_status"] != "current":
            facts["note"] = "the work order was released on this older revision, so its limits apply"
        inside = c["lower_mm"] - 1e-9 <= value <= c["upper_mm"] + 1e-9
        if inside:
            self.note("inside", value=value, lower=c["lower_mm"], upper=c["upper_mm"])
            _, rec = self._must(
                "record_inspection",
                work_order_id=wo["work_order_id"],
                characteristic=c["id"],
                unit=unit,
                value_mm=value,
                gauge_id=gauge["gauge_id"],
                result="pass",
            )
            self.outcome, self.summary = "pass", facts | {"record_id": rec["record_id"]}
            return self.say(
                "confirm the part is within the drawing limits of the work order's revision and that the "
                "measurement was recorded as pass; production can continue",
                **self.summary,
            )
        return self._out_of_tolerance(wo, c, value, unit, gauge["gauge_id"], facts)

    def _out_of_tolerance(
        self, wo: dict[str, Any], c: dict[str, Any], value: float, unit: int, gauge_id: str, facts: dict[str, Any]
    ) -> str:
        self.note("outside", value=value, lower=c["lower_mm"], upper=c["upper_mm"])
        wid = wo["work_order_id"]
        self._must(
            "record_inspection",
            work_order_id=wid,
            characteristic=c["id"],
            unit=unit,
            value_mm=value,
            gauge_id=gauge_id,
            result="fail",
        )
        _, recs = self._must("get_inspection_records", work_order_id=wid, characteristic=c["id"])
        first = recs["last_pass_unit"] + 1
        self.note("scope", last=recs["last_pass_unit"], first=first, to=unit)
        _, ncr = self._must(
            "create_ncr",
            lot_id=wo["lot_id"],
            characteristic=c["id"],
            measured_mm=value,
            gauge_id=gauge_id,
            scope_from_unit=first,
            scope_to_unit=unit,
        )
        self._must("place_hold", lot_id=wo["lot_id"], ncr_id=ncr["ncr_id"])
        _, disp = self._must("request_disposition", ncr_id=ncr["ncr_id"])
        self.outcome = "ncr"
        self.summary = facts | {
            "ncr_id": ncr["ncr_id"],
            "lot_id": wo["lot_id"],
            "lot_status": "on_hold",
            "scope_from_unit": first,
            "scope_to_unit": unit,
            "scope_units": ncr["scope_units"],
            "disposition_decided_by": disp["assigned_to"],
        }
        return self.say(
            "say the part is outside the drawing limits; an NCR was opened covering the units in scope (since the "
            "last passing inspection), the lot is on hold, and the quality engineer decides the disposition; the "
            "affected parts must not be used or shipped until then",
            **self.summary,
        )

    # release (Q4)

    def _release(self) -> str:
        if "lot_id" not in self.known:
            return self._ask(["lot number"])
        lid = self.known["lot_id"]
        self.note("lot", lot=lid)
        status, lot = self.tool("get_lot", lot_id=lid)
        if status != "ok":
            self.known.pop("lot_id")
            return self._ask(["lot number"], problem=f"{lot}")
        facts = {"lot_id": lot["lot_id"], "customer": lot["customer"], "due_date": lot["due_date"]}
        if lot["status"] != "on_hold" or not lot["ncr_id"]:
            self.outcome, self.summary = "status", facts | {"lot_status": lot["status"]}
            return self.say("tell the colleague the lot's current status; no release action is needed", **self.summary)
        self.note("ncr", ncr=lot["ncr_id"])
        _, ncr = self._must("get_ncr", ncr_id=lot["ncr_id"])
        facts |= {"ncr_id": ncr["ncr_id"], "ncr_status": ncr["status"], "disposition": ncr["disposition"]}
        if ncr["status"] == "approved" and ncr["disposition"] == "use_as_is":
            _, rel = self._must("release_lot", lot_id=lot["lot_id"])
            self.outcome = "released"
            self.summary = facts | {
                "approved_by": ncr["approved_by"],
                "approved_on": ncr["approved_on"],
                "lot_status": rel["status"],
            }
            return self.say(
                "confirm the lot was released for shipping because the quality engineer approved the disposition "
                "use as is",
                **self.summary,
            )
        if ncr["status"] == "approved":
            self.outcome = "not_releasable"
            self.summary = facts | {"approved_by": ncr["approved_by"], "lot_status": "on_hold"}
            return self.say(
                "explain the lot cannot be released: the approved disposition is not use as is (say which), so it "
                "stays on hold",
                **self.summary,
            )
        self.outcome = "waiting"
        self.summary = facts | {"lot_status": "on_hold"}
        return self.say(
            "explain the lot stays on hold and is not released: the NCR has no approved disposition yet, and only "
            "the quality engineer can approve it; the assistant cannot release it",
            **self.summary,
        )

    # restart (Q5, Q6)

    def _restart(self) -> str:
        if "machine_id" not in self.known:
            return self._ask(["machine id"])
        mid = self.known["machine_id"]
        self.note("machine", machine=mid)
        status, ev = self.tool("get_machine_events", machine_id=mid)
        if status != "ok":
            self.known.pop("machine_id")
            return self._ask(["machine id"], problem=f"{ev}")
        stop = _open_stop(ev["events_today"])
        worn = [t for t in ev["tools"] if t["parts_since_change"] >= t["rated_life"]]
        wo_id = self.known.get("work_order_id") or ev["current_work_order"]
        facts: dict[str, Any] = {"machine_id": ev["machine_id"], "work_order_id": wo_id}
        if stop is not None:
            facts["stop_minutes"] = stop
        long_stop = (stop or 0) >= policy.SPINDLE_STOP_MIN
        if worn or long_stop:
            self.note("restart_actions", stop=stop or 0, worn=[t["tool_id"] for t in worn] or "none")
        for t in worn:
            _, task = self._must("request_tool_change", machine_id=ev["machine_id"], tool_id=t["tool_id"])
            facts.setdefault("tool_changes", []).append(
                {
                    "tool_id": t["tool_id"],
                    "tool": t["description"],
                    "parts_since_change": t["parts_since_change"],
                    "rated_life": t["rated_life"],
                    "task_id": task["task_id"],
                }
            )
        if long_stop:
            _, fai = self._must(
                "request_first_article_check",
                machine_id=ev["machine_id"],
                work_order_id=wo_id,
                pieces=policy.FIRST_PIECES_AFTER_STOP,
            )
            facts |= {
                "warmup_min": policy.WARMUP_MIN,
                "first_pieces_to_inspect": policy.FIRST_PIECES_AFTER_STOP,
                "first_article_task_id": fai["task_id"],
            }
        self.summary = facts
        if not (worn or long_stop):
            self.outcome = "continue"
            facts |= {"tools_within_life": True, "stop_limit_min": policy.SPINDLE_STOP_MIN}
            return self.say(
                "say production may continue: the stop was shorter than the warm-up limit and all tools are within "
                "their rated life",
                **facts,
            )
        self.outcome = "restart_conditions"
        # Only the rules that apply: a generic "after a long stop, warm up" made the 70B demand a warm-up after an
        # 8-minute stop, a hidden error in a trace labelled clean.
        steps = []
        if worn:
            steps.append("each worn tool must be changed before the next part (a tool change was requested)")
        if long_stop:
            steps.append(
                "the machine must warm up first and the first pieces must be inspected before production continues "
                "(a first-article check was requested)"
            )
        else:
            steps.append("the stop was short, so no warm-up and no first-article check are needed")
        return self.say("explain what happens before production continues: " + "; ".join(steps), **facts)


def _open_stop(events: list[dict[str, Any]]) -> int | None:
    for e in reversed(events):
        if e.get("event") == "first_article_check" and e.get("result") == "passed":
            return None
        if e.get("event") == "spindle_stop":
            return int(e["duration_min"])
    return None
