# ADR-009: Epistemic Uncertainty Quantification & Calibrated Threat Scoring
**Status:** ACCEPTED  
**Date:** 2026-11-14  
**Context:** Machine learning models are prone to uncalibrated overconfidence, which can trigger disruptive false alarms in high-consequence physical security environments.  
**Decision:** Enforce epistemic transparency across all detection DTOs (`is_prediction: bool = True`), apply Platt temperature scaling to raw softmax latents, and bound threat scoring within explicit 95% confidence intervals.  
**Consequences:** Mandatory Human-in-the-Loop review is enforced whenever confidence bounds overlap high-severity thresholds; legal and forensic compliance is achieved by never presenting algorithmic inferences as established facts.
