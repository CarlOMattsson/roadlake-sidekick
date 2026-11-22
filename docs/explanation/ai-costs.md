# AI costs

[Svenska](ai-costs.sv.md)

<!-- description: What Sidekick can cost besides the license: nothing extra in Claude with a subscription, and per-call charges for features your server runs with an API key. -->

Sidekick itself is free. The AI around it is not always free. This page says where the cost comes from, what Sidekick limits and what you decide yourself, so that you know what you are signing up for before you turn anything on.

## The short version

- **Use Sidekick in Claude with a Claude subscription. We recommend it.** When you work through the connector, Claude does the AI work and it is covered by your subscription. Sidekick adds no AI cost on top.
- **A subscription does not cover everything.** Anything that your own server runs by itself needs an API key, and an API key is billed per call by the provider. That applies to AI steps that run on the server, to memory (Hindsight) when it uses a model through a key, and, later, to automations and their check model.
- **Nothing in this list is on by default.** You turn each one on, and each one needs a key you supply.
- **You can use Sidekick without any of it.** Tasks, journal, contacts and shopping lists do not call a model.

## What costs money, and what does not

| Feature | Runs where | Pays | Default |
| --- | --- | --- | --- |
| Using Sidekick in Claude through the connector | Claude | Your Claude subscription, nothing extra | Always available |
| AI steps run by your own Claude Code | Your computer | Your Claude plan, or an API key if you use one | You start them |
| AI steps run on your server (Run) | Your server | Per call with your Anthropic API key | Off |
| Memory (Hindsight) | Your server | Per call with the key of the model provider you choose; embeddings run locally | Off |
| Automations and a check model (coming, not built yet) | Your server | Per call with your key | Not available; off by default when they arrive |

## The two kinds of key

- **Anthropic API.** Billed by Anthropic per token, to the key you create in the Anthropic Console. Set a spending limit there too.
- **OpenRouter.** One key that reaches many models from many providers. You pay OpenRouter, and the price depends on the model and the provider you pick. You can also point Sidekick at a model on your own network (for example Ollama or LM Studio), which costs nothing per call.

Neither key is needed to use Sidekick in Claude. Both are only for features your server runs.

## Limits that Sidekick sets

These apply to AI steps that run on your server. The values are the defaults; you can change them in your server settings.

| Limit | Default |
| --- | --- |
| Spending per calendar month for AI steps that bill per call | 50 USD |
| Spending per task | 2 USD |
| Attempts at one step in a task | 3 |
| AI steps started per day on the server | 50 |
| AI steps started per day by your own Claude Code | 50 |

The server works out the most a call can cost before it makes the call, and refuses it if it would pass a limit. Runs on a local model cost nothing and can be kept out of the money limits with `SIDEKICK_AI_LOCAL_MODELS_EXEMPT_FROM_CAP`. Sidekick's figure is an estimate, rounded up. The provider's invoice is the record, so also set a limit with the provider.

Memory has its own daily limits on how much is sent to the model provider: by default 40 records from live changes, 150 from the backfill, and 400 000 characters in total per owner and day.

## Coming: automations

*Not built yet. This is the plan, not a feature you can use.* Automations will be off by default and run on your server with an API key, together with a check model that reviews what they propose. Planned limits: a separate automation cap, 15 USD per month by default inside the 50 USD monthly cap and adjustable; at most 1 USD per run; at most 20 runs per day. The check model's calls count against the same cap. With an Anthropic key, Sonnet is the planned default model. With OpenRouter we recommend a cheap model from a trusted host.

## Choosing with OpenRouter

With OpenRouter you pick the provider and the model, so the cost and the privacy are yours to choose well.

- **Choose providers you trust.** Prefer a provider that runs the model outside China, and that says it does not store your prompts and does not train on them. Check this in OpenRouter's provider settings and in the provider's own terms. A setting that lets you require "no data collection" is the safer choice.
- **Where a model runs matters more than where it was made.** Open models developed in China, such as DeepSeek, are fine when a trusted host outside China runs them, for example Google, Azure or AWS or a similar provider. What counts is where the model runs and whether that provider stores or trains on your data.
- **Use cheap models for simple jobs.** A short summary or a checklist does not need the largest model. Start with a small, inexpensive model and move up only if the result is not good enough.
- **Watch the prices.** They change, so this page lists none. See [Anthropic's pricing](https://www.anthropic.com/pricing) and [OpenRouter's models and prices](https://openrouter.ai/models).

## What a number means

Cost depends on how much text goes in and comes out, and on the model. A step's brief and answer are text of a few pages at most, but the same step costs several times more on a large model than on a small one. Because the prices change, Sidekick gives you the ceilings above instead of a price per task. With the defaults, AI steps on your server cannot cost more than 50 USD in a calendar month.

## Read more

- [Run AI steps](../operate/ai-steps.md): turning on the runner and the limits in detail.
- [Turn on memory](../operate/memory.md).
- [Resource limits and secrets](../operate/limits-and-secrets.md): where the keys live.
- [License, license key and price](licensing.md): the license is separate from these costs.
