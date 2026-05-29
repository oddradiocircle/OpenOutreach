# Product Guide: OpenOutreach

## Vision

OpenOutreach is a self-hosted, open-source LinkedIn automation platform for B2B lead generation. You describe your product and your target market — the system autonomously discovers, qualifies, and contacts the right people, then manages multi-turn follow-up conversations until a deal is closed or disqualified.

The system gets smarter with every decision: it starts by exploring broadly, then progressively focuses on the highest-value profiles as it learns your ideal customer profile from its own history.

## Target Users

- **Founders and solo operators** running their own B2B outreach who need automation without expensive SaaS tools or account bans.
- **Sales teams at SMBs and scale-ups** who want to automate prospecting and follow-up at scale without maintaining contact lists.
- **Marketing and growth agencies** managing outreach campaigns for multiple clients, each with their own product description and target market.

## Core Value Propositions

- **Autonomous lead discovery** — No contact lists needed. The AI generates LinkedIn search queries from a product description and target market definition, then discovers and qualifies candidates automatically.
- **Undetectable operation** — Playwright + stealth plugins mimic real human behavior (typing cadence, mouse movement, session pacing) to minimize the risk of LinkedIn detection and account bans.
- **Full data ownership** — Entirely self-hosted. No SaaS subscription, no third-party data exposure. The full CRM (leads, deals, campaigns, messages) is owned by the operator and browsable via Django Admin.

## Key Features

- **AI-powered lead qualification** — A Bayesian ML model (Gaussian Process Regressor on profile embeddings) combined with an LLM classifier selects and scores candidates. The model uses an explore/exploit strategy (BALD active learning) to balance finding good leads now vs. improving future selection.
- **Autonomous multi-turn follow-up** — An LLM agent manages follow-up conversations end-to-end, using a structured memory system (profile summary + chat summary as incremental fact lists) to personalize each message based on what's been learned about the lead.
- **Campaign management** — Campaigns define a product description, target market, and outreach parameters. Multiple campaigns can run in parallel. All configuration is managed via Django Admin.
- **State machine CRM** — Leads progress through well-defined states (QUALIFIED → READY_TO_CONNECT → PENDING → CONNECTED → COMPLETED / FAILED). Deal outcomes are tracked (converted, not_interested, wrong_fit, etc.).
- **Lazy Poisson task scheduler** — Outreach actions are distributed naturally across working hours using Poisson spacing to avoid detectable automation patterns.
- **Multi-provider LLM support** — Bring your own model: OpenAI, Anthropic, Google, Groq, Mistral, Cohere, or any OpenAI-compatible endpoint.
- **One-command Docker deployment** — Dockerized setup with interactive onboarding wizard, VNC access for browser inspection, and persistent SQLite storage.

## Success Metrics

- Leads discovered and qualified per campaign cycle
- Connection acceptance rate
- Follow-up reply rate
- Deals converted vs. disqualified (and reason distribution)
- Model qualification accuracy improving over time (GP posterior tightening)
