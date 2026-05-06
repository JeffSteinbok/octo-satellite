"""Utility for expanding environment variable references in strings.

Supports ${VAR_NAME} syntax. If the referenced variable is unset,
the reference is left unexpanded (or raises depending on strict mode).
"""

import os
import re

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def expand_env(value: str, *, strict: bool = False) -> str:
    """Expand ${VAR} references in a string with their env var values.

    Args:
        value: The string potentially containing ${VAR} references.
        strict: If True, raise ValueError for undefined variables.

    Returns:
        The string with all resolvable references expanded.
    """
    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            if strict:
                raise ValueError(f"Environment variable '{var_name}' is not set")
            return match.group(0)  # leave unexpanded
        return env_value

    return _ENV_VAR_PATTERN.sub(_replace, value)
