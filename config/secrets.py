'''
Author:     Sai Vignesh Golla
LinkedIn:   https://www.linkedin.com/in/saivigneshgolla/

Copyright (c) 2024-2026 Sai Vignesh Golla

License:    MIT License
            https://opensource.org/license/mit
            
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Support me: https://github.com/sponsors/GodsScion

version:    24.12.3.10.30
'''


###################################################### CONFIGURE YOUR TOOLS HERE ######################################################


# Login Credentials for LinkedIn (Optional)
username = "username@example.com"       # Enter your username in the quotes
password = "example_password"           # Enter your password in the quotes


## Artificial Intelligence (optional)
# Master switch. Turn AI on to let the tool draft answers to application questions
# and pull the required skills out of job descriptions. It needs either a paid API
# key or a local model server, so it stays off by default.
use_AI = False                           # True or False (case-sensitive)

# Which AI service to use. The tool reaches all of them through LangChain, so this
# one setting is usually all you change:
#   "openai"     - OpenAI, or ANY OpenAI-compatible server (Ollama, LM Studio,
#                  vLLM, ...). Point llm_api_url at that server.
#   "deepseek"   - DeepSeek (behaves like "openai"; uses its own url).
#   "openrouter" - OpenRouter (one key, hundreds of models). Uses the
#                  openrouter_api_key below and its own url by default.
#   "gemini"     - Google Gemini (uses your Google API key; llm_api_url is ignored).
ai_provider = "openai"                    # "openai", "deepseek", "openrouter", or "gemini"

# The model name to use. Type whatever your provider offers, for example:
#   OpenAI:     "gpt-4o-mini", "gpt-4o", "gpt-5-mini"
#   Local:      "llama-3.2-3b-instruct", "qwen2.5:latest"
#   OpenRouter: "openrouter/auto", "openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet"
#   Gemini:     "gemini-2.5-flash", "gemini-2.5-pro"
llm_model = "gpt-4o-mini"

# Your API key. For local servers (Ollama / LM Studio) any placeholder is fine, so
# leave it as "not-needed". For OpenAI or DeepSeek, paste a real key here.
llm_api_key = "not-needed"

# Dedicated keys for specific providers (overrides llm_api_key for that provider,
# so you can fill several in and switch providers without re-pasting anything):
#   gemini_api_key     - Google Gemini   (get one free at https://aistudio.google.com/apikey)
#   openrouter_api_key - OpenRouter      (get one at https://openrouter.ai/keys)
# Leave a provider's dedicated key blank to fall back to llm_api_key above.
gemini_api_key = ""
openrouter_api_key = ""

# Base URL of your AI server. Used by the "openai" provider family and DeepSeek.
# OpenRouter switches to https://openrouter.ai/api/v1 automatically.
#   OpenAI:    "https://api.openai.com/v1/"
#   LM Studio: "http://localhost:1234/v1/"
#   Ollama:    "http://localhost:11434/v1/"
#   DeepSeek:  "https://api.deepseek.com/v1"
#   OpenRouter:"https://openrouter.ai/api/v1"
llm_api_url = "https://api.openai.com/v1/"

# Sampling temperature. Leave as None to use the model's own default (some newer
# models only allow their default). Set a number like 0 or 0.3 to override it.
llm_temperature = None


## Licensing (paid product)
# Free plan: up to `free_daily_limit` applications per day, with no key needed.
# Unlimited: paste your Gumroad license key below (from your purchase receipt).
#
# How to find gumroad_product_id: on your Gumroad product's edit page, scroll to
# the "License keys" block - the ID is shown there next to "product_id". The
# app verifies the key against the Gumroad API before unlocking.
gumroad_product_id = "7DoHfAaLX02IZoMe0Vr1Ew=="   # from your Gumroad product's License keys block
gumroad_license_key = ""                           # your Gumroad license key (Blank = Free plan)
free_daily_limit = 10                              # applications allowed per day on the Free plan

# Referral limits (scan + send)
referral_free_daily_limit = 1                      # referral scans allowed per day on Free plan
referral_paid_daily_limit = 4                      # referral scans allowed per day on Paid plan
referral_msg_free_daily_limit = 3                  # referral messages allowed per day on Free plan
referral_msg_paid_daily_limit = 0                  # 0 = unlimited on Paid plan




############################################################################################################
'''
THANK YOU for using my tool 😊! Wishing you the best in your job hunt 🙌🏻!

Sharing is caring! If you found this tool helpful, please share it with your peers 🥺. Your support keeps this project alive.

Support my work on <PATREON_LINK>. Together, we can help more job seekers.

As an independent developer, I pour my heart and soul into creating tools like this, driven by the genuine desire to make a positive impact.

Your support, whether through donations big or small or simply spreading the word, means the world to me and helps keep this project alive and thriving.

Gratefully yours 🙏🏻,
Sai Vignesh Golla
'''

# --- Load user settings saved by the local control panel (user_config.json).
# --- No-op if that file is absent: values fall back to the defaults above.
from config import _overrides as _o
_o.apply(__name__, globals())
############################################################################################################