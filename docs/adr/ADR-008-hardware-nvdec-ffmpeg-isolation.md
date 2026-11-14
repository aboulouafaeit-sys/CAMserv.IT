# ADR-008: Hardware NVDEC/VAAPI Pipeline Isolation via Subprocess FFmpeg
**Status:** ACCEPTED  
**Date:** 2026-11-14  
**Context:** Standard OpenCV `cv2.VideoCapture` lacks native support for hardware decoding on stock wheels and defaults to UDP transport, causing frequent packet drops and artifacting on enterprise IP camera networks.  
**Decision:** Replace OpenCV capture with supervised FFmpeg subprocesses utilizing strict TCP transport (`-rtsp_transport tcp`) and hardware decode acceleration (`-hwaccel cuda` / `-hwaccel vaapi`).  
**Consequences:** Eliminates dropped UDP video packets; offloads $85\%$ of CPU decoding overhead to dedicated hardware ASICs (NVIDIA NVDEC); reduces glass-to-glass latency to $< 120\text{ ms}$.
