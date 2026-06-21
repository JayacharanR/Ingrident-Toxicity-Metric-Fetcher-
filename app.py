"""
Streamlit dashboard for the Ingredient Toxicity Metric Fetcher.

A premium, interactive web UI for uploading food label images and
viewing ingredient toxicity analysis in real-time.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path

import streamlit as st

from src.config import validate_config
from src.ocr.extractor import TextExtractor
from src.parser.ingredient_parser import parse_ingredients
from src.report.generator import generate_pdf
from src.toxicity.models import RiskLevel
from src.toxicity.scorer import generate_report

logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Ingredient Toxicity Analyzer",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS for premium look
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    /* Global styles */
    .stApp {
        font-family: 'Inter', sans-serif;
    }

    /* Header gradient */
    .main-header {
        background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
        padding: 2rem 2.5rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    }
    .main-header h1 {
        color: #ffffff;
        font-size: 2rem;
        font-weight: 700;
        margin-bottom: 0.3rem;
    }
    .main-header p {
        color: rgba(255, 255, 255, 0.7);
        font-size: 1rem;
        margin: 0;
    }

    /* Score cards */
    .score-card {
        padding: 1.5rem;
        border-radius: 12px;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        transition: transform 0.2s ease;
    }
    .score-card:hover {
        transform: translateY(-2px);
    }
    .score-card h2 {
        font-size: 2.5rem;
        font-weight: 700;
        margin: 0;
    }
    .score-card p {
        font-size: 0.85rem;
        color: #666;
        margin: 0.3rem 0 0 0;
    }

    /* Risk badges */
    .risk-safe { background: linear-gradient(135deg, #d4edda, #c3e6cb); color: #155724; }
    .risk-low { background: linear-gradient(135deg, #fff3cd, #ffeeba); color: #856404; }
    .risk-moderate { background: linear-gradient(135deg, #ffe0b2, #ffcc80); color: #e65100; }
    .risk-high { background: linear-gradient(135deg, #f8d7da, #f5c6cb); color: #721c24; }
    .risk-critical { background: linear-gradient(135deg, #d32f2f, #b71c1c); color: #ffffff; }

    /* Ingredient card */
    .ingredient-card {
        background: #ffffff;
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        margin-bottom: 1rem;
        border-left: 4px solid;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
        transition: box-shadow 0.2s ease;
    }
    .ingredient-card:hover {
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
    }
    .ingredient-card h4 {
        margin: 0 0 0.5rem 0;
        font-weight: 600;
    }
    .ingredient-card .score-badge {
        display: inline-block;
        padding: 0.2rem 0.8rem;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.85rem;
    }

    /* Sidebar styles */
    .sidebar-info {
        background: rgba(255, 255, 255, 0.05);
        padding: 1rem;
        border-radius: 8px;
        margin-bottom: 1rem;
    }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Risk level styling helpers
# ---------------------------------------------------------------------------

_RISK_COLORS: dict[RiskLevel, str] = {
    RiskLevel.SAFE:     "#22c55e",
    RiskLevel.LOW:      "#eab308",
    RiskLevel.MODERATE: "#f97316",
    RiskLevel.HIGH:     "#ef4444",
    RiskLevel.CRITICAL: "#7f1d1d",
}

_RISK_BG: dict[RiskLevel, str] = {
    RiskLevel.SAFE:     "risk-safe",
    RiskLevel.LOW:      "risk-low",
    RiskLevel.MODERATE: "risk-moderate",
    RiskLevel.HIGH:     "risk-high",
    RiskLevel.CRITICAL: "risk-critical",
}

_RISK_ICONS: dict[RiskLevel, str] = {
    RiskLevel.SAFE:     "🟢",
    RiskLevel.LOW:      "🟡",
    RiskLevel.MODERATE: "🟠",
    RiskLevel.HIGH:     "🔴",
    RiskLevel.CRITICAL: "⛔",
}


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

def app() -> None:
    """Main Streamlit application."""

    # Header
    st.markdown("""
    <div class="main-header">
        <h1>🧪 Ingredient Toxicity Analyzer</h1>
        <p>Upload a food label image to analyze ingredient safety and toxicity</p>
    </div>
    """, unsafe_allow_html=True)

    # Sidebar
    with st.sidebar:
        st.markdown("### ⚙️ Settings")

        # Configuration status
        issues = validate_config()
        if issues:
            for issue in issues:
                if "GEMINI_API_KEY" in issue:
                    st.error(f"🔑 {issue}")
                else:
                    st.warning(f"⚠️ {issue}")

        st.markdown("---")
        st.markdown("### 📖 How it works")
        st.markdown("""
        1. **Upload** a photo of a food product label
        2. **OCR** extracts text from the image
        3. **AI** identifies individual ingredients
        4. **Database** lookup for toxicity data
        5. **Scoring** assigns a 1-10 risk rating
        6. **Report** with detailed analysis
        """)

        st.markdown("---")
        st.markdown("### 🎯 Toxicity Scale")
        st.markdown("""
        - 🟢 **1-2**: Safe
        - 🟡 **3-4**: Low Risk
        - 🟠 **5-6**: Moderate Risk
        - 🔴 **7-8**: High Risk
        - ⛔ **9-10**: Critical
        """)

    # Main content
    col_upload, col_preview = st.columns([1, 1])

    with col_upload:
        st.markdown("### 📷 Upload Food Label Image")
        uploaded_file = st.file_uploader(
            "Choose an image file",
            type=["jpg", "jpeg", "png", "bmp", "webp"],
            help="Upload a clear photo of the ingredient list on a food product.",
        )

    if uploaded_file is not None:
        with col_preview:
            st.markdown("### 🖼️ Image Preview")
            st.image(uploaded_file, use_container_width=True)

        # Analyze button
        if st.button("🔍 Analyze Ingredients", type="primary", use_container_width=True):
            _run_analysis(uploaded_file)

    # Show results if already computed
    elif "report" in st.session_state:
        _display_results(st.session_state["report"])


def _run_analysis(uploaded_file) -> None:
    """Run the full analysis pipeline with progress indicators."""

    # Save uploaded file to temp location
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    try:
        # Stage 1: OCR
        with st.status("🔍 Analyzing image...", expanded=True) as status:
            st.write("📷 **Stage 1/4:** Extracting text from image...")
            extractor = TextExtractor()
            raw_text, confidence = extractor.extract_with_confidence(tmp_path)

            if not raw_text.strip():
                st.error("❌ No text could be extracted from the image. Please try a clearer photo.")
                return

            st.write(f"✅ OCR complete — Confidence: **{confidence:.1%}**")
            with st.expander("📝 Raw OCR Text"):
                st.code(raw_text, language=None)

            # Stage 2: Parse
            st.write("🧠 **Stage 2/4:** Identifying ingredients with AI...")
            ingredients = parse_ingredients(raw_text)

            if not ingredients:
                st.error("❌ No ingredients could be identified in the text.")
                return

            st.write(f"✅ Found **{len(ingredients)}** ingredients")

            # Stage 3 & 4: Lookup + Score
            st.write("⚖️ **Stage 3/4:** Scoring toxicity for each ingredient...")
            report = generate_report(
                ingredients=ingredients,
                image_path=tmp_path,
                raw_ocr_text=raw_text,
            )

            st.write("📊 **Stage 4/4:** Generating report...")
            status.update(label="✅ Analysis complete!", state="complete")

        # Save to session state
        st.session_state["report"] = report

        # Display results
        _display_results(report)

    except Exception as exc:
        exc_str = str(exc)
        if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
            st.error("⚠️ **Gemini API Rate Limit / Quota Exceeded (429)**")
            st.markdown("""
            The Gemini API returned a `429 Resource Exhausted` error. 
            
            **Suggestions to resolve:**
            1. **Wait and Retry**: The free tier of Gemini has strict rate limits. Please wait 30-60 seconds and click **Analyze Ingredients** again.
            2. **Check API Key Quota**: Go to [Google AI Studio](https://aistudio.google.com/) to monitor your usage and quotas.
            3. **Billing config**: Ensure that your API key project is configured correctly and billing setup hasn't disabled your free tier quota.
            """)
        elif "400" in exc_str or "API_KEY_INVALID" in exc_str:
            st.error("🔑 **Invalid Gemini API Key (400)**")
            st.markdown("""
            The Gemini API key provided in your `.env` file is invalid. 
            
            Please go to [Google AI Studio](https://aistudio.google.com/apikey) to generate a valid API key, copy it, and replace the `GEMINI_API_KEY` in your `.env` file.
            """)
        else:
            st.error(f"❌ **An unexpected error occurred:** {exc}")


def _display_results(report) -> None:
    """Display the analysis results in a premium layout."""

    st.markdown("---")

    # --- Summary Cards ---
    st.markdown("### 📊 Analysis Summary")
    c1, c2, c3, c4 = st.columns(4)

    risk_class = _RISK_BG[report.overall_risk]
    icon = _RISK_ICONS[report.overall_risk]

    with c1:
        st.markdown(f"""
        <div class="score-card {risk_class}">
            <h2>{report.overall_score}</h2>
            <p>Overall Score (out of 10)</p>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown(f"""
        <div class="score-card" style="background: #f8f9fa;">
            <h2>{report.total_ingredients}</h2>
            <p>Total Ingredients</p>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        st.markdown(f"""
        <div class="score-card" style="background: #f8f9fa;">
            <h2>{icon} {report.overall_risk.value}</h2>
            <p>Risk Level</p>
        </div>
        """, unsafe_allow_html=True)

    with c4:
        high_color = "#ef4444" if report.high_risk_count > 0 else "#22c55e"
        st.markdown(f"""
        <div class="score-card" style="background: #f8f9fa;">
            <h2 style="color: {high_color};">{report.high_risk_count}</h2>
            <p>High-Risk Ingredients</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown(f"**{report.summary}**")

    # --- Ingredient Details ---
    st.markdown("---")
    st.markdown("### 🧪 Ingredient Breakdown")

    # Sort options
    sort_option = st.selectbox(
        "Sort by:",
        ["Toxicity Score (High → Low)", "Toxicity Score (Low → High)", "Name (A → Z)"],
        label_visibility="collapsed",
    )

    sorted_ingredients = list(report.ingredients)
    if sort_option == "Toxicity Score (High → Low)":
        sorted_ingredients.sort(key=lambda x: x.toxicity_score, reverse=True)
    elif sort_option == "Toxicity Score (Low → High)":
        sorted_ingredients.sort(key=lambda x: x.toxicity_score)
    else:
        sorted_ingredients.sort(key=lambda x: x.ingredient.name)

    for item in sorted_ingredients:
        color = _RISK_COLORS[item.risk_level]
        icon = _RISK_ICONS[item.risk_level]

        with st.container():
            st.markdown(f"""
            <div class="ingredient-card" style="border-left-color: {color};">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <h4>{icon} {item.ingredient.name}</h4>
                    <span class="score-badge" style="background: {color}; color: white;">
                        {item.toxicity_score}/10 — {item.risk_level.value}
                    </span>
                </div>
                <p style="margin: 0.5rem 0; color: #555;">{item.summary}</p>
            </div>
            """, unsafe_allow_html=True)

            with st.expander(f"📋 Details for {item.ingredient.name}"):
                detail_cols = st.columns([2, 1])
                with detail_cols[0]:
                    st.markdown(f"**Why it's harmful (or safe):**\n\n{item.harm_explanation}")
                with detail_cols[1]:
                    if item.ingredient.e_number:
                        st.markdown(f"**E-Number:** {item.ingredient.e_number}")
                    st.markdown(f"**Category:** {item.ingredient.category.value}")
                    if item.adi:
                        st.markdown(f"**ADI:** {item.adi}")
                    if item.data_sources:
                        st.markdown(f"**Sources:** {', '.join(item.data_sources)}")

    # --- Export Options ---
    st.markdown("---")
    st.markdown("### 📥 Export")

    col_pdf, col_json = st.columns(2)

    with col_pdf:
        if st.button("📄 Download PDF Report", use_container_width=True):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                generate_pdf(report, tmp.name)
                with open(tmp.name, "rb") as f:
                    pdf_bytes = f.read()
                st.download_button(
                    label="💾 Save PDF",
                    data=pdf_bytes,
                    file_name="toxicity_report.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )

    with col_json:
        json_data = report.model_dump_json(indent=2)
        st.download_button(
            label="💾 Download JSON Data",
            data=json_data,
            file_name="toxicity_report.json",
            mime="application/json",
            use_container_width=True,
        )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
else:
    app()
