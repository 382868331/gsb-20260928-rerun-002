import type { SceneDoc, WorldInfo } from "./types";

const BASE = "/api";

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail;
    if (detail && typeof detail === "object" && "code" in detail) {
      throw new ApiError(res.status, detail.code, detail.message);
    }
    throw new ApiError(res.status, "http_error", JSON.stringify(detail));
  }
  return data as T;
}

export const api = {
  health: () => req("GET", "/health"),
  list: () => req<{ scenes: string[] }>("GET", "/scenes"),
  create: (id: string, doc?: SceneDoc) => req("POST", `/scenes/${id}`, doc),
  get: (id: string) => req<{ doc: SceneDoc }>("GET", `/scenes/${id}/doc`),
  save: (id: string, doc: SceneDoc) => req("PUT", `/scenes/${id}/doc`, doc),
  world: (id: string) => req<{ world: Record<string, WorldInfo> }>("GET", `/scenes/${id}/world`),
  computeWorld: (doc: SceneDoc) => req<{ world: Record<string, WorldInfo> }>("POST", "/compute/world", doc),
};
