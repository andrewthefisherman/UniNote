# UniNote 📝➡️🧠
**Status:** ⚠️ Proof of Concept / Inactive
**Core Technologies:** Python, Notion API, Google Gemini (Vision), Cohere (NLP), PyMuPDF, Regex.

## The Vision
UniNote is an experimental pipeline designed to bridge the gap between analog note-taking and structured digital databases. The goal was to eliminate the friction of manually digitizing handwritten mathematical notes and organizing them into Notion.

The core innovation of this project is "Meta-Handwriting". By writing specific commands, symbols, or pseudo-tags directly on a physical notebook or an iPad, the system was designed to parse the handwriting and execute complex Notion commands. For example, writing `wiki(Weierstrass)` or `<date> tomorrow </date>` by hand would automatically generate linked database properties, fetch Wikipedia references, and create rich text blocks in Notion.

## Why it is inactive
The project was put on hold due to the current limitations of free-tier Vision AI models (such as Gemini 1.5 Pro). While the Python backend and the Notion API integration work flawlessly, the OCR pipeline struggled to consistently and accurately recognize custom meta-syntax when mixed with complex, handwritten mathematical notation (LaTeX). The bottleneck was the AI's transcription accuracy, not the system's logic.

## How It Works (Architecture)
Despite the OCR limitations, the backend architecture is fully developed and consists of several robust modules:

### 1. Vision & PDF Processing (exrecv4.py)
* **Color-Coded Extraction:** Uses PyMuPDF and numpy to scan PDF notes and isolate specific strokes based on color (e.g., extracting only the text written in a specific green or blue pen).
* **Chunking & OCR:** Dynamically crops the detected regions based on spatial tolerance and sends them to Google Gemini's Vision API with instructions to transcribe text and convert mathematical formulas into standard LaTeX.
* **Rate Limiting:** Implements custom logic to respect API rate limits (requests per minute) and handle exponential backoffs.

### 2. Notion Meta-Processor (notion_processor_V6.py)
This is the core engine of the project. A custom-built, highly resilient wrapper for the Notion API that translates transcribed text into complex Notion structures.
* **Smart Parsing:** Uses advanced Regex to detect custom meta-tags from the OCR output.
* **NLP Integration (Cohere):** Integrates Cohere's LLM to handle fuzzy logic tasks, such as:
  * Guessing the correct emoji for a page icon based on context.
  * Correcting spelling mistakes in wiki requests.
  * Parsing natural language dates (e.g., "next Tuesday at 5 PM") into strict ISO 8601 formats for Notion properties.
* **Automated Linking & Footnotes:** Automatically detects requested wiki links or internal database references, creates the appropriate hyperlinks in the text, and dynamically generates structured footnote sections at the bottom of the page.
* **Caching & Reliability:** Implements caching for Notion and Cohere requests to minimize redundant API calls and speed up execution.

## Future Developments
The initial roadmap for UniNote included deploying the system on a Raspberry Pi via a Flask web server. This would have allowed different access levels and provided a centralized local hub to process notes continuously in the background without tying up a primary workstation.
