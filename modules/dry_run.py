"""
Dry-run (rehearsal) mode, activated with `--dry-run` on the command line.

In dry-run mode the bot runs its real code paths (searching, card parsing,
Easy Apply walking, referral scanning, connection resolution, message
composition) but performs NO irreversible action: no application is
submitted, no LinkedIn DM / connection request is sent, no Gmail is sent,
and no usage counters or result logs are written. Each point where the
real flow would act is instead logged as "[DRY RUN] ...".
"""

import os
import sys

DRY_RUN: bool = "--dry-run" in sys.argv

# Upper bound on jobs walked per search run while in dry-run mode. Keeps a
# rehearsal short and predictable; only applied when --dry-run is active.
DRY_MAX_JOBS = int(os.environ.get("AJA_DRY_MAX_JOBS", "10"))


class _Counts(dict):
    def add(self, key: str) -> None:
        self[key] = self.get(key, 0) + 1


_counts = _Counts()


def is_dry_run() -> bool:
    return DRY_RUN


def reset() -> None:
    _counts.clear()


def count(key: str) -> None:
    if DRY_RUN:
        _counts.add(key)


def summary() -> str:
    if not _counts:
        return "[DRY RUN] No actions rehearsed."
    lines = [f"  {label}: {_counts.get(key, 0)}"
             for key, label in (
                 ("easy_apply", "Easy Apply jobs rehearsed (not submitted)"),
                 ("external", "External applications skipped"),
                 ("referral_dm", "Referral DMs rehearsed (not sent)"),
                 ("referral_connect", "Connect requests rehearsed (not sent)"),
                 ("referral_gmail", "Referral Gmails rehearsed (not sent)"),
             ) if key in _counts]
    return "[DRY RUN] Rehearsal summary:\n" + "\n".join(lines)