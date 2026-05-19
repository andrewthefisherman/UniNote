# UniNote 📝➡️🧠

An experimental automation pipeline designed to bridge the gap between analog note-taking and structured digital databases. UniNote allows you to write custom commands, symbols, or pseudo-tags directly on a physical notebook or iPad ("Meta-Handwriting"), automatically parsing them to execute complex structural actions within Notion (e.g., creating page properties, fetching Wikipedia references, building bi-directional internal links, and generating structured footnotes).

---

## ⚠️ Project Status: Proof of Concept / Inactive

**Why it is on hold:** The Python backend wrapper and the core structural synchronization logic with the Notion API are fully functional and stable. However, the project was paused due to the current limitations of free-tier Vision AI models when processing dense, handwriting-mixed text. While standard text is transcribed correctly, mixed inputs containing custom meta-syntax alongside complex mathematical notation (LaTeX) frequently led to formatting anomalies and structural parsing errors during the OCR stage. The bottleneck lies entirely within the third-party transcription precision, not the system's underlying architectural logic.

---

## 🚀 Core Innovation: "Meta-Handwriting"

Instead of manually creating pages, typing metadata, and linking documents after digitizing your notes, UniNote treats your pen as a command-line interface. By embedding specific markdown-like tags inside your handwritten text, the parser executes backend routines:

* **Database Metadata Block:** Writing `<meta> title(Elettrotecnica Appello) date(tomorrow) checkbox(yes) </meta>` initializes a fully configured database row with appropriate field mappings.
* **Automated Reference Hunting:** Writing `wiki(Teorema di Weierstrass)` triggers a backend lookup that searches Wikipedia, validates the language, fetches the correct URL, and highlights it inside Notion.
* **Deep Workspace Search:** Writing `ref(Esercizio Circuiti)` performs a fuzzy query across your existing Notion workspace to link relevant past pages directly to your current notes.

---

## 🛠️ System Architecture & Component Breakdown

The pipeline is entirely modular, separated into data acquisition, algorithmic segmentation, large language model orchestration, and structural database synchronization.

### 1. Vision & PDF Processor (`exrecv4.py`)
This module handles raw visual inputs (scanned notebooks, iPad exports) and prepares optimized text blocks for the pipeline.
* **Color-Coded Semantic Segmentation:** Uses `PyMuPDF` (`fitz`) and `numpy` arrays to scan PDF documents and isolate regions matching exact RGB targets (e.g., text emphasized or tagged with a specific green or blue ink).
* **Spatial Bounding Isolation:** Scans row matrices to detect contiguous regions containing target strokes. Applies a customizable `SPACE_TOLERANCE` threshold to group related lines while isolating layout components, ignoring non-relevant sections, and applying pixel margins (`MARGIN`) prior to cropping.
* **Formula-Aware OCR Orchestration:** Dispatches cropped regions to the Google Gemini API (`gemini-1.5-pro`) with advanced system prompts ensuring math notations are strictly translated into pristine LaTeX equations (`$ ... $`), which are then internally normalized to an operational syntax.
* **API Resilience:** Incorporates proactive rate-limiting compliance (monitoring requests-per-minute tokens) and safe execution loops using exponential backoffs and retry mechanisms (`MAX_RETRIES`).

### 2. Notion Meta-Processor (`notion_processor_V6.py`)
The logic engine of the project. A robust object-oriented wrapper built over the official Notion API to handle layout rendering, block trees, and multi-tier reference anchoring.
* **Fuzzy Natural Language Parsing:** Integrates `Cohere` API endpoints to evaluate text blocks using fuzzy matching logic for semantic enhancements:
    * **Contextual Emoji Resolving:** Infers and assigns appropriate structural emojis to page icons based on the textual theme of the notes.
    * **Chronological Normalization:** Parses conversational date phrases (e.g., *"per il prossimo mercoledì"*, *"entro sabato alle sette"*) and serializes them into rigid ISO 8601 timestamps with appropriate timezone offsets (`+02:00`).
* **Layout Graph Compiling:** Transforms raw, marker-embedded text strings into compliant Notion nested block JSON structures. It supports hierarchical headings (`hd1`, `hd2`, `hd3`), paragraphs (`pgr`), block equations (`blq`), code snippets (`cod`), and dynamically managed indentation states for nested bulleted or numbered item lists.
* **Automated Footnote & Anchor Mapping (`NotionLink`):** * Traverses the page block graph recursively using specialized callbacks.
    * Maintains deep state dictionaries (`wiki_pairs`, `url_pairs`, `ref_pairs`) tracking inline entity occurrences.
    * Appends isolated, stylized summary sections (*"Wiki Footnote"*, *"Link Footnote"*, *"Reference Links"*) inside localized quote blocks at the end of the document.
    * Wires bi-directional anchors connecting the inline citation numbers directly to their corresponding footnote list indices via Notion block UUID hyperlinks.
* **Cache Optimization Engine:** Intercepts outgoing Network payloads, keeping a stateful ledger of duplicate Notion queries and Cohere LLM prompts to prevent unnecessary credit consumption and accelerate execution.

### 3. Driver Orchestrator (`uninote to notion.py`)
A compact entry-point automation script using python's `subprocess` engine to smoothly pipe data streams from the front-end capture module directly into the active Notion API ingestion framework.

---

## 📈 Future Expansion Roadmap

* **Edge Hardware Deployment:** Running the complete ingestion pipeline locally on a dedicated **Raspberry Pi** server.
* **Flask Control Web Interface:** Exposing an internal Flask web server to allow headless network uploads, providing multi-tiered access tokens to separate administrative configurations from automated ingestion triggers.
* **Advanced Local OCR Hybrids:** Integrating fine-tuned local models (e.g., customized TrOCR variants) to decouple the handwriting parser from cloud API dependencies, allowing zero-cost processing of dense mathematical configurations.
