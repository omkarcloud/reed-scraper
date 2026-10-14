"""/reed/courses/* — the Reed Courses catalogue: search with every filter the
site has (and a reed.co.uk course listing link accepted as the query), one
course in full, learner reviews, the course provider directory and a
provider's profile.

Search pages are server-rendered cards plus a Vue init blob whose GA item
list carries each course's rating, badges and qualification type; the
course page's blob carries the Q&A, the provider id and the classroom
count. Reviews and the provider directory are plain JSON routes.
"""
import re

from reed import parsers as P
from reed import refs
from reed.fetch import ReedNotFound, ReedUpstreamError, get_html, get_json, get_page, init_blobs

SORTS = {"relevance": None, "most_popular": "MostPopular", "price_low_to_high": "PriceAsc",
         "price_high_to_low": "PriceDesc", "newest": "RecentlyAdded"}
REVIEW_SORTS = {"newest": "MostRecent", "highest_rating": "RatingDesc", "lowest_rating": "RatingAsc"}
STUDY_METHODS = {"online": "online", "classroom": "classroom", "in_company": "onsite", "on_demand": "ondemand"}
QUALIFICATIONS = {"cpd": "cpd", "professional": "professional", "regulated": "regulated", "higher_education": "highereducation"}
LEVELS = ("beginner", "intermediate", "advanced")
PROVIDER_PAGE_SIZE_MAX = 96


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def _merge_link(link, kw):
    out = dict(kw)
    for key in ("subject", "location", "min_price", "max_price", "duration", "awarding_body", "sort", "page", "per_page"):
        if out.get(key) is None and link.get(key) is not None:
            out[key] = link[key]
    if out.get("provider") is None and link.get("provider_id"):
        out["provider"] = {"id": link["provider_id"], "slug": None}
    for key in ("study_method", "level", "qualification", "qualification_level"):
        if not out.get(key) and link.get(key):
            out[key] = list(link[key])
    for key in ("tutor_support", "finance_available", "funding_available", "job_guarantee", "on_offer", "trending", "buy_online"):
        if out.get(key) is None and link.get(key):
            out[key] = True
    return out


def _upstream(kw):
    params = {
        "keywords": kw.get("keywords"),
        "location": kw.get("location"),
        "distance": kw.get("distance_miles"),
        "pricefrom": kw.get("min_price"),
        "priceto": kw.get("max_price"),
        "duration": kw.get("duration"),
        "awardingBody": kw.get("awarding_body"),
        "providerIds": (kw.get("provider") or {}).get("id") if kw.get("provider") else None,
        "sortby": SORTS.get(kw.get("sort") or "relevance"),
        "pageno": kw.get("page"),
        "pagesize": kw.get("per_page"),
        "tutorSupport": kw.get("tutor_support") is True,
        "financeOptions": kw.get("finance_available") is True,
        "fundingOptions": kw.get("funding_available") is True,
        "jobGuarantee": kw.get("job_guarantee") is True,
        "discount": kw.get("on_offer") is True,
        "trending": kw.get("trending") is True,
        "buynow": kw.get("buy_online") is True,
    }
    for method in kw.get("study_method") or []:
        params[STUDY_METHODS[method]] = True
    for level in kw.get("level") or []:
        params[level] = True
    for qualification in kw.get("qualification") or []:
        params[QUALIFICATIONS[qualification]] = True
    for level in kw.get("qualification_level") or []:
        params[f"level{level}"] = True
    if kw.get("max_price") == 0:
        params["pricefrom"] = 0
    return params


