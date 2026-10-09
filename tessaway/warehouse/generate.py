# Copyright 2026 Robert H. Mowery III
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Generates the synthetic Tessaway Freight warehouse from a fixed seed.

Tessaway Freight is a fictional mid-size freight broker with a small fleet of
its own. The data models three source systems landed in one warehouse:
transportation management (``tms_*``), carrier billing (``bil_*``) and the
customer portal (``ptl_*``), plus customer master and reference data.

Nothing in the data is broken. Every table is complete and every join key
resolves. What the tables do not carry is meaning: which rows count as a load,
which account is the customer, which clock a time is on. Each of those gaps is
planted on purpose and written down in ``data/TRAPS.md``.

Usage:
    python -m tessaway.warehouse.generate            # writes data/generated/*.ndjson

The same seed always produces the same rows. Nothing here reads the clock.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tessaway.warehouse import schema

SEED = 20261009

# Loads are booked from the first day through the last. The warehouse is a
# snapshot taken at SNAPSHOT: nothing after that moment has happened yet.
FIRST_DAY = date(2026, 1, 2)
LAST_DAY = date(2026, 9, 30)
SNAPSHOT = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)

OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "generated"

Row = dict[str, Any]
Tables = dict[str, list[Row]]

# --- Share of bookings that take each path -----------------------------------
# These are the knobs behind the traps. They were set before any agent ran and
# are not changed afterward.
TEST_SHARE = 0.012  # test loads: flagged, never deleted
VOID_SHARE = 0.020  # entered in error and voided: flagged, never deleted
CANCEL_SHARE = 0.040
RETENDER_SHARE = 0.060  # first carrier falls off; the load appears twice
TWO_DROP_SHARE = 0.10
FLEET_SHARE = 0.12  # hauled by Tessaway's own trucks
CANADA_DEST_SHARE = 0.07
CAD_SHARE_OF_CROSS_BORDER = 0.60
CREDIT_SHARE = 0.05  # invoices later reduced by a credit memo
CAD_PER_USD = 1.37  # used only to size amounts on loads rated in Canadian dollars

# Delivery arrival relative to the end of the appointment window.
ARRIVAL_MIX = [("on_time", 0.83), ("late_minor", 0.09), ("late_major", 0.05), ("late_days", 0.03)]
# Why a late load was late. SHPR is a delay the shipper caused.
LATE_REASONS = [("SHPR", 28), ("CARR", 30), ("WTHR", 12), ("RCVR", 8), ("MECH", 10), (None, 12)]

# Canadian dollar to US dollar, one rate per month.
CAD_TO_USD = {
    1: "0.721400",
    2: "0.718900",
    3: "0.724300",
    4: "0.730500",
    5: "0.735100",
    6: "0.731800",
    7: "0.727600",
    8: "0.723100",
    9: "0.719800",
    10: "0.722500",
}
FUEL_PCT = {
    1: 0.118,
    2: 0.121,
    3: 0.127,
    4: 0.131,
    5: 0.125,
    6: 0.119,
    7: 0.116,
    8: 0.122,
    9: 0.128,
}

US_CITIES = [
    ("Joliet", "IL", "America/Chicago"),
    ("Reno", "NV", "America/Los_Angeles"),
    ("Allentown", "PA", "America/New_York"),
    ("Fresno", "CA", "America/Los_Angeles"),
    ("Kansas City", "MO", "America/Chicago"),
    ("Savannah", "GA", "America/New_York"),
    ("Dallas", "TX", "America/Chicago"),
    ("Houston", "TX", "America/Chicago"),
    ("Laredo", "TX", "America/Chicago"),
    ("Atlanta", "GA", "America/New_York"),
    ("Memphis", "TN", "America/Chicago"),
    ("Columbus", "OH", "America/New_York"),
    ("Indianapolis", "IN", "America/Indiana/Indianapolis"),
    ("Louisville", "KY", "America/Kentucky/Louisville"),
    ("Nashville", "TN", "America/Chicago"),
    ("Charlotte", "NC", "America/New_York"),
    ("Jacksonville", "FL", "America/New_York"),
    ("Harrisburg", "PA", "America/New_York"),
    ("Newark", "NJ", "America/New_York"),
    ("Buffalo", "NY", "America/New_York"),
    ("Detroit", "MI", "America/Detroit"),
    ("Minneapolis", "MN", "America/Chicago"),
    ("Omaha", "NE", "America/Chicago"),
    ("Denver", "CO", "America/Denver"),
    ("Salt Lake City", "UT", "America/Denver"),
    ("Phoenix", "AZ", "America/Phoenix"),
    ("Stockton", "CA", "America/Los_Angeles"),
    ("Riverside", "CA", "America/Los_Angeles"),
    ("Portland", "OR", "America/Los_Angeles"),
    ("Tacoma", "WA", "America/Los_Angeles"),
    ("Boise", "ID", "America/Boise"),
    ("El Paso", "TX", "America/Denver"),
    ("Green Bay", "WI", "America/Chicago"),
    ("St. Louis", "MO", "America/Chicago"),
]
CA_CITIES = [
    ("Brampton", "ON", "America/Toronto"),
    ("Mississauga", "ON", "America/Toronto"),
    ("Montreal", "QC", "America/Toronto"),
    ("Calgary", "AB", "America/Edmonton"),
    ("Edmonton", "AB", "America/Edmonton"),
    ("Winnipeg", "MB", "America/Winnipeg"),
    ("Delta", "BC", "America/Vancouver"),
    ("Moncton", "NB", "America/Moncton"),
]

