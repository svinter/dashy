EMAIL_TO_PERSON: dict[str, str] = {}
NAME_TO_PERSON: dict[str, str] = {}


def _get_email_domain() -> str:
    """Get the user's email domain from profile config."""
    try:
        from app_config import get_profile

        return get_profile().get("user_email_domain", "")
    except Exception:
        return ""


def _get_user_email() -> str:
    """Get the user's email from profile config."""
    try:
        from app_config import get_profile

        return get_profile().get("user_email", "")
    except Exception:
        return ""


def build_person_mapping(people: list[dict]):
    global EMAIL_TO_PERSON, NAME_TO_PERSON
    EMAIL_TO_PERSON.clear()
    NAME_TO_PERSON.clear()

    domain = _get_email_domain()

    for person in people:
        name = person["name"]
        person_id = person["id"]
        parts = name.lower().split()

        NAME_TO_PERSON[name.lower()] = person_id

        if len(parts) >= 2:
            first, last = parts[0], parts[-1]
            if domain:
                EMAIL_TO_PERSON[f"{first}@{domain}"] = person_id
                EMAIL_TO_PERSON[f"{first}.{last}@{domain}"] = person_id
                EMAIL_TO_PERSON[f"{first[0]}{last}@{domain}"] = person_id
                EMAIL_TO_PERSON[f"{last}@{domain}"] = person_id
            NAME_TO_PERSON[first] = person_id
            NAME_TO_PERSON[last] = person_id
            NAME_TO_PERSON[f"{first} {last}"] = person_id

            NICKNAMES = {
                "benjamin": ["ben"],
                "michael": ["mike"],
                "katherine": ["kate"],
                "samuel": ["sam"],
                "richard": ["rich", "rick"],
                "william": ["will"],
                "alexander": ["alex"],
                "nicholas": ["nick"],
                "elizabeth": ["liz", "beth"],
                "frances": ["fran"],
                "guillaume": ["gui"],
            }
            for nick in NICKNAMES.get(first, []):
                NAME_TO_PERSON[nick] = person_id
                if domain:
                    EMAIL_TO_PERSON[f"{nick}@{domain}"] = person_id

        # Also index by explicit email if provided
        email = person.get("email", "")
        if email:
            EMAIL_TO_PERSON[email.lower()] = person_id


def rebuild_from_db():
    """Rebuild person matching maps from database."""
    from database import get_db_connection

    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT id, name, email FROM people").fetchall()
    build_person_mapping([dict(r) for r in rows])


def match_email_to_person(email: str) -> str | None:
    return EMAIL_TO_PERSON.get(email.lower())


def match_name_to_person(name: str) -> str | None:
    return NAME_TO_PERSON.get(name.lower())


def get_person_email_patterns(person_id: str) -> list[str]:
    """Return all email patterns that could match this person in calendar attendees."""
    return [email for email, pid in EMAIL_TO_PERSON.items() if pid == person_id]


def match_attendees_to_person(attendees: list[dict], exclude_email: str | None = None) -> str | None:
    """Given meeting attendees, find the non-user person."""
    if exclude_email is None:
        exclude_email = _get_user_email()

    user_local = exclude_email.split("@")[0].lower() if exclude_email else ""

    for a in attendees:
        email = a.get("email", "").lower()
        name = a.get("name", "").lower()

        if exclude_email and exclude_email.lower() in email:
            continue
        if user_local and user_local == email.split("@")[0]:
            continue

        match = match_email_to_person(email)
        if match:
            return match
        match = match_name_to_person(name)
        if match:
            return match

    return None
