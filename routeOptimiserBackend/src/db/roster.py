"""The demonstration operator roster, in one place.

Both the startup bootstrap and `seed_users.py` read this list, so the credentials printed by
the seeding script, the ones shown on the sign-in page, and the ones that actually exist in
the database cannot drift apart — which they will the moment there are two copies.

These are published demonstration accounts. In a deployment the roster would come from the
state's own directory (a DDMA or ASDMA staff list), not from a file in the repository.
"""

DEMO_USERS = [
    dict(username="reporter",    full_name="Bhaskar Das",      role="reporter",
         organisation="Volunteer, Kamrup district",            jurisdiction=None,
         password="reporter123"),
    dict(username="verifier.as", full_name="Anjali Baruah",    role="verifier",
         organisation="DDMA Assam",                            jurisdiction="Assam,Meghalaya",
         password="verify123"),
    dict(username="verifier.mn", full_name="Thangboi Kipgen",  role="verifier",
         organisation="DDMA Manipur",                          jurisdiction="Manipur,Nagaland,Mizoram",
         password="verify123"),
    dict(username="controller",  full_name="R. Lalthanmawia",  role="controller",
         organisation="State EOC / ASDMA",                     jurisdiction=None,
         password="control123"),
]


def ensure_roster(session, only_if_empty=True):
    """Create any missing demonstration accounts. Returns the usernames created.

    An empty roster means nobody can sign in and the review queue is unreachable, which reads
    as "the login is broken" rather than "a setup step was missed". Bootstrapping on first run
    removes that failure entirely; set NER_DISABLE_DEMO_SEED=1 to turn it off for a real
    deployment, where accounts should come from the state directory instead.
    """
    from src.api.auth import hash_password
    from src.db.models import User

    if only_if_empty and session.query(User).count() > 0:
        return []

    created = []
    for spec in DEMO_USERS:
        spec = dict(spec)
        password = spec.pop("password")
        if session.query(User).filter(User.username == spec["username"]).first():
            continue
        session.add(User(password_hash=hash_password(password), **spec))
        created.append(spec["username"])
    if created:
        session.commit()
    return created
