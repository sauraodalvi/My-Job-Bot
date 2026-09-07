'''
Author:     Sai Vignesh Golla
LinkedIn:   https://www.linkedin.com/in/saivigneshgolla/

Copyright (c) 2024-2026 Sai Vignesh Golla

License:    MIT License
            https://opensource.org/license/mit

GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

------------------------------------------------------------------------------
Provider-agnostic AI layer built on LangChain + LangGraph.

A single code path serves OpenAI, any OpenAI-compatible endpoint (Ollama,
LM Studio, DeepSeek, vLLM, and similar) and Google Gemini. Pick the provider,
model, key and URL in `config/secrets.py`.

Public interface (used by runAiBot.py):
    create_ai_client()  -> AIClient | None
    extract_skills(client, job_description) -> dict
    answer_question(client, question, ...)  -> str
    close_ai_client(client) -> None
------------------------------------------------------------------------------
'''

from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, START, END

import config.secrets as cfg
from config import _overrides as _cfg_overrides
from config.questions import question_cache_enabled, question_cache_path
from config.settings import showAiErrorAlerts
from modules.helpers import print_lg, critical_error_log, convert_to_json
from modules.ai.prompts import extract_skills_prompt, ai_answer_prompt

try:
    from pyautogui import confirm
except Exception:  # pyautogui may be unavailable in headless environments
    confirm = None


# Whether to keep popping up AI error dialogs (disabled once the user asks to pause them).
_alerts_enabled = bool(showAiErrorAlerts)

# --- Question answer cache ----------------------------------------------------------
# Reuses AI answers for repeated form questions across runs so we save Gemini tokens.
_JOB_SPECIFIC_WORDS = (
    "company", "corporate", "employer", "hiring", "job", "role", "position",
    "vacancy", "title", "describe", "why", "interest", "passion", "motivat",
    "qualif", "about you", "tell us", "tell me", "cover letter", "portfolio",
    "projects", "our team", "this team",
)


def _question_cache_path() -> str:
    path = question_cache_path
    if os.path.isabs(path):
        return path
    return os.path.join(_cfg_overrides._root_dir(), path)


def _load_question_cache() -> dict:
    try:
        with open(_question_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}


