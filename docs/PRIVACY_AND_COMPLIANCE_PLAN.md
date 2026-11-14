# CAMserv Privacy & Legal Compliance Plan
**Document ID:** PRIV-COMP-2026-001  
**Author:** Principal Privacy Architect & Legal Technology Compliance Director  
**Date:** November 14, 2026  
**Status:** APPROVED FOR IMPLEMENTATION  
**Regulatory Frameworks:** EU GDPR (Regulation 2016/679), EU AI Act (Regulation 2024/1689), Italian Data Protection Code (D.Lgs. 196/2003 as amended by D.Lgs. 101/2018), Garante Guidelines on Video Surveillance (8 April 2010)

---

## 1. Privacy-by-Design Architecture (GDPR Article 25)

Video surveillance intrinsically involves the processing of personal data. CAMserv incorporates privacy protections directly into its software architecture:

### 1.1 Strict Non-Biometric Processing Guarantee
* **No Facial Recognition:** CAMserv does not extract facial embeddings, feature descriptors, or 128D/512D biometric vectors.
* **No Identity Resolution:** The system cannot associate a person detected in a camera frame with a real-world name, national ID, or biographical database.
* **Anonymous Kinematic Tracking:** Transient tracking integers ($ID \in \mathbb{N}$) are used purely for localized trajectory velocity calculation and expire automatically when the target leaves the camera view.

---

## 2. EU AI Act (Regulation 2024/1689) Conformity Assessment

### 2.1 Classification Under the EU AI Act
* **Prohibited AI Practices (Article 5):**
  - Real-time remote biometric identification in publicly accessible spaces for law enforcement: **NOT IMPLEMENTED / ABSENT IN CAMSERV**.
  - Biometric categorization to deduce race, political opinions, or sexual orientation: **STRICTLY PROHIBITED & PHYSICALLY ABSENT**.
  - Emotion recognition in workplace/educational institutions: **ABSENT**.
* **High-Risk AI Systems (Annex III):**
  - Systems used for security of critical infrastructure: CAMserv complies with Chapter 2 mandatory requirements:
    1. *Risk Management System (Article 9):* Continuous logging of false positives and model boundary conditions.
    2. *Data Governance (Article 10):* Models trained and evaluated on diverse, public non-biometric benchmark datasets.
    3. *Technical Documentation (Article 11):* Complete documentation package maintained in `docs/`.
    4. *Human Oversight (Article 14):* Mandatory Human-in-the-Loop review for all high-consequence alarms.

---

## 3. Italian Garante Video Surveillance Compliance

CAMserv adheres strictly to the **Linee Guida in materia di trattamento di dati personali per videosorveglianza** issued by the Italian Garante per la protezione dei dati personali:

1. **Principle of Proportionality (Proporzionalità):**
   - Video capture is limited strictly to monitored perimeters. Geometric exclusion zones (`ExclusionZone`) black out public roadways and neighboring private residences.
2. **Strict Retention Limits (Tempi di Conservazione):**
   - Routine non-incident video recordings are retained for a maximum of **24 to 72 hours**, after which automated cryptographic purging irrevocably destroys the DEKs and raw chunks.
   - Prolonged retention ($> 72\text{ hours}$) requires an explicit high-severity incident trigger or judicial preservation warrant.
3. **Mandatory Signage & Informative Notice (Informativa):**
   - Platform web console includes downloadable, standardized Garante-compliant informative templates (Art. 13 GDPR).

---

## 4. Fail-Closed Automated Redaction

To prevent unredacted video leakage during operator live monitoring or external FOIA / judicial disclosure:
* Redaction operates in **Fail-Closed Mode**: If the segmentation model fails or frame latency exceeds safety budgets, the entire visual frame is obscured with a solid neutral grey mask rather than displaying unmasked human subjects.
* Redaction modes supported:
  - *Gaussian Mosaic Pixelation:* Redacts faces and license plates with dynamic kernel scaling ($31 \times 31$).
  - *Solid Silhouette:* Replaces human contours with translucent cybernetic avatars ($15\%$ alpha).
