import re

import pytest

from aap_gateway_api.preferences import gateway_preference_registry

# Words that should remain lowercase in Title Case unless they are the first or last word.
_MINOR_WORDS = frozenset(
    {
        'a',
        'an',
        'the',
        'and',
        'or',
        'but',
        'nor',
        'for',
        'yet',
        'so',
        'in',
        'of',
        'to',
        'at',
        'by',
        'on',
        'up',
        'as',
        'per',
    }
)

# Pattern matching fully-uppercase tokens (acronyms like URL, JWT, CSRF, etc.)
_ACRONYM_RE = re.compile(r'^[A-Z][A-Z0-9]+$')

# Pattern matching tokens inside parentheses, e.g. "(seconds)"
_PAREN_RE = re.compile(r'^\(.*\)$')


def _is_title_case(label: str) -> bool:
    """Return True if *label* follows Title Case conventions.

    Rules:
    * The first and last word are always capitalized.
    * Acronyms (e.g. URL, JWT, CSRF, OIDC) stay fully uppercase.
    * Minor words (articles, short prepositions, conjunctions) are lowercase
      unless they are the first or last word.
    * All other words start with an uppercase letter.
    * Parenthesized tokens like ``(seconds)`` are allowed lowercase.
    """
    words = label.split()
    if not words:
        return False

    for idx, word in enumerate(words):
        is_first = idx == 0
        is_last = idx == len(words) - 1

        # Skip parenthesized tokens
        if _PAREN_RE.match(word):
            continue

        # Acronyms must stay fully uppercase
        if _ACRONYM_RE.match(word):
            continue

        lower = word.lower()

        if is_first or is_last:
            # First and last words must be capitalized
            if not word[0].isupper():
                return False
        elif lower in _MINOR_WORDS:
            # Minor words in the middle should be lowercase
            if word != lower:
                return False
        else:
            # Other words must start with an uppercase letter
            if not word[0].isupper():
                return False

    return True


@pytest.mark.django_db
class TestPreferenceLabels:
    """Validate that every registered preference has a non-None label in Title Case."""

    def _get_all_preferences(self):
        """Return all registered gateway preferences."""
        return list(gateway_preference_registry.preferences())

    def test_all_preferences_have_labels(self):
        """Every preference must have a non-None, non-empty label."""
        missing = []
        for pref in self._get_all_preferences():
            if not getattr(pref, 'label', None):
                missing.append(f"{pref.section.name}.{pref.name}")

        assert not missing, (
            f"The following preferences are missing labels: {', '.join(missing)}. Every preference registration must include a label=_('...') parameter."
        )

    def test_all_labels_use_title_case(self):
        """Every preference label must follow Title Case conventions."""
        violations = []
        for pref in self._get_all_preferences():
            label = getattr(pref, 'label', None)
            if label and not _is_title_case(str(label)):
                violations.append(f"{pref.section.name}.{pref.name}: '{label}'")

        assert not violations, (
            "The following preference labels do not follow Title Case conventions:\n"
            + "\n".join(f"  - {v}" for v in violations)
            + "\n\nTitle Case rules: capitalize all words except articles (a, an, the), "
            "coordinating conjunctions (and, or, but), and short prepositions "
            "(in, of, for, to, at, by) -- unless first or last word."
        )

    def test_help_texts_have_no_trailing_stray_apostrophes(self):
        """No help_text should end with a stray apostrophe before the closing quote."""
        bad = []
        for pref in self._get_all_preferences():
            help_text = getattr(pref, 'help_text', None)
            if help_text and str(help_text).endswith(".'"):
                bad.append(f"{pref.section.name}.{pref.name}: {help_text!r}")

        assert not bad, "The following preferences have help_text with a trailing stray apostrophe:\n" + "\n".join(f"  - {b}" for b in bad)
