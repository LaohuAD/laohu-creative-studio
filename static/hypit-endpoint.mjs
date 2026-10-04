/*
 * 老胡创意工作台的 Hypit 原生 Endpoint。
 *
 * 这是静态随工作台发布的真实 Node 模块，不安装 Studio、不创建 symlink。
 * Runtime profile 只传 projectId/baseURL/pollIntervalMs；平台 Key 始终由
 * 工作台后端读取，不能从 Hypit Endpoint 配置或请求中传入。
 */

import { createHash } from "node:crypto";
import { canonicalize, defineEndpointPackage, wakeAfter } from "@hypit/hypit/endpoint-kit";
import {
  generationTypes,
  sealGeneratedAudioSet,
  sealGeneratedImageSet,
  sealGeneratedVideoSet,
} from "@hypit/hypit/generation";
import { sealText, textTypes } from "@hypit/hypit/text";
import {
  createRuntimeEndpointAdapterFacet,
  runtimeConfigExact,
  runtimeConfigObject,
  runtimeConfigPositiveInteger,
  runtimeConfigString,
} from "@hypit/hypit/runtime-kit";


export const HYPIT_STUDIO_MODULE = Object.freeze({ name: "@laohu/studio-models", version: "1" });
export const HYPIT_RUNTIME_USE = "@laohu/studio-models";
export const HYPIT_ENDPOINT_FACET = "studio-models";

function capability(name) {
  return Object.freeze({ module: HYPIT_STUDIO_MODULE, name });
}

export const HYPIT_CAPABILITIES = Object.freeze({
  text: capability("text-generation"),
  image: capability("image-generation"),
  video: capability("video-generation"),
  speech: capability("speech-generation"),
  audio: capability("audio-generation"),
  music: capability("music-generation"),
});

export const HYPIT_RETURNS = Object.freeze({
  text: textTypes.text,
  image: generationTypes.imageSet,
  video: generationTypes.videoSet,
  speech: generationTypes.audioSet,
  audio: generationTypes.audioSet,
  music: generationTypes.audioSet,
});

const MODEL_PARAMETER_NAMES = new Map([
  ["aspectratio", "aspect_ratio"],
  ["aspect_ratio", "aspect_ratio"],
  ["duration", "duration"],
  ["resolution", "resolution"],
  ["generateaudio", "generate_audio"],
  ["generate_audio", "generate_audio"],
  ["returnlastframe", "return_last_frame"],
  ["return_last_frame", "return_last_frame"],
  ["speaker", "speaker"],
  ["voice", "voice"],
  ["format", "format"],
  ["samplerate", "sample_rate"],
  ["sample_rate", "sample_rate"],
  ["speechrate", "speech_rate"],
  ["speech_rate", "speech_rate"],
  ["loudnessrate", "loudness_rate"],
  ["loudness_rate", "loudness_rate"],
  ["pitchrate", "pitch_rate"],
  ["pitch_rate", "pitch_rate"],
  ["seed", "seed"],
  ["count", "count"],
  ["watermark", "watermark"],
  ["quality", "quality"],
  ["size", "size"],
]);

const PROMPT_PORTS = new Set([
  "prompt", "text", "message", "instruction", "description", "lyrics",
  "voiceDescription", "voice_description",
]);
const SYSTEM_PORTS = new Set(["systemPrompt", "system_prompt"]);


function object(value, subject) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${subject} must be an object`);
  }
  return value;
}

function nonEmptyString(value, subject) {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${subject} must be a non-empty string`);
  }
  return value.trim();
}

function integer(value, subject, fallback) {
  if (value === undefined) return fallback;
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`${subject} must be a positive integer`);
  return value;
}

function address(value) {
  const url = new URL(nonEmptyString(value, "baseURL"));
  const loopback = ["localhost", "127.0.0.1", "[::1]", "::1"].includes(url.hostname);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && loopback)) {
    throw new Error("baseURL must use HTTPS or loopback HTTP");
  }
  return url.href.replace(/\/$/u, "");
}

function project(value) {
  const result = nonEmptyString(value, "projectId");
  if (!/^[A-Za-z0-9_-]{1,128}$/u.test(result)) throw new Error("projectId is invalid");
  return result;
}

