"""Domain filtering utilities for search results."""

from urllib.parse import urlparse


def is_domain_allowed(
    url: str,
    allowed_domains: list[str],
    blocked_domains: list[str],
) -> bool:
    """
    Check if URL's domain passes filtering rules.

    Args:
        url: Full URL to check
        allowed_domains: Whitelist (empty = allow all)
        blocked_domains: Blacklist

    Returns:
        True if domain is allowed
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # If no netloc (invalid URL like "not-a-valid-url"), block it
        if not domain:
            return False

        # Strip port if present
        if ":" in domain:
            domain = domain.split(":")[0]

        # Remove www. prefix for comparison
        if domain.startswith("www."):
            domain = domain[4:]

        # Check blacklist first
        if blocked_domains:
            for blocked in blocked_domains:
                if not blocked:  # Skip empty strings
                    continue
                blocked_clean = blocked.lower().removeprefix("www.")
                # Strip port from blocked domain too
                if ":" in blocked_clean:
                    blocked_clean = blocked_clean.split(":")[0]
                if domain == blocked_clean or domain.endswith(f".{blocked_clean}"):
                    return False

        # Check whitelist if present
        if allowed_domains:
            has_valid_allowed = False
            for allowed in allowed_domains:
                if not allowed:  # Skip empty strings
                    continue
                has_valid_allowed = True
                allowed_clean = allowed.lower().removeprefix("www.")
                # Strip port from allowed domain too
                if ":" in allowed_clean:
                    allowed_clean = allowed_clean.split(":")[0]
                if domain == allowed_clean or domain.endswith(f".{allowed_clean}"):
                    return True
            # If there are valid entries in allowed list and we didn't match, block
            if has_valid_allowed:
                return False

        return True  # No whitelist = allow all (except blacklisted)

    except Exception:
        return False  # Invalid URL = block
