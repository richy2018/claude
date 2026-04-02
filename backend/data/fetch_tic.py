#!/usr/bin/env python3
"""Fetch and parse TIC data from US Treasury website, or from a local file."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.data.tic_parser import parse_tic_text, save_tic_json, apply_supplemental

def fetch_and_parse():
    """Try to fetch from URL, fall back to local file."""
    raw_text = None

    # Try local file first
    local_path = os.path.join(os.path.dirname(__file__), 'tic_raw.txt')
    if os.path.exists(local_path):
        print(f"Reading from local file: {local_path}")
        with open(local_path, encoding='utf-8', errors='replace') as f:
            raw_text = f.read()
    else:
        # Try to fetch from URL
        try:
            import requests
            url = "https://ticdata.treasury.gov/Publish/mfhhis01.txt"
            print(f"Fetching from: {url}")
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            raw_text = resp.text
            # Save locally for future use
            with open(local_path, 'w', encoding='utf-8') as f:
                f.write(raw_text)
            print(f"Saved to: {local_path}")
        except Exception as e:
            print(f"Failed to fetch: {e}")
            print(f"Please save the TIC data to: {local_path}")
            return

    if not raw_text:
        print("No data available")
        return

    print("Parsing TIC data...")
    parsed = parse_tic_text(raw_text)

    # Apply supplemental data (newer months not yet in the main file)
    parsed = apply_supplemental(parsed)

    print(f"Countries: {parsed['metadata']['countries_count']}")
    print(f"Date range: {parsed['metadata']['date_range']}")

    # Validate key values
    countries = parsed['countries']
    if 'Japan' in countries:
        jp = countries['Japan']
        print(f"Japan: {len(jp['dates'])} months, latest={jp['values'][-1]} ({jp['dates'][-1]})")
    if 'China, Mainland' in countries:
        cn = countries['China, Mainland']
        print(f"China: {len(cn['dates'])} months, latest={cn['values'][-1]} ({cn['dates'][-1]})")

    # Save
    output = save_tic_json(parsed)
    print(f"Saved parsed data to: {output}")

if __name__ == '__main__':
    fetch_and_parse()
