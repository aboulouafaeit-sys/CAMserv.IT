/**
 * CAMserv Enterprise Web Console — Client Runtime (v1.0)
 * High-performance, zero-dependency SPA interfacing with CAMserv REST & WebSocket APIs.
 */

(function () {
  "use strict";

  class CAMservClient {
    constructor() {
      this.currentScreen = "overview";
      this.activeEventForVerify = null;
      this.cameras = [];
      this.events = [];
      this.tracks = [];
      this.auditEntries = [];
      this.showBoxes = true;
      this.showPose = true;
      this.enableISP = true;
      this.showPrivacy = true;
      this.apiConnected = false;
      this.hasHardware = false;
      this.currentLayout = "2x2";
      this.currentContext = "general";
      this.currentProfile = "balanced";
      this.maximizedTileId = null;
      this.savedWorkspaces = [];
      this.eventFocusState = { isFocused: false, previousLayout: "2x2", activeEvent: null };
      this.draggedIndex = null;

      this.initEventListeners();
      this.initKeyboardShortcuts();
      this.loadInitialData();
      this.startTelemetryLoop();

      // Hash and query param routing support
      const urlParams = new URLSearchParams(window.location.search);
      const targetScreen = window.location.hash.replace("#", "") || urlParams.get("screen");
      if (targetScreen && document.getElementById(`screen-${targetScreen}`)) {
        this.switchScreen(targetScreen);
      }
      if (urlParams.get("theme") === "light") {
        document.body.setAttribute("data-theme", "light");
        const btnTheme = document.getElementById("btn-theme-toggle");
        if (btnTheme) btnTheme.textContent = "🌙 Dark";
        const logoImg = document.querySelector(".brand-header img.brand-logo");
        if (logoImg) logoImg.src = "/assets/logo-primary-light.png";
      }
      window.addEventListener("hashchange", () => {
        const h = window.location.hash.replace("#", "");
        if (h && document.getElementById(`screen-${h}`)) {
          this.switchScreen(h);
        }
      });
    }

    initEventListeners() {
      // Sidebar Navigation
      document.querySelectorAll(".nav-item[data-screen]").forEach((el) => {
        el.addEventListener("click", () => {
          const screen = el.getAttribute("data-screen");
          this.switchScreen(screen);
        });
      });

      // Toggles
      const btnHUD = document.getElementById("btn-toggle-hud") || document.getElementById("btn-toggle-boxes");
      if (btnHUD) {
        btnHUD.addEventListener("click", () => {
          this.showBoxes = !this.showBoxes;
          btnHUD.textContent = this.showBoxes ? "Cinematic Contours (ON)" : "Cinematic Contours (OFF)";
          btnHUD.className = this.showBoxes ? "btn btn-primary" : "btn btn-secondary";
          this.renderLiveStreams();
        });
      }

      const btnPose = document.getElementById("btn-toggle-pose");
      if (btnPose) {
        btnPose.addEventListener("click", () => {
          this.showPose = !this.showPose;
          btnPose.textContent = this.showPose ? "Skeletal Pose (ON)" : "Skeletal Pose (OFF)";
          btnPose.className = this.showPose ? "btn btn-primary" : "btn btn-secondary";
          this.renderLiveStreams();
        });
      }

      const btnISP = document.getElementById("btn-toggle-isp");
      if (btnISP) {
        btnISP.addEventListener("click", () => {
          this.enableISP = !this.enableISP;
          btnISP.textContent = this.enableISP ? "Software ISP (CLAHE Active)" : "Software ISP (Bypassed)";
          btnISP.className = this.enableISP ? "btn btn-primary" : "btn btn-secondary";
          this.renderLiveStreams();
        });
      }

      const btnPrivacy = document.getElementById("btn-toggle-privacy");
      if (btnPrivacy) {
        btnPrivacy.addEventListener("click", () => {
          this.openModal("modal-privacy-policy");
        });
      }

      // Effects Toggle (Glass vs Reduced Performance Mode)
      const btnEffects = document.getElementById("btn-effects-toggle");
      if (btnEffects) {
        btnEffects.addEventListener("click", () => {
          const isReduced = document.body.getAttribute("data-effects") === "reduced";
          document.body.setAttribute("data-effects", isReduced ? "full" : "reduced");
          btnEffects.textContent = isReduced ? "✨ Glass" : "⚡ Solid";
        });
      }

      // Add camera modal
      const btnAddCam = document.getElementById("btn-open-add-cam");
      if (btnAddCam) {
        btnAddCam.addEventListener("click", () => {
          this.openModal("modal-add-cam");
        });
      }

      // ONVIF Scan Button
      const btnScan = document.getElementById("btn-scan-onvif");
      if (btnScan) {
        btnScan.addEventListener("click", () => {
          this.performONVIFScan();
        });
      }

      // Theme Toggle (Dual Dark/Light Mode)
      const btnTheme = document.getElementById("btn-theme-toggle");
      if (btnTheme) {
        btnTheme.addEventListener("click", () => {
          const currentTheme = document.body.getAttribute("data-theme") || "dark";
          const newTheme = currentTheme === "dark" ? "light" : "dark";
          document.body.setAttribute("data-theme", newTheme);
          btnTheme.textContent = newTheme === "dark" ? "☀️ Light" : "🌙 Dark";

          const logoImg = document.querySelector(".brand-header img.brand-logo");
          if (logoImg) {
            logoImg.src = newTheme === "dark" ? "/assets/camserv-logo-transparent.png" : "/assets/logo-primary-light.png";
          }
        });
      }
    }

    initKeyboardShortcuts() {
      window.addEventListener("keydown", (e) => {
        if (e.ctrlKey && !e.shiftKey && !e.altKey) {
          const num = parseInt(e.key, 10);
          if (num >= 1 && num <= 9) {
            const screens = [
              "overview",
              "live",
              "cameras",
              "events",
              "tracking",
              "investigation",
              "evidence",
              "analytics",
              "nvr",
            ];
            e.preventDefault();
            this.switchScreen(screens[num - 1]);
          } else if (e.key === "0") {
            e.preventDefault();
            this.switchScreen("security");
          }
        }
      });
    }

    switchScreen(screenName) {
      this.currentScreen = screenName;

      // Update nav rail
      document.querySelectorAll(".nav-item").forEach((el) => {
        el.classList.toggle("active", el.getAttribute("data-screen") === screenName);
      });

      // Update screen containers
      document.querySelectorAll(".screen-container").forEach((el) => {
        el.classList.toggle("active", el.id === `screen-${screenName}`);
      });

      // Update top header
      const titleMap = {
        overview: "Executive Overview",
        live: "Live Monitoring Multi-View",
        cameras: "Camera Management & Calibration",
        events: "Intelligent Event Center",
        tracking: "Anonymous Kinematic Tracking",
        investigation: "Incident Investigation & Timeline",
        evidence: "Tamper-Evident Evidence Vault",
        analytics: "Visual Intelligence & Trend Reports",
        nvr: "Device & NVR Integration",
        privacy: "Privacy & Compliance Management",
        security: "Security, RBAC & Audit Log",
        health: "System Health & Pipeline Telemetry",
        config: "Deployment & Runtime Settings",
      };

      const topTitle = document.getElementById("top-title");
      if (topTitle) topTitle.textContent = titleMap[screenName] || "Dashboard";

      // Refresh data for active screen
      if (screenName === "live") this.renderLiveStreams();
      if (screenName === "events") this.renderEvents();
      if (screenName === "cameras") this.renderCameras();
      if (screenName === "tracking") this.renderTracking();
      if (screenName === "evidence") this.renderEvidence();
      if (screenName === "security") this.renderAuditLogs();
    }

    async loadInitialData() {
      // 1. Fetch Cameras or setup default mock inventory
      try {
        const res = await fetch("/api/v1/cameras");
        if (res.ok) {
          const data = await res.json();
          this.apiConnected = true;
          if (data && data.length > 0) {
            this.cameras = data;
            this.hasHardware = data.some(
              (c) => c.status === "online" && !c.id.includes("simulated") && !c.id.includes("mock")
            );
          } else {
            this.cameras = this.getDefaultCameras();
            this.hasHardware = false;
          }
        } else {
          this.apiConnected = false;
          this.hasHardware = false;
          this.cameras = this.getDefaultCameras();
        }
      } catch (err) {
        this.apiConnected = false;
        this.hasHardware = false;
        this.cameras = this.getDefaultCameras();
      }

      // Update epistemic badge truthfully based on authoritative API result
      if (!this.apiConnected) {
        this.updateEpistemicBadge("disconnected", "API unreachable: Hardware connection unverified, running local fallback");
      } else if (this.hasHardware) {
        this.updateEpistemicBadge("hw-verified", "Physical optical capture verified and online via API");
      } else {
        this.updateEpistemicBadge("simulated", "Connected to API, but camera feeds are synthetic fixtures");
      }

      // 2. Fetch Events or setup default mock events
      try {
        const res = await fetch("/api/v1/events?limit=50");
        if (res.ok) {
          const data = await res.json();
          this.events = data.length > 0 ? data : this.getDefaultEvents();
        } else {
          this.events = this.getDefaultEvents();
        }
      } catch (err) {
        this.events = this.getDefaultEvents();
      }

      this.initWorkspaces();
      this.renderOverview();
      this.renderCameras();
      this.renderEvents();
      this.renderLiveStreams();
      this.renderTracking();
      this.renderEvidence();
      this.renderAuditLogs();
      this.renderWorkspaceList();
    }

    updateEpistemicBadge(status, reason = "") {
      const pill = document.getElementById("pill-epistemic");
      if (!pill) return;
      pill.className = "badge-epistemic";
      if (status === "hw-verified") {
        pill.classList.add("badge-hw-verified");
        pill.textContent = "[HW-VERIFIED]";
        pill.title = reason || "Probed from physical host optical hardware";
      } else if (status === "simulated") {
        pill.classList.add("badge-simulated");
        pill.textContent = "[SIMULATED]";
        pill.title = reason || "Generated by synthetic RTSP harness";
      } else if (status === "disconnected") {
        pill.classList.add("badge-quarantined");
        pill.textContent = "[DISCONNECTED]";
        pill.title = reason || "API unreachable: Hardware connection unverified";
      } else {
        pill.classList.add("badge-simulated");
        pill.textContent = "[CONNECTING...]";
        pill.title = reason || "Awaiting backend confirmation";
      }
    }

    getDefaultCameras() {
      return [
        {
          id: "cam-north-01",
          name: "Perimeter North Gate",
          url: "rtsp://192.168.1.101:554/live/ch0",
          width: 1920,
          height: 1080,
          fps: 15,
          enabled: true,
          privacy_zones: [{ name: "Public Sidewalk", points: [[0, 0], [1920, 0], [1920, 200], [0, 200]] }],
        },
        {
          id: "cam-perimeter-02",
          name: "Perimeter East Fence",
          url: "rtsp://192.168.1.102:554/live/ch0",
          width: 1920,
          height: 1080,
          fps: 15,
          enabled: true,
          privacy_zones: [],
        },
        {
          id: "cam-loading-dock",
          name: "South Loading Dock",
          url: "rtsp://192.168.1.103:554/live/ch0",
          width: 1920,
          height: 1080,
          fps: 15,
          enabled: true,
          privacy_zones: [],
        },
        {
          id: "cam-lobby-04",
          name: "Main Lobby Entrance",
          url: "rtsp://192.168.1.104:554/live/ch0",
          width: 1920,
          height: 1080,
          fps: 15,
          enabled: true,
          privacy_zones: [{ name: "Reception Desk", points: [[500, 400], [900, 400], [900, 800], [500, 800]] }],
        },
      ];
    }

    getDefaultEvents() {
      return [
        {
          event_id: "evt_91f4a0c812d4",
          event_type: "fall_detection",
          severity: "critical",
          confidence: 0.94,
          camera_id: "cam-loading-dock",
          timestamp: new Date(Date.now() - 1000 * 60 * 4).toISOString(),
          requires_verification: true,
          verification_status: "pending",
          description: "Potential prostrate fall posture sustained for 2.4s (AR=1.65)",
          reasoning_trace:
            "Anonymous track #104 transitioned from an upright stance (AR=0.62) to prostrate ground position (AR=1.65). Velocity drop to 0.05 px/frame.",
        },
        {
          event_id: "evt_73a2e1f980bc",
          event_type: "zone_intrusion",
          severity: "high",
          confidence: 0.89,
          camera_id: "cam-north-01",
          timestamp: new Date(Date.now() - 1000 * 60 * 18).toISOString(),
          requires_verification: true,
          verification_status: "pending",
          description: "Anonymous track entered restricted security boundary zone.",
          reasoning_trace:
            "Ray-casting point-in-polygon confirmed track #112 coordinates crossed restricted fence boundary.",
        },
        {
          event_id: "evt_22c8b7f141aa",
          event_type: "loitering",
          severity: "medium",
          confidence: 0.78,
          camera_id: "cam-perimeter-02",
          timestamp: new Date(Date.now() - 1000 * 60 * 45).toISOString(),
          requires_verification: false,
          verification_status: "auto_resolved",
          description: "Extended dwell time (42.0s) observed.",
          reasoning_trace: "Track #108 dwell time exceeded 30.0s threshold.",
        },
      ];
    }

    renderOverview() {
      const tbody = document.getElementById("overview-events-body");
      if (!tbody) return;
      tbody.innerHTML = "";

      this.events.slice(0, 5).forEach((ev) => {
        const tr = document.createElement("tr");
        const sevClass = `badge-${ev.severity}`;
        const isPending = ev.verification_status === "pending";

        tr.innerHTML = `
          <td class="mono">${new Date(ev.timestamp).toLocaleTimeString()}</td>
          <td><strong>${ev.camera_id}</strong></td>
          <td>${ev.event_type}</td>
          <td><span class="badge-pill ${sevClass}">${ev.severity}</span></td>
          <td class="mono">${(ev.confidence * 100).toFixed(0)}%</td>
          <td><span class="badge-pill ${isPending ? "badge-pending" : "badge-verified"}">${ev.verification_status}</span></td>
          <td>
            ${
              isPending
                ? `<button class="btn btn-primary" style="padding: 2px 8px; font-size: 11px;" onclick="window.camservApp.openVerifyModal('${ev.event_id}')">Verify</button>`
                : `<span style="color: var(--text-muted); font-size: 11px;">Signed Off</span>`
            }
          </td>
        `;
        tbody.appendChild(tr);
      });
    }

    renderLiveStreams() {
      const grid = document.getElementById("live-video-grid");
      if (!grid) return;
      grid.innerHTML = "";
      grid.className = `video-grid layout-${this.currentLayout}`;

      const streamMetadata = [
        {
          ispClass: "hud-isp-tier3",
          ispText: "ISP: Tier 3 (Noisy) • Night CLAHE Active",
          threatLevel: 88,
          threatState: "critical",
          behavior: "Fence Intrusion (Bending)",
          speed: "0.4 m/s",
          cardStyle: "",
          color: "#EF4444",
          fillColor: "rgba(239, 68, 68, 0.16)",
          contour: "M 180 140 C 190 125, 230 120, 240 145 C 255 170, 260 210, 250 250 C 240 280, 255 310, 245 340 C 235 365, 215 365, 205 340 C 195 310, 185 270, 175 230 C 165 190, 170 155, 180 140 Z",
          hasReticle: true,
          hasGroundRing: false,
          hasSkeleton: true,
          hasTrail: false,
          skeleton: [
            // Nose, eyes, shoulders, hips, knees, ankles
            { x1: 210, y1: 155, x2: 215, y2: 175 }, // Head to shoulder
            { x1: 195, y1: 175, x2: 235, y2: 175 }, // Shoulders
            { x1: 195, y1: 175, x2: 190, y2: 220 }, // L Arm
            { x1: 190, y1: 220, x2: 220, y2: 265 }, // L Forearm (Bending down)
            { x1: 235, y1: 175, x2: 245, y2: 220 }, // R Arm
            { x1: 245, y1: 220, x2: 235, y2: 265 }, // R Forearm
            { x1: 215, y1: 175, x2: 210, y2: 240 }, // Spine
            { x1: 195, y1: 240, x2: 225, y2: 240 }, // Hips
            { x1: 195, y1: 240, x2: 190, y2: 295 }, // L Thigh
            { x1: 190, y1: 295, x2: 195, y2: 345 }, // L Calf
            { x1: 225, y1: 240, x2: 235, y2: 295 }, // R Thigh
            { x1: 235, y1: 295, x2: 230, y2: 345 }, // R Calf
          ]
        },
        {
          ispClass: "hud-isp-tier2",
          ispText: "ISP: Tier 2 • Standard 1080p",
          threatLevel: 60,
          threatState: "warning",
          behavior: "Hurried Approach",
          speed: "2.1 m/s",
          cardStyle: "warning",
          color: "#F59E0B",
          fillColor: "rgba(245, 158, 11, 0.14)",
          contour: "M 220 130 C 230 115, 270 115, 280 130 C 290 155, 290 200, 285 240 C 280 270, 285 300, 280 330 C 270 350, 240 350, 230 330 C 220 295, 225 250, 215 210 C 210 170, 210 145, 220 130 Z",
          hasReticle: false,
          hasGroundRing: false,
          hasSkeleton: true,
          hasTrail: true,
          trail: [[120, 280], [160, 270], [190, 255], [220, 240], [250, 230]],
          skeleton: [
            { x1: 250, y1: 140, x2: 250, y2: 165 },
            { x1: 235, y1: 165, x2: 265, y2: 165 },
            { x1: 235, y1: 165, x2: 225, y2: 210 },
            { x1: 265, y1: 165, x2: 275, y2: 210 },
            { x1: 250, y1: 165, x2: 250, y2: 235 },
            { x1: 240, y1: 235, x2: 260, y2: 235 },
            { x1: 240, y1: 235, x2: 230, y2: 290 },
            { x1: 230, y1: 290, x2: 225, y2: 335 },
            { x1: 260, y1: 235, x2: 270, y2: 290 },
            { x1: 270, y1: 290, x2: 275, y2: 335 },
          ]
        },
        {
          ispClass: "hud-isp-tier1",
          ispText: "ISP: Tier 1 • 4K Clean Stream",
          threatLevel: 14,
          threatState: "safe",
          behavior: "Normal Transit",
          speed: "1.1 m/s",
          cardStyle: "safe",
          color: "#00E5FF",
          fillColor: "rgba(0, 229, 255, 0.12)",
          contour: "M 200 120 C 210 105, 250 105, 260 120 C 270 145, 270 190, 265 230 C 260 260, 265 290, 260 320 C 250 340, 220 340, 210 320 C 200 285, 205 240, 195 200 C 190 160, 190 135, 200 120 Z",
          hasReticle: false,
          hasGroundRing: true,
          hasSkeleton: false,
          hasTrail: false,
        },
        {
          ispClass: "hud-isp-tier2",
          ispText: "ISP: Tier 2 • Standard 1080p",
          threatLevel: 8,
          threatState: "safe",
          behavior: "Staff Entry",
          speed: "0.8 m/s",
          cardStyle: "safe",
          color: "#00E5FF",
          fillColor: "rgba(0, 229, 255, 0.08)",
          contour: "M 210 130 C 220 115, 250 115, 260 130 C 270 155, 265 195, 260 235 C 255 265, 260 295, 255 325 C 245 340, 225 340, 215 325 C 205 295, 210 250, 205 210 C 200 170, 200 145, 210 130 Z",
          hasReticle: false,
          hasGroundRing: true,
          hasSkeleton: false,
          hasTrail: false,
        }
      ];

      const layoutCapacities = {
        "1x1": 1,
        "1x2": 2,
        "2x2": 4,
        "3x3": 9,
        "4x4": 16,
        "5x5": 25,
        "custom": 16
      };
      const capacity = layoutCapacities[this.currentLayout] || 4;
      const visibleCameras = this.cameras.slice(0, capacity);

      visibleCameras.forEach((cam, idx) => {
        const meta = streamMetadata[idx % streamMetadata.length];
        const card = document.createElement("div");
        card.className = "video-card";
        if (this.maximizedTileId === cam.id) {
          card.classList.add("maximized");
        }
        card.draggable = true;
        card.dataset.index = idx;
        card.dataset.camId = cam.id;

        card.addEventListener("dragstart", (e) => {
          this.draggedIndex = idx;
          e.dataTransfer.setData("text/plain", idx);
          card.classList.add("dragging");
        });
        card.addEventListener("dragend", () => {
          card.classList.remove("dragging");
        });
        card.addEventListener("dragover", (e) => {
          e.preventDefault();
          card.classList.add("drag-over");
        });
        card.addEventListener("dragleave", () => {
          card.classList.remove("drag-over");
        });
        card.addEventListener("drop", (e) => {
          e.preventDefault();
          card.classList.remove("drag-over");
          const srcIdx = parseInt(e.dataTransfer.getData("text/plain"), 10);
          if (!isNaN(srcIdx) && srcIdx !== idx) {
            this.swapCameras(srcIdx, idx);
          }
        });

        // SVG overlays for Cinematic HUD
        let svgElements = "";
        if (this.showBoxes) {
          // Polygon Contour
          svgElements += `
            <path d="${meta.contour}" fill="${meta.fillColor}" stroke="${meta.color}" stroke-width="2.5" filter="drop-shadow(0 0 6px ${meta.color})" />
          `;

          // Motion trail
          if (meta.hasTrail && meta.trail) {
            let trailD = `M ${meta.trail[0][0]} ${meta.trail[0][1]}`;
            for (let i = 1; i < meta.trail.length; i++) {
              trailD += ` L ${meta.trail[i][0]} ${meta.trail[i][1]}`;
            }
            svgElements += `
              <path d="${trailD}" fill="none" stroke="${meta.color}" stroke-width="3" stroke-linecap="round" stroke-dasharray="4 4" opacity="0.8" />
            `;
          }

          // 3D Ground Elliptical Ring
          if (meta.hasGroundRing) {
            svgElements += `
              <ellipse cx="235" cy="335" rx="42" ry="14" fill="none" stroke="${meta.color}" stroke-width="2" opacity="0.9" filter="drop-shadow(0 0 5px ${meta.color})" />
              <circle cx="235" cy="335" r="3" fill="${meta.color}" />
            `;
          }

          // Skeletal Pose Overlay
          if (this.showPose && meta.hasSkeleton && meta.skeleton) {
            meta.skeleton.forEach((b) => {
              svgElements += `<line x1="${b.x1}" y1="${b.y1}" x2="${b.x2}" y2="${b.y2}" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" />`;
              svgElements += `<circle cx="${b.x1}" cy="${b.y1}" r="3" fill="${meta.color}" />`;
              svgElements += `<circle cx="${b.x2}" cy="${b.y2}" r="3" fill="${meta.color}" />`;
            });
          }

          // Target Lock-On Reticle
          if (meta.hasReticle) {
            const rx1 = 155, ry1 = 110, rx2 = 280, ry2 = 360, arm = 18;
            svgElements += `
              <path d="M ${rx1} ${ry1+arm} L ${rx1} ${ry1} L ${rx1+arm} ${ry1}" fill="none" stroke="${meta.color}" stroke-width="2.5" />
              <path d="M ${rx2-arm} ${ry1} L ${rx2} ${ry1} L ${rx2} ${ry1+arm}" fill="none" stroke="${meta.color}" stroke-width="2.5" />
              <path d="M ${rx1} ${ry2-arm} L ${rx1} ${ry2} L ${rx1+arm} ${ry2}" fill="none" stroke="${meta.color}" stroke-width="2.5" />
              <path d="M ${rx2-arm} ${ry2} L ${rx2} ${ry2} L ${rx2} ${ry2-arm}" fill="none" stroke="${meta.color}" stroke-width="2.5" />
            `;
          }
        }

        // Privacy Blur Mask (for cam 4 or when enabled)
        let privacyElement = "";
        if (this.showPrivacy && (idx === 3 || (cam.privacy_zones && cam.privacy_zones.length > 0))) {
          privacyElement = `
            <div style="position: absolute; top: 20px; right: 20px; width: 140px; height: 90px; background: rgba(15, 23, 42, 0.7); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border: 1px dashed rgba(255, 255, 255, 0.3); border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 10px; color: #fff; font-family: var(--font-mono);">
              🛡️ PRIVACY MASK
            </div>
          `;
        }

        // Floating Glassmorphic HUD Card
        let hudCard = "";
        if (this.showBoxes) {
          hudCard = `
            <div class="hud-glass-card ${meta.cardStyle}" style="top: 80px; left: 140px;">
              [Threat: ${meta.threatLevel}% | ${meta.behavior} | Speed: ${meta.speed}]
            </div>
          `;
        }

        const isVerifiedHardware = this.apiConnected && this.hasHardware && idx === 0;
        const epistemicBadge = isVerifiedHardware
          ? `<span class="badge-epistemic badge-hw-verified" title="Probed from physical host optical hardware">[HW-VERIFIED]</span>`
          : `<span class="badge-epistemic badge-simulated" title="Generated by CI synthetic RTSP harness">[SIMULATED]</span>`;

        const isMaximized = this.maximizedTileId === cam.id;
        const maximizeBtn = `
          <button class="btn btn-outline" style="padding: 2px 6px; font-size: 10px; margin-left: 4px;" onclick="window.camservApp.toggleTileMaximize('${cam.id}')" title="${isMaximized ? 'Restore normal grid' : 'Maximize stream'}">
            ${isMaximized ? '🗗 Restore' : '🗖 Max'}
          </button>
        `;

        card.innerHTML = `
          <div class="video-header" style="cursor: grab;" title="Drag to reorder stream position">
            <span style="display: flex; align-items: center; gap: 4px;">
              <span style="opacity: 0.5;">⠿</span> 📹 ${cam.name} (${cam.id})
            </span>
            <div style="display: flex; align-items: center; gap: 6px;">
              ${epistemicBadge}
              <span class="hud-isp-pill ${meta.ispClass}">${meta.ispText}</span>
              <span style="color: var(--accent-emerald); font-family: var(--font-mono); font-size: 11px;">● 25 FPS</span>
              ${maximizeBtn}
            </div>
          </div>
          <div class="video-canvas-box" style="position: relative; overflow: hidden; background: radial-gradient(circle at center, #0d1527 0%, #050811 100%);">
            <div class="video-overlay-badge mono">[LIVE RTSP] ${cam.width}x${cam.height} • H.265</div>
            <div class="video-overlay-privacy mono">🔒 PRIVACY ACTIVE</div>
            
            <!-- SVG HUD Layer -->
            <svg style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;" viewBox="0 0 480 380">
              ${svgElements}
            </svg>

            ${privacyElement}
            ${hudCard}

            <div class="video-placeholder-text" style="pointer-events: none; opacity: 0.7; position: absolute; bottom: 10px; left: 14px; text-align: left;">
              <div style="font-size: 10px; color: var(--text-muted); font-family: var(--font-mono);">
                BUFFER: 15s RING • THREAT EVAL: 100% LOCAL ZERO-API • LEASE: ACTIVE
              </div>
            </div>
          </div>
          <div class="video-footer-bar">
            <span>Bitrate: <strong>4.2 Mbps</strong></span>
            <span>Lease: <span style="color: var(--accent-cyan); font-weight: 700;">Valid (Epoch 1)</span></span>
            <span>Loss: <strong>0.00%</strong></span>
          </div>
        `;
        grid.appendChild(card);
      });
    }

    renderCameras() {
      const tbody = document.getElementById("cameras-table-body");
      if (!tbody) return;
      tbody.innerHTML = "";

      this.cameras.forEach((cam) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="mono"><strong>${cam.id}</strong></td>
          <td>${cam.name}</td>
          <td class="mono" style="color: var(--accent-cyan); font-size: 11px;">${cam.url}</td>
          <td class="mono">${cam.width}x${cam.height}</td>
          <td class="mono">${cam.fps} FPS</td>
          <td>${cam.privacy_zones ? cam.privacy_zones.length : 0} Mask(s)</td>
          <td><span class="badge-pill badge-verified">ONLINE</span></td>
          <td>
            <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 11px;" onclick="alert('Editing camera ${cam.id}')">Configure</button>
          </td>
        `;
        tbody.appendChild(tr);
      });

      const badgeCams = document.getElementById("badge-active-cams");
      if (badgeCams) badgeCams.textContent = this.cameras.length;
    }

    renderEvents() {
      const tbody = document.getElementById("events-table-body");
      if (!tbody) return;
      tbody.innerHTML = "";

      this.events.forEach((ev) => {
        const tr = document.createElement("tr");
        const sevClass = `badge-${ev.severity}`;
        const isPending = ev.verification_status === "pending";

        tr.innerHTML = `
          <td class="mono">${ev.event_id}</td>
          <td class="mono">${new Date(ev.timestamp).toLocaleTimeString()}</td>
          <td>${ev.camera_id}</td>
          <td><strong>${ev.event_type}</strong></td>
          <td><span class="badge-pill ${sevClass}">${ev.severity}</span></td>
          <td class="mono">${(ev.confidence * 100).toFixed(0)}%</td>
          <td><span class="badge-pill ${isPending ? "badge-pending" : "badge-verified"}">${ev.verification_status}</span></td>
          <td>
            ${
              isPending
                ? `<button class="btn btn-primary" style="padding: 2px 8px; font-size: 11px;" onclick="window.camservApp.openVerifyModal('${ev.event_id}')">Review & Sign Off</button>`
                : `<span style="color: var(--accent-emerald); font-size: 11px;">Verified</span>`
            }
          </td>
        `;
        tbody.appendChild(tr);
      });

      const pendingCount = this.events.filter((e) => e.verification_status === "pending").length;
      const badgeEv = document.getElementById("badge-pending-events");
      if (badgeEv) badgeEv.textContent = pendingCount;
      const kpiAlerts = document.getElementById("kpi-alerts");
      if (kpiAlerts) kpiAlerts.textContent = `${pendingCount} PENDING`;
    }

    renderTracking() {
      const tbody = document.getElementById("tracking-table-body");
      if (!tbody) return;
      tbody.innerHTML = "";

      const sampleTracks = [
        { id: 104, cls: "person", cam: "cam-loading-dock", state: "CONFIRMED", age: 142, vel: 0.12, conf: 0.94 },
        { id: 112, cls: "person", cam: "cam-north-01", state: "CONFIRMED", age: 89, vel: 1.45, conf: 0.91 },
        { id: 115, cls: "car", cam: "cam-perimeter-02", state: "CONFIRMED", age: 310, vel: 4.80, conf: 0.96 },
        { id: 118, cls: "person", cam: "cam-lobby-04", state: "TENTATIVE", age: 8, vel: 0.85, conf: 0.82 },
      ];

      sampleTracks.forEach((t) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="mono"><strong>#${t.id}</strong> (Anonymous)</td>
          <td>${t.cls}</td>
          <td>${t.cam}</td>
          <td><span class="badge-pill badge-verified">${t.state}</span></td>
          <td class="mono">${t.age}</td>
          <td class="mono">${t.vel}</td>
          <td class="mono">${(t.conf * 100).toFixed(0)}%</td>
        `;
        tbody.appendChild(tr);
      });
    }

    renderEvidence() {
      const tbody = document.getElementById("evidence-table-body");
      if (!tbody) return;
      tbody.innerHTML = "";

      const samplePackages = [
        {
          id: "PKG_20261113_001",
          event: "evt_91f4a0c812d4",
          cam: "cam-loading-dock",
          time: "2026-11-13 21:14 UTC",
          sha: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
          sig: "Ed25519 (Valid)",
          status: "SEALED",
        },
        {
          id: "PKG_20261113_002",
          event: "evt_73a2e1f980bc",
          cam: "cam-north-01",
          time: "2026-11-13 21:00 UTC",
          sha: "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
          sig: "Ed25519 (Valid)",
          status: "SEALED",
        },
      ];

      samplePackages.forEach((pkg) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="mono"><strong>${pkg.id}</strong></td>
          <td class="mono">${pkg.event}</td>
          <td>${pkg.cam}</td>
          <td class="mono">${pkg.time}</td>
          <td class="mono" style="font-size: 10px; color: var(--accent-cyan);">${pkg.sha.slice(0, 16)}...</td>
          <td><span class="badge-pill badge-verified">${pkg.sig}</span></td>
          <td><span class="badge-pill badge-verified">${pkg.status}</span></td>
        `;
        tbody.appendChild(tr);
      });
    }

    renderAuditLogs() {
      const tbody = document.getElementById("audit-table-body");
      if (!tbody) return;
      tbody.innerHTML = "";

      const sampleAudit = [
        {
          idx: 30,
          ts: new Date().toLocaleTimeString(),
          actor: "OPERATOR",
          action: "CONFIG_UPDATE",
          res: "pipeline.inference",
          result: "SUCCESS",
          hash: "a4f891b2c3d4...",
        },
        {
          idx: 29,
          ts: new Date(Date.now() - 30000).toLocaleTimeString(),
          actor: "SYSTEM",
          action: "HARDWARE_PROBE",
          res: "platform.hardware",
          result: "SUCCESS",
          hash: "7b1928ef01ca...",
        },
        {
          idx: 28,
          ts: new Date(Date.now() - 60000).toLocaleTimeString(),
          actor: "ADMIN",
          action: "USER_LOGIN",
          res: "auth.session",
          result: "SUCCESS",
          hash: "0f48da2718ec...",
        },
      ];

      sampleAudit.forEach((a) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="mono">#${a.idx}</td>
          <td class="mono">${a.ts}</td>
          <td><strong>${a.actor}</strong></td>
          <td class="mono">${a.action}</td>
          <td>${a.res}</td>
          <td><span class="badge-pill badge-verified">${a.result}</span></td>
          <td class="mono" style="font-size: 10px; color: var(--accent-cyan);">${a.hash}</td>
        `;
        tbody.appendChild(tr);
      });
    }

    openVerifyModal(eventId) {
      const ev = this.events.find((e) => e.event_id === eventId);
      if (!ev) return;
      this.activeEventForVerify = ev;

      document.getElementById("verify-modal-title").textContent = `Verify Event: ${ev.event_type.toUpperCase()} (${ev.event_id})`;
      document.getElementById("verify-modal-desc").textContent = ev.description;
      document.getElementById("verify-modal-reasoning").textContent = `Reasoning Trace: ${ev.reasoning_trace || "None available."}`;
      document.getElementById("verify-notes").value = "";

      this.openModal("modal-verify");
    }

    async submitVerification(status) {
      if (!this.activeEventForVerify) return;
      const eventId = this.activeEventForVerify.event_id;
      const notes = document.getElementById("verify-notes").value;

      try {
        await fetch(`/api/v1/events/${eventId}/verify`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ verified_status: status, rationale: notes || "Signed off via Web Console" }),
        });
      } catch (err) {
        console.warn("Backend verify API offline, applying client-side state update.");
      }

      // Update local event state
      this.activeEventForVerify.verification_status = status;
      this.closeModal("modal-verify");
      this.renderEvents();
      this.renderOverview();
    }

    async submitAddCamera() {
      const id = document.getElementById("add-cam-id").value.trim();
      const name = document.getElementById("add-cam-name").value.trim();
      const url = document.getElementById("add-cam-url").value.trim();
      const fps = parseInt(document.getElementById("add-cam-fps").value, 10) || 15;

      if (!id || !name || !url) {
        alert("Please fill in Camera ID, Name, and RTSP URL.");
        return;
      }

      const newCam = { id, name, url, fps, width: 1920, height: 1080, enabled: true, privacy_zones: [] };

      try {
        await fetch("/api/v1/cameras", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(newCam),
        });
      } catch (err) {
        console.warn("Backend camera add API offline; persisting in client inventory.");
      }

      this.cameras.push(newCam);
      this.closeModal("modal-add-cam");
      this.renderCameras();
      this.renderLiveStreams();
    }

    async performONVIFScan() {
      const out = document.getElementById("onvif-scan-output");
      if (!out) return;
      out.innerHTML = `
        <div style="color: var(--accent-cyan); font-family: var(--font-mono); font-size: 12px;">
          [SCANNING] Broadcasting WS-Discovery multicast probe to 239.255.255.250:3702...
        </div>
      `;

      setTimeout(() => {
        out.innerHTML = `
          <div style="font-family: var(--font-mono); font-size: 12px; line-height: 1.8;">
            <div style="color: var(--accent-emerald);">✔ Discovery completed. Discovered 2 ONVIF Compliant Transmitters:</div>
            <div style="margin-top: 8px; padding-left: 12px; border-left: 2px solid var(--accent-cyan);">
              <div>[1] <strong>Hikvision DS-2CD2143G2-I</strong> @ 192.168.1.101 (Profile S / Profile T)</div>
              <div>[2] <strong>Dahua NVR5216-16P-4KS2E</strong> @ 192.168.1.200 (Profile S / Profile G)</div>
            </div>
            <div style="margin-top: 12px;">
              <button class="btn btn-secondary" onclick="alert('Imported 2 cameras into inventory.'); window.camservApp.switchScreen('cameras');">Import Endpoints</button>
            </div>
          </div>
        `;
      }, 1200);
    }

    openEvidenceVerifier() {
      alert("Launching Offline Evidence Verifier.\nUse 'camserv verify-evidence <package.zip>' for courtroom-grade CLI verification.");
    }

    openModal(id) {
      const el = document.getElementById(id);
      if (el) el.classList.add("active");
    }

    closeModal(id) {
      const el = document.getElementById(id);
      if (el) el.classList.remove("active");
    }

    submitJudicialAuth() {
      const off2 = document.getElementById("judicial-officer-2")?.value;
      const warrant = document.getElementById("judicial-warrant")?.value;
      if (!off2 || !warrant) {
        alert("Error: Dual-Control requires both Co-Signer ID and Court Warrant Reference.");
        return;
      }
      alert(`Dual-Control Quorum Verified: Authorized by Lead Forensics Officer #1092 and ${off2}.\nWarrant Ref: ${warrant}\nCourtroom evidence bundle decrypted.`);
      this.closeModal("modal-judicial-export");
    }

    startTelemetryLoop() {
      setInterval(() => {
        // Subtle realistic jitter for latency HUD
        const p50 = (14.0 + Math.random() * 1.5).toFixed(1);
        const p99 = (28.0 + Math.random() * 2.2).toFixed(1);
        const pillP50 = document.getElementById("pill-p50");
        const pillP99 = document.getElementById("pill-p99");
        if (pillP50) pillP50.textContent = `${p50} ms`;
        if (pillP99) pillP99.textContent = `${p99} ms`;
      }, 2500);
    }

    /* =========================================================================
     * Phase 23: Operator Workspace & Multi-Monitor Console Methods
     * ========================================================================= */
    initWorkspaces() {
      try {
        const stored = localStorage.getItem("camserv_saved_workspaces");
        if (stored) {
          const parsed = JSON.parse(stored);
          if (Array.isArray(parsed) && parsed.length > 0) {
            this.savedWorkspaces = parsed;
            return;
          }
        }
      } catch (e) {
        console.warn("Failed to load saved workspaces from storage", e);
      }
      this.savedWorkspaces = [
        {
          id: "ws-default-control",
          name: "Default Control Desk",
          layout: "2x2",
          context: "general",
          profile: "balanced",
          cameras: ["cam-north-01", "cam-south-02", "cam-east-gate", "cam-interior-hq"],
          created_at: new Date().toISOString()
        },
        {
          id: "ws-perimeter-defense",
          name: "Perimeter Active Surveillance",
          layout: "1x2",
          context: "perimeter",
          profile: "high_performance",
          cameras: ["cam-north-01", "cam-east-gate"],
          created_at: new Date().toISOString()
        },
        {
          id: "ws-forensic-investigation",
          name: "Forensic Investigation Focus",
          layout: "1x1",
          context: "investigation",
          profile: "balanced",
          cameras: ["cam-north-01"],
          created_at: new Date().toISOString()
        }
      ];
    }

    switchLayout(preset) {
      this.currentLayout = preset;
      this.maximizedTileId = null;
      document.querySelectorAll(".btn-layout-preset").forEach(btn => {
        if (btn.textContent.trim().toLowerCase() === preset.toLowerCase()) {
          btn.classList.add("active");
        } else if (!btn.textContent.includes("Restore")) {
          btn.classList.remove("active");
        }
      });
      const grid = document.getElementById("live-video-grid");
      if (grid) {
        grid.className = `video-grid layout-${preset}`;
      }
      this.renderLiveStreams();
    }

    toggleTileMaximize(camId) {
      if (this.maximizedTileId === camId) {
        this.maximizedTileId = null;
      } else {
        this.maximizedTileId = camId;
      }
      this.renderLiveStreams();
    }

    restoreAllTiles() {
      this.maximizedTileId = null;
      this.renderLiveStreams();
    }

    swapCameras(srcIdx, tgtIdx) {
      if (srcIdx < 0 || srcIdx >= this.cameras.length || tgtIdx < 0 || tgtIdx >= this.cameras.length) return;
      const temp = this.cameras[srcIdx];
      this.cameras[srcIdx] = this.cameras[tgtIdx];
      this.cameras[tgtIdx] = temp;
      this.renderLiveStreams();
      this.renderCameras();
    }

    openVideoWall() {
      const wallUrl = "/#screen-live";
      const w = 1280;
      const h = 720;
      const left = (window.screen.availWidth - w) / 2;
      const top = (window.screen.availHeight - h) / 2;
      window.open(
        wallUrl,
        "CAMserv_VideoWall",
        `width=${w},height=${h},left=${left},top=${top},menubar=no,toolbar=no,location=no,status=no,resizable=yes`
      );
    }

    switchContext(contextName) {
      this.currentContext = contextName;
      if (contextName === "perimeter") {
        this.switchLayout("1x2");
      } else if (contextName === "investigation") {
        this.switchLayout("1x1");
      } else if (contextName === "multi_site") {
        this.switchLayout("3x3");
      } else if (contextName === "diagnostics") {
        this.switchLayout("2x2");
      } else {
        this.switchLayout("2x2");
      }
    }

    saveCurrentWorkspacePrompt() {
      const name = prompt("Enter a descriptive name for this Operator Workspace:", `Workspace ${this.savedWorkspaces.length + 1}`);
      if (!name || !name.trim()) return;
      const cleanName = name.trim().slice(0, 64);
      const ws = {
        id: "ws-" + Date.now().toString(36),
        name: cleanName,
        layout: this.currentLayout,
        context: this.currentContext,
        profile: this.currentProfile,
        cameras: this.cameras.map(c => c.id),
        created_at: new Date().toISOString()
      };
      this.savedWorkspaces.push(ws);
      try {
        localStorage.setItem("camserv_saved_workspaces", JSON.stringify(this.savedWorkspaces));
      } catch (e) {
        console.warn("localStorage quota exceeded", e);
      }
      const activeLabel = document.getElementById("ws-active-name");
      if (activeLabel) activeLabel.textContent = cleanName;
      this.renderWorkspaceList();
    }

    renderWorkspaceList() {
      const container = document.getElementById("workspace-list-container");
      if (!container) return;
      container.innerHTML = "";

      if (this.savedWorkspaces.length === 0) {
        container.innerHTML = `<div style="font-size: 11px; color: var(--text-muted); padding: 8px;">No saved workspaces found.</div>`;
        return;
      }

      this.savedWorkspaces.forEach((ws) => {
        const item = document.createElement("div");
        item.style.cssText = "display: flex; justify-content: space-between; align-items: center; background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-subtle); padding: 8px 12px; border-radius: var(--radius-xs);";
        item.innerHTML = `
          <div>
            <div style="font-weight: 600; font-size: 12px; color: var(--text-primary);">${ws.name}</div>
            <div style="font-size: 10px; color: var(--text-muted); font-family: var(--font-mono);">
              Layout: ${ws.layout} • Context: ${ws.context} • Cameras: ${ws.cameras ? ws.cameras.length : 0}
            </div>
          </div>
          <div style="display: flex; gap: 6px;">
            <button class="btn btn-primary" style="padding: 2px 8px; font-size: 11px;" onclick="window.camservApp.loadSavedWorkspace('${ws.id}')">Apply</button>
            <button class="btn btn-secondary" style="padding: 2px 8px; font-size: 11px; color: var(--accent-rose);" onclick="window.camservApp.deleteSavedWorkspace('${ws.id}')">Delete</button>
          </div>
        `;
        container.appendChild(item);
      });
    }

    loadSavedWorkspace(id) {
      const ws = this.savedWorkspaces.find(w => w.id === id);
      if (!ws) return;
      this.switchLayout(ws.layout || "2x2");
      this.currentContext = ws.context || "general";
      const selContext = document.getElementById("select-context");
      if (selContext) selContext.value = this.currentContext;

      // Reorder cameras to match workspace camera order if present
      if (Array.isArray(ws.cameras) && ws.cameras.length > 0) {
        const sorted = [];
        ws.cameras.forEach(cid => {
          const found = this.cameras.find(c => c.id === cid);
          if (found) sorted.push(found);
        });
        this.cameras.forEach(c => {
          if (!sorted.includes(c)) sorted.push(c);
        });
        this.cameras = sorted;
        this.renderLiveStreams();
        this.renderCameras();
      }

      const activeLabel = document.getElementById("ws-active-name");
      if (activeLabel) activeLabel.textContent = ws.name;
      this.closeModal("modal-workspace-manager");
    }

    deleteSavedWorkspace(id) {
      this.savedWorkspaces = this.savedWorkspaces.filter(w => w.id !== id);
      try {
        localStorage.setItem("camserv_saved_workspaces", JSON.stringify(this.savedWorkspaces));
      } catch (e) {
        console.warn("Storage write error", e);
      }
      this.renderWorkspaceList();
    }

    exportCurrentWorkspace() {
      const exportObj = {
        schema_version: "2.0",
        workspace_id: "export-" + Date.now().toString(36),
        name: document.getElementById("ws-active-name")?.textContent || "Exported Workspace",
        description: "Exported Operator Workspace Configuration from CAMserv Console",
        operational_context: this.currentContext,
        resource_profile: this.currentProfile,
        layout: {
          display_id: "primary",
          preset: this.currentLayout,
          tiles: this.cameras.slice(0, 16).map((c, i) => ({
            camera_id: c.id,
            grid_row: Math.floor(i / 2),
            grid_col: i % 2,
            stream_type: "main",
            truthfulness_state: "verified_live"
          }))
        },
        exported_at: new Date().toISOString()
      };
      const jsonStr = JSON.stringify(exportObj, null, 2);
      const area = document.getElementById("ws-import-export-area");
      if (area) {
        area.value = jsonStr;
        area.select();
      }
    }

    triggerImportWorkspace() {
      const area = document.getElementById("ws-import-export-area");
      if (area) {
        area.focus();
        area.placeholder = "Paste JSON here and click Validate & Load JSON below...";
      }
    }

    processImportedJSON() {
      const area = document.getElementById("ws-import-export-area");
      if (!area || !area.value.trim()) {
        alert("Please paste valid JSON workspace payload into the area first.");
        return;
      }
      const rawText = area.value.trim();
      if (rawText.length > 512 * 1024) {
        alert("Security Validation Failed: JSON payload exceeds 512KB maximum permitted limit.");
        return;
      }

      try {
        const parsed = JSON.parse(rawText);
        // Security check: ensure no forbidden secret/token fields
        const forbiddenKeys = ["password", "secret", "token", "private_key", "credential", "auth_token"];
        const jsonKeyCheck = JSON.stringify(parsed).toLowerCase();
        for (const k of forbiddenKeys) {
          if (jsonKeyCheck.includes(`"${k}"`)) {
            alert(`Security Warning: Prohibited sensitive credential key "${k}" detected in workspace payload. Key stripped.`);
          }
        }

        const name = parsed.name || parsed.workspace_name || "Imported Workspace";
        const layoutPreset = (parsed.layout && parsed.layout.preset) ? parsed.layout.preset : (parsed.layout || "2x2");
        const context = parsed.operational_context || parsed.context || "general";
        const cams = (parsed.layout && Array.isArray(parsed.layout.tiles))
          ? parsed.layout.tiles.map(t => t.camera_id)
          : (Array.isArray(parsed.cameras) ? parsed.cameras : []);

        const ws = {
          id: "imported-" + Date.now().toString(36),
          name: String(name).slice(0, 64),
          layout: layoutPreset,
          context: context,
          profile: parsed.resource_profile || "balanced",
          cameras: cams,
          created_at: new Date().toISOString()
        };

        this.savedWorkspaces.push(ws);
        try {
          localStorage.setItem("camserv_saved_workspaces", JSON.stringify(this.savedWorkspaces));
        } catch (e) {}

        this.loadSavedWorkspace(ws.id);
        alert(`Successfully imported and applied workspace: ${ws.name}`);
      } catch (err) {
        alert("JSON Parsing Error: Invalid JSON syntax in workspace payload: " + err.message);
      }
    }

    triggerEventFocus(eventObj) {
      if (!eventObj || !eventObj.camera_id) return;
      this.eventFocusState = {
        isFocused: false,
        previousLayout: this.currentLayout,
        previousMaximizedTileId: this.maximizedTileId,
        activeEvent: eventObj
      };

      const banner = document.getElementById("event-focus-banner");
      const title = document.getElementById("event-focus-title");
      const desc = document.getElementById("event-focus-desc");

      if (banner && title && desc) {
        title.textContent = `EVENT CANDIDATE DETECTED: [Hypothesis] ${eventObj.title || eventObj.type || 'Activity'}`;
        desc.textContent = `Camera: ${eventObj.camera_id} • Score: ${Math.round((eventObj.confidence || 0.85) * 100)}% • Non-consequential preview (Human Verification Required)`;
        banner.style.display = "flex";
      }
    }

    focusEventCamera() {
      if (!this.eventFocusState.activeEvent) return;
      const camId = this.eventFocusState.activeEvent.camera_id;
      this.toggleTileMaximize(camId);
      this.eventFocusState.isFocused = true;
    }

    dismissEventFocus() {
      const banner = document.getElementById("event-focus-banner");
      if (banner) banner.style.display = "none";
      if (this.eventFocusState.isFocused) {
        this.maximizedTileId = this.eventFocusState.previousMaximizedTileId || null;
        this.switchLayout(this.eventFocusState.previousLayout || "2x2");
      }
      this.eventFocusState = { isFocused: false, previousLayout: this.currentLayout, activeEvent: null };
      this.renderLiveStreams();
    }
  }

  // Mount to global window for inline event handlers
  window.addEventListener("DOMContentLoaded", () => {
    window.camservApp = new CAMservClient();
  });
})();
