"""/reed/jobs/* — job search with every filter the site has (and a reed.co.uk
search / employer listing link accepted as the query), one job in full,
jobs in batch, the site's similar jobs and the search facets alone.

Every search page of the jobs app embeds its results as JSON
(pageProps.searchResults), so a search is ONE page load: `take` sets the
page size (1..100), `pageno` the page. A keyword search carries the place
in the path (/jobs/{keywords}-jobs-in-{place}) and as `locationName=`, the
way the site's own filter links do: the bare /jobs?keywords=&location= form
redirects to the slug page and loses `take`, `perhour` and the place on the
way, and `location=` alone on a slug page is ignored. An employer listing
(/jobs/{name}/p{id}) takes the place ONLY as `locationName=` — a trailing
place segment (the directory's own link form) drops the employer scope.
Keywords go in the slug AND as `keywords=` (the slug drops punctuation). The site serves the first 10,000
results of a search (page x per_page must stay within that); a page past the
end answers a PAGE_NOT_FOUND shell.
"""
import re

from reed import parsers as P
from reed import refs
from reed.fetch import ReedNotFound, ReedUpstreamError, gather, get_html, get_page, page_props

POSTED_WITHIN = {"today": "today", "last_3_days": "lastthreedays", "last_week": "lastweek", "last_2_weeks": "lasttwoweeks"}
REMOTE_WORKING = {"remote": "remote", "hybrid": "hybrid", "on_site": "onsite"}
MAX_RESULTS = 10000

FILTER_KEYS = ("location", "distance_miles", "min_salary", "max_salary", "salary_period", "contract_type",
               "full_time", "part_time", "remote_working", "sector_ids", "posted_within", "posted_by",
               "graduate", "easy_apply", "early_bird", "visa_sponsorship", "salary_shown_only",
               "exclude_training", "exclude_survey_jobs")


def _merge_link(link, kwargs):
    """A parsed search link's own filters fill the gaps of the explicit
    params (explicit values win)."""
    if not link:
        return kwargs
    out = dict(kwargs)
    simple = {"location": "location", "distance_miles": "distance_miles", "min_salary": "min_salary",
              "max_salary": "max_salary", "sector_ids": "sector_ids", "posted_within": "posted_within",
              "remote_working": "remote_working", "page": "page", "per_page": "per_page"}
    for src, dst in simple.items():
        if out.get(dst) is None and link.get(src) is not None:
            out[dst] = link[src]
    if link.get("per_hour") and out.get("salary_period") is None:
        out["salary_period"] = "hourly"
    if not out.get("contract_type"):
        types = [t for t in ("permanent", "contract", "temporary") if link.get(t)]
        if types:
            out["contract_type"] = types
    if not out.get("posted_by"):
        who = [{"agency": "recruitment_agency", "direct": "direct_employer", "posted_by_reed": "reed"}[k]
               for k in ("agency", "direct", "posted_by_reed") if link.get(k)]
        if who:
            out["posted_by"] = who
    for key in ("full_time", "part_time", "graduate", "early_bird", "easy_apply", "visa_sponsorship",
                "salary_shown_only", "exclude_training", "exclude_survey_jobs"):
        if out.get(key) is None and link.get(key):
            out[key] = True
    return out


def upstream_params(kw):
    """Our search kwargs -> the site's query string."""
    contract = set(kw.get("contract_type") or [])
    posted_by = set(kw.get("posted_by") or [])
    return {
        "keywords": kw.get("keywords"),
        "locationName": kw.get("location"),
        "proximity": kw.get("distance_miles"),
        "salaryfrom": kw.get("min_salary"),
        "salaryto": kw.get("max_salary"),
        "perhour": kw.get("salary_period") == "hourly",
        "perm": "permanent" in contract,
        "contract": "contract" in contract,
        "temp": "temporary" in contract,
        "fulltime": kw.get("full_time") is True,
        "parttime": kw.get("part_time") is True,
        "workingOption": REMOTE_WORKING.get(kw.get("remote_working")),
        "sectorIds": kw.get("sector_ids"),
        "datecreatedoffset": POSTED_WITHIN.get(kw.get("posted_within")),
        "agency": "recruitment_agency" in posted_by,
        "direct": "direct_employer" in posted_by,
        "isReed": "reed" in posted_by,
        "graduate": kw.get("graduate") is True,
        "isEasyApply": kw.get("easy_apply") is True,
        "isEarlyBird": kw.get("early_bird") is True,
        "visaSponsorship": kw.get("visa_sponsorship") is True,
        "hideJobsWithoutSalary": kw.get("salary_shown_only") is True,
        "hideTrainingJobs": kw.get("exclude_training") is True,
        "hideSurveyJobs": kw.get("exclude_survey_jobs") is True,
        "pageno": kw.get("page"),
        "take": kw.get("per_page"),
    }


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def search_path(keywords=None, location=None, employer_id=None, employer_slug=None):
    """The listing page that carries a search: /jobs, /jobs/{kw}-jobs,
    /jobs/jobs-in-{place}, /jobs/{kw}-jobs-in-{place}, or an employer's
    /jobs/{name}/p{id} (its place rides in `locationName=` only)."""
    place = _slug(location)
    if employer_id:
        return f"/jobs/{employer_slug or 'employer'}/p{employer_id}"
    words = _slug(keywords)
    if words and place:
        return f"/jobs/{words}-jobs-in-{place}"
    if words:
        return f"/jobs/{words}-jobs"
    if place:
        return f"/jobs/jobs-in-{place}"
    return "/jobs"


