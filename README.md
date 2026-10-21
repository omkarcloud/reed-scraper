# 💼 Reed Scraper

Reed Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Reed.co.uk jobs data for free.

## ✨ What Can I Get?

- 💼 **Search 100K+ live UK jobs** — 20 filters: salary, place, radius, contract, remote, sector & date
- 📄 **Full job details** — description, salary range, postcode, skills, employer IDs & similar jobs
- 🏢 **3,500+ employers hiring now** — company profiles, benefits, social links & every live job
- 💷 **Salary benchmarks & 31K+ courses** — average, low & high pay; course prices, curricula & reviews

## 🎥 Example: A Full Reed Job

```json
{
  "id": 57453090,
  "title": "Software Engineer — Full Stack / Backend Focus",
  "link": "https://www.reed.co.uk/jobs/software-engineer--full-stack-backend-focus/57453090",
  "description_text": "Software Engineer\nBuild products, shape technical decisions and help a team deliver...",
  "contract_type": "permanent",
  "is_full_time": true,
  "remote_working": "hybrid",
  "salary": { "display": "£ 70,000 - £ 75,000 per annum", "min": 70000, "max": 75000, "currency": "GBP", "period": "annual", "is_hidden": false },
  "location": { "town": "London", "region": "South East England", "country_code": "GB", "postcode": "EC1A" },
  "employer": {
    "name": "Southern Lights",
    "type": "recruitment_agency",
    "profile_id": 9810,
    "company_profile_id": 86205,
    "link": "https://www.reed.co.uk/jobs/southern-lights/p9810",
    "logo": "https://resources.reed.co.uk/profileimages/logos/thumbs/Logo_9810.png"
  },
  "sector": { "id": 138, "name": "Software Engineer", "parent_id": 52, "parent_name": "IT & Telecoms" },
  "skills": ["API Connectivity", "AWS & Azure Cloud", "Full Stack Development", "Python", "React (JavaScript)"],
  "application": { "is_easy_apply": true, "is_external": false, "requires_uk_eligibility": true },
  "posted_at": "2026-10-13T09:41:24Z",
  "expires_at": "2026-11-24T23:59:59Z"
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Reed Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/reed-scraper
cd reed-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/jobs/details?job=57453090"
```

```json
{
  "job": {
    "id": 57453090,
    "title": "Software Engineer — Full Stack / Backend Focus",
    "link": "https://www.reed.co.uk/jobs/software-engineer--full-stack-backend-focus/57453090",
    "contract_type": "permanent",
    "remote_working": "hybrid",
    "salary": { "min": 70000, "max": 75000, "currency": "GBP", "period": "annual" },
    "location": { "town": "London", "region": "South East England", "postcode": "EC1A" },
    "employer": { "name": "Southern Lights", "type": "recruitment_agency", "profile_id": 9810 },
    "skills": ["API Connectivity", "AWS & Azure Cloud", "CI/CD (Continuous Integration/Delivery)", "Full Stack Development"],
    "posted_at": "2026-10-13T09:41:24Z",
    "expires_at": "2026-11-24T23:59:59Z"
  }
}
```

All 17 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

17 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Job Details | `/jobs/details` | Everything about one job advert in a single call |
| Search Jobs | `/jobs/search` | Up to 100 jobs per page with 20 filters and facets |
| Job Facets | `/jobs/facets` | Job counts per sector, contract, work location and date |
| Jobs by IDs / Similar Jobs | `/jobs/batch`, `/jobs/similar` | Up to 25 full adverts at once, or Reed's similar jobs |
| Salary Benchmark | `/salary/benchmark` | Average, low and high pay for any job title |
| Location / Job Title Autocomplete | `/locations/suggest`, `/job-titles/suggest` | Typeahead for places and job titles |
| Sectors | `/sectors` | Every sector with its ID and live job count |
| Search Employers | `/employers/search` | Employers hiring now with live job counts |
| Employer Jobs | `/employers/jobs` | Every live job of one employer, fully filterable |
| Company Profile | `/employers/profile` | Website, size, benefits, social links and recent jobs |
| Search Courses / Course Details | `/courses/search`, `/courses/details` | Courses with prices, ratings, curricula and Q&A |
| Course Reviews | `/courses/reviews` | Learner reviews with per-aspect star ratings |
| Course Providers / Provider Details | `/courses/providers`, `/courses/providers/details` | Provider ratings, review counts and popular courses |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-reed-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-reed-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-reed-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/jobs/search",
    params={"query": "software engineer", "location": "London", "remote_working": "hybrid"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Reed Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Reed%20Scraper%20API.)

[![Ask Us by Email about Reed Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Reed%20Scraper%20API&body=I%20need%20help%20using%20the%20Reed%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**Totaljobs Scraper**](https://github.com/omkarcloud/totaljobs-scraper) — Totaljobs UK jobs, salaries, employers & 250+ job descriptions
- [**Glassdoor Scraper**](https://github.com/omkarcloud/glassdoor-scraper) — Glassdoor jobs, company ratings, salaries & reviews
- [**We Work Remotely Scraper**](https://github.com/omkarcloud/we-work-remotely-scraper) — remote jobs with salary ranges, skills, countries & company profiles
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/reed-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/reed-scraper)
