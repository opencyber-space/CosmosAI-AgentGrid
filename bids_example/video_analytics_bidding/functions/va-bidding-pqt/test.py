"""Local checks for pre-qualification, per contracts/pqt-function.md.

Run from this directory:  ../../../venv/bin/python test.py

The cases mirror the five companies in the demonstrated round, so a change that would
alter who qualifies fails here rather than in the cluster.
"""
import json

from function.code.function import AIOSv1PolicyRule

SETTINGS = {
    "required_certifications_any_of": ["NIST", "benchmarking", "UL"],
    "min_licenses_supplied": 10000,
    "min_projects_served": 5,
}


def rule():
    return AIOSv1PolicyRule("va-bidding-pqt:1.0-stable", SETTINGS, {})


def bid(subject, credentials, status="submitted"):
    return {
        "bid_job": {"bid_job_id": "job-1", "bid_job_description": {"task_type": "video_analytics_rfp"}},
        "bid": {"bid_id": "b-1", "bid_subject_id": subject,
                "bid_data": {"bid_status": status, "credentials": credentials}},
    }


def test_camfacesolution_qualifies():
    out = rule().eval({}, bid("camfacesolution-bid-manager", {
        "certifications": ["NIST FRVT", "UL CyberSecurity"],
        "projects_served": 14, "licenses_supplied": 42000}), {})
    assert out["accepted"] is True, out


def test_ultravideotech_qualifies():
    out = rule().eval({}, bid("ultravideotech-bid-manager", {
        "certifications": ["NIST FRVT", "ISO 27001"],
        "projects_served": 22, "licenses_supplied": 61000}), {})
    assert out["accepted"] is True, out


def test_newgentech_is_rejected_on_every_bar():
    """The company the round is built around: bids honestly, fails on credentials."""
    out = rule().eval({}, bid("newgentech-bid-manager", {
        "certifications": [], "projects_served": 2, "licenses_supplied": 3500}), {})
    assert out["accepted"] is False
    assert "certification" in out["reason"]
    assert "3500" in out["reason"]
    assert "2" in out["reason"]


def test_missing_certification_alone_rejects():
    out = rule().eval({}, bid("x", {
        "certifications": [], "projects_served": 14, "licenses_supplied": 42000}), {})
    assert out["accepted"] is False
    assert "certification" in out["reason"]


def test_licences_below_bar_alone_rejects():
    out = rule().eval({}, bid("x", {
        "certifications": ["NIST FRVT"], "projects_served": 14, "licenses_supplied": 3500}), {})
    assert out["accepted"] is False
    assert "3500" in out["reason"]


def test_projects_below_bar_alone_rejects():
    out = rule().eval({}, bid("x", {
        "certifications": ["NIST FRVT"], "projects_served": 2, "licenses_supplied": 42000}), {})
    assert out["accepted"] is False
    assert "projects served 2" in out["reason"]


def test_certification_match_is_substring_and_case_insensitive():
    """A company states 'NIST FRVT' where the RFP says 'NIST'."""
    out = rule().eval({}, bid("x", {
        "certifications": ["nist frvt"], "projects_served": 9, "licenses_supplied": 15000}), {})
    assert out["accepted"] is True, out


def test_declining_bid_passes_through():
    """A decline carries nothing to judge; the evaluator excludes it on bid_status."""
    out = rule().eval({}, bid("multifacetech-bid-manager", {
        "certifications": ["NIST FRVT"], "projects_served": 9, "licenses_supplied": 15000},
        status="declined"), {})
    assert out["accepted"] is True
    assert "declining" in out["reason"]


def test_declining_bid_with_weak_credentials_still_passes_through():
    out = rule().eval({}, bid("x", {"certifications": [], "projects_served": 0,
                                    "licenses_supplied": 0}, status="declined"), {})
    assert out["accepted"] is True


def test_missing_credentials_rejects_without_raising():
    out = rule().eval({}, {"bid_job": {}, "bid": {"bid_data": {"bid_status": "submitted"}}}, {})
    assert out["accepted"] is False
    assert "credentials" in out["reason"]


def test_non_numeric_counts_reject_without_raising():
    out = rule().eval({}, bid("x", {"certifications": ["NIST"],
                                    "projects_served": "many",
                                    "licenses_supplied": "lots"}), {})
    assert out["accepted"] is False
    assert "not a number" in out["reason"]


def test_comma_formatted_counts_are_read():
    out = rule().eval({}, bid("x", {"certifications": ["NIST"],
                                    "projects_served": 14,
                                    "licenses_supplied": "42,000"}), {})
    assert out["accepted"] is True, out


def test_garbage_input_does_not_raise():
    for bad in ({}, {"bid": None}, {"bid": {"bid_data": None}}, None):
        out = rule().eval({}, bad, {})
        assert isinstance(out, dict) and "accepted" in out


def test_settings_drive_the_bars_not_code():
    """A different RFP changes settings, not this function."""
    lenient = AIOSv1PolicyRule("x", {"required_certifications_any_of": ["ISO"],
                                     "min_licenses_supplied": 100,
                                     "min_projects_served": 1}, {})
    out = lenient.eval({}, bid("x", {"certifications": ["ISO 27001"],
                                     "projects_served": 2, "licenses_supplied": 3500}), {})
    assert out["accepted"] is True, out


def test_never_sets_bid_rejected():
    """Marking a rejected bid is OpenArcade's job, not this function's."""
    out = rule().eval({}, bid("x", {"certifications": [], "projects_served": 2,
                                    "licenses_supplied": 3500}), {})
    assert "bid_rejected" not in out



def test_a_broken_his_config_does_not_change_the_verdict():
    """Observability must never cost a round.

    A HIS_CONFIG that arrives misshapen -- a string where a dict was meant, say -- is
    read before any of the reporting code's own error handling. If that raised, this
    function would reject every bid it saw, which is how an observability change turns
    into a round where nobody qualifies.
    """
    broken = AIOSv1PolicyRule("va-bidding-pqt:1.1-stable",
                              dict(SETTINGS, HIS_CONFIG="http://his:8080"), {})
    out = broken.eval({}, bid("camfacesolution-bid-manager", {
        "certifications": ["NIST FRVT"], "projects_served": 14,
        "licenses_supplied": 42000}), {})
    assert out["accepted"] is True, out


def test_every_verdict_carries_its_checks():
    """The bid only records the failures as prose; the dashboard needs both sides."""
    out = rule().eval({}, bid("newgentech-bid-manager", {
        "certifications": ["ISO 9001"], "projects_served": 2,
        "licenses_supplied": 3500}), {})
    names = [c["check"] for c in out["checks"]]
    assert names == ["certification", "licenses_supplied", "projects_served"], out
    assert all(c["passed"] is False for c in out["checks"]), out
    passed = rule().eval({}, bid("camfacesolution-bid-manager", {
        "certifications": ["NIST FRVT"], "projects_served": 14,
        "licenses_supplied": 42000}), {})
    assert all(c["passed"] is True for c in passed["checks"]), passed


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("\nrejection reason:", json.dumps(rule().eval({}, bid("newgentech-bid-manager", {
        "certifications": [], "projects_served": 2, "licenses_supplied": 3500}), {}), indent=2))
