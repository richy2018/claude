"""Operational scripts (backfill, weekly update, name resolution).

Marks this directory as a package so the COT cron jobs in render.yaml can be
invoked as `python -m backend.scripts.cot_weekly_update` (backend is a regular
package, so its subdirectories need an __init__.py to be importable as
submodules). The scripts also run standalone via file path.
"""
