# PTZ Vehicle Visits: read-only grouping preview

This experimental feature groups multiple Frigate car event IDs into one logical
vehicle visit when there is strong independent visual and spatial evidence.
It does not replace Frigate events, modify review segments, concatenate MP4
files, or change any existing notification behavior.

## Test endpoint

Using the authenticated Frigate API:

    GET /api/vehicle_visits/preview?camera=obrotowa&hours=24&limit=200

Each returned visit contains a representative visit ID (the first source event
ID), start/end times, source event IDs, and a match reason for every member.

Only events belonging to cameras that the current user can access are returned.
There is no public endpoint or write operation.

## Matching limits

- Same camera is required.
- New object IDs alone do not imply a new physical vehicle.
- Time proximity alone never causes events to merge.
- Very strong image hash similarity and overlapping relative object boxes can
  reconnect detections after the camera returns to a similar viewpoint.
- A matching recognized plate may support a recent visually plausible match.
- Conflicting recognized plates prevent merging.
- Missing thumbnails, changed PTZ viewpoints, or ambiguous appearances remain
  separate. This errs on the side of not hiding a real second arrival.
- A 12-hour lookback is a conservative heuristic, not proof of continuous
  presence. A car that leaves and later returns to exactly the same spot may
  look identical; the preview cannot reliably distinguish that case.

The preview is not yet a persistent identity system and does not yet provide
one item in the Frigate Reviews UI. Those steps require validation against
actual PTZ events and a model of departures/returns, plus persistence and UI
integration. Never use preview visit IDs as the sole authority for suppressing
Driveway Guard notifications until these cases are validated.

## Validation

    python3 -u -m unittest frigate.test.test_vehicle_visit_matching

No data migration is required for this preview. Restore the base branch to
disable the endpoint. The original recordings and review events remain intact.
