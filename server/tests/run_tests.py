#!/usr/bin/env python3
"""Lightweight test runner (no pytest required)."""

from __future__ import annotations

import importlib
import inspect
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Isolate DB for whole run
_tmp = tempfile.mkdtemp(prefix="dq1_mmo_test_")
os.environ["DATABASE_URL"] = str(Path(_tmp) / "test.db")
os.environ["ALLOW_DEBUG"] = "1"

import config  # noqa: E402

config.DATABASE_URL = os.environ["DATABASE_URL"]
config.ALLOW_DEBUG = True


class FakeMonkey:
    def __init__(self):
        self._env = {}

    def setenv(self, k, v):
        self._env[k] = os.environ.get(k)
        os.environ[k] = v
        if k == "DATABASE_URL":
            config.DATABASE_URL = v


def run_module(name: str) -> tuple[int, int, list[str]]:
    mod = importlib.import_module(name)
    passed = failed = 0
    errors: list[str] = []
    tests = [
        (n, fn)
        for n, fn in inspect.getmembers(mod, inspect.isfunction)
        if n.startswith("test_")
    ]
    for name_, fn in tests:
        try:
            sig = inspect.signature(fn)
            kwargs = {}
            if "tmp_path" in sig.parameters:
                kwargs["tmp_path"] = Path(tempfile.mkdtemp())
            if "monkeypatch" in sig.parameters:
                kwargs["monkeypatch"] = FakeMonkey()
            fn(**kwargs)
            print(f"  PASS  {name_}")
            passed += 1
        except Exception:
            print(f"  FAIL  {name_}")
            errors.append(f"{name_}\n{traceback.format_exc()}")
            failed += 1
    return passed, failed, errors


