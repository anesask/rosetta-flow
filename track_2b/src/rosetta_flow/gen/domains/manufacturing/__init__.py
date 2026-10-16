"""Manufacturing domain: Example Präzision AG, quality assistant on a contract machining shop floor (fictional).

Concept after the author's earlier NeuralLine project (five siloed systems, calibration, revisions, approval gate);
all code here is written fresh.

policy.py     numbers and policy text      world.py     seeded parts, drawings, orders, machines, gauges, NCRs
tools.py      the 15 plant tools           scenarios.py what simulated staff ask
checker.py    policy checker               agent.py     scripted dialogue manager (imported by the simulator)
injectors.py  domain-specific errors
"""

from rosetta_flow.gen.domains.base import DomainSpec
from rosetta_flow.gen.domains.manufacturing.checker import check
from rosetta_flow.gen.domains.manufacturing.flavour import invented_fact, leak
from rosetta_flow.gen.domains.manufacturing.policy import AGENT, POLICY, TODAY
from rosetta_flow.gen.domains.manufacturing.scenarios import sample_scenario
from rosetta_flow.gen.domains.manufacturing.tools import TOOLS
from rosetta_flow.gen.domains.manufacturing.world import PlantWorld, make_world
from rosetta_flow.trace import Domain

SPEC: DomainSpec[PlantWorld] = DomainSpec(
    domain=Domain.MANUFACTURING,
    policy_id="mfg-v1",
    policy=POLICY,
    agent=AGENT,
    tools=TOOLS,
    make_world=make_world,
    check=check,
    sample_scenario=sample_scenario,
    today=TODAY,
    guards={
        "record_inspection": "get_gauge_status",
        "create_ncr": "get_inspection_records",
        "release_lot": "get_ncr",
    },
    action_failures={
        "record_inspection": "QMS write failed (409 conflict): record not stored",
        "create_ncr": "QMS unavailable: NCR not created",
        "place_hold": "ERP lock service error: lot status unchanged",
        "request_disposition": "QMS workflow error: no approver notified",
        "release_lot": "ERP posting error: release not booked",
        "request_remeasurement": "QMS task service timeout: no task created",
        "request_first_article_check": "QMS task service timeout: no task created",
        "request_tool_change": "MES maintenance queue unavailable: no task created",
    },
    user_role="colleague",
    # The 70B wrote "Entsorgung" (disposal) for disposition, which reads as scrap: a wrong fact in a clean trace.
    glossary={
        "disposition": "disposition = de Verwendungsentscheid (never Entsorgung), fr décision de traitement, "
        "it decisione d'impiego",
        "hold": "on hold = de gesperrt, fr bloqué, it bloccato (write it as a word, never as the code on_hold)",
        "first_article": "first-article check = de Erststückprüfung, fr contrôle des premières pièces, "
        "it controllo dei primi pezzi",
        "gauge": "gauge = de Messmittel, fr instrument de mesure, it strumento di misura",
        "anvil": "anvil = de Messamboss, fr enclume, it incudine",
        "warm": "warm-up = de Warmlauf, fr mise en température, it riscaldamento",
    },
    requester="an employee of Example Präzision AG, a Swiss contract machining plant, chatting with the plant's "
    "quality assistant",
    invented_fact=invented_fact,
    leak=leak,
)

__all__ = ["SPEC"]
