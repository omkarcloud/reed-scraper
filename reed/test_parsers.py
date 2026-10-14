"""Offline tests: ref parsing, the request schemas and the normalizers
against raw reed.co.uk pages captured 2026-10-14 (reed/fixtures/; the HTML
pages are stripped of scripts, styles and SVG except the __NEXT_DATA__ /
Vue init payloads the parsers read).

    python -m pytest reed/test_parsers.py -q
"""
import json
import os

import pytest
from marshmallow import ValidationError

from reed import fetch, refs, schemas
from reed import parsers as P
from reed.jobs import applied_criteria, upstream_params

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def fx(name):
    with open(os.path.join(FIX, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def page(name):
    with open(os.path.join(FIX, name + ".html"), encoding="utf-8") as f:
        return f.read()


def _no_camel_or_url_keys(obj, path="$"):
    """Every emitted key is snake_case and no key is named *url*."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key == key.lower() and " " not in key, f"{path}.{key} not snake_case"
            assert "url" not in key, f"{path}.{key} should be a *link"
            _no_camel_or_url_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _no_camel_or_url_keys(value, f"{path}[{i}]")


# ---- refs -----------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("57452596", "57452596"),
    ("https://www.reed.co.uk/jobs/software-engineer-london/57452596", "57452596"),
    ("https://www.reed.co.uk/jobs/x/57452596?source=searchResults&sid=abc", "57452596"),
    ("reed.co.uk/jobs/software-engineer/57452596/apply", "57452596"),
])
def test_resolve_job(value, expected):
    assert refs.resolve_job(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "https://www.indeed.com/jobs/1", "https://www.reed.co.uk/jobs/python-jobs"])
def test_resolve_job_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_job(value)


def test_resolve_employer():
    assert refs.resolve_employer("36210") == {"id": "36210", "link": None}
    assert refs.resolve_employer("p36210")["id"] == "36210"
    linked = refs.resolve_employer("https://www.reed.co.uk/jobs/hays-specialist-recruitment-limited/p36210?keywords=python")
    assert linked["id"] == "36210" and linked["link"]["keywords"] == "python" and linked["link"]["employer_slug"] == "hays-specialist-recruitment-limited"
    with pytest.raises(ValueError):
        refs.resolve_employer("https://www.reed.co.uk/company-profile/FDM-Group-746")


def test_resolve_company():
    assert refs.resolve_company("746") == "746"
    assert refs.resolve_company("FDM-Group-746") == "746"
    assert refs.resolve_company("https://www.reed.co.uk/company-profile/FDM-Group-746") == "746"
    with pytest.raises(ValueError):
        refs.resolve_company("https://www.reed.co.uk/jobs/fdm-group/p4784")


def test_resolve_course_and_provider():
    assert refs.resolve_course("230612") == "230612"
    assert refs.resolve_course("https://www.reed.co.uk/courses/python-complete-course/230612#/courses/python") == "230612"
    assert refs.resolve_provider("1778") == {"id": "1778", "slug": None}
    assert refs.resolve_provider("https://www.reed.co.uk/courses/janets/p1778") == {"id": "1778", "slug": None}
    assert refs.resolve_provider("https://www.reed.co.uk/courses/provider-profiles/janets") == {"id": None, "slug": "janets"}
    with pytest.raises(ValueError):
        refs.resolve_provider("janets")


def test_parse_search_link():
    link = refs.parse_search_link("https://www.reed.co.uk/jobs/contract-python-developer-jobs-in-london?keywords=python+developer"
                                  "&locationName=london&proximity=20&salaryFrom=40000&salaryTo=90000&contract=true&fullTime=true"
                                  "&dateCreatedOffSet=lastweek&sectorIds=52&workingOption=remote&pageno=2&take=50")
    assert link["keywords"] == "python developer" and link["location"] == "london"
    assert link["distance_miles"] == 20 and link["min_salary"] == 40000 and link["max_salary"] == 90000
    assert link["contract"] is True and link["full_time"] is True and link["posted_within"] == "last_week"
    assert link["sector_ids"] == ["52"] and link["remote_working"] == "remote" and link["page"] == 2 and link["per_page"] == 50
    bare = refs.parse_search_link("https://www.reed.co.uk/jobs/nurse-jobs-in-leeds")
    assert bare["keywords"] == "nurse" and bare["location"] == "leeds"
    employer = refs.parse_search_link("https://www.reed.co.uk/jobs/academics/p14099/leeds?proximity=30")
    assert employer["employer_id"] == "14099" and employer["employer_slug"] == "academics" and employer["location"] == "leeds"
    with pytest.raises(ValueError):
        refs.parse_search_link("https://www.reed.co.uk/courses/python")


def test_parse_course_link():
    link = refs.parse_course_link("https://www.reed.co.uk/courses/python/online?pageno=2&pagesize=50&sortby=PriceAsc")
    assert link["subject"] == "python" and link["study_method"] == ["online"] and link["page"] == 2
    assert link["per_page"] == 50 and link["sort"] == "price_low_to_high"
    link = refs.parse_course_link("https://www.reed.co.uk/courses/all?keywords=first+aid&location=Manchester&classroom=true&level3=true&pricefrom=10&priceto=50")
    assert link["keywords"] == "first aid" and link["location"] == "Manchester" and link["study_method"] == ["classroom"]
    assert link["qualification_level"] == ["3"] and link["min_price"] == 10 and link["max_price"] == 50
    assert refs.parse_course_link("https://www.reed.co.uk/courses/janets/p1778")["provider_id"] == "1778"


# ---- schemas ----------------------------------------------------------------------------

def test_job_search_schema():
    data = schemas.JobSearchSchema().load({"query": "nurse", "location": "Leeds", "contract_type": "permanent, Temporary",
                                           "posted_within": "LAST_WEEK", "remote_working": "hybrid", "sector_ids": "36,68",
                                           "min_salary": "30000", "per_page": "100", "easy_apply": "yes"})
    assert data["contract_type"] == ["permanent", "temporary"] and data["posted_within"] == "last_week"
    assert data["sector_ids"] == ["36", "68"] and data["easy_apply"] is True and data["per_page"] == 100
    params = upstream_params(dict(data, keywords=data["query"]))
    assert params["perm"] and params["temp"] and not params["contract"] and params["datecreatedoffset"] == "lastweek"
    assert params["workingOption"] == "hybrid" and params["sectorIds"] == ["36", "68"] and params["isEasyApply"]
    with pytest.raises(ValidationError):
        schemas.JobSearchSchema().load({"query": "x", "page": "101", "per_page": "100"})
    with pytest.raises(ValidationError):
        schemas.JobSearchSchema().load({"query": "x", "distance_miles": "10"})
    with pytest.raises(ValidationError):
        schemas.JobSearchSchema().load({"query": "x", "salary_period": "hourly"})
    with pytest.raises(ValidationError):
        schemas.JobSearchSchema().load({"query": "x", "bogus": "1"})


def test_other_schemas():
    assert schemas.JobsSchema().load({"jobs": "57452596, https://www.reed.co.uk/jobs/x/57377207,57452596"})["jobs"] == ["57452596", "57377207"]
    assert schemas.EmployerSearchSchema().load({"sector": "IT & Telecoms", "employer_type": "Recruitment_Agency"})["sector"] == "it-telecoms"
    assert schemas.EmployerSearchSchema().load({"sector": "it-telecoms"})["sector"] == "it-telecoms"
    with pytest.raises(ValidationError):
        schemas.EmployerSearchSchema().load({"sector": "plumbing"})
    course = schemas.CourseSearchSchema().load({"query": "python", "study_method": "online,on_demand", "qualification_level": "3,4", "max_price": "0"})
    assert course["study_method"] == ["online", "on_demand"] and course["qualification_level"] == ["3", "4"] and course["max_price"] == 0
    with pytest.raises(ValidationError):
        schemas.CourseSearchSchema().load({"provider": "https://www.reed.co.uk/courses/provider-profiles/janets"})
    with pytest.raises(ValidationError):
        schemas.ReviewsSchema().load({"course": "230612"})
    loaded = schemas.ReviewsSchema().load({"provider": "1778", "course": "230612"})
    assert loaded["sort"] == "newest" and loaded["provider"] == {"id": "1778", "slug": None} and loaded["course"] == "230612"


# ---- jobs --------------------------------------------------------------------------------

def test_search_rows_and_facets():
    props = fx("search_pageprops")
    rows = P.job_rows(props["searchResults"]["jobs"])
    assert len(rows) == 5
    _no_camel_or_url_keys(rows)
    first = rows[0]
    assert first["id"] == 57452766 and first["link"].endswith("/57452766") and "sid=" not in first["link"]
    assert first["contract_type"] == "permanent" and first["remote_working"] == "on_site"
    assert first["salary"] == {"display": "£45,000 per annum", "min": 45000, "max": 45000, "currency": "GBP",
                               "period": "annual", "is_hidden": False, "hidden_as": None}
    assert first["employer"]["type"] == "direct_employer" and first["employer"]["profile_id"] == 44325
    assert first["employer"]["logo"].endswith("/thumbs/Logo_44325.png")
    assert first["posted_at"] == "2026-10-13T08:54:05Z"       # BST wall clock -> UTC
    assert first["flags"]["is_early_bird"] is True and first["flags"]["requires_uk_eligibility"] is True
    names = P.sector_names_from_filters(props["filters"])
    facets = P.search_facets(props["searchResults"]["searchFacets"], names)
    assert facets["contract_type"] == {"permanent": 11, "contract": 2, "temporary": 3}
    assert facets["sectors"][0] == {"id": 68, "name": "Education", "jobs_count": 6}
    assert facets["remote_working"]["on_site"] == 11 and facets["locations"][0] == {"name": "Leeds", "jobs_count": 4}
    applied = applied_criteria(props["criteria"], {})
    assert applied["keywords"] == "nurse" and applied["location"] == "leeds" and applied["distance_miles"] == 20
    assert applied["contract_type"] == ["permanent"] and applied["posted_within"] == "last_week"
    assert P.similar_searches(props["searchResults"]["similarSearchResponses"])[0]["link"] == "https://www.reed.co.uk/jobs/care-assistant-jobs-in-leeds"


def test_card_salaries_merge():
    salaries = P.card_salaries(page("search_page"))
    assert len(salaries) == 25 and salaries["57377207"] == "£550 - £617.55 per day"
    row = {"jobDetail": {"jobId": 57377207, "jobTitle": "Python Developer", "jobType": 2, "salaryFrom": 550, "salaryTo": 617.55,
                         "salaryType": 2, "salaryDescription": 0, "ouType": 1, "profileId": 36210},
           "url": "/jobs/python-developer/57377207"}
    parsed = P.job_rows([row], salaries)[0]
    assert parsed["salary"]["display"] == "£550 - £617.55 per day" and parsed["salary"]["period"] == "daily"
    assert parsed["salary"]["max"] == 617.55 and parsed["contract_type"] == "contract"


def test_hidden_salary_codes():
    negotiable = P.job_row({"jobId": 1, "jobTitle": "x", "salaryFrom": 40, "salaryTo": 41, "salaryType": 1, "salaryDescription": 16})
    assert negotiable["salary"]["is_hidden"] is True and negotiable["salary"]["hidden_as"] == "negotiable" and negotiable["salary"]["min"] is None
    competitive = P.job_row({"jobId": 2, "jobTitle": "x", "salaryFrom": 20000, "salaryTo": 100000, "salaryType": 5, "salaryDescription": 64})
    assert competitive["salary"]["hidden_as"] == "competitive"
    unspecified = P.job_row({"jobId": 3, "jobTitle": "x", "salaryFrom": 0, "salaryTo": 0, "salaryType": 5, "salaryDescription": 0})
    assert unspecified["salary"]["is_hidden"] is True and unspecified["salary"]["display"] is None
    assert P.job_row({"jobTitle": "no id"}) is None and P.job_row(None) is None


def test_job_details():
    block = fx("job_details_raw")
    job = P.job_details(block["jobDetails"], canonical_link="https://www.reed.co.uk/jobs/software-engineer-london/57452596")
    _no_camel_or_url_keys(job)
    assert job["id"] == 57452596 and job["contract_type"] == "contract" and job["remote_working"] == "hybrid"
    assert job["salary"]["display"] == "Salary negotiable" and job["salary"]["is_hidden"] is True and job["salary"]["hidden_as"] == "negotiable"
    assert job["salary"]["min_annual"] == 45000 and job["salary"]["period"] == "annual"
    assert job["location"]["region"] == "South East England" and job["location"]["country_code"] == "GB"
    assert job["employer"] == {"id": 377422, "name": "FDM Group", "profile_id": 4784, "profile_name": "FDM Group",
                               "company_profile_id": 746, "type": "direct_employer",
                               "link": "https://www.reed.co.uk/jobs/fdm-group/p4784",
                               "company_profile_link": "https://www.reed.co.uk/company-profile/FDM-Group-746",
                               "logo": "https://resources.reed.co.uk/profileimages/logos/Logo_4784.png",
                               "banner": "https://resources.reed.co.uk/profileimages/logos/HeroBanner_4784.png",
                               "job_reference": "3165"}
    assert job["sector"] == {"id": 138, "name": "Software Engineer", "parent_id": 52, "parent_name": "IT & Telecoms"}
    assert job["breadcrumbs"] == ["Information Technology", "Engineer", "Software Engineer"]
    assert job["application"]["is_external"] is True and job["application"]["cover_letter"] == "none"
    assert job["branding"]["banner"].endswith("/brandedjob/banners/resized/Banner_377422.png")
    assert job["description_text"].startswith("About The Role\nFDM is a global")
    assert job["posted_at"] == "2026-10-13T08:23:08Z" and job["expires_at"] == "2026-11-10T23:59:59Z"
    similar = [P.job_details(r, truncated=True) for r in block["similarJobs"]]
    assert len(similar) == 6 and all(s["is_description_truncated"] for s in similar)
    courses = P.recommended_courses(block["recommendedCourses"])
    assert courses[0]["price"] == {"amount": 15, "currency": "GBP", "display": "£15"} and courses[0]["link"].startswith("https://www.reed.co.uk/courses/")
    assert P.job_details({}) is None and P.job_details(None) is None


# ---- employers -------------------------------------------------------------------------------

def test_company_profile():
    cp = P.company_profile(fx("company_raw"))
    _no_camel_or_url_keys(cp)
    assert cp["id"] == 746 and cp["profile_id"] == 4784 and cp["jobs_link"] == "https://www.reed.co.uk/jobs/fdm-group/p4784"
    assert cp["employee_count_range"] == "2,500–4,999" and cp["sector"]["name"] == "IT & Telecoms"
    assert cp["location"]["latitude"] == 51.50735 and len(cp["benefits"]) == 7 and len(cp["social_links"]) == 4 and len(cp["images"]) == 4
    assert cp["about"][0]["title"] == "What we do" and cp["about"][0]["text"].startswith("FDM is an award-winning")
    assert cp["live_jobs_count"] == 30 and cp["recent_jobs"][0]["application_count"] == 22
    assert cp["recent_jobs"][0]["external_application_link"].startswith("https://careers.fdmgroup.com/")
    assert cp["recent_jobs"][0]["location"]["latitude"] == 53.8367255
    assert P.company_profile({}) is None


def test_directory():
    html = page("directory")
    cards = P.directory_cards(html)
    assert len(cards) == 20 and cards[0] == {"name": "Academics", "profile_id": 14099,
                                             "link": "https://www.reed.co.uk/jobs/academics/p14099",
                                             "logo": "https://resources.reed.co.uk/profileimages/logos/thumbs/Logo_14099.png",
                                             "live_jobs_count": 2695}
    assert P.directory_last_page(html) == 80 and P.directory_heading(html) == "Company recruiter directory"
    assert P.directory_cards("") == []


# ---- salary / reference -----------------------------------------------------------------------

def test_salary_page():
    record = P.salary_page(page("salary_page"), "python developer")
    _no_camel_or_url_keys(record)
    assert record["average"] == 85425 and record["low"] == 80305 and record["high"] == 98916
    assert record["jobs_count"] == 334 and record["new_jobs_last_day_count"] == 2 and record["jobs_above_average_count"] == 19
    assert record["jobs_link"] == "https://www.reed.co.uk/jobs/python-developer-jobs?parentsector=it-telecoms"
    assert {"location": "Leeds", "link": "https://www.reed.co.uk/average-salary/average-python-developer-salary-in-leeds"} in record["by_location"]
    assert P.salary_page("<html></html>", "x") is None


def test_suggestions_and_sectors():
    assert P.place_suggestions(fx("locations"))[:2] == ["Leeds", "Leek"]
    assert P.job_title_suggestions(fx("job_titles"))[0] == "Band Nurse"
    sectors = P.sectors_from_filters(fx("search_pageprops")["filters"])
    assert sectors[0]["id"] == 2 and sectors[0]["name"] == "Accountancy" and len(sectors) == 37


# ---- courses -----------------------------------------------------------------------------------

def test_course_cards():
    html = page("course_search")
    blob = fetch.init_blobs(html)["course-search.index"]
    cards = P.course_cards(html, blob["coursesToBeDisplayed"])
    _no_camel_or_url_keys(cards)
    assert len(cards) == 27 and sum(c["is_sponsored"] for c in cards) == 2
    organic = [c for c in cards if not c["is_sponsored"]]
    card = next(c for c in organic if c["id"] == 284930)
    assert card["title"] == "Python Data Science with Numpy, Pandas and Matplotlib" and card["provider"]["name"] == "One Education"
    assert card["link"] == "https://www.reed.co.uk/courses/python-data-science-with-numpy-pandas-and-matplotlib/284930"
    assert card["price"]["amount"] == 19 and card["study_method"] == "online" and card["is_on_demand"] is True
    assert card["students_count"] == 147 and card["cpd_points"] == 10 and card["has_tutor_support"] is True
    assert card["duration"] == "6.2 hours · Self-paced" and "great_service" in card["badges"]
    discounted = next(c for c in cards if c["price"]["was_amount"])
    assert discounted["price"]["discount_percent"] and discounted["price"]["amount"] < discounted["price"]["was_amount"]
    assert P.course_search_total(html) == 244 and P.course_search_last_page(html) == 10
    assert P.course_search_heading(html) == "Online Python courses"


def test_course_details():
    html = page("course_page")
    blob = fetch.init_blobs(html)["course-view.view"]
    course = P.course_details(html, blob, "230612")
    _no_camel_or_url_keys(course)
    assert course["id"] == 230612 and course["title"].startswith("Python Complete Course")
    assert course["price"] == {"amount": 19, "was_amount": 21, "currency": "GBP", "discount_percent": 9, "is_free": False,
                               "includes_vat": True, "offer_ends": "31 October 2026", "is_ex_vat": False}
    assert course["study_method"] == "Online, On Demand" and course["is_on_demand"] is True and course["can_buy_online"] is True
    assert course["duration"] == "16.6 hours · Self-paced" and course["cpd_points"] == 330 and course["cpd"] == "330 CPD hours / points"
    assert course["awarding_body"]["name"] == "The Quality Licence Scheme" and len(course["certificates"]) == 3
    assert course["rating"] == {"average": 4.0, "service_percent": 76, "content_percent": 80, "value_for_money_percent": 86}
    assert course["students_purchased_count"] == 444 and course["badges"] == ["great_service", "highly_rated"]
    assert course["provider"]["id"] == 1778 and course["provider"]["slug"] == "janets"
    assert course["breadcrumbs"] == ["Online", "IT", "IT support"]
    assert course["curriculum"]["format"].startswith("107 Videos") and len(course["curriculum"]["modules"]) == 16
    assert course["curriculum"]["modules"][0]["lectures"][0] == {"title": "001 Why Learn Coding", "duration": "04:32"}
    assert course["questions_and_answers"][0]["asked_by"] == "Noel" and course["questions_and_answers"][0]["helpful_count"] == 3
    assert course["sections"]["requirements"]["text"].startswith("The course is open to all")
    assert course["sections"]["who_is_this_for"]["text"].startswith("This course is designed for")


def test_reviews_and_providers():
    rows, pagination = P.reviews_page(fx("reviews"), 1, 100)
    _no_camel_or_url_keys(rows)
    assert pagination == {"page": 1, "items_per_page": 100, "total_pages": 1, "total_count": 6}
    assert rows[0]["rating"] == {"overall": 3.67, "service": 3.0, "content": 4.0, "value_for_money": 4.0}
    assert rows[0]["reviewer_name"] == "Tony W" and rows[0]["created_at"] == "2025-12-05T10:50:18Z"
    assert P.reviews_page({}, 2, 10) == ([], {"page": 2, "items_per_page": 10, "total_pages": 0, "total_count": 0})
    provider = P.provider_result(fx("providers_search")["results"][0])
    assert provider["id"] == 1054 and provider["slug"] == "21st-century-new-media-limited" and provider["courses_count"] == 1
    assert provider["rating"] is None and provider["has_online_courses"] is True
    html = page("provider_profile")
    blob = fetch.init_blobs(html)["provider-profile.details"]
    profile = P.provider_profile(html, blob, 1778, "janets")
    _no_camel_or_url_keys(profile)
    assert profile["name"] == "Janets" and profile["rating"] == 4.2 and profile["reviews_count"] == 543
    assert profile["courses_link"] == "https://www.reed.co.uk/courses/janets/p1778" and len(profile["popular_courses"]) == 25
    assert profile["popular_courses"][0]["badges"] == ["trending", "great_service", "popular", "highly_rated"]
    assert profile["about_text"].startswith("Janets, is a popular")


# ---- helpers -----------------------------------------------------------------------------------

def test_value_helpers():
    assert P.iso_datetime("2026-07-14T09:00:00") == "2026-07-14T08:00:00Z"   # BST
    assert P.iso_datetime("2026-01-14T09:00:00") == "2026-01-14T09:00:00Z"   # GMT
    assert P.iso_datetime("2026-01-14T09:00:00Z") == "2026-01-14T09:00:00Z" and P.iso_datetime("junk") is None
    assert P.first_number("£85,425") == 85425 and P.first_number("£617.55 per day") == 617.55 and P.first_number("none") is None
    assert P.strip_html("<p>One</p><ul><li>a</li><li>b</li></ul>") == "One\n- a\n- b"
    assert P.working_option("NotSpecified") is None and P.working_option("onSite") == "on_site"
    assert P.pagination(2, 25, 60) == {"page": 2, "items_per_page": 25, "total_pages": 3, "total_count": 60}
    assert fetch.next_data("<html></html>") is None and fetch.init_blobs("") == {}