def _save_question_cache(cache: dict) -> None:
    # Keep the cache bounded: drop oldest entries beyond 500.
    if len(cache) > 500:
        for key in list(cache)[: len(cache) - 500]:
            cache.pop(key, None)
    try:
        with open(_question_cache_path(), "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=0, ensure_ascii=False)
    except OSError as e:
        print_lg(f"Could not save question answer cache: {e}")


def _question_is_cacheable(question: str) -> bool:
    low = question.lower()
    return not any(word in low for word in _JOB_SPECIFIC_WORDS)


def _lookup_cached_answer(question: str, question_type: str) -> Optional[str]:
    if not question_cache_enabled or not _question_is_cacheable(question):
        return None
    try:
        cache = _load_question_cache()
        answer = cache.get(_question_cache_key(question, question_type))
        return answer if isinstance(answer, str) and answer else None
    except Exception:
        return None


def _store_cached_answer(question: str, question_type: str, answer: str) -> None:
    if not question_cache_enabled or not _question_is_cacheable(question) or not answer:
        return
    try:
        cache = _load_question_cache()
        cache[_question_cache_key(question, question_type)] = answer
        _save_question_cache(cache)
    except Exception:
        pass


def _question_cache_key(question: str, question_type: str) -> str:
    normalized = " ".join(question.lower().split())
    return hashlib.sha256(f"{normalized}|{question_type}".encode("utf-8")).hexdigest()


def _is_unknown_answer(answer: str) -> bool:
    '''
    True when the AI failed to ground its answer in the applicant information and
    returned the UNKNOWN marker (see modules/ai/prompts.py). Such answers are
    never cached and are surfaced to callers as an empty string so they can
    pause for manual input instead of submitting a hallucinated value.
    '''
    core = " ".join((answer or "").lower().split()).strip(".:- \"'\t\n")
    return core in ("unknown", "i don't know", "i do not know", "n/a", "na", "not sure", "not available", "not provided")


def _ai_error_alert(message: str, error: Exception, title: str = "AI Error") -> None:
    '''Log an AI error and (optionally) show a dismissible dialog, mirroring the rest of the tool.'''
    global _alerts_enabled
    if _alerts_enabled and confirm is not None:
        try:
            choice = confirm(f"{message}\n\n{error}\n", title, ["Pause AI alerts", "Okay, continue"])
            if choice == "Pause AI alerts":
                _alerts_enabled = False
        except Exception:
            pass
    critical_error_log(message, error)


def _resolve_provider(name: Optional[str]) -> str:
    '''
    Map the user-facing provider name to a LangChain model provider.
    Everything OpenAI-compatible (OpenAI, Ollama, LM Studio, DeepSeek, OpenRouter,
    vLLM, ...) runs through the "openai" provider by pointing the URL at the right
    server. Only Google Gemini uses the native "google_genai" provider.
    '''
    n = (name or "openai").strip().lower()
    if n in ("gemini", "google", "google_genai", "google-genai"):
        return "google_genai"
    return "openai"


def _dedicated_key(attr: str) -> str:
    '''The value of a dedicated per-provider API key setting ('' if unset).'''
    return str(getattr(cfg, attr, "") or "").strip()


def _ai_api_key(provider: str) -> str:
    '''
    Pick the API key for the resolved provider. A dedicated key wins; the generic
    llm_api_key is the fallback; finally an environment variable is consulted,
    mirroring how the Google path already worked.
    '''
    generic = str(getattr(cfg, "llm_api_key", "") or "").strip()
    if provider == "google_genai":
        return (_dedicated_key("gemini_api_key") or generic
                or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or "")
    if provider == "openrouter":
        return _dedicated_key("openrouter_api_key") or generic or os.environ.get("OPENROUTER_API_KEY") or ""
    return generic


_OPENAI_DEFAULT_URL = "https://api.openai.com/v1/"
_OPENROUTER_URL = "https://openrouter.ai/api/v1"


def _ai_base_url(provider: str) -> str:
    '''
    Base URL for the OpenAI-compatible path. OpenRouter gets its own endpoint by
    default: switching the provider must not keep sending requests at api.openai.com.
    '''
    url = str(getattr(cfg, "llm_api_url", "") or "").strip()
    if provider == "openrouter" and (
        not url or url.rstrip("/") == _OPENAI_DEFAULT_URL.rstrip("/") or url.rstrip("/").lower() == "https://api.deepseek.com"
    ):
        return _OPENROUTER_URL
    return url


def _msg_text(message) -> str:
    '''Extract plain text from a LangChain message (handles str content and content-block lists).'''
    text = getattr(message, "text", None)
    if isinstance(text, str) and text:
        return text
    if callable(text):  # legacy method form, e.g. older wrappers
        try:
            text = text()
        except Exception:
            text = None
    if isinstance(text, str) and text:
        return text
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text") or block.get("content") or "")
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


class AIClient:
    '''Small holder for the chat model and its compiled answer graph.'''
    def __init__(self, model):
        self.model = model
        self.answer_graph = _build_answer_graph(model)


def create_ai_client() -> Optional[AIClient]:
    '''
    Build the chat model from `config/secrets.py`.
    Returns an `AIClient`, or `None` if AI is turned off or setup fails.
    '''
    if not cfg.use_AI:
        print_lg("AI is turned off (use_AI = False in config/secrets.py). Skipping AI setup.")
        return None
    try:
        provider = _resolve_provider(cfg.ai_provider)
        model_name = cfg.llm_model
        api_key = _ai_api_key(provider)
        temperature = getattr(cfg, "llm_temperature", None)

        kwargs = {}
        # Some newer models only accept their default temperature; leave it unset unless the user opts in.
        if temperature is not None:
            kwargs["temperature"] = temperature

        if provider == "google_genai":
            usable_key = api_key if (api_key and api_key.lower() != "not-needed") else ""
            if not usable_key:
                raise ValueError(
                    "No Google (Gemini) API key was found. Open the AI section of the "
                    "control panel and paste a Gemini API key "
                    "(get one free at https://aistudio.google.com/apikey) into the "
                    "'Gemini API key' field (or the 'AI API key' field), or set the "
                    "GOOGLE_API_KEY / GEMINI_API_KEY environment variable, then click Start again."
                )
            os.environ.setdefault("GOOGLE_API_KEY", usable_key)
            model = init_chat_model(model_name, model_provider="google_genai", **kwargs)
        else:
            base_url = _ai_base_url(provider)
            # OpenAI-compatible servers accept any key; use a placeholder when none is given.
            kwargs["api_key"] = api_key or "not-needed"
            if base_url:
                kwargs["base_url"] = base_url
            model = init_chat_model(model_name, model_provider="openai", **kwargs)

        print_lg("---- AI CLIENT READY ----")
        print_lg(f"Provider: {cfg.ai_provider}   |   Model: {model_name}")
        print_lg("Change these anytime in ./config/secrets.py")
        print_lg("-------------------------")
        return AIClient(model)
    except Exception as e:
        _ai_error_alert(
            "Could not start the AI client. Check your provider, model name, API key and URL in config/secrets.py.",
            e,
        )
        return None


def close_ai_client(client: Optional[AIClient]) -> None:
    '''LangChain chat models hold no long-lived connection to close; kept for interface symmetry.'''
    return None


# --------------------------------------------------------------------------- #
# Skill extraction (structured output)
# --------------------------------------------------------------------------- #
class ExtractedSkills(BaseModel):
    '''Skills extracted from a job description and grouped into five buckets.'''
    tech_stack: list[str] = Field(default_factory=list, description="Programming languages, frameworks, libraries, databases and tools")
    technical_skills: list[str] = Field(default_factory=list, description="Technical expertise beyond specific tools (system design, data engineering, ...)")
    other_skills: list[str] = Field(default_factory=list, description="Non-technical / soft skills (communication, leadership, teamwork, ...)")
    required_skills: list[str] = Field(default_factory=list, description="Skills explicitly listed as required or expected")
    nice_to_have: list[str] = Field(default_factory=list, description="Skills listed as preferred or beneficial but not mandatory")


def extract_skills(client: Optional[AIClient], job_description: str, stream: bool = False) -> dict:
    '''
    Extract and classify skills from a job description.
    Returns a dict with the five skill buckets, or an ``{"error": ...}`` dict on failure.
    '''
    if not client or not job_description:
        return {"error": "AI client unavailable or empty job description."}
    prompt = extract_skills_prompt.format(job_description)
    try:
        structured = client.model.with_structured_output(ExtractedSkills)
        result = structured.invoke(prompt)
        return result.model_dump()
    except Exception as e:
        # Some local or older models don't support structured output — fall back to plain JSON parsing.
        print_lg("Structured skill extraction unavailable, falling back to plain parsing.", e)
        try:
            return convert_to_json(_msg_text(client.model.invoke(prompt)))
        except Exception as e2:
            _ai_error_alert("Could not extract skills from the job description.", e2)
            return {"error": str(e2)}


# --------------------------------------------------------------------------- #
# Question answering (LangGraph pipeline)
# --------------------------------------------------------------------------- #
class _AnswerState(TypedDict, total=False):
    question: str
    options: Optional[list]
    question_type: str
    job_description: Optional[str]
    about_company: Optional[str]
    user_information: Optional[str]
    prompt: str
    raw: str
    answer: str


def _build_answer_graph(model):
    '''
    Compile a small LangGraph pipeline for answering a form question:

        build_prompt -> generate -> (route by question type) -> format_text | select_option

    Free-text questions are returned as-is; select questions are snapped to one of
    the allowed options. The graph gives us a clean seam to extend later (validation,
    retries, resume/cover-letter nodes).
    '''
    def build_prompt(state: _AnswerState) -> dict:
        prompt = ai_answer_prompt.format(state.get("user_information") or "N/A", state.get("question") or "")
        jd = state.get("job_description")
        if jd and jd != "Unknown":
            prompt += f"\n\nJob description:\n{jd}"
        about = state.get("about_company")
        if about and about != "Unknown":
            prompt += f"\n\nAbout the company:\n{about}"
        options = state.get("options")
        if options:
            prompt += "\n\nAnswer with exactly one of these options:\n" + "\n".join(f"- {o}" for o in options)
        return {"prompt": prompt}

    def generate(state: _AnswerState) -> dict:
        message = model.invoke(state["prompt"])
        return {"raw": _msg_text(message).strip()}

    def format_text(state: _AnswerState) -> dict:
        return {"answer": (state.get("raw") or "").strip()}

    def select_option(state: _AnswerState) -> dict:
        raw = (state.get("raw") or "").strip()
        options = state.get("options") or []
        for opt in options:                       # exact
            if raw == opt:
                return {"answer": opt}
        low = raw.lower()
        for opt in options:                       # case-insensitive
            if low == opt.lower():
                return {"answer": opt}
        for opt in options:                       # substring (either direction)
            if opt.lower() in low or low in opt.lower():
                return {"answer": opt}
        return {"answer": raw}

    def route(state: _AnswerState) -> str:
        return "select" if state.get("question_type") in ("single_select", "multiple_select") else "text"

    graph = StateGraph(_AnswerState)
    graph.add_node("build_prompt", build_prompt)
    graph.add_node("generate", generate)
    graph.add_node("format_text", format_text)
    graph.add_node("select_option", select_option)
    graph.add_edge(START, "build_prompt")
    graph.add_edge("build_prompt", "generate")
    graph.add_conditional_edges("generate", route, {"text": "format_text", "select": "select_option"})
    graph.add_edge("format_text", END)
    graph.add_edge("select_option", END)
    return graph.compile()


def answer_question(
    client: Optional[AIClient],
    question: str,
    options: Optional[list] = None,
    question_type: str = "text",
    job_description: Optional[str] = None,
    about_company: Optional[str] = None,
    user_information_all: Optional[str] = None,
    stream: bool = False,
) -> str:
    '''
    Generate an answer to a single application-form question.
    Returns the answer string, or "" if AI is unavailable or the call fails.

    Cached answers for previously-seen questions are reused to save tokens
    (job-specific questions are never cached).
    '''
    if not client or not question:
        return ""

    cached_answer = _lookup_cached_answer(question, question_type)
    if cached_answer is not None:
        print_lg(f'AI answered (cached) "{question}" -> "{cached_answer}"')
        return cached_answer

    try:
        final = client.answer_graph.invoke({
            "question": question,
            "options": options,
            "question_type": question_type,
            "job_description": job_description,
            "about_company": about_company,
            "user_information": user_information_all,
        })
        answer = final.get("answer", "") or ""
        print_lg(f'AI answered "{question}" -> "{answer}"')
        if not _is_unknown_answer(answer):
            _store_cached_answer(question, question_type, answer)
        else:
            answer = ""
        return answer
    except Exception as e:
        _ai_error_alert("Could not generate an AI answer for a question.", e)
        return ""