function refKey(ref) {
  return `${ref.module.name}@${ref.module.version}#${ref.name}`;
}

function capabilityKind(ref) {
  const item = object(ref, "capability");
  if (item.module?.name !== HYPIT_STUDIO_MODULE.name || item.module?.version !== HYPIT_STUDIO_MODULE.version) {
    return undefined;
  }
  return Object.entries(HYPIT_CAPABILITIES).find(([, value]) => value.name === item.name)?.[0];
}

function typeKind(ref) {
  if (!ref || typeof ref !== "object") return undefined;
  return Object.entries(HYPIT_RETURNS).find(([, value]) =>
    value.module?.name === ref.module?.name
    && value.module?.version === ref.module?.version
    && value.name === ref.name
  )?.[0];
}

function kindForRequest(request) {
  return capabilityKind(request.capability) ?? typeKind(request.returns);
}

function mediaRole(role) {
  if (role === "image") return "reference";
  if (role === "video") return "source_video";
  if (role === "audio") return "reference_audio";
  throw new Error(`Unsupported media role ${String(role)}`);
}

function mediaItem(value) {
  return value && typeof value === "object" && !Array.isArray(value)
    && (value.artifact || value.role || value.url || value.src || value.path);
}

function directUrl(value) {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return undefined;
  for (const key of ["url", "src", "href", "path"]) {
    if (typeof value[key] === "string" && value[key].length > 0) return value[key];
  }
  return undefined;
}

function artifact(value) {
  if (!value || typeof value !== "object") return undefined;
  if (value.kind === "blob" && typeof value.resource === "string") return value;
  if (value.artifact && typeof value.artifact === "object") return artifact(value.artifact);
  return undefined;
}

function asArray(value) {
  if (value === undefined || value === null) return [];
  return Array.isArray(value) ? value : [value];
}

function normalizePortName(name) {
  return String(name).replace(/[^a-z0-9_]/giu, "").toLowerCase();
}

function addValue(target, key, value) {
  if (!target[key]) target[key] = [];
  target[key].push(value);
}

function addMediaPort(target, portName, value) {
  const role = value && typeof value === "object" ? value.role : undefined;
  const explicit = normalizePortName(portName);
  let outputRole;
  if (explicit.includes("firstframe")) outputRole = "first_frame";
  else if (explicit.includes("lastframe")) outputRole = "last_frame";
  else if (role) outputRole = mediaRole(role);
  else if (explicit.includes("image")) outputRole = "reference";
  else if (explicit.includes("video")) outputRole = "source_video";
  else if (explicit.includes("audio")) outputRole = "reference_audio";
  else throw new Error(`Cannot determine media role for port ${portName}`);
  addValue(target, outputRole, value);
}

async function bytesToDataUrl(value, resources) {
  const url = directUrl(value);
  if (url) return url;
  const ref = artifact(value);
  if (!ref) throw new Error("Media input has no URL or BlobRef");
  if (!resources || typeof resources.get !== "function") throw new Error("Runtime resource store is required for media input");
  const bytes = await resources.get(ref.resource);
  if (!bytes) throw new Error(`Resource ${ref.resource} is unavailable`);
  const base64 = typeof Buffer === "function"
    ? Buffer.from(bytes).toString("base64")
    : btoa(String.fromCharCode(...bytes));
  return `data:${ref.mediaType};base64,${base64}`;
}

