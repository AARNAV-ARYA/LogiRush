"""Seed the operator roster.

These are demonstration accounts with published passwords, which is fine for a demo and
obviously not for a deployment — in the field these accounts would come from the state's
existing directory rather than a seed script. Kept separate from seed_demo_data.py so the
roster can be created without also inventing incidents and shipments.
"""

from src.db.models import Base
from src.db.roster import DEMO_USERS, ensure_roster
from src.db.session import get_engine, get_session

# state names must match those in the location data, since jurisdiction is checked against
# the state of the corridor an incident was attributed to.
def main():
    Base.metadata.create_all(bind=get_engine())
    session = get_session()
    try:
        # only_if_empty=False: run explicitly, and it tops up whatever is missing.
        created = ensure_roster(session, only_if_empty=False)
    finally:
        session.close()

    print(f"Seeded {len(created)} operator account(s).")
    print()
    print("  username      password      role              jurisdiction")
    print("  " + "-" * 66)
    for u in DEMO_USERS:
        print(f"  {u['username']:<13} {u['password']:<13} {u['role']:<17} "
              f"{u['jurisdiction'] or '(all states)' if u['role'] != 'reporter' else '—'}")
    print()
    print("  Demonstration credentials. Two different verifiers exist on purpose: closing a")
    print("  road needs a countersign, so one account alone cannot do it.")


if __name__ == "__main__":
    main()
