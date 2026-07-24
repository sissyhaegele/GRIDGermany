# LiteLLM Proxy auf Kyma (SAP AI Core → OpenAI-kompatibel)

Deployt einen LiteLLM-Proxy auf Kyma, der SAP AI Core (Generative AI Hub) als
OpenAI-kompatiblen `/chat/completions`-Endpoint bereitstellt. Danach kann jede
Anwendung die SAP-LLMs (Claude / GPT) über die Standard-OpenAI-API nutzen.

```
Deine App  →  LiteLLM-Proxy (Kyma)  →  SAP Generative AI Hub  →  Anthropic / OpenAI
   OpenAI-Format      Bearer: LITELLM_MASTER_KEY
```

Setup-Vorlage von Willem. Manifeste hier im Ordner.

## Was DU anpassen musst (2 Stellen)

1. **`secrets.yaml`** — aus `secrets.yaml.example` kopieren und füllen:
   - `AICORE_AUTH_URL`, `AICORE_CLIENT_ID`, `AICORE_CLIENT_SECRET`, `AICORE_BASE_URL`
     → aus dem **Service Key deiner AI-Core-Instanz** (BTP Cockpit → Instances &
       Subscriptions → deine `aicore`-Instanz → Service Keys, oder per `cf` / `btp` CLI).
   - `AICORE_RESOURCE_GROUP` — i.d.R. `default`.
   - `LITELLM_MASTER_KEY` — frei wählbar (z.B. UUID); das ist der Bearer-Key,
     mit dem sich deine Apps am Proxy authentifizieren.
   - **`secrets.yaml` ist in .gitignore** und wird NICHT eingecheckt.

2. **`apirule.yaml`** — `hosts:` steht auf dem Kurznamen `litellm-proxy`; der
   volle Host ergibt sich aus **deinem** Kyma-Cluster-Domain (nicht Willems
   `c-110a74e`). Endpoint danach:
   `https://litellm-proxy.<dein-kyma-host>/`

Ggf. **`configmap.yaml`** — `model_list` auf die Modelle beschränken, die in
deinem AI Core tatsächlich **deployed** sind (siehe unten „Modelle prüfen").

## Deployment (Reihenfolge nach Willem)

```bash
cd litellm-proxy
kubectl apply -f namepace.yaml
kubectl apply -f secrets.yaml       # deine gefüllte Version
kubectl apply -f configmap.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl apply -f apirule.yaml
```

## Test

```bash
# Modelle listen
curl https://litellm-proxy.<dein-kyma-host>/models \
  -H "Authorization: Bearer <LITELLM_MASTER_KEY>"

# Chat
curl -X POST https://litellm-proxy.<dein-kyma-host>/chat/completions \
  -H "authorization: Bearer <LITELLM_MASTER_KEY>" \
  -H "content-type: application/json" \
  -d '{"model":"foundational--anthropic-claude-4.6-sonnet",
       "messages":[{"role":"user","content":"what llm are you"}]}'
```
