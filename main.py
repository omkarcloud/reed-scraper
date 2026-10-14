"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. The functions live in reed/ (jobs, employers, salary,
reference, courses). Employer, company, course and provider inputs take the
same validated refs the API builds, so go through reed.refs first.
"""
import json
import os

from reed import jobs, salary

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # search with filters: software engineers in London, newest 2 weeks, 25 per page
    found = jobs.search("software engineer", location="London", posted_within="last_2_weeks")
    save("search_software_engineer_london.json", found)

    # one advert in full — a job id or any reed.co.uk job link
    save("job_details.json", jobs.details(str(found["jobs"][0]["id"])))

    # what does a data scientist earn in London?
    save("salary_data_scientist_london.json", salary.benchmark("data scientist", "London"))