# Two customers are written by hand because questions name them. A customer
# is three kinds of row: the parent account, the sites that ship, and the
# parties that get the bill.
#   (parent name, segment,
#    [(shipper site name, city, volume weight, bill-to index)], [bill-to names])
ANCHOR_PARENTS: list[tuple[str, str, list[tuple[str, str, float, int]], list[str]]] = [
    (
        "Northgate Foods Group",
        "FOOD",
        [
            ("Northgate Foods - Joliet DC", "Joliet", 2.4, 0),
            ("Northgate Foods - Reno DC", "Reno", 2.0, 0),
            ("Northgate Foods - Allentown DC", "Allentown", 2.2, 0),
            ("Harlow Dairy Co. - Fresno", "Fresno", 2.3, 1),
            ("Sunmeadow Bakeries - Kansas City", "Kansas City", 2.1, 0),
            ("Northgate Foods Canada - Brampton", "Brampton", 1.6, 0),
        ],
        ["Northgate Foods AP Shared Services", "Harlow Dairy Co. Accounts Payable"],
    ),
    (
        "Pellam Paper Corp",
        "PAPR",
        [("Pellam Paper - Savannah Mill", "Savannah", 6.5, 0)],
        ["Pellam Paper Corp Accounts Payable"],
    ),
]

# A freight payment firm: it is the bill-to party for several customers'
# freight but ships nothing itself.
FREIGHT_PAYER = "Ledgerline Freight Payment Services"
FREIGHT_PAYER_BILL_TOS = [
    "Ledgerline Freight Payment - Client Remit A",
    "Ledgerline Freight Payment - Client Remit B",
]
FREIGHT_PAYER_CLIENTS = 9  # generated parents whose freight Ledgerline pays

GENERATED_PARENTS = [
    ("Aldermoor Building Products", "BLDG"),
    ("Brightwater Beverage Co.", "BEVG"),
    ("Calloway Home Goods", "RETL"),
    ("Dunmere Plastics", "INDL"),
    ("Eastlake Automotive Parts", "AUTO"),
    ("Fennick Pet Nutrition", "FOOD"),
    ("Garrow Steel Fabricators", "INDL"),
    ("Hollin & Pryce Furniture", "RETL"),
    ("Ironvale Chemicals", "CHEM"),
    ("Juniper Trail Outfitters", "RETL"),
    ("Kestrel Packaging", "PAPR"),
    ("Larkfield Produce", "FOOD"),
    ("Maritime Tile & Stone", "BLDG"),
    ("Norwick Appliance", "RETL"),
    ("Oakhollow Lumber", "BLDG"),
    ("Parrish Medical Supply", "HLTH"),
    ("Quillon Paints", "CHEM"),
    ("Redfern Agricultural", "AGRI"),
    ("Stonebridge Brewing", "BEVG"),
    ("Tamsin Textiles", "RETL"),
    ("Underhill Seed Co.", "AGRI"),
    ("Varley Electric Components", "INDL"),
    ("Westmark Tire", "AUTO"),
    ("Yarrowdale Dairy Cooperative", "FOOD"),
    ("Zeller Glassworks", "INDL"),
    ("Ashgrove Confections", "FOOD"),
    ("Bexley Industrial Supply", "INDL"),
    ("Cinderford Castings", "INDL"),
    ("Dovetail Cabinetry", "BLDG"),
    ("Elmsworth Paper Goods", "PAPR"),
    ("Farrowgate Feed & Grain", "AGRI"),
    ("Glenhaven Frozen Foods", "FOOD"),
    ("Highmoor Sporting Goods", "RETL"),
    ("Islip Marine Hardware", "INDL"),
    ("Jessamy Cosmetics", "RETL"),
    ("Kirkwall Roofing Systems", "BLDG"),
]
INACTIVE_PARENTS = 2  # the last two generated parents are on file but ship nothing

CARRIER_PREFIXES = [
    "Brightline", "Copper Basin", "Tallgrass", "Ridgeback", "Blue Heron", "Ironwood",
    "Northfork", "Cedar Run", "Summit Pass", "Lakeshore", "Red Mesa", "Prairie Wind",
    "Gulf Coast Star", "Timberline", "Silver Birch", "Eagle Crest", "Stone Harbor", "Highline",
    "Foxglove", "Granite Peak", "Riverbend", "Sandhill", "Black Oak", "Wolf Creek",
    "Marlow", "Kessler", "Dalton Bros", "Whitcombe", "Abernathy", "Voss",
    "Ortega", "Lindqvist", "Okafor", "Brannigan", "Halvorsen", "Petrov",
    "Nakamura", "Castellan", "Three Rivers", "Twin Pines", "Great Basin", "High Plains",
    "Bluegrass", "Bayou", "Keystone State", "Lone Pine", "Maple Leaf", "Tri-County",
    "Crossroads", "Midvale", "Pioneer Trail", "Old Mill", "Cobalt", "Meridian",
    "Vantage Point", "Sorrel", "Anchor Bay", "Harvest Moon", "Frontier Line", "Canyon Rim",
    "Delta Ridge", "Evergreen State", "Fairmont", "Glacier",
]  # fmt: skip
CARRIER_SUFFIXES = [
    "Haulage", "Transport", "Trucking", "Logistics",
    "Freight Lines", "Carriers", "Express", "Motor Lines",
]  # fmt: skip
OWN_FLEET = ("Tessaway Fleet", "TSWF")