def applied_criteria(criteria, kw):
    """The site's normalised criteria -> what was actually applied."""
    c = criteria if isinstance(criteria, dict) else {}
    loc = c.get("location") if isinstance(c.get("location"), dict) else {}
    types = [t for t, key in (("permanent", "perm"), ("contract", "contract"), ("temporary", "temp")) if c.get(key)]
    posted_by = [t for t, key in (("recruitment_agency", "agency"), ("direct_employer", "direct"), ("reed", "isReed")) if c.get(key)]
    offset = (c.get("dateCreatedOffSet") or "").lower()
    return {
        "keywords": P.text(c.get("keywords")) or kw.get("keywords"),
        "location": P.text(loc.get("locationName")) or kw.get("location"),
        "distance_miles": P.to_int(c.get("proximity")),
        "min_salary": P.number(c.get("salaryFrom")) or None,
        "max_salary": P.number(c.get("salaryTo")) or None,
        "salary_period": "hourly" if c.get("perHour") else "annual",
        "contract_type": types or None,
        "full_time": True if c.get("fullTime") else None,
        "part_time": True if c.get("partTime") else None,
        "remote_working": P.working_option(c.get("workingOption")),
        "sector_ids": [P.to_int(s) for s in (c.get("parentSectorIds") or []) if P.to_int(s)] or None,
        "posted_within": {v: k for k, v in POSTED_WITHIN.items()}.get(offset) if offset and offset != "anytime" else None,
        "posted_by": posted_by or None,
        "graduate": True if c.get("graduate") else None,
        "easy_apply": True if c.get("isEasyApply") else None,
        "early_bird": True if c.get("isEarlyBird") else None,
        "visa_sponsorship": True if c.get("visaSponsorship") else None,
        "salary_shown_only": True if c.get("hideJobsWithoutSalary") else None,
        "exclude_training": True if c.get("hideTrainingJobs") else None,
        "exclude_survey_jobs": True if c.get("hideSurveyJobs") else None,
        "employer_profile_id": P.to_int(c.get("clientProfileId")) or None,
        "employer_name": P.text(c.get("recruiterName")),
    }


def load_search(path, kw, label="job search"):
    """One search page -> (pageProps, display salaries from the cards)."""
    status, html, _ = get_page(path, upstream_params(kw), label=label)
    props = page_props(html, label)
    if status != 200 or props.get("notFoundReason"):
        reason = props.get("notFoundReason") or f"HTTP {status}"
        if reason == "PAGE_NOT_FOUND":
            raise ReedNotFound(f"page {kw.get('page') or 1} is past the last page of this search")
        raise ReedNotFound(f"{label}: {reason}")
    if not isinstance(props.get("searchResults"), dict):
        raise ReedUpstreamError(f"{label} page carried no results block (layout changed?)")
    return props, P.card_salaries(html)


