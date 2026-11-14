# ADR-011: Strict Non-Biometric Sovereign Edge Anonymization & Fail-Closed Redaction
**Status:** ACCEPTED  
**Date:** 2026-11-14  
**Context:** Global data protection regulations (GDPR Article 9, EU AI Act Annex III, Italian Garante guidelines) strictly penalize non-consensual biometric profiling and unredacted surveillance exports.  
**Decision:** Prohibit biometric extraction and facial recognition models permanently. Implement fail-closed client-side redaction (Gaussian blur / mosaic pixelation / solid avatars) where analytical failures drop unredacted visual feeds immediately.  
**Consequences:** Complete regulatory compliance across the European Union and internationally; eliminates legal liability associated with biometric data leaks while preserving operational tracking capabilities.
