"""The 17 Reed endpoints. Every path is served with and without the `/reed`
prefix, so code generated against the hosted API on RapidAPI (paths like
/jobs/details) runs unchanged against this server.

Params are validated by the marshmallow schemas in reed/schemas.py (the same
ones the hosted API uses): ONE param per input — `job`, `employer`,
`company`, `course` and `provider` take an id or a reed.co.uk link, and
`query` on the search endpoints takes text or a full reed.co.uk listing link
whose own filters are then applied. Unknown params are rejected with a 400
so typos surface.

Lists page with `page` + `per_page` (count / total_pages / next / previous
in the response)."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from reed import courses, employers, jobs, reference, salary
from reed import schemas as S
from schema_fields import load_query
from scraper_errors import BadRequest, NotFound


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Café" would arrive as "CafÃ©")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _page_link(params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "")}
    query["page"] = page
    return f"{request.urlparts.scheme}://{request.urlparts.netloc}{request.path}?{urlencode(query)}"


def paginate(result, params):
    """Lift the scraper's `pagination` block into the flat shape the hosted
    API returns: count / per_page / current_page / total_pages / next /
    previous first, then the data."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)
    page = int(pagination.get("page") or params.get("page") or 1)
    total_pages = int(pagination.get("total_pages") or 0)
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(params, page + 1 if page < total_pages else None),
        "previous": _page_link(params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(label, schema, fn, paginated=False):
    """Validate the query, run the scraper, map errors: bad params -> 400,
    missing entity -> 404, transport/blocks -> 500."""
    params = query_dict()
    data, error = load_query(schema, params)
    if error:
        return json_response(error, 400)
    try:
        result = fn(**data)
    except ValueError as e:                # bad id / params
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:                # upstream rejected the request
        return json_response({"error": f"reed rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:                 # retries exhausted / blocked
        return json_response({"error": f"reed {label} failed: {e}"}, 500)
    return json_response(paginate(result, params) if paginated else result)


def mount(path, schema, fn, paginated=False):
    """Serve an endpoint at /path and /reed/path."""
    def handler():
        return call(path.strip("/"), schema, fn, paginated)
    handler.__name__ = "reed_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/reed" + path, method="GET")(handler)


P = True   # paginated (page + per_page)
ENDPOINTS = [
    ("/jobs/details", S.JobSchema, jobs.details, False),
    ("/jobs/search", S.JobSearchSchema, jobs.search, P),
    ("/jobs/facets", S.JobFacetsSchema, jobs.facets, False),
    ("/jobs/batch", S.JobsSchema, jobs.batch, False),
    ("/jobs/similar", S.JobSchema, jobs.similar, False),
    ("/salary/benchmark", S.SalarySchema, salary.benchmark, False),
    ("/locations/suggest", S.SuggestSchema, reference.locations, False),
    ("/job-titles/suggest", S.SuggestSchema, reference.job_titles, False),
    ("/sectors", S.EmptySchema, reference.sectors, False),
    ("/employers/search", S.EmployerSearchSchema, employers.search, P),
    ("/employers/jobs", S.EmployerJobsSchema, employers.jobs, P),
    ("/employers/profile", S.CompanySchema, employers.profile, False),
    ("/courses/search", S.CourseSearchSchema, courses.search, P),
    ("/courses/details", S.CourseSchema, courses.details, False),
    ("/courses/reviews", S.ReviewsSchema, courses.reviews, P),
    ("/courses/providers", S.ProvidersSchema, courses.providers, P),
    ("/courses/providers/details", S.ProviderSchema, courses.provider, False),
]

for _path, _schema, _fn, _paginated in ENDPOINTS:
    mount(_path, _schema, _fn, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
