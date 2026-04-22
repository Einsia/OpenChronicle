"""Activity timeline — wall-clock-aligned, verbatim-preserving normalizer of captures.

Sits between raw capture JSON files and the S2 reducer. Each block covers
a short wall-clock window (default 1 min) and *normalizes* the captures
— stripping UI chrome, collapsing duplicate snapshots, separating
independent conversations — while preserving authored text, URLs,
titles, and proper nouns verbatim. The real compression happens one
stage later in the session reducer, which consumes a batch of these
blocks per flush.
"""
