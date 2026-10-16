"""Seeded fictional shop: customers in four languages, localised catalogue, orders in every delivery state."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from rosetta_flow.gen.domains.refunds.policy import LOST_PARCEL_DAYS, TODAY
from rosetta_flow.gen.names import LANGUAGE_WEIGHTS, NAMES
from rosetta_flow.trace import Language

# Fictional catalogue; names localised because the order confirmation is in the customer's language.
CATALOGUE: list[tuple[str, float, dict[Language, str]]] = [
    (
        "BAG-30",
        89.90,
        {
            "de": "Wanderrucksack 30 L",
            "fr": "Sac de randonnée 30 L",
            "it": "Zaino da escursione 30 L",
            "en": "Hiking backpack 30 L",
        },
    ),
    (
        "COF-01",
        349.00,
        {
            "de": "Kaffeevollautomat",
            "fr": "Machine à café automatique",
            "it": "Macchina da caffè automatica",
            "en": "Bean-to-cup coffee machine",
        },
    ),
    (
        "HP-BT",
        129.90,
        {"de": "Bluetooth-Kopfhörer", "fr": "Casque Bluetooth", "it": "Cuffie Bluetooth", "en": "Bluetooth headphones"},
    ),
    (
        "LAP-14",
        1199.00,
        {
            "de": "Laptop 14 Zoll",
            "fr": "Ordinateur portable 14 pouces",
            "it": "Portatile 14 pollici",
            "en": "14-inch laptop",
        },
    ),
    ("HEL-V", 79.90, {"de": "Velohelm", "fr": "Casque de vélo", "it": "Casco da bici", "en": "Bike helmet"}),
    (
        "RAC-4",
        119.00,
        {
            "de": "Raclette-Ofen für 4",
            "fr": "Four à raclette pour 4",
            "it": "Fornetto per raclette 4",
            "en": "Raclette grill for 4",
        },
    ),
    ("JAC-W", 229.00, {"de": "Winterjacke", "fr": "Veste d'hiver", "it": "Giacca invernale", "en": "Winter jacket"}),
    ("SW-2", 299.00, {"de": "Smartwatch", "fr": "Montre connectée", "it": "Smartwatch", "en": "Smartwatch"}),
    ("FON-6", 59.90, {"de": "Fondue-Set", "fr": "Service à fondue", "it": "Set per fonduta", "en": "Fondue set"}),
    ("LMP-F", 149.00, {"de": "Stehlampe", "fr": "Lampadaire", "it": "Lampada da terra", "en": "Floor lamp"}),
    ("BUG-K", 649.00, {"de": "Kinderwagen", "fr": "Poussette", "it": "Passeggino", "en": "Pram"}),
    (
        "DRL-18",
        159.00,
        {
            "de": "Akku-Bohrschrauber",
            "fr": "Perceuse-visseuse sans fil",
            "it": "Trapano avvitatore a batteria",
            "en": "Cordless drill",
        },
    ),
]


@dataclass
class Customer:
    id: str
    name: str
    email: str
    language: Language


@dataclass
class Item:
    sku: str
    name: str
    qty: int
    unit_price_chf: float


@dataclass
class Order:
    id: str
    customer_id: str
    items: list[Item]
    order_date: date
    status: str  # delivered | in_transit | returned
    shipped_date: date
    delivery_date: date | None
    tracking_id: str
    refunded_chf: float = 0.0

    @property
    def amount_chf(self) -> float:
        return round(sum(i.qty * i.unit_price_chf for i in self.items), 2)


@dataclass
class RefundsWorld:
    seed: int
    today: date
    customers: dict[str, Customer]
    orders: dict[str, Order]
    refunds: list[dict[str, Any]] = field(default_factory=list)
    vouchers: list[dict[str, Any]] = field(default_factory=list)
    tickets: list[dict[str, Any]] = field(default_factory=list)


def make_world(seed: int, n_customers: int = 40) -> RefundsWorld:
    rng = random.Random(seed)
    customers: dict[str, Customer] = {}
    orders: dict[str, Order] = {}
    langs, weights = zip(*LANGUAGE_WEIGHTS.items(), strict=True)
    for _ in range(n_customers):
        lang: Language = rng.choices(langs, weights)[0]
        first, last = rng.choice(NAMES[lang][0]), rng.choice(NAMES[lang][1])
        cid = _unique(rng, customers, "C-", 5)
        local = f"{first}.{last}".lower().translate(str.maketrans("éèàç", "eeac"))
        customers[cid] = Customer(cid, f"{first} {last}", f"{local}{rng.randint(1, 99)}@mail.example", lang)
        for _ in range(rng.randint(1, 4)):
            oid = _unique(rng, orders, "A-", 4)
            orders[oid] = _make_order(rng, oid, customers[cid])
    return RefundsWorld(seed, TODAY, customers, orders)


def _unique(rng: random.Random, taken: dict[str, Any], prefix: str, digits: int) -> str:
    if len(taken) >= 9 * 10 ** (digits - 1) // 2:
        raise ValueError(f"id space {prefix}{'#' * digits} too full for rejection sampling")
    while (key := f"{prefix}{rng.randrange(10 ** (digits - 1), 10**digits)}") in taken:
        pass
    return key


def _make_order(rng: random.Random, oid: str, customer: Customer) -> Order:
    picks = rng.sample(CATALOGUE, k=rng.choice((1, 1, 1, 2, 2, 3)))
    items = [Item(sku, names[customer.language], rng.choice((1, 1, 1, 2)), price) for sku, price, names in picks]
    order_date = TODAY - timedelta(days=rng.randint(1, 90))
    shipped = order_date + timedelta(days=rng.randint(0, 2))
    roll = rng.random()
    if roll < 0.12 and (TODAY - shipped).days > LOST_PARCEL_DAYS:
        status, delivered = "in_transit", None  # stuck parcel
    elif (TODAY - shipped).days < 3:
        status, delivered = "in_transit", None
    else:
        status, delivered = "delivered", min(TODAY, shipped + timedelta(days=rng.randint(1, 4)))
    tracking = f"EX{rng.randrange(10**9, 10**10)}CH"
    order = Order(oid, customer.id, items, order_date, status, shipped, delivered, tracking)
    if status == "delivered" and rng.random() < 0.08:
        order.refunded_chf = order.amount_chf  # already refunded earlier
    return order
