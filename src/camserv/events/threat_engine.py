"""100% Local Threat Scoring, Behavior Interpretation, & Narrative Engine for CAMserv.

Zero-API Edge Intelligence providing:
1. Multi-Factor Threat Scoring Engine:
   Threat Score = min(100, w1*Zone + w2*Time + w3*Kinematics + w4*Pose + w5*Duration)
2. Body Pose Geometry Analysis (bending/tampering, climbing, crawling, falling).
3. Object Interaction Logic (unattended/abandoned luggage detection via centroid divergence).
4. Local Deterministic Narrative Engine (Immediate incident reports in Arabic & English).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timezone
from typing import Any, Sequence

from camserv.inference.segmentation import SkeletalPose
from camserv.pipeline.interfaces import BoundingBox, Track


@dataclass(slots=True)
class ThreatScoreBreakdown:
    """Detailed point breakdown across the five threat factors."""
    zone_score: float        # w1 (0-25)
    time_score: float        # w2 (0-15)
    kinematics_score: float  # w3 (0-25)
    pose_score: float        # w4 (0-20)
    duration_score: float    # w5 (0-15)
    total_score: float       # Sum clamped to 0-100
    dominant_behavior: str   # Behavioral label
    is_critical: bool        # total_score >= 80


@dataclass(slots=True)
class SecurityNarrative:
    """Dual-language deterministic operational security report."""
    track_id: int
    threat_score: float
    behavior: str
    speed_mps: float
    duration_sec: float
    english_report: str
    arabic_report: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class LocalThreatEngine:
    """Heuristic and kinematic behavioral threat engine running 100% locally."""

    def __init__(
        self,
        weight_zone: float = 25.0,
        weight_time: float = 15.0,
        weight_kinematics: float = 25.0,
        weight_pose: float = 20.0,
        weight_duration: float = 15.0,
        normal_speed_threshold_mps: float = 1.8,
        sprint_speed_threshold_mps: float = 3.5,
        loiter_time_threshold_sec: float = 30.0,
        night_start_hour: int = 22,
        night_end_hour: int = 6,
    ) -> None:
        self.w_zone = weight_zone
        self.w_time = weight_time
        self.w_kin = weight_kinematics
        self.w_pose = weight_pose
        self.w_dur = weight_duration
        self.normal_speed = normal_speed_threshold_mps
        self.sprint_speed = sprint_speed_threshold_mps
        self.loiter_threshold = loiter_time_threshold_sec
        self.night_start = night_start_hour
        self.night_end = night_end_hour

    def evaluate_threat(
        self,
        track: Track,
        zone_type: str = "perimeter",
        current_time: datetime | None = None,
        pose: SkeletalPose | None = None,
        associated_bag_track: Track | None = None,
    ) -> ThreatScoreBreakdown:
        """Compute multi-factor threat score for an active track."""
        now = current_time or datetime.now(timezone.utc)

        # 1. Zone Score (0-25)
        zone_lower = zone_type.lower()
        if "sterile" in zone_lower or "restricted" in zone_lower or "vault" in zone_lower:
            z_factor = 1.0
        elif "fence" in zone_lower or "perimeter" in zone_lower:
            z_factor = 0.8
        elif "corridor" in zone_lower or "entry" in zone_lower:
            z_factor = 0.4
        else:
            z_factor = 0.1
        z_pts = min(self.w_zone, self.w_zone * z_factor)

        # 2. Time Score (0-15) - High score during after-hours / nighttime
        hr = now.hour
        is_night = (hr >= self.night_start or hr < self.night_end)
        t_factor = 1.0 if is_night else 0.2
        t_pts = min(self.w_time, self.w_time * t_factor)

        # 3. Kinematics Score (0-25)
        vx, vy = track.velocity
        speed = math.hypot(vx, vy)
        if speed > self.sprint_speed:
            k_factor = 1.0  # Sudden sprinting / evasion
            behavior = "Rapid Sprint / Evasion"
        elif speed < 0.2 and track.age > 45:
            k_factor = 0.7  # Pacing or lingering stationary
            behavior = "Perimeter Lingering"
        elif speed > self.normal_speed:
            k_factor = 0.5  # Fast walking / hurried approach
            behavior = "Hurried Approach"
        else:
            k_factor = 0.1  # Normal transit
            behavior = "Normal Transit"
        k_pts = min(self.w_kin, self.w_kin * k_factor)

        # 4. Body Pose Geometry Score (0-20)
        p_factor, pose_behavior = self._analyze_pose(pose, track)
        if pose_behavior:
            behavior = pose_behavior
        p_pts = min(self.w_pose, self.w_pose * p_factor)

        # 5. Duration Score (0-15)
        dwell_seconds = track.age / 25.0  # assuming 25 fps pipeline
        d_factor = min(1.0, dwell_seconds / self.loiter_threshold)
        d_pts = min(self.w_dur, self.w_dur * d_factor)

        # 6. Object Interaction Modifier (Unattended Luggage check)
        if associated_bag_track is not None:
            obj_alert = self.check_unattended_object(track, associated_bag_track)
            if obj_alert:
                behavior = "Unattended Object Departure"
                z_pts = max(z_pts, 20.0)
                k_pts = max(k_pts, 20.0)

        total = min(100.0, z_pts + t_pts + k_pts + p_pts + d_pts)
        return ThreatScoreBreakdown(
            zone_score=round(z_pts, 1),
            time_score=round(t_pts, 1),
            kinematics_score=round(k_pts, 1),
            pose_score=round(p_pts, 1),
            duration_score=round(d_pts, 1),
            total_score=round(total, 1),
            dominant_behavior=behavior,
            is_critical=total >= 80.0,
        )

    def _analyze_pose(
        self,
        pose: SkeletalPose | None,
        track: Track
    ) -> tuple[float, str | None]:
        """Analyze keypoint geometry to detect bending, climbing, crawling, or falling."""
        if pose is None or pose.valid_count < 8:
            return 0.1, None

        # Check explicit posture hint if set
        if getattr(pose, "posture_hint", None) == "bending":
            return 0.9, "Repeated Bending / Lock Tampering"
        elif getattr(pose, "posture_hint", None) == "climbing":
            return 0.95, "Fence / Structure Climbing"
        elif getattr(pose, "posture_hint", None) == "crawling":
            return 0.85, "Low Crawling / Concealment"
        elif getattr(pose, "posture_hint", None) == "fallen":
            return 0.9, "Sudden Fall / Incapacitation"

        # Check for Bending (Shoulder-Hip-Knee angle < 140 degrees)
        sh_hip_knee = pose.calculate_angle(5, 11, 13) or pose.calculate_angle(6, 12, 14)
        if sh_hip_knee is not None and sh_hip_knee < 140.0:
            return 0.9, "Repeated Bending / Lock Tampering"

        # Check for Climbing (Wrists higher than shoulders, knees high)
        l_sh = pose.get_joint("left_shoulder")
        r_sh = pose.get_joint("right_shoulder")
        l_wr = pose.get_joint("left_wrist")
        r_wr = pose.get_joint("right_wrist")
        if (l_sh and l_wr and l_wr[1] < l_sh[1]) or (r_sh and r_wr and r_wr[1] < r_sh[1]):
            return 0.95, "Fence / Structure Climbing"

        # Check for Crawling (Horizontal torso aspect ratio near ground)
        bbox = track.bbox
        if bbox.width > bbox.height * 1.3:
            return 0.85, "Low Crawling / Concealment"

        # Check for Falling (Aspect ratio shift from tall to flat + sudden stop)
        if bbox.height < bbox.width * 0.7:
            return 0.9, "Sudden Fall / Incapacitation"

        return 0.1, None

    def check_unattended_object(
        self,
        person_track: Track,
        object_track: Track,
        separation_threshold_px: float = 120.0
    ) -> bool:
        """Detect when a carried object (bag/suitcase) is abandoned while person moves away."""
        px, py = person_track.bbox.center
        ox, oy = object_track.bbox.center
        distance = math.hypot(px - ox, py - oy)

        # Object is stationary (velocity ~ 0) but person is moving away
        obj_vx, obj_vy = object_track.velocity
        obj_speed = math.hypot(obj_vx, obj_vy)
        per_vx, per_vy = person_track.velocity
        per_speed = math.hypot(per_vx, per_vy)

        if distance > separation_threshold_px and obj_speed < 0.2 and per_speed > 0.4:
            return True
        return False

    def generate_narrative(
        self,
        track: Track,
        breakdown: ThreatScoreBreakdown,
        zone_name: str = "Northern Perimeter",
        is_enhanced_isp: bool = True
    ) -> SecurityNarrative:
        """Generate deterministic operational narrative in English and Arabic."""
        vx, vy = track.velocity
        speed = math.hypot(vx, vy)
        duration_sec = track.age / 25.0
        threat = breakdown.total_score
        behavior = breakdown.dominant_behavior

        isp_en = " in nighttime-enhanced camera zone" if is_enhanced_isp else ""
        isp_ar = " في منطقة مراقبة معززة للرؤية الليلية" if is_enhanced_isp else ""

        # English report
        en_report = (
            f"Object (ID #{track.track_id}) detected in {zone_name} exhibiting {behavior}. "
            f"Speed: {speed:.1f} m/s, Dwell time: {duration_sec:.0f}s{isp_en}. "
            f"Calculated Threat Level: {threat:.0f}%."
        )

        # Arabic report
        ar_behavior_map = {
            "Rapid Sprint / Evasion": "الجري السريع أو محاولة التملص",
            "Perimeter Lingering": "التسكع والتردد قرب السياج الأمني",
            "Hurried Approach": "الاقتراب المتعجل نحو المنطقة المحظورة",
            "Normal Transit": "حركة عبور اعتيادية",
            "Repeated Bending / Lock Tampering": "حركات انحناء متكررة تشير لمحاولة العبث أو فتح الأقفال",
            "Fence / Structure Climbing": "محاولة تسلق السياج أو الهيكل الأمني",
            "Low Crawling / Concealment": "الزحف المنخفض لتفادي كواشف المراقبة",
            "Sudden Fall / Incapacitation": "سقوط مفاجئ أو فقدان القدرة على الحركة",
            "Unattended Object Departure": "مغادرة وترك حقيبة أو جسم مشبوه دون مراقبة",
        }
        ar_behavior = ar_behavior_map.get(behavior, behavior)
        ar_report = (
            f"تم رصد الكائن (المعرف #{track.track_id}) في {zone_name} بنمط سلوكي: ({ar_behavior}). "
            f"السرعة الحركية: {speed:.1f} م/ث، زمن التواجد: {duration_sec:.0f} ثانية{isp_ar}. "
            f"مستوى التهديد المحسوب: {threat:.0f}%."
        )

        return SecurityNarrative(
            track_id=track.track_id,
            threat_score=threat,
            behavior=behavior,
            speed_mps=round(speed, 2),
            duration_sec=round(duration_sec, 1),
            english_report=en_report,
            arabic_report=ar_report,
        )
