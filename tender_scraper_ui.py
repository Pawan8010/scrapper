from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from tender_scraper_system import (
    AI_KEYWORDS,
    PORTALS,
    TenderScraperEngine,
    filter_portals,
    looks_like_tender,
    with_max_pages,
)


RESULT_FILES = [
    "realtime_all_pages_tenders.csv",
    "realtime_verified_tenders.csv",
    "live_all_tenders_terminal_clean.csv",
    "live_all_tenders_terminal.csv",
    "tender_results.csv",
]


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
        .app-header {
            border: 1px solid rgba(148, 163, 184, .25);
            border-radius: 8px;
            padding: 18px 20px;
            margin-bottom: 18px;
            background: linear-gradient(180deg, rgba(15,23,42,.06), rgba(15,23,42,.02));
        }
        .app-header h1 { font-size: 28px; line-height: 1.2; margin: 0 0 6px 0; letter-spacing: 0; }
        .app-header p { margin: 0; color: #64748b; font-size: 14px; }
        .section-label {
            margin: 18px 0 8px;
            font-size: 13px;
            font-weight: 700;
            color: #475569;
            text-transform: uppercase;
            letter-spacing: .04em;
        }
        .result-title { font-weight: 700; font-size: 15px; line-height: 1.35; margin-bottom: 8px; }
        .meta-line { color: #64748b; font-size: 13px; line-height: 1.4; }
        .pill {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 999px;
            border: 1px solid rgba(148, 163, 184, .35);
            font-size: 12px;
            margin-right: 6px;
            margin-bottom: 4px;
        }
        .score-pill {
            background: rgba(37, 99, 235, .12);
            color: #2563eb;
            border-color: rgba(37, 99, 235, .35);
            font-weight: 700;
        }
        .open-anchor {
            display:block;
            width:100%;
            box-sizing:border-box;
            text-align:center;
            padding:0.55rem 0.75rem;
            margin-bottom:0.45rem;
            border-radius:0.5rem;
            background:#2563eb;
            color:white !important;
            text-decoration:none !important;
            font-weight:700;
            border: 1px solid #1d4ed8;
        }
        .open-anchor:hover { background:#1d4ed8; }
        .tender-table-wrap {
            max-height: 680px;
            overflow: auto;
            border: 1px solid rgba(128,128,128,.28);
            border-radius: 8px;
        }
        table.tender-table { width: 100%; border-collapse: collapse; font-size: 14px; }
        .tender-table th {
            position: sticky;
            top: 0;
            background: #0f172a;
            color: #f8fafc;
            text-align: left;
            padding: 10px;
            z-index: 1;
        }
        .tender-table td {
            border-top: 1px solid rgba(128,128,128,.22);
            padding: 9px 10px;
            vertical-align: top;
        }
        .tender-table .title { min-width: 420px; max-width: 720px; }
        .open-link {
            display: inline-block;
            padding: 6px 10px;
            border-radius: 6px;
            background: #2563eb;
            color: white !important;
            text-decoration: none;
            font-weight: 600;
            white-space: nowrap;
        }
        .ref-table-header {
            background: #2f363c;
            color: #ffffff;
            font-weight: 700;
            border: 1px solid #46505a;
            border-bottom: none;
        }
        .ref-table-cell {
            min-height: 72px;
            padding: 13px 15px;
            border-left: 1px solid #d9dee4;
            border-bottom: 1px solid #d9dee4;
            background: #ffffff;
            color: #111827;
            line-height: 1.45;
            overflow-wrap: anywhere;
        }
        .ref-title {
            font-size: 15px;
            color: #111827;
        }
        .ref-muted {
            color: #64748b;
            font-size: 12px;
            margin-top: 6px;
        }
        div.stButton > button {
            border: 0;
            color: #16a34a;
            background: transparent;
            font-weight: 700;
            box-shadow: none;
        }
        div.stButton > button:hover {
            color: #15803d;
            background: rgba(22, 163, 74, .08);
            border: 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        import nest_asyncio

        nest_asyncio.apply()
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)


async def scrape_from_ui(args: argparse.Namespace) -> pd.DataFrame:
    portals = with_max_pages(filter_portals(args.portal), args.max_pages)
    engine = TenderScraperEngine(
        portals=portals,
        concurrency=args.concurrency,
        headless=True,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        retries=args.retries,
        browser_enabled=not args.static_only,
        all_tenders=args.all_tenders,
    )
    return await engine.scrape_all()


def load_default_results() -> pd.DataFrame:
    for filename in RESULT_FILES:
        path = Path(filename)
        if path.exists():
            return pd.read_csv(path)
    return pd.DataFrame()


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    expected = [
        "portal",
        "title",
        "tender_url",
        "tender_id",
        "department",
        "deadline",
        "ai_score",
        "matched_keywords",
        "hash",
        "closing_date",
        "bid_opening_date",
        "description",
        "source_page",
        "scraped_at",
    ]
    for column in expected:
        if column not in df.columns:
            df[column] = ""
    df["ai_score"] = pd.to_numeric(df["ai_score"], errors="coerce").fillna(0).astype(int)
    normalized = df[expected].copy()
    if not normalized.empty:
        mask = normalized.apply(
            lambda row: looks_like_tender(str(row["title"]), str(row["tender_url"]), str(row["description"])),
            axis=1,
        )
        normalized = normalized[mask]
        normalized["row_id"] = normalized.apply(build_row_id, axis=1)
    else:
        normalized["row_id"] = []
    return normalized.reset_index(drop=True)


def build_row_id(row: pd.Series) -> str:
    existing_hash = str(row.get("hash", "")).strip()
    if existing_hash and existing_hash.lower() != "nan":
        return existing_hash
    raw = "|".join(
        [
            str(row.get("portal", "")),
            str(row.get("title", "")),
            str(row.get("tender_url", "")),
            str(row.get("deadline", "")) or str(row.get("closing_date", "")),
        ]
    )
    return hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()


def persist_latest_results(df: pd.DataFrame, prefix: str = "realtime_all_pages_tenders") -> None:
    if df.empty:
        return
    export_df = df.drop(columns=["row_id"], errors="ignore")
    export_df.to_csv(f"{prefix}.csv", index=False, encoding="utf-8-sig")
    export_df.to_json(f"{prefix}.json", orient="records", indent=2, force_ascii=False)
    try:
        export_df.to_excel(f"{prefix}.xlsx", index=False)
    except Exception:
        pass


def parse_date_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values.astype(str).str.replace("  ", " ", regex=False), errors="coerce", dayfirst=True)


def filter_dataframe(df: pd.DataFrame, keyword: str, portals: list[str], min_score: int, date_from, date_to) -> pd.DataFrame:
    if df.empty:
        return df

    filtered = df.copy()
    if portals:
        filtered = filtered[filtered["portal"].isin(portals)]

    if keyword.strip():
        terms = [term.strip().lower() for term in keyword.split(",") if term.strip()]
        haystack = (
            filtered["title"].fillna("").astype(str)
            + " "
            + filtered["description"].fillna("").astype(str)
            + " "
            + filtered["matched_keywords"].fillna("").astype(str)
        ).str.lower()
        filtered = filtered[haystack.apply(lambda text: any(term in text for term in terms))]

    filtered = filtered[filtered["ai_score"] >= min_score]
    parsed_closing = parse_date_series(filtered["deadline"].where(filtered["deadline"].astype(str).str.len() > 0, filtered["closing_date"]))
    if date_from:
        filtered = filtered[parsed_closing >= pd.Timestamp(date_from)]
        parsed_closing = parse_date_series(filtered["deadline"].where(filtered["deadline"].astype(str).str.len() > 0, filtered["closing_date"]))
    if date_to:
        filtered = filtered[parsed_closing <= pd.Timestamp(date_to) + pd.Timedelta(days=1)]
    return filtered.sort_values(["ai_score", "portal", "title"], ascending=[False, True, True]).reset_index(drop=True)


def render_open_anchor(label: str, url: str, target: str = "_blank") -> None:
    safe_label = html.escape(label)
    safe_url = html.escape(str(url), quote=True)
    safe_target = html.escape(target, quote=True)
    st.markdown(
        f'<a class="open-anchor" href="{safe_url}" target="{safe_target}" rel="noopener noreferrer">{safe_label}</a>',
        unsafe_allow_html=True,
    )


def stable_listing_url(row: pd.Series) -> str:
    source_page = str(row.get("source_page", "")).strip()
    if source_page:
        return source_page
    tender_url = str(row.get("tender_url", "")).strip()
    parsed = urlparse(tender_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return tender_url


def clean_tender_title(title: str) -> str:
    text = str(title or "").strip()
    text = re.sub(r"^\d+\.\s*", "", text)
    text = re.sub(
        r"\b\d{1,2}[-/][A-Za-z]{3}[-/]\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s{2,}", " ", text).strip(" -|")


def tender_reference(row: pd.Series) -> str:
    explicit_reference = str(row.get("tender_id", "") or "").strip()
    if explicit_reference:
        return explicit_reference
    title = str(row.get("title", "") or "")
    text = title

    patterns = [
        r"\bGEM/\d{4}/[A-Z]/\d+\b",
        r"\bCIL/[A-Za-z0-9()._-]+(?:/[A-Za-z0-9()._-]+){1,}\b",
        r"\b[A-Z]{2,}[A-Z0-9()._-]*(?:/[A-Z0-9()._-]+){2,}\b",
        r"\b[A-Z][A-Z0-9()._-]*(?:/[A-Z0-9()._-]+){2,}\b",
        r"\b[A-Z]{2,}[-_/][A-Z0-9()._/-]*\d[A-Z0-9()._/-]*\b",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        if matches:
            return str(matches[-1]).strip(".,;:")

    portal = str(row.get("portal", "") or "Tender").strip()
    row_hash = str(row.get("row_id", row.get("hash", "")) or "")[:10]
    return f"{portal}-{row_hash}" if row_hash else portal


def opening_expiry_date(row: pd.Series) -> str:
    opening = str(row.get("bid_opening_date", "") or "").strip()
    closing = str(row.get("deadline", "") or "").strip() or str(row.get("closing_date", "") or "").strip()
    if opening and closing and opening != closing:
        return f"{opening} / {closing}"
    return opening or closing or "Not found"


def render_header(last_scrape_at: str) -> None:
    st.markdown(
        f"""
        <div class="app-header">
            <h1>Government Tender Hunting System</h1>
            <p>Realtime procurement scraping, PDF keyword scoring, date filtering, and tender review.</p>
            <p><strong>Status:</strong> {html.escape(last_scrape_at)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_downloads(df: pd.DataFrame) -> None:
    csv_data = df.to_csv(index=False).encode("utf-8-sig")
    json_data = df.to_json(orient="records", indent=2, force_ascii=False).encode("utf-8")
    left, right = st.columns(2)
    with left:
        st.download_button("Download CSV", csv_data, "filtered_tenders.csv", "text/csv", width="stretch")
    with right:
        st.download_button("Download JSON", json_data, "filtered_tenders.json", "application/json", width="stretch")


def render_selected_tender(df: pd.DataFrame) -> None:
    selected_id = st.session_state.get("selected_tender_id", "")
    if not selected_id:
        return
    selected = df[df["row_id"].astype(str) == str(selected_id)]
    if selected.empty:
        st.session_state.selected_tender_id = ""
        return

    row = selected.iloc[0]
    st.markdown('<div class="section-label">Selected Tender</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(f"### {row.get('title', '')}")
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Portal", str(row.get("portal", "")))
        col_b.metric("AI score", int(row.get("ai_score", 0) or 0))
        col_c.metric("Deadline", str(row.get("deadline", "")) or str(row.get("closing_date", "")) or "Not found")
        if st.button("Clear selected tender", key="clear_selected_tender"):
            st.session_state.selected_tender_id = ""
            st.rerun()
        meta_a, meta_b = st.columns(2)
        meta_a.write(f"Tender reference: {str(row.get('tender_id', '')).strip() or tender_reference(row)}")
        meta_b.write(f"Department: {str(row.get('department', '')).strip() or 'Not found'}")
        if str(row.get("matched_keywords", "")).strip():
            st.write(f"Matched keywords: {row.get('matched_keywords', '')}")
        st.write("Description")
        st.info(str(row.get("description", "")) or str(row.get("title", "")))
        st.write("Exact scraped session URL")
        st.code(str(row.get("tender_url", "")), language=None)
        st.caption("Many NIC/GePNIC DirectLink URLs expire. The tender details above are preserved locally.")
        link_col_a, link_col_b = st.columns(2)
        with link_col_a:
            render_open_anchor("Open portal listing", stable_listing_url(row), "_blank")
        with link_col_b:
            render_open_anchor("Open exact scraped URL", str(row.get("tender_url", "")), "_blank")


def render_tender_reference_table(df: pd.DataFrame, key_prefix: str = "results") -> None:
    top_left, top_right = st.columns([1, 1])
    with top_left:
        page_size = st.selectbox("Rows per page", [10, 25, 50, 100], index=1, key=f"{key_prefix}_page_size")
    total_pages = max(1, (len(df) + page_size - 1) // page_size)
    with top_right:
        page_number = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1, key=f"{key_prefix}_page_number")
    start = (page_number - 1) * page_size
    page_df = df.iloc[start : start + page_size]

    st.caption(f"Showing rows {start + 1:,}-{min(start + page_size, len(df)):,} of {len(df):,}.")
    header = st.columns([2.1, 3.7, 1.4, 0.55], gap="small")
    for col, label in zip(header, ["Tender Reference No.", "Title / Description", "Opening / Expiry Date (IST)", "View"]):
        col.markdown(f"<div class='ref-table-header ref-table-cell'>{html.escape(label)}</div>", unsafe_allow_html=True)

    for row_number, row in page_df.iterrows():
        row_id = str(row.get("row_id", build_row_id(row)))
        reference = tender_reference(row)
        description = clean_tender_title(str(row.get("title", "")))
        score = int(row.get("ai_score", 0) or 0)
        portal = str(row.get("portal", "") or "")
        keywords = str(row.get("matched_keywords", "") or "").strip()
        date_text = opening_expiry_date(row)

        ref_col, title_col, date_col, view_col = st.columns([2.1, 3.7, 1.4, 0.55], gap="small")
        ref_col.markdown(
            f"<div class='ref-table-cell'>{html.escape(reference)}<div class='ref-muted'>{html.escape(portal)}</div></div>",
            unsafe_allow_html=True,
        )
        keyword_line = f"<div class='ref-muted'>Score {score}"
        if keywords:
            keyword_line += f" | {html.escape(keywords)}"
        keyword_line += "</div>"
        title_col.markdown(
            f"<div class='ref-table-cell'><div class='ref-title'>{html.escape(description)}</div>{keyword_line}</div>",
            unsafe_allow_html=True,
        )
        date_col.markdown(f"<div class='ref-table-cell'>{html.escape(date_text)}</div>", unsafe_allow_html=True)
        with view_col:
            st.markdown("<div class='ref-table-cell'>", unsafe_allow_html=True)
            if st.button("View details", key=f"{key_prefix}_view_details_{row_number}_{row_id}"):
                st.session_state.selected_tender_id = row_id
                st.rerun()
            render_open_anchor("Open", str(row.get("tender_url", "")), "_blank")
            st.markdown("</div>", unsafe_allow_html=True)


def render_clickable_table(df: pd.DataFrame, max_rows: int = 300) -> None:
    visible = df.head(max_rows).copy()
    rows = []
    for _, row in visible.iterrows():
        title = html.escape(str(row.get("title", "")))
        portal = html.escape(str(row.get("portal", "")))
        closing_date = html.escape(str(row.get("closing_date", "")))
        bid_opening_date = html.escape(str(row.get("bid_opening_date", "")))
        ai_score = html.escape(str(row.get("ai_score", "")))
        matched_keywords = html.escape(str(row.get("matched_keywords", "")))
        portal_url = html.escape(stable_listing_url(row), quote=True)
        rows.append(
            "<tr>"
            f"<td>{portal}</td><td class='title'>{title}</td><td>{closing_date}</td>"
            f"<td>{bid_opening_date}</td><td>{ai_score}</td><td>{matched_keywords}</td>"
            f"<td><a class='open-link' href='{portal_url}' target='_blank' rel='noopener noreferrer'>Open</a></td>"
            "</tr>"
        )
    st.markdown(
        "<div class='tender-table-wrap'><table class='tender-table'>"
        "<thead><tr><th>Portal</th><th>Tender Title</th><th>Closing Date</th><th>Bid Opening</th>"
        "<th>AI Score</th><th>Matched Keywords</th><th>Portal</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    if len(df) > max_rows:
        st.caption(f"Showing first {max_rows:,} rows. Use filters or downloads for the full {len(df):,} rows.")


def main() -> None:
    st.set_page_config(page_title="Tender Hunting System", layout="wide")
    inject_styles()

    if "results_df" not in st.session_state:
        default_df = load_default_results()
        st.session_state.results_df = normalize_columns(default_df) if not default_df.empty else pd.DataFrame()
    if "last_scrape_at" not in st.session_state:
        st.session_state.last_scrape_at = "Loaded existing results" if not st.session_state.results_df.empty else "Not scraped yet"
    if "selected_tender_id" not in st.session_state:
        st.session_state.selected_tender_id = ""

    render_header(st.session_state.last_scrape_at)

    with st.sidebar:
        st.header("Scraper")
        portal_names = [portal.name for portal in PORTALS]
        selected_portals = st.multiselect("Portals from PDF", portal_names, default=portal_names)
        all_tenders = st.toggle("Keep all tenders", value=True)
        static_only = st.toggle("Static mode", value=True, help="Faster. Dynamic mode may work better on JS-heavy portals.")

        st.markdown('<div class="section-label">Run Settings</div>', unsafe_allow_html=True)
        max_pages = st.number_input("Max listing pages per portal", min_value=1, max_value=100, value=10, step=1)
        concurrency = st.number_input("Concurrency", min_value=1, max_value=8, value=3, step=1)
        min_delay = st.number_input("Min delay seconds", min_value=0.0, max_value=60.0, value=1.0, step=0.5)
        max_delay = st.number_input("Max delay seconds", min_value=0.0, max_value=90.0, value=2.0, step=0.5)
        retries = st.number_input("Retries", min_value=1, max_value=5, value=1, step=1)
        run_scrape = st.button("Run Realtime Scraper", type="primary", width="stretch")

        st.markdown('<div class="section-label">Load Data</div>', unsafe_allow_html=True)
        load_csv = st.file_uploader("Load CSV results", type=["csv"])

    if load_csv is not None:
        st.session_state.results_df = normalize_columns(pd.read_csv(load_csv))
        st.session_state.last_scrape_at = f"CSV loaded at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        st.session_state.selected_tender_id = ""
        st.success("CSV loaded.")

    if run_scrape:
        args = argparse.Namespace(
            portal=selected_portals,
            max_pages=int(max_pages),
            concurrency=int(concurrency),
            min_delay=float(min_delay),
            max_delay=float(max_delay),
            retries=int(retries),
            static_only=bool(static_only),
            all_tenders=bool(all_tenders),
        )
        with st.spinner("Scraping portals. This can take a few minutes..."):
            st.session_state.results_df = normalize_columns(run_async(scrape_from_ui(args)))
            persist_latest_results(st.session_state.results_df)
        st.session_state.selected_tender_id = ""
        st.session_state.last_scrape_at = f"Realtime scrape finished at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        st.success(f"Scraping complete: {len(st.session_state.results_df):,} tenders found.")

    df = normalize_columns(st.session_state.results_df) if not st.session_state.results_df.empty else pd.DataFrame()

    st.markdown('<div class="section-label">Search And Filters</div>', unsafe_allow_html=True)
    preset_keywords = st.multiselect("PDF keyword presets", AI_KEYWORDS, default=[])
    search_col, portal_col, score_col = st.columns([2, 1.4, 1])
    with search_col:
        keyword = st.text_input("Keyword search", value=", ".join(preset_keywords), placeholder="thermal camera, LRF, NVG, PTZ camera")
    with portal_col:
        available_portals = sorted(df["portal"].dropna().unique().tolist()) if not df.empty else []
        table_portals = st.multiselect("Filter portal", available_portals)
    with score_col:
        min_score = st.number_input("Minimum AI score", min_value=0, max_value=100, value=0, step=10)

    date_col_a, date_col_b = st.columns(2)
    with date_col_a:
        date_from = st.date_input("Closing date from", value=None)
    with date_col_b:
        date_to = st.date_input("Closing date to", value=None)

    filtered = filter_dataframe(df, keyword, table_portals, int(min_score), date_from, date_to) if not df.empty else df

    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("Total tenders", f"{len(df):,}")
    metric_b.metric("Visible rows", f"{len(filtered):,}")
    metric_c.metric("Portals", f"{df['portal'].nunique() if not df.empty else 0:,}")
    metric_d.metric("Keyword hits", f"{len(filtered[filtered['ai_score'] > 0]) if not filtered.empty else 0:,}")

    if filtered.empty:
        st.info("No tenders to show. Run the scraper or load a CSV file.")
        return

    results_tab, table_tab, export_tab = st.tabs(["Results", "Table", "Export"])
    with results_tab:
        first_row = filtered.iloc[0]
        open_col, info_col = st.columns([1, 3])
        with open_col:
            if st.button("View First Tender", type="primary", width="stretch"):
                st.session_state.selected_tender_id = str(first_row["row_id"])
                st.rerun()
        with info_col:
            st.caption("View details shows the exact scraped tender data locally. Use portal listing for stable external navigation.")
        render_selected_tender(filtered)
        render_tender_reference_table(filtered, key_prefix="results")

    with table_tab:
        render_tender_reference_table(filtered, key_prefix="table")

    with export_tab:
        render_downloads(filtered)
        st.caption("Raw table for copying URLs, hashes, and timestamps.")
        table_df = filtered[[
            "portal",
            "tender_id",
            "title",
            "department",
            "deadline",
            "closing_date",
            "bid_opening_date",
            "ai_score",
            "matched_keywords",
            "tender_url",
            "hash",
            "scraped_at",
        ]].copy()
        table_df["open_tender"] = table_df["tender_url"]
        st.dataframe(
            table_df[["portal", "tender_id", "title", "department", "deadline", "closing_date", "bid_opening_date", "ai_score", "matched_keywords", "open_tender", "hash", "scraped_at"]],
            width="stretch",
            height=650,
            hide_index=True,
            column_config={
                "tender_id": st.column_config.TextColumn("Tender Reference No.", width="medium"),
                "title": st.column_config.TextColumn("Tender Title", width="large"),
                "department": st.column_config.TextColumn("Department", width="medium"),
                "deadline": st.column_config.TextColumn("Deadline", width="medium"),
                "open_tender": st.column_config.LinkColumn("Tender Link", display_text="Open tender", width="small"),
                "ai_score": st.column_config.NumberColumn("AI Score"),
                "hash": st.column_config.TextColumn("Hash", width="small"),
            },
        )


if __name__ == "__main__":
    main()