def main() -> int:
    print("DQ1 MMO tests")
    total_p = total_f = 0
    all_err: list[str] = []
    for mod in (
        "tests.test_formulas",
        "tests.test_combat",
        "tests.test_presence",
        "tests.test_api",
        "tests.test_multiplayer",
        "tests.test_adversarial",
        "tests.test_items",
        "tests.test_mp_reliability",
        "tests.test_inn",
        "tests.test_who",
        "tests.test_field_magic",
        "tests.test_mp_teleport",
        "tests.test_online_roster",
        "tests.test_mp_expand",
        "tests.test_adversarial_hunt",
        "tests.test_features_v0513",
        "tests.test_mp_look",
        "tests.test_mp_session",
        "tests.test_mp_zone",
        "tests.test_features_v0521",
        "tests.test_mp_find",
        "tests.test_features_v0524",
        "tests.test_mp_ignore",
        "tests.test_mp_aoi_fix",
        "tests.test_features_v0528",
        "tests.test_mp_presence_heal",
        "tests.test_adversarial_nan",
        "tests.test_features_v0531",
        "tests.test_mp_reply_zone",
        "tests.test_features_v0533",
        "tests.test_mp_find_zone",
        "tests.test_features_v0536",
        "tests.test_features_v0538",
        "tests.test_adversarial_v0539",
        "tests.test_mp_reliability_v0540",
        "tests.test_features_v0541",
        "tests.test_mp_expand_v0542",
        "tests.test_features_v0543",
        "tests.test_features_v0544",
        "tests.test_mp_reliability_v0545",
        "tests.test_features_v0546",
        "tests.test_features_v0547",
        "tests.test_mp_expand_v0548",
        "tests.test_features_v0549",
        "tests.test_mp_expand_v0550",
        "tests.test_features_v0551",
        "tests.test_mp_expand_v0552",
        "tests.test_adversarial_v0553",
        "tests.test_mp_reliability_v0554",
        "tests.test_features_v0555",
        "tests.test_adversarial_v0556",
        "tests.test_mp_reliability_v0557",
        "tests.test_features_v0558",
        "tests.test_adversarial_v0559",
        "tests.test_mp_reliability_v0560",
        "tests.test_features_v0561",
        "tests.test_adversarial_v0562",
        "tests.test_mp_reliability_v0563",
        "tests.test_features_v0564",
        "tests.test_mp_reliability_v0565",
        "tests.test_features_v0566",
        "tests.test_mp_reliability_v0567",
        "tests.test_adversarial_v0568",
        "tests.test_features_v0569",
        "tests.test_mp_reliability_v0570",
        "tests.test_adversarial_v0571",
        "tests.test_mp_reliability_v0573",
        "tests.test_features_v0573",
        "tests.test_adversarial_v0574",
        "tests.test_features_v0575",
        "tests.test_mp_reliability_v0576",
        "tests.test_adversarial_v0577",
        "tests.test_features_v0578",
        "tests.test_mp_reliability_v0579",
        "tests.test_adversarial_v0580",
        "tests.test_features_v0581",
        "tests.test_mp_reliability_v0582",
        "tests.test_features_v0582",
        "tests.test_features_v0583",
        "tests.test_adversarial_v0583",
        "tests.test_adversarial_v0584",
        "tests.test_mp_reliability_v0585",
        "tests.test_features_v0585",
        "tests.test_features_v0586",
        "tests.test_mp_reliability_v0587",
        "tests.test_features_v0587",
        "tests.test_adversarial_v0588",
        "tests.test_features_v0589",
        "tests.test_mp_reliability_v0590",
        "tests.test_features_v0590",
        "tests.test_adversarial_v0590",
        "tests.test_adversarial_hunt_v0591",
        "tests.test_features_v0592",
        "tests.test_mp_reliability_v0593",
        "tests.test_features_v0593",
        "tests.test_adversarial_hunt_v0594",
        "tests.test_features_v0595",
        "tests.test_mp_reliability_v0596",
        "tests.test_features_v0597",
        "tests.test_features_v0598",
        "tests.test_mp_reliability_v0598",
        "tests.test_features_v0599",
        "tests.test_mp_reliability_v0599",
        "tests.test_adversarial_hunt_v05100",
        "tests.test_features_v05101",
        "tests.test_mp_reliability_v05101",
        "tests.test_features_v05102",
        "tests.test_mp_reliability_v05102",
        "tests.test_adversarial_hunt_v05103",
        "tests.test_features_v05104",
        "tests.test_mp_reliability_v05104",
        "tests.test_adversarial_hunt_v05105",
        "tests.test_features_v05106",
        "tests.test_mp_reliability_v05106",
        "tests.test_features_v05107",
        "tests.test_mp_reliability_v05107",
        "tests.test_features_v05108",
        "tests.test_mp_reliability_v05108",
        "tests.test_features_v05109",
        "tests.test_mp_reliability_v05109",
        "tests.test_adversarial_hunt_v05110",
        "tests.test_features_v05110",
        "tests.test_features_v05111",
        "tests.test_mp_reliability_v05111",
        "tests.test_features_v05112",
        "tests.test_mp_reliability_v05112",
        "tests.test_features_v05113",
        "tests.test_mp_reliability_v05113",
        "tests.test_features_v05114",
        "tests.test_mp_reliability_v05114",
        "tests.test_features_v05115",
        "tests.test_mp_reliability_v05115",
        "tests.test_features_v05116",
        "tests.test_mp_reliability_v05116",
        "tests.test_features_v05117",
        "tests.test_mp_reliability_v05117",
        "tests.test_features_v05118",
        "tests.test_mp_reliability_v05118",
        "tests.test_features_v05119",
        "tests.test_mp_reliability_v05119",
        "tests.test_features_v05120",
        "tests.test_mp_reliability_v05120",
        "tests.test_features_v05121",
        "tests.test_mp_reliability_v05121",
        "tests.test_features_v05122",
        "tests.test_mp_reliability_v05122",
        "tests.test_features_v05123",
        "tests.test_mp_reliability_v05123",
        "tests.test_features_v05124",
        "tests.test_mp_reliability_v05124",
        "tests.test_features_v05125",
        "tests.test_mp_reliability_v05125",
        "tests.test_features_v05126",
        "tests.test_mp_reliability_v05126",
        "tests.test_features_v05127",
        "tests.test_mp_reliability_v05127",
        "tests.test_features_v05128",
        "tests.test_mp_reliability_v05128",
        "tests.test_features_v05129",
        "tests.test_mp_reliability_v05129",
        "tests.test_features_v05130",
        "tests.test_mp_reliability_v05130",
        "tests.test_features_v05131",
        "tests.test_mp_reliability_v05131",
        "tests.test_features_v05132",
        "tests.test_mp_reliability_v05132",
        "tests.test_features_v05133",
        "tests.test_mp_reliability_v05133",
        "tests.test_features_v05134",
        "tests.test_mp_reliability_v05134",
        "tests.test_features_v05135",
        "tests.test_mp_reliability_v05135",
        "tests.test_features_v05136",
        "tests.test_mp_reliability_v05136",
        "tests.test_features_v05137",
        "tests.test_mp_reliability_v05137",
        "tests.test_features_v05138",
        "tests.test_mp_reliability_v05138",
        "tests.test_features_v05139",
        "tests.test_mp_reliability_v05139",
        "tests.test_features_v05140",
        "tests.test_mp_reliability_v05140",
        "tests.test_features_v05141",
        "tests.test_mp_reliability_v05141",
        "tests.test_features_v05142",
        "tests.test_mp_reliability_v05142",
        "tests.test_features_v05143",
        "tests.test_mp_reliability_v05143",
    ):
        print(f"\n[{mod}]")
        p, f, err = run_module(mod)
        total_p += p
        total_f += f
        all_err.extend(err)
    print(f"\n{total_p} passed, {total_f} failed")
    for e in all_err:
        print("---")
        print(e)
    return 1 if total_f else 0


if __name__ == "__main__":
    raise SystemExit(main())
