# Architecture diagrams

## How it works (non-technical)
The four-step idea, for a general audience.

![How the assistant works](how-it-works.svg)

---

## Request-flow diagrams (detailed)

Request-flow diagrams for the two embedded assistants. They run through the **same
RAG engine** (nomic embeddings → ChromaDB → `llama3.2:3b`); the only differences are
the retrieval **product filter** and the WebUI **performance redirect**.

## OneFS WebUI assistant
Walled to OneFS docs only; performance questions are redirected to InsightIQ.

![OneFS WebUI assistant flow](onefs-webui-assistant-flow.svg)

## InsightIQ assistant
No wall — retrieves OneFS **+** InsightIQ docs, so it answers performance questions
and explains cluster alerts (grounded in the OneFS Event Reference).

![InsightIQ assistant flow](insightiq-assistant-flow.svg)