def _applied(criteria, kw):
    c = criteria if isinstance(criteria, dict) else {}
    methods = [m for m, key in (("online", "online"), ("classroom", "classroom"), ("in_company", "onSite"), ("on_demand", "onDemand")) if c.get(key)]
    quals = [q for q, key in (("cpd", "cpd"), ("professional", "professional"), ("regulated", "regulated"), ("higher_education", "higherEducation")) if c.get(key)]
    return {
        "keywords": P.text(c.get("keywords")) or kw.get("keywords"),
        "subject": P.text(c.get("subject")) or kw.get("subject"),
        "location": P.text(c.get("location")) or kw.get("location"),
        "distance_miles": P.number(c.get("distance")) or None,
        "is_location_recognised": (not c.get("locationNotRecognised")) if c.get("location") else None,
        "min_price": P.number(c.get("priceFrom")),
        "max_price": P.number(c.get("priceTo")),
        "study_method": methods or None,
        "level": [l for l in LEVELS if c.get(l)] or None,
        "qualification": quals or None,
        "qualification_level": [str(n) for n in range(1, 9) if c.get(f"level{n}")] or None,
        "duration": P.text(c.get("duration")),
        "awarding_body": P.text(c.get("awardingBody")),
        "provider_ids": [P.to_int(p) for p in (c.get("providerIds") or []) if P.to_int(p)] or ([P.to_int(c.get("providerId"))] if P.to_int(c.get("providerId")) else None),
        "tutor_support": True if c.get("tutorSupport") else None,
        "finance_available": True if c.get("financeOptions") else None,
        "funding_available": True if c.get("fundingOptions") else None,
        "job_guarantee": True if c.get("jobGuarantee") else None,
        "on_offer": True if c.get("discount") else None,
        "trending": True if c.get("trending") else None,
        "buy_online": True if c.get("buyNow") else None,
        "sort": {1: "relevance", 2: "most_popular", 3: "price_low_to_high", 4: "price_high_to_low", 5: "newest"}.get(P.to_int(c.get("sortBy"))) or kw.get("sort") or "relevance",
    }


def search(query=None, **kw):
    kw = dict(kw)
    kw["keywords"] = query
    if query and refs.is_link(query):
        link = refs.parse_course_link(query)
        kw["keywords"] = link.get("keywords")
        kw = _merge_link(link, kw)
    path = f"/courses/{_slug(kw['subject'])}" if kw.get("subject") else "/courses/all"
    status, html, final_url = get_page(path, _upstream(kw), label="course search")
    if status != 200:
        raise ReedNotFound("course search page not found" + (f" (subject '{kw.get('subject')}' is not a catalogue subject)" if kw.get("subject") else ""))
    blob = init_blobs(html).get("course-search.index") or {}
    cards = P.course_cards(html, blob.get("coursesToBeDisplayed"))
    organic = [c for c in cards if not c["is_sponsored"]]
    sponsored = [c for c in cards if c["is_sponsored"]]
    page = kw.get("page") or 1
    per_page = kw.get("per_page") or P.to_int((blob.get("criteria") or {}).get("pageSize")) or 25
    total = P.course_search_total(html)
    pagination = P.pagination(page, per_page, total if total is not None else len(organic))
    if total is None:
        pagination["total_pages"] = max(P.course_search_last_page(html), page)
        pagination["total_count"] = None
    if page > 1 and not organic and total is not None and (page - 1) * per_page >= total:
        raise ReedNotFound(f"page {page} is past the last page of this search")
    return {
        "query": kw.get("keywords"),
        "subject": kw.get("subject"),
        "location": kw.get("location"),
        "heading": P.course_search_heading(html),
        "link": final_url.split("?sid=")[0] if final_url else None,
        "applied": _applied(blob.get("criteria"), kw),
        "pagination": pagination,
        "sponsored_courses": sponsored,
        "courses": organic,
    }


# ---- one course ----------------------------------------------------------------------

def _course_page(course_id):
    status, html, final_url = get_page(f"/courses/course/{course_id}", label=f"course {course_id}")
    if status != 200 or "course-view.view" not in html:
        raise ReedNotFound(f"course {course_id} not found")
    blob = init_blobs(html).get("course-view.view") or {}
    return html, blob


def details(course):
    html, blob = _course_page(course)
    record = P.course_details(html, blob, course)
    if not record.get("title"):
        raise ReedUpstreamError(f"course {course} page carried no course data")
    return record


# ---- reviews -----------------------------------------------------------------------

def _provider_id_from_slug(slug):
    """A provider-profiles slug -> its numeric id (one profile page load)."""
    status, html, _ = get_page(f"/courses/provider-profiles/{slug}", label=f"provider {slug}")
    if status != 200:
        raise ReedNotFound(f"course provider '{slug}' not found")
    blob = init_blobs(html).get("provider-profile.details") or {}
    pid = P.to_int(blob.get("providerId"))
    if not pid:
        match = re.search(r'href="/courses/[^"/]+/p(\d+)"', html)
        pid = int(match.group(1)) if match else None
    if not pid:
        raise ReedNotFound(f"course provider '{slug}' not found")
    return pid, html, blob


