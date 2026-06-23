# 🧪 Ingredient Toxicity Metric Fetcher

> **Analyze food product labels to detect ingredients and score their toxicity for human consumption.**

An end-to-end AI pipeline that takes a photo of a food product's ingredient label, extracts text via OCR, identifies individual ingredients using an LLM, cross-references them against a curated toxicological knowledge base, and scores each ingredient on a **1–10 toxicity scale** with detailed harm explanations.

![Python](https://img.shields.io/badge/Python-3.13+-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B?logo=streamlit&logoColor=white)
![Gemini](https://img.shields.io/badge/Google_Gemini-2.0_Flash-4285F4?logo=google&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

---

## 🏗️ Architecture

```
📷 Input Image ──► 🔍 OCR ──► 🧠 LLM Parser ──► 📚 Toxicity DB ──► ⚖️ Scorer ──► 📊 Report
  (Food Label)     PaddleOCR    Gemini 2.0       SQLite (EFSA,      Gemini 2.0    Streamlit
                                Flash             JECFA, FDA)        Flash         + PDF
```

| Stage | What It Does | Technology |
|:------|:-------------|:-----------|
| **1. Text Extraction** | Pre-processes image + OCR | PaddleOCR, OpenCV |
| **2. Ingredient Parsing** | LLM cleans OCR errors, splits ingredients | Google Gemini 2.0 Flash |
| **3. Toxicity Lookup** | Cross-references ingredients against DB | SQLite, thefuzz (fuzzy matching) |
| **4. Toxicity Scoring** | LLM assigns 1-10 score with explanation | Google Gemini 2.0 Flash |
| **5. Report Generation** | Interactive dashboard + PDF export | Streamlit, fpdf2 |

---

## 📊 Toxicity Scale

| Score | Label | Description | Example |
|:------|:------|:------------|:--------|
| 🟢 1–2 | **Safe** | Natural, widely consumed, no known adverse effects | Water, Citric Acid |
| 🟡 3–4 | **Low Risk** | Generally safe, minor concerns at very high doses | Sodium Benzoate |
| 🟠 5–6 | **Moderate** | Some studies show adverse effects; ADI can be exceeded | Aspartame, MSG |
| 🔴 7–8 | **High Risk** | Banned in some countries, linked to health issues | Tartrazine, BHA |
| ⛔ 9–10 | **Critical** | Banned substances, known carcinogens/toxins | Trans fats, Potassium Bromate |

---

## 🎨 Artificial Food Color & Synthetic Dye Detection

The pipeline features a dedicated lookup and alerting system for artificial food colors and synthetic dyes (covering FD&C, E-numbers/INS, and CI numbers):

* **Smart Resolving:** Automatically maps INS codes (e.g., `E102`, `102`), FD&C names (`FD&C Yellow No. 5`, `Yellow 5`), CI indices (`CI 19140`), and standard names (`Tartrazine`).
* **Southampton Six Warnings:** Flags the six colorants linked to hyperactivity in children (*Southampton Six*: Tartrazine, Quinoline Yellow, Sunset Yellow, Carmoisine, Ponceau 4R, Allura Red AC) with orange warnings on the dashboard and in generated PDF reports.
* **Bans & Restructured Dyes:** Automatically alerts on toxic/industrial dyes like Rhodamine B and Sudan Red, or FDA-phased-out colors like FD&C Red No. 3.
* **Rich Metadata:** Displays chemical class (azo, xanthene, triarylmethane, etc.), CI number, color shade, and specific EFSA/FDA regulatory warnings.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A [Google AI Studio API key](https://aistudio.google.com/apikey) (free tier available)

### Installation

```bash
# Clone the repository
git clone https://github.com/JayacharanR/Ingrident-Toxicity-Metric-Fetcher-.git
cd Ingrident-Toxicity-Metric-Fetcher-

# Install dependencies with uv
uv sync

# Set up your API key
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# Build the toxicity database
uv run python scripts/build_database.py
```

### Usage

#### 🖥️ CLI
```bash
# Basic analysis
uv run python main.py --image path/to/food_label.jpg

# With PDF report
uv run python main.py --image path/to/food_label.jpg --output report.pdf

# JSON output
uv run python main.py --image path/to/food_label.jpg --json
```

#### 🌐 Web Dashboard
```bash
uv run streamlit run app.py
```

---

## 📁 Project Structure

```
├── src/
│   ├── ocr/
│   │   ├── preprocessor.py       # Image preprocessing (OpenCV)
│   │   └── extractor.py          # PaddleOCR text extraction
│   ├── parser/
│   │   └── ingredient_parser.py  # LLM-based ingredient parsing
│   ├── toxicity/
│   │   ├── models.py             # Pydantic data models
│   │   ├── database.py           # SQLite DB interface + fuzzy matching
│   │   └── scorer.py             # Toxicity scoring engine
│   ├── report/
│   │   └── generator.py          # PDF report generation
│   └── config.py                 # Configuration management
├── scripts/
│   └── build_database.py         # Database builder (seed + Open Food Facts)
├── data/
│   ├── raw/                      # Downloaded datasets
│   ├── processed/                # Built SQLite database
│   └── samples/                  # Sample food label images
├── tests/                        # Test suite
├── app.py                        # Streamlit dashboard
├── main.py                       # CLI entry point
└── pyproject.toml                # Project configuration
```

---

## 📚 Data Sources

| Source | Description |
|:-------|:------------|
| **EFSA OpenFoodTox** | European Food Safety Authority hazard assessments |
| **JECFA** | FAO/WHO Joint Expert Committee evaluations |
| **FDA GRAS** | US FDA "Generally Recognized As Safe" database |
| **Open Food Facts** | Community-maintained food product database |
| **FSSAI** | Food Safety and Standards Authority of India |

---

## 🛠️ Tech Stack

- **OCR**: PaddleOCR + OpenCV preprocessing
- **LLM**: Google Gemini 2.0 Flash (via `google-genai`)
- **Data Models**: Pydantic v2
- **Database**: SQLite with fuzzy matching (thefuzz)
- **Dashboard**: Streamlit
- **Reports**: fpdf2
- **Package Manager**: uv

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
