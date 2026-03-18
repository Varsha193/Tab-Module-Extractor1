# app.py
import streamlit as st
import pandas as pd
import json
import os
from tab_extractor_backend import start_browser, extract_tabs, click_tab_and_extract_url, extract_all_tab_modules
from selenium.common.exceptions import WebDriverException
from io import BytesIO
import base64
# --- Custom Styling for Hackathon Demo ---
st.markdown("""
    <style>
    /* App-wide layout adjustments */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1100px;
    }

    /* Headings */
    h1, h2, h3, h4 {
        font-family: 'Poppins', sans-serif;
        font-weight: 600;
        color: #1f2937; /* dark slate */
    }

    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background-color: #f9fafb;
        border-right: 1px solid #e5e7eb;
    }

    /* Buttons */
    div.stButton > button {
        background-color: #2563eb;
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.6rem 1.4rem;
        font-weight: 500;
        transition: background 0.3s ease;
    }
    div.stButton > button:hover {
        background-color: #1e40af;
        color: #f9fafb;
    }

    /* Inputs */
    .stTextInput > div > div > input {
        border-radius: 6px;
        border: 1px solid #d1d5db;
    }

    /* Card style for results/logs */
    .result-box {
        background-color: #f3f4f6;
        border-radius: 10px;
        padding: 1rem 1.5rem;
        margin-top: 1rem;
    }

    /* Link styling */
    a {
        color: #2563eb;
        text-decoration: none;
    }
    a:hover {
        text-decoration: underline;
    }
    </style>
""", unsafe_allow_html=True)
with st.container():
    st.markdown("### 📊 Results / Logs")
    st.markdown('<div class="result-box">', unsafe_allow_html=True)
    # (your current result display code here)
    st.markdown('</div>', unsafe_allow_html=True)
    st.title("🧩 Tab Module Extractor")
st.subheader("Automated Tab Detection using Selenium + Streamlit")
st.caption("Detect, Click & Extract Tab Modules with Smart Heuristics")
st.divider()



st.set_page_config(page_title="Tab Module Extractor", layout="wide")

st.title("Tab Module Extractor — Selenium + Streamlit")

# Sidebar controls
st.sidebar.header("Controls")
headless = st.sidebar.checkbox("Headless browser", value=False)
screenshot_dir = st.sidebar.text_input("Screenshot directory (optional)", value="assets/screenshots")
st.sidebar.markdown("---")
st.sidebar.caption("⚠️ Only test on sites you own or have permission to scrape.")

# Main panel
url = st.text_input("Target URL", value="https://example.com")
col1, col2 = st.columns([2,1])

with col1:
    if st.button("Detect Tabs"):
        if not url:
            st.error("Enter a URL first")
        else:
            try:
                driver = start_browser(headless=headless)
                with st.spinner("Detecting tabs..."):
                    tabs = extract_tabs(driver, url)
                driver.quit()
                if not tabs:
                    st.warning("No tabs detected with heuristics.")
                else:
                    st.success(f"Detected {len(tabs)} tab candidates.")
                    # Store tabs in session state
                    st.session_state['detected_tabs'] = tabs
            except Exception as e:
                st.exception(e)

    tabs = st.session_state.get('detected_tabs', [])
    if tabs:
        st.markdown("### Select tabs to extract")
        # Build selection checkboxes
        selected = []
        for i, t in enumerate(tabs):
            label = f"{i+1}. {t.get('text') or t.get('name')} — xpath:{t.get('xpath')[:80]}"
            if st.checkbox(label, key=f"tab_{i}", value=True):
                selected.append(t)
        st.session_state['selected_tabs'] = selected

        col_extract1, col_extract2 = st.columns(2)
        with col_extract1:
            if st.button("Extract Selected Tabs"):
                driver = start_browser(headless=headless)
                try:
                    driver.get(url)
                    st.info("Starting extraction...")
                    results = []
                    for t in selected:
                        with st.spinner(f"Clicking {t.get('name')}"):
                            res = click_tab_and_extract_url(driver, t, screenshot_dir=screenshot_dir)
                            results.append(res)
                    st.success("Extraction complete")
                    st.session_state['extraction_results'] = results
                except WebDriverException as e:
                    st.exception(e)
                finally:
                    driver.quit()

        with col_extract2:
            if st.button("Extract All Tabs (Auto)"):
                driver = start_browser(headless=headless)
                try:
                    with st.spinner("Extracting all tabs..."):
                        out = extract_all_tab_modules(driver, url, screenshot_dir=screenshot_dir)
                        st.session_state['extraction_results'] = out.get('results', [])
                        st.session_state['detected_tabs'] = out.get('tabs', [])
                    st.success("Auto extraction complete")
                except Exception as e:
                    st.exception(e)
                finally:
                    driver.quit()

with col2:
    st.markdown("### Results / Logs")
    results = st.session_state.get('extraction_results', None)
    if results:
        # Create dataframe summary
        summary = []
        for r in results:
            summary.append({
                "name": r.get('requested_name'),
                "initial_url": r.get('initial_url'),
                "final_url": r.get('final_url'),
                "url_changed": r.get('url_changed'),
                "title": r.get('page_title'),
                "status": r.get('status'),
                "elapsed_s": round(r.get('elapsed', 0), 2),
                "error": r.get('error')
            })
        df = pd.DataFrame(summary)
        st.dataframe(df)

        # Download options
        csv = df.to_csv(index=False).encode('utf-8')
        json_bytes = json.dumps(summary, indent=2).encode('utf-8')
        to_excel = BytesIO()
        df.to_excel(to_excel, index=False)
        to_excel.seek(0)

        st.download_button("Download CSV", data=csv, file_name="tab_extraction.csv", mime="text/csv")
        st.download_button("Download JSON", data=json_bytes, file_name="tab_extraction.json", mime="application/json")
        st.download_button("Download XLSX", data=to_excel, file_name="tab_extraction.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        st.markdown("#### Screenshots (base64 preview)")
        for i, r in enumerate(results):
            if r.get("screenshot_base64"):
                st.markdown(f"**{i+1}.** {r.get('requested_name')} — {r.get('final_url')}")
                img_bytes = base64.b64decode(r.get("screenshot_base64"))
                st.image(img_bytes, caption=f"{r.get('requested_name')} screenshot", use_column_width=True)
    else:
        st.info("No extraction run yet.")

st.markdown("---")
st.caption("Built with Selenium + Streamlit — Tab Module Extractor")