CONSIGNEE_WORDS = [
    "Kettle Ridge", "Fallow Creek", "Marrow Bend", "Tanner Point", "Wren Hollow", "Ashby",
    "Culver Park", "Dunlin", "Easton Yard", "Farthing", "Gable End", "Hartsell",
    "Inglenook", "Jarrow", "Kinder Lake", "Lowell Gate", "Mossgiel", "Nettleton",
    "Orchard Row", "Penhallow", "Quarry Road", "Rushmere", "Saltbox", "Thistle Down",
    "Upland", "Vesper", "Wickham", "Yardley", "Zennor", "Briar Glen",
]  # fmt: skip
CONSIGNEE_KINDS = ["Cold Storage", "Distribution Center", "Crossdock"]


@dataclass(frozen=True)
class Facility:
    """A place a truck picks up or delivers."""

    fac_id: str
    country: str
    tz: str


@dataclass(frozen=True)
class Site:
    """A shipper account: the row a load is booked against."""

    acct_id: str
    bill_to_id: str
    facility: Facility
    weight: float


@dataclass(frozen=True)
class Carrier:
    """A trucking company, or Tessaway's own fleet."""

    carr_id: str
    own_fleet: bool


@dataclass
class Event:
    """One planned status event. Events after the snapshot are never written."""

    ts: datetime
    code: str
    reason: str | None = None
    stop_index: int | None = None


@dataclass
class Stop:
    """One planned stop: appointment in local time, actual times in UTC."""

    kind: str  # "PU" or "DL"
    facility: Facility
    appt_start: datetime  # naive, local to the facility
    appt_end: datetime
    arrived: datetime | None = None
    departed: datetime | None = None


def to_utc(local: datetime, tz: str) -> datetime:
    """Read a naive local time at ``tz`` and return it in UTC."""
    return local.replace(tzinfo=ZoneInfo(tz)).astimezone(UTC)


def fmt_ts(moment: datetime) -> str:
    """Format a UTC instant the way BigQuery reads a TIMESTAMP."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_local(moment: datetime) -> str:
    """Format a naive local time the way BigQuery reads a DATETIME."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def money(amount: float) -> str:
    """Format an amount as a two-decimal string, which loads as NUMERIC exactly."""
    return f"{amount:.2f}"


# Load status after each kind of event. A status the snapshot has not reached
# is never written.
STATUS_AFTER = {
    "TNDR": "TNDR",
    "ACPT": "BOOK",
    "DISP": "DISP",
    "PKUP": "INTR",
    "DLVD": "DLVD",
    "CANC": "CANC",
    "RJCT": "RTND",
    "VOID": "VOID",
}