async function projectPorts(ports, resources) {
  const output = {};
  let parameters = {};
  let prompt = [];
  let systemPrompt = [];
  for (const [name, rawValues] of Object.entries(object(ports, "constraints.ports"))) {
    const values = asArray(rawValues);
    const normal = normalizePortName(name);
    if (normal === 'parameters') {
      if (values.length !== 1 || typeof values[0] !== 'string') throw new Error('parameters requires one JSON object');
      parameters = { ...parameters, ...object(JSON.parse(values[0]), 'parameters') };
      continue;
    }
    if (PROMPT_PORTS.has(name) || PROMPT_PORTS.has(normal)) {
      prompt = prompt.concat(values.filter((item) => String(item).trim()).map(String));
      continue;
    }
    if (SYSTEM_PORTS.has(name) || SYSTEM_PORTS.has(normal)) {
      systemPrompt = systemPrompt.concat(values.filter((item) => String(item).trim()).map(String));
      continue;
    }
    const parameter = MODEL_PARAMETER_NAMES.get(normal);
    if (parameter) {
      if (values.length > 0) parameters[parameter] = values[0];
      continue;
    }
    for (const value of values) {
      if (mediaItem(value)) {
        const copy = { ...value, url: await bytesToDataUrl(value, resources) };
        delete copy.artifact;
        addMediaPort(output, name, copy);
      } else if (value !== undefined && value !== null && value !== "") {
        throw new Error(`Unsupported Endpoint input port ${name}`);
      }
    }
  }
  return { ports: output, parameters, prompt, systemPrompt };
}

async function projectInputs(inputs, resources) {
  if (inputs === undefined) return {};
  const source = object(inputs, "constraints.inputs");
  const output = {};
  for (const [key, rawValues] of Object.entries(source)) {
    if (key === "prompt") continue;
    const role = normalizePortName(key);
    const mapped = role.includes("firstframe") ? "first_frame"
      : role.includes("lastframe") ? "last_frame"
        : role.includes("video") ? "source_video"
          : role.includes("audio") ? "reference_audio"
            : role.includes("image") || role === "reference" ? "reference" : undefined;
    if (!mapped) throw new Error(`Unsupported Endpoint input type ${key}`);
    for (const value of asArray(rawValues)) addValue(output, mapped, await bytesToDataUrl(value, resources));
  }
  return output;
}

/** Project Hypit's port/value vocabulary to the workbench's typed media request. */
export async function projectNativeRequest(request, resources) {
  const source = object(request, "Endpoint request");
  const kind = kindForRequest(source);
  if (!kind) throw new Error("Hypit capability is not supported by the workbench bridge");
  const constraints = object(source.constraints ?? {}, "request.constraints");
  const projected = {
    kind: kind === "speech" ? "audio" : kind,
    slot: kind === "speech" ? "voice" : kind,
  };
  for (const key of ["provider_id", "provider", "model", "model_id", "slot"]) {
    if (constraints[key] !== undefined) projected[key] = constraints[key];
  }
  if (constraints.prompt !== undefined) projected.prompt = constraints.prompt;
  if (constraints.system_prompt !== undefined) projected.system_prompt = constraints.system_prompt;
  if (constraints.parameters !== undefined) projected.parameters = object(constraints.parameters, "request.parameters");
  if (constraints.kind !== undefined) projected.kind = constraints.kind;

  const portResult = constraints.ports === undefined
    ? { ports: {}, parameters: {}, prompt: [], systemPrompt: [] }
    : await projectPorts(constraints.ports, resources);
  const inputResult = await projectInputs(constraints.inputs, resources);
  projected.parameters = { ...(projected.parameters ?? {}), ...portResult.parameters };
  if (portResult.prompt.length > 0) projected.prompt = portResult.prompt.join("\n");
  if (portResult.systemPrompt.length > 0) projected.system_prompt = portResult.systemPrompt.join("\n");

  const mergedInputs = { ...inputResult };
  for (const [role, values] of Object.entries(portResult.ports)) {
    mergedInputs[role] = (mergedInputs[role] ?? []).concat(
      await Promise.all(values.map((item) => bytesToDataUrl(item, resources))),
    );
  }
  if (Object.keys(mergedInputs).length > 0) projected.inputs = mergedInputs;
  return canonicalize(projected);
}

function support(kind, request) {
  try {
    if (kindForRequest(request) !== kind) return { status: "unsupported", reason: "Capability is not this Endpoint's declared type" };
    const constraints = object(request.constraints ?? {}, "request.constraints");
    if (constraints.kind !== undefined && constraints.kind !== kind && !(kind === "speech" && constraints.kind === "audio")) {
      return { status: "unsupported", reason: `Request kind ${String(constraints.kind)} does not match ${kind}` };
    }
    if (constraints.ports && typeof constraints.ports !== "object") {
      return { status: "unsupported", reason: "Endpoint ports must be an object" };
    }
    return { status: "supported" };
  } catch (error) {
    return { status: "unsupported", reason: error instanceof Error ? error.message : String(error) };
  }
}

