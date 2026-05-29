"""Verify the infrared.city SDK environment is ready.

Checks, in order:
  1. INFRARED_API_KEY is present (loaded from .env or the shell environment).
  2. InfraredClient() constructs with that key.
  3. A client-side preflight runs (no API call, no quota cost).

Run:  python verify_setup.py
"""

import os
import sys

import infrared_sdk as ir  # importing also auto-loads .env via python-dotenv


def main() -> int:
    key = os.getenv("INFRARED_API_KEY")
    if not key:
        print("FAIL: INFRARED_API_KEY is not set.")
        print("  Fix: cp .env.example .env  then add your key, or `export INFRARED_API_KEY=...`")
        return 1
    print(f"OK  : INFRARED_API_KEY loaded (ends with ...{key[-4:]})")

    try:
        # No argument -> client reads INFRARED_API_KEY from the environment.
        client = ir.InfraredClient()
    except Exception as exc:  # noqa: BLE001 - surface any construction error verbatim
        print(f"FAIL: InfraredClient() did not construct: {exc}")
        return 1
    print("OK  : InfraredClient() constructed")

    # Client-side sanity check (no network call) using a Dublin coordinate.
    try:
        result = ir.estimate_sun_context_loss(
            lat=53.3498,
            lon=-6.2603,
            start_month=5, start_day=28, start_hour=9,
            end_month=5, end_day=28, end_hour=17,
        )
        print(f"OK  : preflight ran client-side (severity={getattr(result, 'severity', 'n/a')})")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: preflight helper errored (non-fatal): {exc}")
    finally:
        client.close()

    print("\nEnvironment is ready. Note: a full API round-trip requires run_area()")
    print("with a real site polygon, which submits a billable analysis job.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
