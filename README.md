# AfrJigi

**AI-powered exam preparation for students in Côte d'Ivoire (BEPC & BAC)**

AfrJigi is an educational platform built around **Akili**, an AI tutor that guides students through their national exam preparation (BEPC, BAC Général, BAC Technique) using official Ivorian curriculum documents (DPFC programs, past exam papers, official lab worksheets).

🌐 [afrjigi.com](https://afrjigi.com) · 💬 WhatsApp access *(coming soon)*

## Why AfrJigi

- 300,000+ students take the BAC in Côte d'Ivoire every year
- BAC pass rate around 40% (2025, up from 34% in 2024) — source: DECO, Côte d'Ivoire
- Near-universal smartphone ownership, but limited access to qualified teachers (especially in sciences)

AfrJigi meets students where they already are — on their phone, and soon on WhatsApp — with a tutor grounded in the real curriculum, not generic web content.

## How Akili works

- **Guides, never gives the answer directly** — a Socratic method that keeps students actively engaged
- **Two modes**: *Étude* (study, leaning on official programs/lessons) and *Examen* (drills on real past papers)
- **Matched to the real curriculum**: separate content and tone for BEPC (3ème), BAC Général and BAC Technique
- **Built for the real device**: full web app (native WhatsApp access in rollout), formulas offered as multiple-choice taps instead of hard typing

## Project structure

```
afrjigi-akili/
├── akili_api/            # FastAPI backend — RAG search, prompt routing, Vertex AI (Gemini)
├── akili_frontend/        # Streamlit web app (main student-facing interface)
│   └── pages/
│       └── espace_enseignant.py   # Teacher sign-up page
├── whatsapp_bot/           # WhatsApp Business API integration
├── landing/                # Marketing landing page (afrjigi.com / afrjigi.web.app)
└── *.py                    # Content ingestion & maintenance scripts (document pipeline, DB fixes)
```

## Tech stack

- **Backend**: Python, FastAPI, Google Vertex AI (Gemini 2.5 Flash)
- **Frontend**: Streamlit
- **Data**: Firestore (users, conversations), Google Cloud Storage (document knowledge base)
- **Messaging**: WhatsApp Business API
- **Hosting**: Google Cloud Run, Firebase Hosting
- **Payments**: Stripe, PayDunya (mobile money)

## Content sources

AfrJigi's knowledge base is built entirely from official sources: DPFC (Direction de la Pédagogie et de la Formation Continue) programs, official past exam papers, official lab worksheets (TP), and official exam coefficients — not generic web content.

## Status

AfrJigi is live and free to use for all students through the current exam season, while we gather real usage data ahead of a freemium rollout.

## About

AfrJigi is built by **AFRJIGI LLC** (New York, USA), founded by Daouda Diarrassouba.

Contact: [contact@afrjigi.com](mailto:contact@afrjigi.com)

## License

All rights reserved. This repository is public for transparency and review purposes; no license is granted to copy, modify, or redistribute this code without explicit permission from AFRJIGI LLC.