function pathFor(baseURL, projectId, requestId) {
  return `${baseURL}/api/studio/hypit/models/projects/${encodeURIComponent(projectId)}/requests/${encodeURIComponent(requestId)}`;
}

async function jsonRequest(fetcher, url, init = {}) {
  if (typeof fetcher !== "function") throw new Error("Global fetch is unavailable");
  const response = await fetcher(url, {
    ...init,
    headers: { "content-type": "application/json", ...(init.headers ?? {}) },
  });
  let body;
  try {
    body = await response.json();
  } catch {
    body = {};
  }
  if (!response.ok) {
    const detail = body?.detail ?? body?.error ?? `HTTP ${response.status}`;
    throw new Error(`Workbench model request failed: ${detail}`);
  }
  return object(body, "Workbench response");
}

function receiptFor(task, operation) {
  return { id: String(task.task_id ?? operation) };
}

function handleFor(projectId, requestId, task) {
  return canonicalize({
    projectId,
    requestId,
    taskId: String(task.task_id ?? ""),
  });
}

async function taskFor(fetcher, baseURL, projectId, requestId, task) {
  if (task && typeof task === "object" && task.status) return task;
  return await jsonRequest(fetcher, pathFor(baseURL, projectId, requestId));
}

function failure(message, code = "STUDIO_MODEL_REQUEST_FAILED") {
  return { status: "failed", failure: { code, message: String(message) } };
}

function outputItems(result, plural, singular) {
  const value = result?.[plural] ?? result?.[singular];
  return asArray(value);
}

async function downloadOutput(fetcher, baseURL, value, expectedKind) {
  const direct = directUrl(value);
  if (!direct) throw new Error(`${expectedKind} result has no URL`);
  if (direct.startsWith("data:")) {
    const match = /^data:([^;,]+)?(;base64)?,(.*)$/su.exec(direct);
    if (!match) throw new Error("Invalid data URL result");
    const mediaType = match[1] || (expectedKind === "image" ? "image/png" : expectedKind === "video" ? "video/mp4" : "audio/wav");
    const bytes = match[2] ? Uint8Array.from(Buffer.from(match[3], "base64")) : new TextEncoder().encode(decodeURIComponent(match[3]));
    return { bytes, mediaType };
  }
  const url = new URL(direct, `${baseURL}/`).href;
  const response = await fetcher(url);
  if (!response.ok) throw new Error(`Unable to collect ${expectedKind} result: HTTP ${response.status}`);
  const headerType = response.headers?.get?.("content-type")?.split(";", 1)[0] || "";
  const defaultType = expectedKind === "image" ? "image/png" : expectedKind === "video" ? "video/mp4" : "audio/wav";
  const prefix = `${expectedKind}/`;
  if (headerType && !headerType.startsWith(prefix)) throw new Error(`Collected result is not ${expectedKind} media`);
  return { bytes: new Uint8Array(await response.arrayBuffer()), mediaType: headerType || defaultType };
}

async function collectMedia(context, fetcher, baseURL, result, kind) {
  const plural = kind === "image" ? "images" : kind === "video" ? "videos" : "audios";
  const items = outputItems(result, plural, kind);
  if (items.length === 0) throw new Error(`Workbench result contains no ${plural}`);
  const artifacts = [];
  for (const item of items) {
    const downloaded = await downloadOutput(fetcher, baseURL, item, kind);
    artifacts.push(await context.resources.put(downloaded.bytes, downloaded.mediaType));
  }
  if (kind === "image") return sealGeneratedImageSet({ images: artifacts });
  if (kind === "video") return sealGeneratedVideoSet({ videos: artifacts });
  return sealGeneratedAudioSet({ audios: artifacts });
}

