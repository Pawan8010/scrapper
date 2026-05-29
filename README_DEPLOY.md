# Tender Scraper Streamlit Deployment

This project is ready to run as a Streamlit app.

## Main App File

Use this as the Streamlit entry point:

```text
tender_scraper_ui.py
```

## Run Locally

```bash
pip install -r requirements.txt
streamlit run tender_scraper_ui.py
```

Then open:

```text
http://localhost:8501
```

## Deploy On Streamlit Cloud

1. Push this folder to a GitHub repository.
2. Go to Streamlit Community Cloud.
3. Create a new app from the GitHub repository.
4. Set the main file path to `tender_scraper_ui.py`.
5. Deploy.

## Files Needed For Deployment

- `tender_scraper_ui.py`
- `tender_scraper_system.py`
- `requirements.txt`
- `packages.txt`
- `runtime.txt`
- `.streamlit/config.toml`
- Optional seed data: `realtime_all_pages_tenders.csv`

## Notes

Some government tender portals expire session-based tender links. The dashboard therefore shows the exact scraped tender details inside the app and provides stable portal/listing links where possible. Raw session links are still available in tender details, but they may show a timeout page on the original government site.

Dynamic browser scraping is supported by Playwright. `packages.txt` provides the Linux browser libraries Streamlit Cloud normally needs. Some government portals may still block hosted datacenter traffic, expire session DirectLink URLs, or show CAPTCHA; the app preserves scraped tender details locally even when the external session URL expires later.
