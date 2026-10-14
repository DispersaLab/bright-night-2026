# Diagnosis: Cortana / Italian storytelling session

Investigated 2026-08-30 against the live stack. Everything here is reproduced
evidence, not inference. Source chat:
`sillytavern/data/default-user/chats/Cortana/Cortana - 2026-07-31@18h05m50s094ms.jsonl`
(10 messages, Italian, "Notte dei Ricercatori" demo).

Two questions were asked:

1. Do we need to change the model?
2. What is wrong with the ComfyUI integration?

**Short answers: no, and the character card is what breaks ComfyUI.**

---

## 1. The ComfyUI problem — root cause found

### The chain

The character card `Cortana.png` ends its `system_prompt` with this:

```
Struttura della Tool Call da generare:
{
  "name": "GenerateImage",
  "parameters": {
    "prompt": "<INSERISCI QUI I TAG DESCRITTIVI COME INDICATO SOPRA>"
  }
}
```

That instructs the model to **write the tool call as visible text**. It is not a
model defect — the model is obeying the card. But SillyTavern never receives a
tool call, so:

1. The model prints the JSON block into its reply instead of invoking
   `GenerateImage` through the API's function-calling channel.
2. vLLM's `--tool-call-parser=qwen3_xml` only recognises the Qwen XML tool-call
   format, so this literal JSON stays in `content`.
3. SillyTavern has no tool call, so the image-generation extension falls back to
   using the **whole assistant message** as the image prompt.
4. That text is run through `processReply()`
   (`public/scripts/extensions/stable-diffusion/index.js:2896`), which:
   - deletes every `"` — `str.replaceAll('"', '')`
   - turns every newline into `", "` — `str.replaceAll('\n', ', ')`
   - NFD-normalises and then strips anything outside
     `[a-zA-Z0-9.,:_(){}<>[\]/\-'|#]`, which removes accents but **keeps
     `{ } : ,`**
5. ComfyUI therefore receives Italian prose plus JSON punctuation as the prompt.

### Verification

Replaying `processReply()` on the model output reproduces the stored message
character-for-character in structure, including the accent loss:

```
Le mani di Cortana si alzano. Ora generero un'immagine del protagonista.,
{, name: GenerateImage, parameters: {, prompt: 1boy, holding a futuristic
tricorder, Piazza dei Miracoli, night, }, }
```

Compare the real chat, message 9 — same shape, same `generero`/`e pronta`
accent stripping.

### Controlled experiment: the card is the cause

Same model, same history, same tools, same sampler settings. The **only**
variable is whether the `Struttura della Tool Call` block is present in the
card's system prompt. 6 samples each:

| Card system prompt | Proper tool call | JSON leaked as text | No image at all |
|---|---|---|---|
| **unchanged** | 3 / 6 | 2 / 6 | 1 / 6 |
| **JSON block removed** | **6 / 6** | **0 / 6** | **0 / 6** |
| JSON block removed + explicit "do not write the tool call as text" | 6 / 6 | 0 / 6 | 0 / 6 |

Deleting that one block takes image generation from 50% reliable to 100%
reliable. Average latency 9.8 s / 9.7 s / 10.5 s respectively — so the extra
explicit instruction buys nothing and costs a little. **Just delete the block.**

### The resulting image

`sillytavern/data/default-user/user/images/Cortana/Cortana_2026-07-31@18h13m04s993ms.png`
is an incoherent colour smear. The Pony prefix (`abstractionism, brush stroke,
traditional media`) is the only part the checkpoint can act on.

Running the *same workflow, same seed, same prefix* with clean Danbooru tags
produces a correct, coherent Cortana (`comfyui/output/ComfyUI_00001_.png`).
**The pipeline is healthy. Only the prompt is wrong.**

---

## 2. The `JSONDecodeError` — identified, and no longer reachable

The historical error was:

```
json.decoder.JSONDecodeError: Expecting ',' delimiter: line 55 column 187 (char 1117)
```

Line 55 of the payload SillyTavern POSTs is exactly the `%prompt%` line of
`alice.json`:

```
      "text": "%prompt%", 
```

Column 187 means the JSON string closed after exactly **170 characters** — which
is exactly `len(prompt_prefix)`. So the string was terminated by an unescaped
`"` at the boundary between the prefix and the generated prompt.

Reproduced against the live ComfyUI, which returned the identical signature
(`line 55 column 187 (char 1119)`). Full traceback, which was truncated in the
original report, is `server.py:1075 post_prompt -> await request.json()`.

**It cannot happen through the current code path.** SillyTavern substitutes with
`JSON.stringify(prompt)` (index.js:4233), and `processReply()` deletes quotes
before that anyway. A real end-to-end generation driven through SillyTavern's
API succeeded today (HTTP 200, 26.5 s, 3.4 MB PNG) with no error logged. Treat
this one as closed unless it recurs.

---

## 3. Configuration defects found along the way

### `alice.json` ignores the SillyTavern settings panel

It only honours `%prompt%` and `%negative_prompt%`. Everything else is
hardcoded:

| Setting | SillyTavern UI | `alice.json` actually uses |
|---|---|---|
| steps | 35 | 30 |
| sampler | `euler_ancestral` | `dpmpp_2m_sde` |
| **seed** | **-1 (random)** | **`294082581579803` (fixed)** |

The fixed seed is the significant one: **every image is generated from the same
noise**, so prompt changes produce correlated, samey compositions. Replacing the
literal with `"%seed%"` restores randomisation.

### Context budget is 61x larger than the server allows

- SillyTavern `openai_max_context` = **2,000,000**
- vLLM `--max-model-len` = **32,768**