async function collectResult(context, fetcher, baseURL, kind, task) {
  const result = object(task.result ?? {}, "Workbench result");
  if (kind === "text") {
    const value = result.text ?? result.value ?? result.content;
    return { status: "completed", result: { value: { kind: "inline", value: sealText(nonEmptyString(value, "text result")) } } };
  }
  const value = await collectMedia(context, fetcher, baseURL, result, kind === "speech" || kind === "music" ? "audio" : kind);
  return { status: "completed", result: { value: {kind: "inline", value} } };
}

function createAsyncEndpoint({ kind, instance, pool, projectId, baseURL, pollIntervalMs, fetcher }) {
  const capabilityRef = kind === "speech" ? HYPIT_CAPABILITIES.speech : HYPIT_CAPABILITIES[kind];
  const returnRef = HYPIT_RETURNS[kind];
  return {
    async start(context) {
      const requestId = "op_" + createHash("sha256").update(nonEmptyString(context.operation, "operation")).digest("hex");
      const request = await projectNativeRequest({
        capability: capabilityRef,
        returns: returnRef,
        constraints: context.need?.constraints ?? {},
      }, context.resources);
      const task = await jsonRequest(fetcher, `${baseURL}/api/studio/hypit/models/projects/${encodeURIComponent(projectId)}/requests`, {
        method: "POST",
        body: JSON.stringify({
          request_id: requestId,
          capability: capabilityRef,
          returns: returnRef,
          constraints: request,
        }),
      });
      const handle = handleFor(projectId, requestId, task);
      const receipt = receiptFor(task, requestId);
      if (typeof context.checkpoint === "function") await context.checkpoint({ handle, receipt });
      return { ...wakeAfter(handle, pollIntervalMs), receipt };
    },

    async poll(context) {
      const handle = object(context.handle, "Endpoint handle");
      if (handle.projectId !== projectId) throw new Error("Endpoint handle belongs to another project");
      const projectValue = projectId;
      const requestId = nonEmptyString(handle.requestId, "handle.requestId");
      const task = await taskFor(fetcher, baseURL, projectValue, requestId);
      const receipt = receiptFor(task, requestId);
      if (task.status === "queued" || task.status === "running") {
        return { ...wakeAfter(handle, pollIntervalMs), receipt };
      }
      if (task.status === "failed" || task.status === "recoverable") return failure(task.error ?? "Workbench model task failed", "STUDIO_MODEL_TASK_FAILED");
      if (task.status === "succeeded") return { status: "ready", handle: canonicalize({ ...handle, result: task.result }), receipt };
      return failure(`Unknown workbench model task status ${String(task.status)}`, "STUDIO_MODEL_TASK_UNKNOWN");
    },

    async collect(context) {
      const handle = object(context.handle, "Endpoint handle");
      const requestId = nonEmptyString(handle.requestId, "handle.requestId");
      const task = await taskFor(fetcher, baseURL, projectId, requestId, handle.result ? { status: "succeeded", result: handle.result } : undefined);
      if (task.status !== "succeeded") return failure(task.error ?? "Workbench model task is not ready", "STUDIO_MODEL_NOT_READY");
      return await collectResult(context, fetcher, baseURL, kind, task);
    },
  };
}

