#!/usr/bin/env python3
"""Discover exact BIS dataflow IDs and series-key structures.

The BIS Explorer needs correct SDMX keys for: total credit (%GDP),
credit-to-GDP gap, debt service ratios, effective exchange rates,
policy rates, residential property prices, and banking statistics.

This script:
  1. Lists all BIS dataflows (ID + name) so we get exact IDs.
  2. For target dataflows, dumps the dimension order (key structure).
  3. Fetches a 2-obs sample for a US/aggregate key to confirm format
     and show the latest period available.

Run on Render (needs external network):
  python backend/scripts/discover_bis_keys.py
"""

import requests
import pandas as pd
from io import StringIO
import xml.etree.ElementTree as ET

BASE = "https://stats.bis.org/api/v2"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
}

# Dataflows we want keys for (search terms to filter the full list)
TARGET_TERMS = ["credit", "exchange", "property", "banking", "policy",
                "debt service", "consumer price", "liquidity"]


def list_dataflows():
    """List all BIS dataflows with IDs and names."""
    print("=" * 70)
    print("  ALL BIS DATAFLOWS (filtered to relevant terms)")
    print("=" * 70)
    url = f"{BASE}/structure/dataflow/BIS/?detail=allstubs"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
        if resp.status_code != 200:
            print(f"  dataflow list HTTP {resp.status_code}")
            return []
        root = ET.fromstring(resp.text)
        flows = []
        for elem in root.iter():
            tag = elem.tag.split("}")[-1]
            if tag == "Dataflow":
                fid = elem.attrib.get("id", "")
                version = elem.attrib.get("version", "")
                name = ""
                for child in elem.iter():
                    ctag = child.tag.split("}")[-1]
                    if ctag == "Name" and child.text:
                        name = child.text
                        break
                flows.append((fid, version, name))
        for fid, ver, name in sorted(flows):
            low = (fid + " " + name).lower()
            if any(t in low for t in TARGET_TERMS):
                print(f"  {fid} (v{ver}): {name}")
        return flows
    except Exception as e:
        print(f"  ERROR listing dataflows: {e}")
        return []


def dump_dimensions(dataflow_id, version="1.0"):
    """Dump the dimension order (key structure) for a dataflow."""
    print(f"\n--- DIMENSIONS: {dataflow_id} v{version} ---")
    # The DSD usually shares the dataflow id or is referenced; try structure call
    url = f"{BASE}/structure/datastructure/BIS/{dataflow_id}/{version}?detail=full"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
        if resp.status_code != 200:
            print(f"  DSD HTTP {resp.status_code} for {dataflow_id}")
            return
        root = ET.fromstring(resp.text)
        dims = []
        for elem in root.iter():
            tag = elem.tag.split("}")[-1]
            if tag in ("Dimension", "TimeDimension"):
                did = elem.attrib.get("id")
                pos = elem.attrib.get("position", "?")
                if did and did not in [d[1] for d in dims]:
                    dims.append((pos, did))
        dims.sort(key=lambda x: (x[0] == "?", x[0]))
        key_order = ".".join(d[1] for d in dims if d[1] != "TIME_PERIOD")
        print(f"  Dimension order: {key_order}")
        for pos, did in dims:
            print(f"    [{pos}] {did}")
    except Exception as e:
        print(f"  ERROR dumping dims for {dataflow_id}: {e}")


def sample(dataflow_version, key, label):
    """Fetch last 2 obs for a key to confirm it works + show latest period."""
    url = f"{BASE}/data/dataflow/BIS/{dataflow_version}/{key}?lastNObservations=2&format=csv"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
        if resp.status_code != 200:
            print(f"  {label} [{key}]: HTTP {resp.status_code}")
            return
        if len(resp.text) < 80:
            print(f"  {label} [{key}]: empty")
            return
        df = pd.read_csv(StringIO(resp.text))
        tcol = next((c for c in df.columns if "TIME_PERIOD" in c.upper() or c.upper() == "TIME"), None)
        vcol = next((c for c in df.columns if "OBS_VALUE" in c.upper() or c.upper() == "VALUE"), None)
        if tcol and vcol:
            latest = df[tcol].iloc[-1]
            val = df[vcol].iloc[-1]
            print(f"  {label} [{key}]: OK latest={latest} val={val} | cols={list(df.columns)[:8]}")
        else:
            print(f"  {label} [{key}]: no time/value cols={list(df.columns)[:8]}")
    except Exception as e:
        print(f"  {label} [{key}]: ERROR {e}")


def main():
    flows = list_dataflows()

    print("\n" + "=" * 70)
    print("  DIMENSION STRUCTURES + SAMPLE KEYS")
    print("=" * 70)

    # Candidate dataflows + sample keys to probe (will adjust based on dim dump)
    candidates = [
        ("WS_TC", "2.0", ["Q.US.C.A.M.770.A", "Q.US.C.A.M.USD.A", "Q.5R.C.A.M.770.A"]),
        ("WS_CREDIT_GAP", "1.0", ["Q.US.C", "Q.US.P.A", "Q.US"]),
        ("WS_DSR", "1.0", ["Q.US.P.A", "Q.US.P", "Q.US.H"]),
        ("WS_EER", "1.0", ["M.N.B.US", "M.R.B.US", "D.N.B.US"]),
        ("WS_CBPOL", "1.0", ["M.US", "D.US"]),
        ("WS_SPP", "1.0", ["Q.US.N.628", "Q.US.R.771", "Q.US"]),
        ("WS_CBS_PUB", "1.0", ["Q.S.US.4B.N.A.A.TO1.A.5J.N", "Q.S.US.5A.4B.5J.N.A.TO1.A.A.A.5J.N"]),
        ("WS_LBS_D_PUB", "1.0", ["Q.S.C.A.TO1.A.5J.N.5A.N", "Q.S.US.A.TO1.A.5J.N.5A.N"]),
    ]

    for fid, ver, keys in candidates:
        dump_dimensions(fid, ver)
        for k in keys:
            sample(f"{fid}/{ver}", k, fid)

    print("\n" + "=" * 70)
    print("  Paste this whole output back to finalize the BIS Explorer keys.")
    print("=" * 70)


if __name__ == "__main__":
    main()
