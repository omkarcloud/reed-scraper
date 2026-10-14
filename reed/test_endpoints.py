"""Live endpoint smoke tests: one call per /reed/* route against a running
service, with example values proven to return data (2026-10-14). The
listing tooling reads each route's FIRST call from this file's AST as its
working example, so the values stay literals.

Skipped unless REED_BASE points at a running service:

    ONLY_SCRAPER=reed python run.py
    REED_BASE=http://127.0.0.1:6002 python -m pytest reed/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("REED_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set REED_BASE to run live endpoint tests")


def call(path, status=200, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=180)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def _live_job():
    """Adverts expire within weeks, so job routes use a fresh one."""
    return call("/reed/jobs/search", query="software engineer", location="london", per_page=3)["jobs"][0]


def test_jobs_search():
    page = call("/reed/jobs/search", query="python developer", location="london", distance_miles=20,
                contract_type="permanent,contract", posted_within="last_2_weeks", per_page=10)
    assert len(page["jobs"]) == 10 and page["count"] > 50 and page["next"]
    first = page["jobs"][0]
    assert first["id"] and first["link"].startswith("https://www.reed.co.uk/jobs/") and first["employer"]["profile_id"]
    assert first["salary"]["currency"] == "GBP" and first["contract_type"] in ("permanent", "contract")
    assert page["applied"]["contract_type"] == ["permanent", "contract"] and page["applied"]["posted_within"] == "last_2_weeks"
    assert page["facets"]["sectors"] and page["location_resolved"] == "London"
    # hourly pay floor + remote only + 100 per page
    hourly = call("/reed/jobs/search", query="nurse", min_salary=20, salary_period="hourly", remote_working="remote", per_page=100)
    assert hourly["applied"]["salary_period"] == "hourly" and all(j["remote_working"] == "remote" for j in hourly["jobs"])
    # a reed.co.uk search link as the query carries its own filters
    linked = call("/reed/jobs/search", query="https://www.reed.co.uk/jobs/nurse-jobs-in-leeds?salaryfrom=30000&perm=true", per_page=3)
    assert linked["applied"]["keywords"] == "nurse" and linked["applied"]["location"] == "leeds" and linked["applied"]["min_salary"] == 30000
    # depth cap
    call("/reed/jobs/search", status=400, query="nurse", page=101, per_page=100)


def test_jobs_facets():
    body = call("/reed/jobs/facets", query="nurse", location="leeds")
    assert body["total_count"] > 10 and body["facets"]["contract_type"]["permanent"] is not None
    assert body["facets"]["sectors"][0]["name"] and body["facets"]["posted_within"]["last_2_weeks"] is not None


def test_jobs_details():
    job = _live_job()
    body = call("/reed/jobs/details", job=job["id"])
    record = body["job"]
    assert record["id"] == job["id"] and record["description_html"] and record["description_text"]
    assert record["employer"]["profile_id"] and record["sector"]["parent_name"] and record["posted_at"]
    assert body["similar_jobs"] and body["similar_jobs"][0]["is_description_truncated"] is True
    by_link = call("/reed/jobs/details", job=job["link"])
    assert by_link["job"]["id"] == job["id"]
    call("/reed/jobs/details", status=404, job=1)


def test_jobs_similar_and_batch():
    job = _live_job()
    similar = call("/reed/jobs/similar", job=job["id"])
    assert similar["job_id"] == job["id"] and similar["count"] >= 1
    batch = call("/reed/jobs/batch", jobs=f"{job['id']},1")
    assert batch["requested_count"] == 2 and batch["found_count"] == 1 and batch["not_found"] == [1]
    assert batch["jobs"][0]["id"] == job["id"]


def test_employers_search():
    body = call("/reed/employers/search", query="hays")
    assert body["employers"][0]["profile_id"] == 36210 and body["employers"][0]["live_jobs_count"] > 100
    agencies = call("/reed/employers/search", employer_type="recruitment_agency", sector="it-telecoms", location="Leeds", distance_miles=10)
    assert len(agencies["employers"]) == 20 and agencies["heading"] == "IT & Telecoms recruitment agency directory"
    assert agencies["sector"]["name"] == "IT & Telecoms" and agencies["next"]
    directory = call("/reed/employers/search", page=3)
    assert directory["current_page"] == 3 and directory["total_pages"] > 100 and directory["previous"]


def test_employers_jobs_and_profile():
    body = call("/reed/employers/jobs", employer=36210, query="python", per_page=5)
    assert body["employer"]["name"] == "Hays Specialist Recruitment Limited" and body["employer"]["live_jobs_count"] >= len(body["jobs"])
    assert all(j["employer"]["profile_id"] == 36210 for j in body["jobs"])
    linked = call("/reed/employers/jobs", employer="https://www.reed.co.uk/jobs/fdm-group/p4784", per_page=3)
    assert linked["employer"]["company_profile_id"] == 746 and linked["jobs"]
    profile = call("/reed/employers/profile", company="https://www.reed.co.uk/company-profile/FDM-Group-746")
    assert profile["id"] == 746 and profile["name"] == "FDM Group" and profile["profile_id"] == 4784
    assert profile["employee_count_range"] and profile["benefits"] and profile["recent_jobs"][0]["application_count"] is not None
    assert call("/reed/employers/profile", company=746)["id"] == 746
    call("/reed/employers/profile", status=404, company=999999999)


def test_salary_benchmark():
    body = call("/reed/salary/benchmark", job_title="python developer")
    assert body["average"] > 20000 and body["low"] <= body["average"] <= body["high"] and body["jobs_count"] > 0
    assert body["by_location"] and body["jobs_link"].startswith("https://www.reed.co.uk/jobs/")
    local = call("/reed/salary/benchmark", job_title="nurse", location="Manchester")
    assert local["average"] > 20000 and "Manchester" in local["heading"]
    call("/reed/salary/benchmark", status=404, job_title="zzqqxx")


def test_reference():
    assert call("/reed/locations/suggest", query="lee")["suggestions"][0] == "Leeds"
    assert "Nurse" in " ".join(call("/reed/job-titles/suggest", query="nur")["suggestions"])
    sectors = call("/reed/sectors")
    assert sectors["count"] >= 35 and sectors["sectors"][0] == {"id": 2, "name": "Accountancy", "jobs_count": sectors["sectors"][0]["jobs_count"]}
    assert sectors["total_jobs_count"] > 10000


def test_courses_search():
    body = call("/reed/courses/search", query="python", study_method="online", max_price=30, sort="price_low_to_high", per_page=5)
    assert len(body["courses"]) == 5 and body["count"] > 20 and body["next"]
    assert all(c["price"]["amount"] is not None and c["price"]["amount"] <= 30 for c in body["courses"])
    assert body["applied"]["study_method"] == ["online"] and body["applied"]["sort"] == "price_low_to_high"
    assert body["courses"][0]["provider"]["name"] and body["courses"][0]["link"].startswith("https://www.reed.co.uk/courses/")
    classroom = call("/reed/courses/search", subject="first aid", location="Manchester", study_method="classroom", per_page=3)
    assert classroom["heading"] == "First Aid training courses in Manchester" and classroom["courses"]
    linked = call("/reed/courses/search", query="https://www.reed.co.uk/courses/python/online?pageno=2", per_page=5)
    assert linked["current_page"] == 2 and linked["applied"]["subject"] == "python"


def test_courses_details():
    course = call("/reed/courses/details", course=230612)
    assert course["title"].startswith("Python Complete Course") and course["price"]["amount"] > 0
    assert course["provider"]["id"] == 1778 and course["curriculum"]["modules"] and course["rating"]["average"] > 0
    assert course["sections"]["overview"]["text"] and course["certificates"]
    assert call("/reed/courses/details", course="https://www.reed.co.uk/courses/python-complete-course/230612")["id"] == 230612
    call("/reed/courses/details", status=404, course=1)


def test_courses_reviews():
    body = call("/reed/courses/reviews", provider=1778, sort="highest_rating", per_page=5)
    assert len(body["reviews"]) == 5 and body["count"] > 100 and body["reviews"][0]["rating"]["overall"] == 5.0
    by_course = call("/reed/courses/reviews", provider=1778, course=230612, per_page=5)
    assert by_course["provider_id"] == 1778 and by_course["course_id"] == 230612 and by_course["reviews"]
    by_slug = call("/reed/courses/reviews", provider="https://www.reed.co.uk/courses/provider-profiles/janets", page=2, per_page=10)
    assert by_slug["current_page"] == 2 and by_slug["previous"]
    call("/reed/courses/reviews", status=400, course=230612)


def test_courses_providers():
    body = call("/reed/courses/providers", query="janets")
    assert body["providers"][0]["id"] == 1778 and body["providers"][0]["courses_count"] > 100
    page2 = call("/reed/courses/providers", page=2, per_page=5)
    assert page2["current_page"] == 2 and len(page2["providers"]) == 5 and page2["count"] > 100
    profile = call("/reed/courses/providers/details", provider="https://www.reed.co.uk/courses/provider-profiles/janets")
    assert profile["id"] == 1778 and profile["rating"] > 3 and profile["reviews_count"] > 100 and profile["popular_courses"]
    assert profile["courses_count"] > 100 and profile["about_text"]
    assert call("/reed/courses/providers/details", provider=1778)["slug"] == "janets"
