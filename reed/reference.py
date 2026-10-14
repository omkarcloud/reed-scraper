"""/reed/locations/suggest, /reed/job-titles/suggest, /reed/sectors — the
search box's own autocompletes and the sector filter list (with live job
counts) that /reed/jobs/search filters by."""
from reed import parsers as P
from reed.fetch import get_html, get_json, page_props


def locations(query):
    rows = get_json("/api/location/getlocationsukonlyautocomplete", {"term": query}, label="location suggestions") or []
    suggestions = P.place_suggestions(rows if isinstance(rows, list) else [])
    return {"query": query, "count": len(suggestions), "suggestions": suggestions}


def job_titles(query):
    rows = get_json("/api/search/getjobtaxonomyautocomplete", {"term": query}, label="job title suggestions") or []
    suggestions = P.job_title_suggestions(rows if isinstance(rows, list) else [])
    return {"query": query, "count": len(suggestions), "suggestions": suggestions}


def sectors():
    """The sector filter of the all-jobs page: id, name and how many live
    adverts each sector has right now."""
    props = page_props(get_html("/jobs", {"take": 1}, label="sectors"), "sectors")
    rows = P.sectors_from_filters(props.get("filters"))
    total = P.to_int((props.get("searchResults") or {}).get("count"))
    return {"total_jobs_count": total, "count": len(rows), "sectors": rows}