class Generator:
    """Builds every table in one pass over the booking calendar."""

    def __init__(self, seed: int = SEED) -> None:
        """Start from an empty warehouse and a seeded random stream."""
        self.rng = random.Random(seed)
        self.tables: Tables = {name: [] for name in schema.TABLES}
        self._next: dict[str, int] = {}
        self._portal_refs: set[str] = set()
        self.sites: list[Site] = []
        self.us_consignees: list[Facility] = []
        self.ca_consignees: list[Facility] = []
        self.carriers: list[Carrier] = []
        self.carrier_weights: list[float] = []
        self.fleet: Carrier | None = None

    # --- ids -------------------------------------------------------------

    def _id(self, prefix: str, width: int, start: int = 1) -> str:
        """Return the next sequential id for a prefix, for example ``L0000042``."""
        value = self._next.get(prefix, start)
        self._next[prefix] = value + 1
        return f"{prefix}{value:0{width}d}"

    # --- reference data --------------------------------------------------

    def _facility(self, name: str, city: tuple[str, str, str], country: str) -> Facility:
        fac_id = self._id("F", 4, 1001)
        self.tables["tms_fac"].append(
            {
                "fac_id": fac_id,
                "fac_nm": name,
                "city_nm": city[0],
                "st_prov_cd": city[1],
                "ctry_cd": country,
                "tz_nm": city[2],
            }
        )
        return Facility(fac_id, country, city[2])

    def _account(
        self, name: str, kind: str, parent: str | None, segment: str, country: str, active: bool
    ) -> str:
        acct_id = self._id("A", 5, 10001)
        self.tables["mdm_cust_acct"].append(
            {
                "acct_id": acct_id,
                "acct_nm": name,
                "acct_typ_cd": kind,
                "prnt_acct_id": parent,
                "seg_cd": segment,
                "ctry_cd": country,
                "actv_flg": active,
            }
        )
        return acct_id

    def _build_customers(self) -> None:
        """Create parents, shipper sites and bill-to parties, three rows deep."""
        rng = self.rng
        cities = {c[0]: (c, "US") for c in US_CITIES} | {c[0]: (c, "CA") for c in CA_CITIES}

        payer_id = self._account(FREIGHT_PAYER, "PRNT", None, "FPAY", "US", True)
        payer_bill_tos = [
            self._account(name, "BLTO", payer_id, "FPAY", "US", True)
            for name in FREIGHT_PAYER_BILL_TOS
        ]

        for parent_name, segment, sites, bill_to_names in ANCHOR_PARENTS:
            parent_id = self._account(parent_name, "PRNT", None, segment, "US", True)
            bill_tos = [
                self._account(name, "BLTO", parent_id, segment, "US", True)
                for name in bill_to_names
            ]
            for site_name, city_name, weight, bill_to_index in sites:
                city, country = cities[city_name]
                acct_id = self._account(site_name, "SHPR", parent_id, segment, country, True)
                facility = self._facility(site_name, city, country)
                self.sites.append(Site(acct_id, bill_tos[bill_to_index], facility, weight))

        active_count = len(GENERATED_PARENTS) - INACTIVE_PARENTS
        for index, (parent_name, segment) in enumerate(GENERATED_PARENTS):
            active = index < active_count
            parent_id = self._account(parent_name, "PRNT", None, segment, "US", active)
            if index < FREIGHT_PAYER_CLIENTS:
                bill_to = payer_bill_tos[index % len(payer_bill_tos)]
            else:
                bill_to = self._account(
                    f"{parent_name} Accounts Payable", "BLTO", parent_id, segment, "US", active
                )
            short = parent_name.removesuffix(" Co.").removesuffix(" Cooperative")
            site_count = rng.choice([1, 1, 2, 2, 3])
            parent_weight = rng.uniform(1.0, 4.0)
            for city in rng.sample(US_CITIES, site_count):
                kind = rng.choice(["Plant", "DC", "Warehouse"])
                site_name = f"{short} - {city[0]} {kind}"
                acct_id = self._account(site_name, "SHPR", parent_id, segment, "US", active)
                facility = self._facility(site_name, city, "US")
                if active:
                    self.sites.append(Site(acct_id, bill_to, facility, parent_weight / site_count))

    def _build_consignees(self) -> None:
        """Create the facilities loads deliver to."""
        rng = self.rng
        names = [f"{word} {kind}" for kind in CONSIGNEE_KINDS for word in CONSIGNEE_WORDS]
        for index, name in enumerate(names):
            if index % 9 == 4:
                self.ca_consignees.append(self._facility(name, rng.choice(CA_CITIES), "CA"))
            else:
                self.us_consignees.append(self._facility(name, rng.choice(US_CITIES), "US"))

    def _build_carriers(self) -> None:
        """Create the outside carriers and Tessaway's own fleet."""
        rng = self.rng
        used: set[str] = {OWN_FLEET[1]}
        rows = []
        for index, prefix in enumerate(CARRIER_PREFIXES):
            name = f"{prefix} {CARRIER_SUFFIXES[index % len(CARRIER_SUFFIXES)]}"
            letters = [word[0] for word in name.upper().replace("-", " ").split()]
            scac = ("".join(letters) + prefix.upper().replace(" ", "")[1:])[:4]
            while scac in used:
                scac = scac[:3] + rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ")
            used.add(scac)
            rows.append((name, scac))
        for name, scac in rows:
            carr_id = self._id("C", 4, 2001)
            self.tables["tms_carr"].append(
                {
                    "carr_id": carr_id,
                    "carr_nm": name,
                    "scac_cd": scac,
                    "carr_typ_cd": "3P",
                    "actv_flg": True,
                }
            )
            self.carriers.append(Carrier(carr_id, False))
        # Outside carriers get uneven shares of the freight, with one clear leader.
        order = list(range(len(self.carriers)))
        rng.shuffle(order)
        weights = [0.0] * len(order)
        for rank, index in enumerate(order):
            weights[index] = (1.7 if rank == 0 else 1.0) / (rank + 3) ** 0.6
        self.carrier_weights = weights
        fleet_id = self._id("C", 4, 2001)
        self.tables["tms_carr"].append(
            {
                "carr_id": fleet_id,
                "carr_nm": OWN_FLEET[0],
                "scac_cd": OWN_FLEET[1],
                "carr_typ_cd": "OWN",
                "actv_flg": True,
            }
        )
        self.fleet = Carrier(fleet_id, True)

    def _build_fx(self) -> None:
        """One Canadian-to-US rate per month, and its inverse."""
        for month, rate in CAD_TO_USD.items():
            first = date(2026, month, 1).isoformat()
            self.tables["ref_fx_rate"].append(
                {"eff_mo_dt": first, "from_curr_cd": "CAD", "to_curr_cd": "USD", "fx_rt": rate}
            )
            self.tables["ref_fx_rate"].append(
                {
                    "eff_mo_dt": first,
                    "from_curr_cd": "USD",
                    "to_curr_cd": "CAD",
                    "fx_rt": f"{1 / float(rate):.6f}",
                }
            )

    # --- one booking -----------------------------------------------------

    def _pick_carrier(self, fleet: bool) -> Carrier:
        if fleet:
            assert self.fleet is not None
            return self.fleet
        return self.rng.choices(self.carriers, weights=self.carrier_weights)[0]

    def _write_load(
        self,
        *,
        load_id: str,
        orig_load_id: str | None,
        site: Site,
        carrier: Carrier,
        dest: Facility,
        miles: int,
        cross_border: bool,
        currency: str,
        revenue: float,
        cost: float,
        requested: date,
        test: bool,
        void: bool,
        created: datetime,
        stops: list[Stop],
        plan: list[Event],
    ) -> str:
        """Write the header, stops and events for one load row. Returns its status."""
        rng = self.rng
        stop_ids = [self._id("S", 8) for _ in stops]
        happened = sorted((e for e in plan if e.ts <= SNAPSHOT), key=lambda e: e.ts)
        status = "TNDR"
        for event in happened:
            status = STATUS_AFTER.get(event.code, status)
            source = "OPS" if event.code in {"TNDR", "CANC", "VOID"} else "EDI"
            if carrier.own_fleet and source == "EDI":
                source = "DRV"
            self.tables["tms_stat_evt"].append(
                {
                    "evt_id": self._id("E", 9),
                    "load_id": load_id,
                    "stop_id": None if event.stop_index is None else stop_ids[event.stop_index],
                    "evt_cd": event.code,
                    "rsn_cd": event.reason,
                    "evt_ts": fmt_ts(event.ts),
                    "src_cd": source,
                }
            )
        for seq, (stop_id, stop) in enumerate(zip(stop_ids, stops, strict=True), start=1):
            arrived = stop.arrived if stop.arrived and stop.arrived <= SNAPSHOT else None
            departed = stop.departed if stop.departed and stop.departed <= SNAPSHOT else None
            self.tables["tms_stop"].append(
                {
                    "stop_id": stop_id,
                    "load_id": load_id,
                    "stop_seq": seq,
                    "stop_typ_cd": stop.kind,
                    "fac_id": stop.facility.fac_id,
                    "tz_nm": stop.facility.tz,
                    "appt_start_lcl": fmt_local(stop.appt_start),
                    "appt_end_lcl": fmt_local(stop.appt_end),
                    "arr_ts": fmt_ts(arrived) if arrived else None,
                    "dep_ts": fmt_ts(departed) if departed else None,
                }
            )
        updated = happened[-1].ts if happened else created
        self.tables["tms_load_hdr"].append(
            {
                "load_id": load_id,
                "orig_load_id": orig_load_id,
                "shpr_acct_id": site.acct_id,
                "bill_to_acct_id": site.bill_to_id,
                "carr_id": carrier.carr_id,
                "load_stat_cd": status,
                "eqp_typ_cd": rng.choices(["VAN", "REEF", "FLAT"], weights=[70, 20, 10])[0],
                "orig_fac_id": site.facility.fac_id,
                "dest_fac_id": dest.fac_id,
                "miles_qty": miles,
                "xbrdr_flg": cross_border,
                "curr_cd": currency,
                "lh_rev_amt": money(revenue),
                "lh_cost_amt": money(cost),
                "req_dlvr_dt": requested.isoformat(),
                "test_flg": test,
                "void_flg": void,
                "crt_ts": fmt_ts(created),
                "upd_ts": fmt_ts(max(updated, created)),
            }
        )
        return status

    def _plan_trip(
        self, created: datetime, stops: list[Stop], *, simulate: bool = True
    ) -> tuple[list[Event], datetime | None]:
        """Plan a load from tender to delivery. Returns events and the delivered time."""
        rng = self.rng
        pickup, final = stops[0], stops[-1]
        tendered = created + timedelta(minutes=rng.randint(5, 90))
        accepted = tendered + timedelta(minutes=rng.randint(10, 240))
        plan = [Event(tendered, "TNDR"), Event(accepted, "ACPT")]
        if not simulate:
            return plan, None

        pickup_start = to_utc(pickup.appt_start, pickup.facility.tz)
        pickup_end = to_utc(pickup.appt_end, pickup.facility.tz)
        dispatched = max(
            pickup_start - timedelta(minutes=rng.randint(120, 1200)),
            accepted + timedelta(minutes=10),
        )
        window_minutes = int((pickup_end - pickup_start).total_seconds() // 60)
        pickup.arrived = max(
            pickup_start + timedelta(minutes=rng.randint(-30, window_minutes)),
            dispatched + timedelta(minutes=30),
        )

        outcome = rng.choices([k for k, _ in ARRIVAL_MIX], weights=[w for _, w in ARRIVAL_MIX])[0]
        if outcome == "on_time":
            roll = rng.random()
            reason = "SHPR" if roll < 0.04 else rng.choice(["CARR", "WTHR"]) if roll < 0.09 else ""
            delayed = bool(reason)
        else:
            picked = rng.choices([r for r, _ in LATE_REASONS], weights=[w for _, w in LATE_REASONS])
            reason = picked[0] or ""
            delayed = bool(reason)

        loading = timedelta(minutes=rng.randint(30, 180))
        if reason == "SHPR":
            loading += timedelta(minutes=rng.randint(180, 480))
        pickup.departed = pickup.arrived + loading

        final_end = to_utc(final.appt_end, final.facility.tz)
        final_start = to_utc(final.appt_start, final.facility.tz)
        if outcome == "on_time":
            span = int((final_end - final_start).total_seconds() // 60)
            arrival = final_start + timedelta(minutes=rng.randint(-90, span))
        elif outcome == "late_minor":
            arrival = final_end + timedelta(minutes=rng.randint(5, 180))
        elif outcome == "late_major":
            arrival = final_end + timedelta(minutes=rng.randint(180, 840))
        else:
            arrival = final_end + timedelta(minutes=rng.randint(1200, 3000))
        final.arrived = max(arrival, pickup.departed + timedelta(hours=2))
        final.departed = final.arrived + timedelta(minutes=rng.randint(30, 180))

        plan += [
            Event(dispatched, "DISP"),
            Event(pickup.arrived, "ARVD", stop_index=0),
            Event(pickup.departed, "PKUP", stop_index=0),
        ]
        if delayed:
            if reason == "SHPR":
                when = pickup.arrived + timedelta(minutes=rng.randint(45, 120))
                plan.append(Event(when, "DLAY", "SHPR", 0))
            else:
                gap = int((final.arrived - pickup.departed).total_seconds() // 60)
                when = pickup.departed + timedelta(minutes=rng.randint(1, max(1, gap - 1)))
                plan.append(Event(when, "DLAY", reason))
        for index, stop in enumerate(stops[1:-1], start=1):
            start = to_utc(stop.appt_start, stop.facility.tz)
            end = to_utc(stop.appt_end, stop.facility.tz)
            span = int((end - start).total_seconds() // 60)
            arrived = start + timedelta(minutes=rng.randint(-30, span))
            earliest = pickup.departed + timedelta(hours=1)
            latest = final.arrived - timedelta(hours=1)
            stop.arrived = min(max(arrived, earliest), max(latest, earliest))
            stop.departed = stop.arrived + timedelta(minutes=rng.randint(20, 50))
            plan += [
                Event(stop.arrived, "ARVD", stop_index=index),
                Event(stop.departed, "DPTD", stop_index=index),
            ]
        last = len(stops) - 1
        plan += [
            Event(final.arrived, "ARVD", stop_index=last),
            Event(final.departed, "DLVD", stop_index=last),
        ]
        return plan, final.departed

    def _bill(
        self,
        *,
        load_id: str,
        site: Site,
        carrier: Carrier,
        currency: str,
        revenue: float,
        cost: float,
        stops: list[Stop],
        delivered: datetime,
    ) -> None:
        """Write everything billing does once a real load is delivered."""
        rng = self.rng
        pickup_month = stops[0].appt_start.month
        pct = FUEL_PCT.get(pickup_month, 0.125)
        scale = CAD_PER_USD if currency == "CAD" else 1.0

        cust_fuel = round(revenue * pct, 2)
        carr_fuel = round(cust_fuel * rng.uniform(0.97, 1.02), 2)
        self.tables["bil_fuel_schg"].append(
            {
                "fsc_id": self._id("FS", 8),
                "load_id": load_id,
                "cust_fsc_amt": money(cust_fuel),
                "carr_fsc_amt": money(carr_fuel),
                "curr_cd": currency,
            }
        )

        accessorials: list[tuple[str, float, float]] = []
        if len(stops) > 2:
            accessorials.append(("STP", 100.0 * scale, 75.0 * scale))
        if rng.random() < 0.22:
            for _ in range(rng.choice([1, 1, 1, 2])):
                code = rng.choices(["DET", "LMP", "LAY", "RDL"], weights=[45, 35, 12, 8])[0]
                if code == "DET":
                    billed = rng.randrange(75, 451, 25) * scale
                    paid = billed * 0.8
                elif code == "LMP":
                    billed = paid = rng.randint(120, 380) * scale
                elif code == "LAY":
                    billed, paid = 300.0 * scale, 250.0 * scale
                else:
                    billed = rng.randrange(150, 401, 50) * scale
                    paid = billed * 0.85
                accessorials.append((code, round(billed, 2), round(paid, 2)))
        for code, billed, paid in accessorials:
            self.tables["bil_accsrl_chrg"].append(
                {
                    "accsrl_id": self._id("AC", 8),
                    "load_id": load_id,
                    "accsrl_cd": code,
                    "cust_bill_amt": money(billed),
                    "carr_pay_amt": money(paid),
                    "curr_cd": currency,
                    "chrg_dt": delivered.date().isoformat(),
                }
            )

        linehaul_pay = cost
        if rng.random() < 0.10:
            linehaul_pay = round(cost * rng.uniform(0.97, 1.04), 2)
        pay_date = delivered.date() + timedelta(days=rng.randint(21, 35))
        paid_out = pay_date <= SNAPSHOT.date()
        self.tables["bil_carr_pay"].append(
            {
                "pay_id": self._id("CP", 8),
                "load_id": load_id,
                "carr_id": carrier.carr_id,
                "lh_pay_amt": money(linehaul_pay),
                "curr_cd": currency,
                "pay_stat_cd": "PAID" if paid_out else "APRV",
                "pay_dt": pay_date.isoformat() if paid_out else None,
            }
        )

        # Proof of delivery. Billing invoices a load only once a signed proof
        # of delivery is on file, so a delivered load can sit unbilled.
        signed_at: datetime | None = None
        if rng.random() >= 0.02:
            lag_days = rng.choices(
                [rng.uniform(0.2, 2), rng.uniform(2, 7), rng.uniform(7, 20)], weights=[70, 25, 5]
            )[0]
            first = delivered + timedelta(days=lag_days)
            first_signed = rng.random() >= 0.05
            docs = [(first, first_signed)]
            if first_signed:
                signed_at = first
            elif rng.random() < 0.85:
                signed_at = first + timedelta(days=rng.uniform(1, 6))
                docs.append((signed_at, True))
            for received, signed in docs:
                if received <= SNAPSHOT:
                    self.tables["bil_pod_doc"].append(
                        {
                            "pod_doc_id": self._id("PD", 8),
                            "load_id": load_id,
                            "rcvd_ts": fmt_ts(received),
                            "signed_flg": signed,
                            "doc_src_cd": rng.choice(["EDI", "EMAIL", "SCAN"]),
                        }
                    )
        if signed_at is None or signed_at > SNAPSHOT:
            return

        invoice_date = signed_at.date()
        invoice_total = round(revenue + cust_fuel + sum(b for _, b, _ in accessorials), 2)
        invoice_id = self._id("INV", 7, 500001)
        old = (SNAPSHOT.date() - invoice_date).days > 35
        self.tables["bil_cust_inv"].append(
            {
                "inv_id": invoice_id,
                "load_id": load_id,
                "bill_to_acct_id": site.bill_to_id,
                "inv_dt": invoice_date.isoformat(),
                "curr_cd": currency,
                "inv_tot_amt": money(invoice_total),
                "inv_stat_cd": "PAID" if old and rng.random() < 0.8 else "OPEN",
            }
        )
        if rng.random() < CREDIT_SHARE:
            credit_date = invoice_date + timedelta(days=rng.randint(3, 40))
            if credit_date <= SNAPSHOT.date():
                self.tables["bil_cr_memo"].append(
                    {
                        "cr_memo_id": self._id("CM", 7),
                        "load_id": load_id,
                        "inv_id": invoice_id,
                        "bill_to_acct_id": site.bill_to_id,
                        "cr_amt": money(round(invoice_total * rng.uniform(0.08, 0.30), 2)),
                        "cr_rsn_cd": rng.choice(["SVC", "RATE", "DMG", "DUP"]),
                        "cr_dt": credit_date.isoformat(),
                        "curr_cd": currency,
                    }
                )

    def _portal(
        self, *, load_id: str, site: Site, status: str, requested: date, stops: list[Stop],
        updated: datetime,
    ) -> None:  # fmt: skip
        """Write the row the customer sees. The portal judges on-time by date."""
        rng = self.rng
        ref = f"TW-{rng.randrange(10_000_000, 100_000_000)}"
        while ref in self._portal_refs:
            ref = f"TW-{rng.randrange(10_000_000, 100_000_000)}"
        self._portal_refs.add(ref)
        final = stops[-1]
        delivered_on: date | None = None
        if status == "DLVD" and final.arrived is not None:
            delivered_on = final.arrived.astimezone(ZoneInfo(final.facility.tz)).date()
        text = {"DLVD": "Delivered", "INTR": "In Transit", "CANC": "Canceled"}.get(
            status, "Scheduled"
        )
        self.tables["ptl_shpmt"].append(
            {
                "shpmt_ref": ref,
                "load_id": load_id,
                "cust_acct_id": site.acct_id,
                "stat_txt": text,
                "req_dlvr_dt": requested.isoformat(),
                "actl_dlvr_dt": delivered_on.isoformat() if delivered_on else None,
                "on_time_ind": None
                if delivered_on is None
                else ("Y" if delivered_on <= requested else "N"),
                "last_upd_ts": fmt_ts(min(updated + timedelta(minutes=5), SNAPSHOT)),
            }
        )

    def _book(self, day: date) -> None:
        """Book one load on ``day`` and follow it as far as the snapshot allows."""
        rng = self.rng
        site = rng.choices(self.sites, weights=[s.weight for s in self.sites])[0]
        origin = site.facility
        to_canada = origin.country == "US" and rng.random() < CANADA_DEST_SHARE
        dest = rng.choice(self.ca_consignees if to_canada else self.us_consignees)
        cross_border = origin.country != dest.country
        currency = "CAD" if cross_border and rng.random() < CAD_SHARE_OF_CROSS_BORDER else "USD"
        scale = CAD_PER_USD if currency == "CAD" else 1.0
        miles = rng.randint(400, 2200) if cross_border else rng.randint(180, 1900)
        revenue = round(max(650.0, miles * rng.uniform(2.05, 3.10)) * scale, 2)
        path = rng.choices(
            ["test", "void", "cancel", "normal"],
            weights=[
                TEST_SHARE,
                VOID_SHARE,
                CANCEL_SHARE,
                1 - TEST_SHARE - VOID_SHARE - CANCEL_SHARE,
            ],
        )[0]
        fleet = not cross_border and path != "test" and rng.random() < FLEET_SHARE
        carrier = self._pick_carrier(fleet)
        cost = round(revenue * (rng.uniform(0.72, 0.80) if fleet else rng.uniform(0.80, 0.90)), 2)
        if path == "test":
            revenue, cost = rng.choice([(1000.0, 800.0), (2500.0, 2000.0)])

        created = to_utc(
            datetime.combine(day, time(rng.randint(7, 17), rng.randint(0, 59), rng.randint(0, 59))),
            origin.tz,
        )
        pickup_day = day + timedelta(days=rng.randint(1, 3))
        pickup_start = datetime.combine(pickup_day, time(rng.randint(6, 15), rng.choice([0, 30])))
        pickup_end = pickup_start + timedelta(hours=rng.choice([2, 3, 4]))
        delivery_day = pickup_day + timedelta(days=max(1, math.ceil(miles / 520)))
        delivery_start = datetime.combine(
            delivery_day, time(rng.randint(6, 17), rng.choice([0, 30]))
        )
        delivery_end = delivery_start + timedelta(hours=rng.choice([1, 2, 2, 4]))
        requested = delivery_day + timedelta(days=rng.choices([0, 1, -1], weights=[85, 10, 5])[0])

        extra: Facility | None = None
        extra_start = delivery_start
        if rng.random() < TWO_DROP_SHARE:
            pool = self.ca_consignees if dest.country == "CA" else self.us_consignees
            candidate = rng.choice(pool)
            extra_start = datetime.combine(
                delivery_day - timedelta(days=1), time(rng.randint(12, 17), 0)
            )
            if candidate.fac_id != dest.fac_id and extra_start > pickup_end + timedelta(hours=6):
                extra = candidate

        def fresh_stops() -> list[Stop]:
            stops = [Stop("PU", origin, pickup_start, pickup_end)]
            if extra is not None:
                stops.append(Stop("DL", extra, extra_start, extra_start + timedelta(hours=2)))
            stops.append(Stop("DL", dest, delivery_start, delivery_end))
            return stops

        common: dict[str, Any] = {
            "site": site,
            "dest": dest,
            "miles": miles,
            "cross_border": cross_border,
            "currency": currency,
            "revenue": revenue,
            "requested": requested,
        }

        if path == "void":
            stops = fresh_stops()
            plan, _ = self._plan_trip(created, stops, simulate=False)
            voided = min(
                created + timedelta(minutes=rng.randint(12, 1200)), SNAPSHOT - timedelta(minutes=1)
            )
            plan = [e for e in plan if e.ts < voided] + [Event(voided, "VOID")]
            self._write_load(
                load_id=self._id("L", 7, 1000001), orig_load_id=None, carrier=carrier, cost=cost,
                test=False, void=True, created=created, stops=stops, plan=plan, **common,
            )  # fmt: skip
            return

        if path == "test":
            stops = fresh_stops()
            plan, _ = self._plan_trip(created, stops, simulate=rng.random() < 0.6)
            self._write_load(
                load_id=self._id("L", 7, 1000001), orig_load_id=None, carrier=carrier, cost=cost,
                test=True, void=False, created=created, stops=stops, plan=plan, **common,
            )  # fmt: skip
            return

        # A re-tender: the first carrier accepts, then falls off before pickup.
        # The first row stays in the table and a second row carries the load.
        orig_load_id: str | None = None
        if not fleet and rng.random() < RETENDER_SHARE:
            stops = fresh_stops()
            plan, _ = self._plan_trip(created, stops, simulate=False)
            pickup_utc = to_utc(pickup_start, origin.tz)
            earliest = plan[-1].ts + timedelta(minutes=60)
            latest = pickup_utc - timedelta(hours=3)
            if latest > earliest:
                gap = int((latest - earliest).total_seconds() // 60)
                rejected = earliest + timedelta(minutes=rng.randint(0, gap))
                if rejected <= SNAPSHOT:
                    orig_load_id = self._id("L", 7, 1000001)
                    self._write_load(
                        load_id=orig_load_id, orig_load_id=None, carrier=carrier, cost=cost,
                        test=False, void=False, created=created, stops=stops,
                        plan=[*plan, Event(rejected, "RJCT", "CARR")], **common,
                    )  # fmt: skip
                    created = rejected + timedelta(minutes=rng.randint(10, 180))
                    carrier = self._pick_carrier(False)
                    cost = round(min(cost * rng.uniform(1.03, 1.10), revenue * 0.97), 2)

        load_id = self._id("L", 7, 1000001)
        stops = fresh_stops()
        plan, delivered = self._plan_trip(created, stops)
        canceled_at: datetime | None = None
        cancel_reason = ""
        late_cancel = False
        if path == "cancel":
            pickup_utc = to_utc(pickup_start, origin.tz)
            accepted = plan[1].ts
            dispatched = next(e.ts for e in plan if e.code == "DISP")
            latest = pickup_utc - timedelta(minutes=60)
            gap = max(1, int((latest - accepted).total_seconds() // 60) - 30)
            canceled_at = accepted + timedelta(minutes=30 + rng.randint(0, gap))
            cancel_reason = rng.choices(["SHPR", "CARR", "OPS"], weights=[60, 25, 15])[0]
            plan = [e for e in plan if e.ts < canceled_at and e.code in {"TNDR", "ACPT", "DISP"}]
            plan.append(Event(canceled_at, "CANC", cancel_reason))
            for stop in stops:
                stop.arrived = stop.departed = None
            delivered = None
            late_cancel = canceled_at > dispatched
        status = self._write_load(
            load_id=load_id, orig_load_id=orig_load_id, carrier=carrier, cost=cost,
            test=False, void=False, created=created, stops=stops, plan=plan, **common,
        )  # fmt: skip

        if status == "CANC" and canceled_at is not None and cancel_reason == "SHPR" and late_cancel:
            # The shipper canceled after a truck was dispatched: a canceled-load fee.
            self.tables["bil_canc_fee"].append(
                {
                    "canc_fee_id": self._id("CF", 7),
                    "load_id": load_id,
                    "cust_fee_amt": money(rng.randrange(250, 451, 25) * scale),
                    "carr_fee_amt": money(
                        0.0 if carrier.own_fleet else rng.randrange(150, 301, 25) * scale
                    ),
                    "curr_cd": currency,
                    "fee_dt": canceled_at.date().isoformat(),
                }
            )
        if status == "DLVD" and delivered is not None:
            self._bill(
                load_id=load_id, site=site, carrier=carrier, currency=currency, revenue=revenue,
                cost=cost, stops=stops, delivered=delivered,
            )  # fmt: skip
        happened = [e.ts for e in plan if e.ts <= SNAPSHOT]
        self._portal(
            load_id=load_id, site=site, status=status, requested=requested, stops=stops,
            updated=max(happened) if happened else created,
        )  # fmt: skip

    # --- the whole warehouse ---------------------------------------------

    def build(self) -> Tables:
        """Generate every table and return them keyed by table name."""
        self._build_customers()
        self._build_consignees()
        self._build_carriers()
        self._build_fx()
        day = FIRST_DAY
        while day <= LAST_DAY:
            base = {5: 14, 6: 7}.get(day.weekday(), 52)
            for _ in range(base + self.rng.randint(-4, 4)):
                self._book(day)
            day += timedelta(days=1)
        return self.tables


def generate(seed: int = SEED) -> Tables:
    """Return the full warehouse for ``seed`` as lists of rows per table."""
    return Generator(seed).build()


def fingerprint(tables: Tables) -> str:
    """Hash every row of every table, so two builds can be compared exactly."""
    digest = hashlib.sha256()
    for name in sorted(tables):
        digest.update(name.encode())
        for row in tables[name]:
            digest.update(json.dumps(row, sort_keys=True).encode())
    return digest.hexdigest()


def write(tables: Tables, out_dir: Path = OUT_DIR) -> None:
    """Write one newline-delimited JSON file per table."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        with (out_dir / f"{name}.ndjson").open("w") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")


def main() -> None:
    """Generate the warehouse, write it, and print the row counts."""
    tables = generate()
    write(tables)
    for name, rows in tables.items():
        print(f"{name:18s} {len(rows):>8,d} rows")
    print(f"fingerprint {fingerprint(tables)}")
    print(f"written to {OUT_DIR}")


if __name__ == "__main__":
    main()
