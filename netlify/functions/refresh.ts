import type { Config } from "@netlify/functions";

const owner = "Saffron-1230";
const repository = "Signal-Desk";
const workflow = "pages.yml";
const allowedOrigins = new Set([
  "https://saffron-1230.github.io",
  "http://127.0.0.1:8000",
  "http://localhost:8000",
]);
const cooldownMilliseconds = 10 * 60 * 1000;

function responseHeaders(origin: string | null) {
  return {
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Origin": origin && allowedOrigins.has(origin)
      ? origin
      : "https://saffron-1230.github.io",
    "Cache-Control": "no-store",
    "Content-Type": "application/json",
    "Vary": "Origin",
  };
}

function json(body: Record<string, unknown>, status: number, origin: string | null) {
  return new Response(JSON.stringify(body), {
    status,
    headers: responseHeaders(origin),
  });
}

export default async (request: Request) => {
  const origin = request.headers.get("origin");

  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: responseHeaders(origin) });
  }
  if (request.method !== "POST") {
    return json({ status: "error", message: "Method not allowed." }, 405, origin);
  }
  if (origin && !allowedOrigins.has(origin)) {
    return json({ status: "error", message: "Origin not allowed." }, 403, origin);
  }

  const token = Netlify.env.get("GITHUB_REFRESH_TOKEN");
  if (!token) {
    return json({ status: "error", message: "Refresh service is not configured." }, 503, origin);
  }

  const apiBase = `https://api.github.com/repos/${owner}/${repository}`;
  const githubHeaders = {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${token}`,
    "User-Agent": "Signal-Desk-Refresh",
    "X-GitHub-Api-Version": "2022-11-28",
  };

  try {
    const runsResponse = await fetch(
      `${apiBase}/actions/workflows/${workflow}/runs?branch=main&per_page=10`,
      { headers: githubHeaders },
    );
    if (!runsResponse.ok) {
      return json({ status: "error", message: "Could not check the update service." }, 502, origin);
    }

    const runsPayload = await runsResponse.json() as {
      workflow_runs?: Array<{
        event: string;
        status: string;
        conclusion: string | null;
        updated_at: string;
      }>;
    };
    const runs = runsPayload.workflow_runs || [];
    const activeRun = runs.find(run => run.status === "queued" || run.status === "in_progress");
    if (activeRun) {
      return json({ status: "running", message: "An article update is already running." }, 202, origin);
    }

    const latestSuccessfulRun = runs.find(run =>
      (run.event === "schedule" || run.event === "workflow_dispatch") &&
      run.status === "completed" &&
      run.conclusion === "success"
    );
    const latestRunTime = latestSuccessfulRun ? Date.parse(latestSuccessfulRun.updated_at) : 0;
    if (latestRunTime && Date.now() - latestRunTime < cooldownMilliseconds) {
      return json({
        status: "recent",
        message: "The dashboard was updated recently.",
        completedAt: latestSuccessfulRun?.updated_at,
      }, 200, origin);
    }

    const dispatchResponse = await fetch(`${apiBase}/actions/workflows/${workflow}/dispatches`, {
      method: "POST",
      headers: { ...githubHeaders, "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "main" }),
    });
    if (dispatchResponse.status !== 204) {
      return json({ status: "error", message: "Could not start the article update." }, 502, origin);
    }

    return json({ status: "started", message: "Article update started." }, 202, origin);
  } catch {
    return json({ status: "error", message: "The update service is temporarily unavailable." }, 502, origin);
  }
};

export const config: Config = {
  path: "/api/refresh",
  method: ["POST", "OPTIONS"],
};
