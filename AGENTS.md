# Repository Guidelines

## Authority and Scope

`PROJECT_SPEC.md` is the highest-priority source of formal requirements. This file guides implementation and must never override or conflict with it. Do not add requirements or AI analysis features outside the specification, including any cancelled AI extension analysis. Do not remove a specified core feature because of a model, platform, or tool limitation. If a free-tier, deployment, or technical constraint blocks implementation, describe the constraint and viable alternatives, then wait for the user to choose before proceeding with dependent changes.

## Project Structure

This is a Python 3.13+ FastAPI application. `app/main.py` defines the web app and API routes; `app/config.py` loads settings; `app/models/` contains Pydantic schemas; and `app/services/` contains PDF and AI service logic. The browser interface is in `app/templates/` and `app/static/`. Tests are in `tests/`. `storage/temp_uploads/` and `storage/temp_results/` hold runtime scratch data and must not contain committed user documents or results.

## Source-Grounded Analysis and Language

AI may only extract, select, organize, and summarize information stated in the uploaded PDF. Never add outside knowledge, unsupported inference, subjective evaluation, commentary, extended advice, or invented research findings. Do not present AI synthesis as the author's own claim. Mark missing information as `【原文未提及】` (or `【原文未探討此面向】` when applicable).

Every important finding must include its supporting original text and the PDF's 1-based physical page number, matching the page shown by a PDF reader—not printed journal pagination. Never invent a quote or page number. If either cannot be verified, say so clearly and do not present it as confirmed.

For English and Japanese documents, present the source language with Traditional Chinese. Convert Simplified Chinese to Traditional Chinese and present it once; present Traditional Chinese documents in Traditional Chinese only. Do not force all documents into an English-Chinese format. Topic relevance analysis is allowed only as specified and must be grounded in the PDF's actual content.

## Zero-Cost and Secrets

Keep total development, testing, deployment, and demonstration spending at NT$0. Do not bind a credit card, enable paid services or models, allow automatic charges, add paid fallbacks, or switch to a paid service for convenience. When free AI quota is exhausted, stop accepting new AI analysis requests; use only the specified free/offline behavior.

API keys may be stored only in backend environment variables or a local `.env`. Never place them in frontend files, source code, public documentation, or GitHub. Keep `.env` excluded by `.gitignore`; `.env.example` may contain variable names and clearly fake example values only. Never commit real credentials, uploaded PDFs, or temporary analysis output.

## Development, Style, and Verification

Create a virtual environment with `python -m venv .venv`; install project dependencies with `python -m pip install -r requirements.txt`. Start the local server with `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000` and run tests with `pytest -v` from the repository root. Match existing Python style: four-space indentation, `snake_case` for modules/functions/variables, and `CapWords` for classes. Keep business logic in services and name tests `test_<area>.py` with `test_<behavior>` functions. No formatter, linter, or coverage threshold is configured.

For each implementation stage, inspect the relevant code and requirements before editing, make only the authorized changes, then run the applicable checks/tests and report their actual results. Never claim a check passed unless it was run and passed. Do not install packages unless the user authorizes it; if required dependencies are unavailable, report that blocker and propose options.

## Commits and Pull Requests

The available Git history does not establish a commit message convention; use concise imperative subjects (for example, `Add PDF page limit validation`). Pull requests should summarize behavior and API/configuration impacts, link related issues when available, report actual test results, and include screenshots for visible UI changes.
