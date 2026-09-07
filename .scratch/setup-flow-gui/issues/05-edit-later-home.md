# 05: Edit-later + "you're all set" home

**What to build:** The post-onboarding experience. A returning user reopens the
flow with everything pre-filled and can change one thing (e.g. add a location by
rewording their wish) without redoing the rest; single settings are editable
from the panel's Settings area (only what the flow touched changes). Users who
already completed onboarding see a "you're all set — change anything here" home
instead of being asked to set up again. Both UIs.

**Blocked by:** 02, 03, 04.

**Status:** done

- [x] Reopening the flow pre-fills every step from saved state.
- [x] Changing one answer (e.g. rewording the wish) leaves all other answers untouched on save.
- [x] A single setting can be edited directly from Settings without opening the full flow.
- [x] The home screen shows an all-set state for completed users and only shows the flow for unfinished or explicitly-editing users.
- [x] Tests: edit-one-answer preserves the rest; the all-set home state is asserted against completed vs incomplete accounts.