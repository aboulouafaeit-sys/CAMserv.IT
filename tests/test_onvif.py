"""Tests for camserv.acquisition.onvif."""
from __future__ import annotations

import pytest

from camserv.acquisition.onvif import (
    DeploymentTopology,
    DiscoveredCamera,
    NVRCompatibilityTester,
    ONVIFDiscovery,
    ONVIFProfile,
)


@pytest.mark.unit
def test_parse_probe_match_xml() -> None:
    """Test extracting device metadata from simulated ONVIF ProbeMatch SOAP XML."""
    sample_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Envelope xmlns="http://www.w3.org/2003/05/soap-envelope">'
        '<Body>'
        '<ProbeMatches xmlns="http://schemas.xmlsoap.org/ws/2005/04/discovery">'
        '<ProbeMatch>'
        '<EndpointReference><Address>urn:uuid:48696b76-6973-696f-6e00-001122334455</Address></EndpointReference>'
        '<Types>dn:NetworkVideoTransmitter</Types>'
        '<Scopes>onvif://www.onvif.org/name/Hikvision onvif://www.onvif.org/hardware/DS-2CD2143G2-I</Scopes>'
        '<XAddrs>http://192.168.1.101/onvif/device_service</XAddrs>'
        '</ProbeMatch>'
        '</ProbeMatches>'
        '</Body>'
        '</Envelope>'
    )

    dev = ONVIFDiscovery._parse_probe_match(sample_xml, source_ip="192.168.1.101")
    assert dev is not None
    assert dev.ip_address == "192.168.1.101"
    assert dev.xaddrs == "http://192.168.1.101/onvif/device_service"
    assert "Hikvision" in dev.manufacturer
    assert "DS-2CD2143G2-I" in dev.model
    assert ONVIFProfile.PROFILE_S in dev.profiles_supported


@pytest.mark.asyncio
async def test_nvr_compatibility_tester() -> None:
    """Test testing an RTSP endpoint with Topology A."""
    report = await NVRCompatibilityTester.test_endpoint(
        rtsp_url="rtsp://127.0.0.1:8554/live/ch1",
        topology=DeploymentTopology.TOPOLOGY_A_NVR_INTERCONNECT,
    )
    assert report.target_host == "127.0.0.1"
    assert report.topology == DeploymentTopology.TOPOLOGY_A_NVR_INTERCONNECT
    assert "H264" in report.supported_codecs
    assert report.stream_stability_score > 0.0
    assert len(report.notes) > 0
