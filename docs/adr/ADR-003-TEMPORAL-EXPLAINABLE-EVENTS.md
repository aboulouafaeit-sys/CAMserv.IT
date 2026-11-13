# ADR-003: Temporal Event Intelligence and Explainable Decision Reasoning

## Status
Accepted

## Context
Standard frame-by-frame rules often generate false positives due to transient detection anomalies (e.g. single-frame aspect ratio jumps mistaken for falls, or shadows mistaken for intrusions). Furthermore, regulatory standards (such as the EU AI Act) mandate that high-impact automated events provide transparent, auditable supporting observations rather than opaque scores.

## Decision
1. Implement a temporal event graph engine (`src/camserv/events/temporal.py`) using sliding temporal windows and multi-frame kinematic state machines.
2. Require every high-severity event payload to include:
   - Primary event type and severity classification.
   - ISO-8601 UTC timestamp and camera identifier.
   - Model and rule version metadata.
   - `supporting_observations`: A structured list of chronologically ordered evidence frames/coordinates leading to the trigger.
   - `reasoning_trace`: An explainable text rationale detailing which conditions were satisfied and when.
   - `verification_status`: Initialized to `PENDING_REVIEW` for all `severity >= HIGH` events.
3. Explicitly prohibit automated dispatch of consequential physical or security countermeasures without verified human operator review.

## Consequences
- Positive: Substantial reduction in false positives; compliance with EU AI Act explainability mandates.
- Negative: Requires storing sliding window history in memory (bounded to 150 frames / ~5 seconds).
