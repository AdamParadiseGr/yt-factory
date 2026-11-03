// OpenAI-compatible /v1/images/generations adapter over Cloudflare Workers AI (FLUX.1 schnell).
// MoneyPrinterTurbo (video_source = "openai_image") sends POST {model, prompt, n, size}
// and reads data[0].b64_json. Auth: Authorization: Bearer <WORKER_TOKEN>.

const MODEL = "@cf/black-forest-labs/flux-1-schnell";

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "POST" || !url.pathname.endsWith("/images/generations")) {
      return json({ error: { message: "not found" } }, 404);
    }
    // Fail closed: without a configured token anyone could burn the free daily quota.
    if (!env.WORKER_TOKEN) {
      return json({ error: { message: "WORKER_TOKEN is not configured" } }, 503);
    }
    const auth = request.headers.get("authorization") || "";
    if (auth !== `Bearer ${env.WORKER_TOKEN}`) {
      return json({ error: { message: "unauthorized" } }, 401);
    }

    let payload;
    try {
      payload = await request.json();
    } catch {
      return json({ error: { message: "invalid json" } }, 400);
    }
    const prompt = String(payload.prompt || "").trim();
    if (!prompt) return json({ error: { message: "prompt is required" } }, 400);

    try {
      // steps: 4 is the model default; FLUX schnell supports up to 8.
      const out = await env.AI.run(MODEL, { prompt: prompt.slice(0, 2000), steps: 4 });
      if (!out || !out.image) {
        return json({ error: { message: "model returned no image" } }, 502);
      }
      return json({ created: Math.floor(Date.now() / 1000), data: [{ b64_json: out.image }] });
    } catch (e) {
      const msg = String((e && e.message) || e);
      // Daily free neuron budget exhausted -> let the client back off (429 is retried by MPT).
      const status = /limit|quota|neurons/i.test(msg) ? 429 : 502;
      return json({ error: { message: msg.slice(0, 300) } }, status);
    }
  },
};
