"""How place names and queries are compared.

The rule under test is symmetry: whatever a stored name becomes, the same words
typed as a query become the same thing, so the two meet.
"""

from __future__ import annotations

import re

from pathable_api.geo.place_text import MAX_QUERY_TERMS, normalise_text, query_terms


class TestNormalisation:
    def test_abbreviated_and_written_out_addresses_meet(self) -> None:
        assert normalise_text("200 University Ave. W") == normalise_text(
            "200 University Avenue West"
        )

    def test_a_street_suffix_and_direction_are_expanded(self) -> None:
        assert normalise_text("King St N") == "king street north"

    def test_accents_do_not_stop_a_match(self) -> None:
        assert normalise_text("Café Pyrus") == "cafe pyrus"

    def test_an_apostrophe_does_not_split_a_word(self) -> None:
        # Regression guard: treating the apostrophe as a space would leave a
        # stray "s", which the abbreviation table reads as "south".
        assert normalise_text("Children's Museum") == "childrens museum"
        assert normalise_text("Children\u2019s Museum") == "childrens museum"

    def test_an_ampersand_is_the_word_and(self) -> None:
        assert normalise_text("Arts & Crafts") == "arts and crafts"

    def test_the_output_needs_no_escaping_in_a_pattern(self) -> None:
        # The search builds regular expressions from this text without escaping.
        hostile = "a.b*c(d)[e]{f}|g^h$i\\j%k_l'm\"n;--o"
        assert re.fullmatch(r"[a-z0-9 ]*", normalise_text(hostile))

    def test_blank_text_normalises_to_nothing(self) -> None:
        assert normalise_text("  ,.;  ") == ""


class TestQueryTerms:
    def test_words_keep_their_order_without_repeats(self) -> None:
        assert query_terms("King St N King") == ("king", "street", "north")

    def test_a_runaway_query_is_cut_short(self) -> None:
        words = " ".join(f"word{index}" for index in range(30))
        assert len(query_terms(words)) == MAX_QUERY_TERMS

    def test_punctuation_alone_has_no_terms(self) -> None:
        assert query_terms("!!! ???") == ()