export function createHypitEndpoint(options) {
  const instance = nonEmptyString(options.instance ?? HYPIT_RUNTIME_USE, "instance");
  const pool = nonEmptyString(options.pool ?? instance, "pool");
  const projectId = project(options.projectId);
  const baseURL = address(options.baseURL ?? options.baseUrl);
  const pollIntervalMs = integer(options.pollIntervalMs, "pollIntervalMs", 1000);
  const fetcher = options.fetcher ?? globalThis.fetch;
  const common = { instance, pool, projectId, baseURL, pollIntervalMs, fetcher };
  return defineEndpointPackage({
    module: HYPIT_STUDIO_MODULE,
    facet: HYPIT_ENDPOINT_FACET,
    instance,
    pool,
    defaultConcurrency: 1,
    actionLimits: {
      submit: { concurrency: 1 },
      poll: { concurrency: 8 },
      collect: { concurrency: 2 },
    },
    capabilities: [
      { lifecycle: "asynchronous", capability: HYPIT_CAPABILITIES.audio,
        returns: generationTypes.audioSet, endpoint: createAsyncEndpoint({...common, kind:"audio"}),
        supports: request => support("audio", request) },
      { lifecycle: "asynchronous", capability: HYPIT_CAPABILITIES.music,
        returns: generationTypes.audioSet, endpoint: createAsyncEndpoint({...common, kind:"music"}),
        supports: request => support("music", request) },
      {
        lifecycle: "asynchronous",
        capability: HYPIT_CAPABILITIES.text,
        returns: textTypes.text,
        endpoint: createAsyncEndpoint({ ...common, kind: "text" }),
        supports: (request) => support("text", request),
      },
      {
        lifecycle: "asynchronous",
        capability: HYPIT_CAPABILITIES.image,
        returns: generationTypes.imageSet,
        endpoint: createAsyncEndpoint({ ...common, kind: "image" }),
        supports: (request) => support("image", request),
      },
      {
        lifecycle: "asynchronous",
        capability: HYPIT_CAPABILITIES.video,
        returns: generationTypes.videoSet,
        endpoint: createAsyncEndpoint({ ...common, kind: "video" }),
        supports: (request) => support("video", request),
      },
      {
        lifecycle: "asynchronous",
        capability: HYPIT_CAPABILITIES.speech,
        returns: generationTypes.audioSet,
        endpoint: createAsyncEndpoint({ ...common, kind: "speech" }),
        supports: (request) => support("speech", request),
      },
    ],
  });
}

/**
 * 主控注入的 Runtime Profile 输出函数。返回值就是 runtime-local 的选择文件
 * 形状，控制器应写入 `.hypit/workbench.runtime.json`，再让 `.hypit/runtime` 保存该相对路径；本函数不做文件写入。
 */
export function createHypitRuntimeProfile(options) {
  const instance = nonEmptyString(options.instance ?? HYPIT_RUNTIME_USE, "instance");
  const pool = nonEmptyString(options.pool ?? instance, "pool");
  const projectId = project(options.projectId);
  const baseURL = address(options.baseURL ?? options.baseUrl);
  const pollIntervalMs = integer(options.pollIntervalMs, "pollIntervalMs", 1000);
  const config = { projectId, baseURL, pollIntervalMs };
  const bindings = Object.fromEntries([
    [HYPIT_CAPABILITIES.text, instance],
    [HYPIT_CAPABILITIES.image, instance],
    [HYPIT_CAPABILITIES.video, instance],
    [HYPIT_CAPABILITIES.speech, instance],
    [HYPIT_CAPABILITIES.audio, instance],
    [HYPIT_CAPABILITIES.music, instance],
  ].map(([ref, value]) => [refKey(ref), value]));
  return {
    format: "hypit.runtime-local@1",
    dataRoot: options.dataRoot ?? ".hypit/runtimes/local",
    credentials: {},
    endpoints: {
      [instance]: { use: HYPIT_RUNTIME_USE, pool, config },
    },
    bindings,
  };
}

export const buildHypitRuntimeProfile = createHypitRuntimeProfile;

const runtimeAdapter = createRuntimeEndpointAdapterFacet({
  use: HYPIT_RUNTIME_USE,
  activate(context) {
    const config = runtimeConfigObject(context.config, "laohu Studio");
    runtimeConfigExact(config, ["projectId", "baseURL", "pollIntervalMs"], "laohu Studio");
    const projectId = runtimeConfigString(config.projectId, "laohu Studio projectId");
    const baseURL = runtimeConfigString(config.baseURL, "laohu Studio baseURL");
    const pollIntervalMs = runtimeConfigPositiveInteger(config.pollIntervalMs, "laohu Studio pollIntervalMs");
    return {
      endpoint: createHypitEndpoint({
        instance: context.instance,
        pool: context.pool ?? context.instance,
        projectId,
        baseURL,
        ...(pollIntervalMs === undefined ? {} : { pollIntervalMs }),
      }),
    };
  },
});

export const hypitPackage = {
  format: "hypit.node-package@1",
  hostFacets: [runtimeAdapter],
};

export default hypitPackage;