def search_block(props, salaries, kw):
    """pageProps -> the shared body of /reed/jobs/search and /reed/employers/jobs."""
    results = props["searchResults"]
    sector_names = P.sector_names_from_filters(props.get("filters"))
    page = kw.get("page") or 1
    per_page = kw.get("per_page") or 25
    total = P.to_int(results.get("count")) or 0
    pagination = P.pagination(page, per_page, total)
    # only the first MAX_RESULTS are reachable (and the schema rejects
    # page x per_page beyond it), so the last page / next link stop there
    pagination["total_pages"] = min(pagination["total_pages"], MAX_RESULTS // per_page)
    return {
        "applied": applied_criteria(props.get("criteria"), kw),
        "location_resolved": P.text(results.get("preferredLocationName")),
        "location_substitutes": P.location_substitutes(results.get("locationSubstitutes")),
        "pagination": pagination,
        "retrievable_count": min(total, MAX_RESULTS),
        "facets": P.search_facets(results.get("searchFacets"), sector_names),
        "similar_searches": P.similar_searches(results.get("similarSearchResponses")),
        "promoted_jobs": P.job_rows(results.get("promotedJobs"), salaries),
        "jobs": P.job_rows(results.get("jobs"), salaries),
    }


def _resolve_query(query, kw):
    """`query` is search text or a reed.co.uk search / employer listing link."""
    kw = dict(kw)
    kw["keywords"] = query
    employer_id = employer_slug = None
    if query and refs.is_link(query):
        try:
            link = refs.parse_search_link(query)
        except ValueError as e:
            raise ValueError(str(e))
        kw["keywords"] = link.get("keywords")
        kw = _merge_link(link, kw)
        employer_id, employer_slug = link.get("employer_id"), link.get("employer_slug")
    return search_path(kw.get("keywords"), kw.get("location"), employer_id, employer_slug), kw


def search(query=None, **kw):
    path, kw = _resolve_query(query, kw)
    props, salaries = load_search(path, kw)
    out = {"query": kw.get("keywords"), "location": kw.get("location")}
    out.update(search_block(props, salaries, kw))
    return out


def facets(query=None, **kw):
    """The counts behind every search filter for a search, in one cheap call
    (the site answers them on a one-row page)."""
    kw = dict(kw, page=1, per_page=1)
    path, kw = _resolve_query(query, kw)
    props, _ = load_search(path, kw, label="job facets")
    results = props["searchResults"]
    sector_names = P.sector_names_from_filters(props.get("filters"))
    return {
        "query": kw.get("keywords"),
        "location": kw.get("location"),
        "applied": applied_criteria(props.get("criteria"), kw),
        "location_resolved": P.text(results.get("preferredLocationName")),
        "total_count": P.to_int(results.get("count")) or 0,
        "facets": P.search_facets(results.get("searchFacets"), sector_names),
        "similar_searches": P.similar_searches(results.get("similarSearchResponses")),
    }


# ---- one job ------------------------------------------------------------------------

def _job_page(job_id):
    status, html, final_url = get_page(f"/jobs/job/{job_id}", label=f"job {job_id}")
    props = page_props(html, f"job {job_id}")
    if status != 200 or props.get("notFoundReason") or not isinstance(props.get("consolidatedJobDetails"), dict):
        reason = (props.get("notFoundReason") or "").upper()
        if reason == "JOB_EXPIRED":
            raise ReedNotFound(f"job {job_id} has expired or does not exist")
        raise ReedNotFound(f"job {job_id} not found" + (f" ({reason})" if reason else ""))
    return props


def _job_body(props):
    block = props["consolidatedJobDetails"]
    canonical = P.text(props.get("canonicalUrl"))
    job = P.job_details(block.get("jobDetails"), canonical_link=canonical)
    if not job:
        raise ReedUpstreamError("job page carried no job record")
    return block, job


def details(job):
    props = _job_page(job)
    block, record = _job_body(props)
    similar = [j for j in (P.job_details(row, truncated=True) for row in block.get("similarJobs") or []) if j]
    return {
        "job": record,
        "similar_jobs": similar,
        "similar_searches": P.similar_searches(block.get("similarSearches")),
        "recommended_courses": P.recommended_courses(block.get("recommendedCourses")),
    }


def similar(job):
    """The jobs the site recommends beside one advert (the page shows up to 6)."""
    props = _job_page(job)
    block, record = _job_body(props)
    rows = [j for j in (P.job_details(row, truncated=True) for row in block.get("similarJobs") or []) if j]
    return {"job_id": record["id"], "title": record["title"], "count": len(rows), "jobs": rows}


def batch(jobs):
    """Up to 25 jobs by id / link in one call, in the order sent."""
    def one(job_id):
        def run():
            try:
                return _job_body(_job_page(job_id))[1]
            except ReedNotFound:
                return None
        return run

    results = gather({job_id: one(job_id) for job_id in jobs})
    found = [results[j] for j in jobs if results.get(j)]
    return {
        "requested_count": len(jobs),
        "found_count": len(found),
        "not_found": [int(j) for j in jobs if not results.get(j)],
        "jobs": found,
    }