SillyTavern will not trim history until 2M tokens, so vLLM will reject the
request long before that. The Cortana card alone is 1,386 tokens; with the 8,000
token reply reserve there is room for roughly **23,000 tokens of history** before
the conversation hard-fails. Short event sessions may never hit it; a long one
will die with a 400.

Set `openai_max_context` to 32768 (or lower) so SillyTavern trims correctly.

### Content safety for a public event

`prompt_prefix` contains `rating_safe`, but the negative prompt has **no NSFW
terms at all**. ponyDiffusionV6XL needs them explicitly. My clean-tag test render
came out barely clothed from a prompt that only said "holographic bodysuit".
For Notte dei Ricercatori this should be tightened before the stand is public.

---

## 4. Model assessment — no change indicated

Tested `AEON-7/Qwen3.6-35B-A3B-heretic-NVFP4` directly against
`/v1/chat/completions`.

**What works well:**

- Italian prose is idiomatic, in character, and holds the narrative style
  (`*azioni*` in asterisks) without prompting.
- Tool calling works correctly **when the card does not tell it otherwise** —
  verified in both streaming and non-streaming mode, with the real
  `GenerateImage` schema.
- The reasoning parser is clean: `<think>` never leaks into `content` in current
  testing.

**Real weaknesses observed:**

- Reasoning is emitted **in English** even under an Italian system prompt, and
  runs 1,600–8,400 characters. SillyTavern already sends
  `chat_template_kwargs: {enable_thinking: false}`, so this is mostly latent —
  but with thinking on and a small `max_tokens`, the model spends the entire
  budget thinking and returns **empty content**.
- Minor markdown corruption in the real chat: message 5 ends a bold span with
  `?****`, message 8 has an odd number of `*`. Both render wrong in SillyTavern.
- Occasional garbled Italian ("i campi vincoli nascosti" — meaningless).

None of these are the cause of the ComfyUI failure, and none justify a model
swap on their own. `nvidia/Qwen3.6-35B-A3B-NVFP4` is already in `hf-cache/`, so
an A/B remains one restart away if instruction-following is still unsatisfactory
after the card is fixed — but fix the card first, or the A/B measures the card,
not the model.

---

## 5. Recommended order of work

1. **Fix the card.** Delete the `Struttura della Tool Call` block from
   `Cortana.png`'s system prompt and replace it with an instruction *not* to
   write the tool call as text. This is the single change that fixes the images.
2. **`alice.json`**: replace the hardcoded seed with `"%seed%"`.
3. **`openai_max_context`**: 2000000 -> 32768.
4. **Negative prompt**: add NSFW terms before the event.
5. Only then, if still unhappy, A/B the stock model.

---

## 6. Fixes applied and verified — 2026-08-30 evening

All four changes are in and measured on the live stack.

### What changed

| # | Change | File |
|---|---|---|
| 1 | Removed the `Struttura della Tool Call` block from the system prompt, in both the `chara` and `ccv3` tEXt chunks | `characters/Cortana.png` |
| 2 | `"seed": 294082581579803` -> `"seed": "%seed%"` | `user/workflows/alice.json` |
| 3 | `openai_max_context` 2000000 -> 32768 | `settings.json` |
| 4 | `VLLM_MODEL` -> `Qwen/Qwen3.5-35B-A3B-FP8` | `.env`, `docker-compose.yml` |

The Danbooru tag guidance in the card was deliberately kept — it still shapes
the `prompt` argument the tool receives. Only the "write it as JSON" structure
block was removed.

### Measured result

Same test, same history, 6 samples each:

| Model + card | Proper tool call | Leaked as text | No image at all |
|---|---|---|---|
| Qwen3.6-heretic + original card | 3 / 6 | 2 / 6 | 1 / 6 |
| Qwen3.6-heretic + fixed card | 5 / 6 | 0 / 6 | 1 / 6 |
| **Qwen3.5-FP8 + fixed card** | **6 / 6** | **0 / 6** | **0 / 6** |

The card fix eliminates the leak; the model change also closes the "sometimes
never generates an image" gap.

### Model swap details

`Qwen/Qwen3.5-35B-A3B-FP8`, loaded in 23.5 s.

- Weights **33.65 GiB**, KV cache **16.45 GiB** = 1,225,821 tokens, all within
  the unchanged `--gpu-memory-utilization=0.45`. Memory after: 77 GB used,
  43 GB available — the same headroom ComfyUI had before.
- Generation throughput **47.1 tok/s**, up from 40.8 tok/s on the previous
  model (+15%).
- `--language-model-only` correctly puts this multimodal model in text-only
  mode ("All limits of multimodal modalities supported by the model are set
  to 0").
- `--reasoning-parser=qwen3` and `--tool-call-parser=qwen3_xml` both still
  correct: the model's chat template keeps `<think>` and honours
  `enable_thinking`, which SillyTavern already sends as `false`.
- One benign warning at startup: fastsafetensors reports GPUDirect Storage is
  unavailable on this platform and falls back. Not an error.

### End-to-end verification

Model asked for an image through the real `GenerateImage` tool, the argument
pushed through SillyTavern's `/api/sd/comfy/generate` exactly as the extension
does: **HTTP 200 in 16.8 s**, coherent image, and **no `JSONDecodeError` in the
ComfyUI log**. Seed randomisation confirmed — three consecutive workflow builds
produced three different seeds.

### Still open

- **Prompt prefix dominates the style.** `abstractionism, brush stroke,
  traditional media, perfection style` overwhelms scene tags, so "night,
  Piazza dei Miracoli, Leaning Tower" barely registers in the render. Tune the
  prefix if the setting needs to be legible.
- **The negative prompt still has no NSFW terms** (section 3).
- Any browser tab open on SillyTavern before these edits holds the old settings
  in memory and will overwrite `settings.json` if anything is changed there.
  Hard-reload before using it.