def _provider_id(provider, course=None):
    if provider and provider.get("id"):
        return int(provider["id"])
    if provider and provider.get("slug"):
        return _provider_id_from_slug(provider["slug"])[0]
    if course:
        _, blob = _course_page(course)
        pid = P.to_int(blob.get("providerId"))
        if pid:
            return pid
    raise ValueError("provider (a provider id or link) or course (a course id or link) is required")


def reviews(provider, course=None, sort="newest", page=1, per_page=25):
    """Learner reviews of a course provider, optionally narrowed to one of its courses."""
    provider_id = _provider_id(provider, course)
    params = {"providerId": provider_id, "courseId": course, "page": page, "pageSize": per_page,
              "sortBy": REVIEW_SORTS.get(sort or "newest")}
    body = get_json("/courses/coursereview/providercoursereviews", params, label="course reviews",
                    referer=refs.provider_courses_link(provider_id))
    rows, pagination = P.reviews_page(body, page, per_page)
    if page > 1 and not rows and pagination["total_pages"] and page > pagination["total_pages"]:
        raise ReedNotFound(f"page {page} is past the last page of reviews (last page {pagination['total_pages']})")
    return {"provider_id": provider_id, "course_id": int(course) if course else None, "sort": sort or "newest",
            "pagination": pagination, "reviews": rows}


# ---- providers -----------------------------------------------------------------------

def providers(query=None, page=1, per_page=24):
    body = get_json("/courses/provider-profiles/search",
                    {"searchText": query or "", "page": page, "pageSize": per_page}, label="course providers") or {}
    rows = [p for p in (P.provider_result(r) for r in body.get("results") or []) if p]
    criteria = body.get("criteria") if isinstance(body.get("criteria"), dict) else {}
    total = P.to_int(body.get("totalResultCount")) or 0
    size = P.to_int(criteria.get("pageSize")) or per_page
    return {"query": query, "pagination": P.pagination(P.to_int(criteria.get("page")) or page, size, total), "providers": rows}


def provider(provider):
    """A course provider's profile: rating, review count, about text, logo,
    popular and discounted courses, plus its catalogue size."""
    slug = provider.get("slug")
    pid = P.to_int(provider.get("id"))
    summary = None
    if not slug:
        # an id names the listing page, whose heading names the provider;
        # the directory search then yields the profile slug
        listing = get_html(f"/courses/provider/p{pid}", label=f"provider {pid} courses")
        heading = P.course_search_heading(listing) or ""
        name = re.sub(r"^Courses (?:with|from|by)\s+", "", heading).strip() or None
        if name:
            body = get_json("/courses/provider-profiles/search", {"searchText": name, "page": 1, "pageSize": 24},
                            label="course providers") or {}
            for row in body.get("results") or []:
                parsed = P.provider_result(row)
                if parsed and parsed["id"] == pid:
                    slug, summary = parsed["slug"], parsed
                    break
        if not slug:
            raise ReedNotFound(f"course provider {pid} has no profile page on reed.co.uk")
    pid, html, blob = _provider_id_from_slug(slug)
    record = P.provider_profile(html, blob, pid, slug)
    if summary is None and record.get("name"):
        body = get_json("/courses/provider-profiles/search", {"searchText": record["name"], "page": 1, "pageSize": 24},
                        label="course providers") or {}
        for row in body.get("results") or []:
            parsed = P.provider_result(row)
            if parsed and parsed["id"] == pid:
                summary = parsed
                break
    record["courses_count"] = (summary or {}).get("courses_count")
    record["has_online_courses"] = (summary or {}).get("has_online_courses")
    record["has_classroom_courses"] = (summary or {}).get("has_classroom_courses")
    record["has_in_company_courses"] = (summary or {}).get("has_in_company_courses")
    if record.get("rating") is None and summary:
        record["rating"] = summary.get("rating")
    return record
