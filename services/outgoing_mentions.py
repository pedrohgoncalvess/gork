import re


def _user_jid(user) -> str | None:
    src_id = (user.src_id or "").strip()
    phone = (user.phone_number or "").removesuffix("@s.whatsapp.net").strip()
    if re.fullmatch(r"\d+@(lid|s\.whatsapp\.net)", src_id):
        return src_id
    if src_id.isdigit():
        # Group ingestion strips @lid before saving src_id. A phone-only
        # identity instead stores the same value in src_id and phone_number.
        return f"{src_id}@{'s.whatsapp.net' if src_id == phone else 'lid'}"
    if phone.isdigit():
        return f"{phone}@s.whatsapp.net"
    return None


def resolve_outgoing_mentions(text: str, users) -> tuple[str, list[str]]:
    """Resolve only known, unambiguous group mentions; leave ordinary text alone."""
    aliases: dict[str, set[str]] = {}
    for user in users:
        jid = _user_jid(user)
        if jid is None:
            continue
        name = (user.name or "").strip()
        parts = name.split()
        names = {" ".join(parts[:length]) for length in range(1, len(parts) + 1)}
        phone = (user.phone_number or "").removesuffix("@s.whatsapp.net")
        identifiers = {
            jid,
            jid.split("@")[0],
            phone,
            f"{phone}@s.whatsapp.net" if phone else "",
        }
        for alias in names | identifiers:
            if alias:
                aliases.setdefault(alias.casefold(), set()).add(jid)

    if not aliases or "@" not in text:
        return text, []
    # Keep ambiguous names in the pattern too: a duplicated full name must not
    # accidentally fall through to a shorter, unique alias.
    pattern = re.compile(
        r"(?<![\w@])@(" + "|".join(
            re.escape(alias) for alias in sorted(aliases, key=len, reverse=True)
        ) + r")(?![\w@])",
        re.IGNORECASE,
    )
    mentioned = []

    def replace(match):
        candidates = aliases[match.group(1).casefold()]
        if len(candidates) != 1:
            return match.group(0)
        jid = next(iter(candidates))
        if jid not in mentioned:
            mentioned.append(jid)
        return f"@{jid.split('@')[0]}"

    return pattern.sub(replace, text), mentioned
