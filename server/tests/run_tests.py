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
