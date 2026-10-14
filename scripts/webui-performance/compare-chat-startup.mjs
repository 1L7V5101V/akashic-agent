/** 交错切换真实聊天制品，按相邻冷/热样本比较，降低宿主负载漂移的影响。 */
import assert from "node:assert/strict";
import { spawnSync, execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, utimesSync, writeFileSync } from "node:fs";
import { loadavg } from "node:os";
import { dirname, resolve, sep } from "node:path";
import { parseArgs } from "node:util";

const { values } = parseArgs({ options: {
  url: { type: "string" }, browser: { type: "string" }, output: { type: "string" },
  baseline: { type: "string" }, candidate: { type: "string" }, "runtime-chat": { type: "string" },
  runs: { type: "string", default: "7" }, profiles: { type: "string", default: "lan,latency,limited" },
} });
for (const key of ["url", "browser", "output", "baseline", "candidate", "runtime-chat"]) {
  if (!values[key]) throw new Error(`需要 --${key}`);
}
const target = resolve(values["runtime-chat"]), output = resolve(values.output);
const builds = { baseline: resolve(values.baseline), candidate: resolve(values.candidate) };
assert.ok(Object.values(builds).every(path => existsSync(resolve(path, "index.html"))));

// 一次性 fixture 身份：目标真实路径必须落在一个由本次运行创建、带隔离标记的
// workspace 内，并且与任何被测构建目录不相同、不互相嵌套。目录名后缀或
// localhost 都不构成隔离证明；resolve() 是词法解析，不解析符号链接。
const FIXTURE_MARKER = ".akashic-oneoff-fixture.json";

function isInside(child, parent) {
  return child === parent || child.startsWith(parent + sep);
}

function findFixtureMarker(start) {
  let directory = start;
  for (let depth = 0; depth < 8; depth += 1) {
    const candidate = resolve(directory, FIXTURE_MARKER);
    if (existsSync(candidate)) return candidate;
    const parent = dirname(directory);
    if (parent === directory) break;
    directory = parent;
  }
  return null;
}

const realTarget = realpathSync(target);
assert.ok(realTarget.endsWith("/plugins/akashic_clients/static/chat"),
  `runtime-chat 不是聊天静态目录: ${realTarget}`);
const realBuilds = Object.fromEntries(
  Object.entries(builds).map(([name, path]) => [name, realpathSync(path)]));
assert.ok(Object.values(realBuilds).every(path => path !== realTarget),
  "runtime-chat 不能就是被测构建目录");
assert.ok(Object.values(realBuilds).every(path => !isInside(realTarget, path) && !isInside(path, realTarget)),
  "runtime-chat 与被测构建目录不得互相嵌套");

const marker = findFixtureMarker(realTarget);
assert.ok(marker, `缺少一次性 fixture 隔离标记 ${FIXTURE_MARKER}: ${realTarget}`);
let fixture;
try {
  fixture = JSON.parse(readFileSync(marker, "utf8"));
} catch (error) {
  throw new Error(`隔离标记不可读: ${marker}: ${error.message}`);
}
assert.equal(fixture.kind, "akashic-webui-oneoff", "隔离标记类型不符");
assert.ok(typeof fixture.workspace === "string" && fixture.workspace, "隔离标记缺少 workspace");
assert.ok(isInside(realTarget, realpathSync(fixture.workspace)),
  `runtime-chat 不属于该隔离标记声明的 workspace: ${realTarget}`);
const profiles = values.profiles.split(","), runs = Number(values.runs);
assert.ok(Number.isSafeInteger(runs) && runs > 0);
assert.ok(profiles.every(name => ["lan", "latency", "limited"].includes(name)));
mkdirSync(output, { recursive: false });
// 恢复目的地同样受隔离约束：不得与目标或被测构建目录互相嵌套。
const realOutput = realpathSync(output);
assert.ok(!isInside(realOutput, realTarget) && !isInside(realTarget, realOutput),
  "output 目录不得与 runtime-chat 互相嵌套");
assert.ok(Object.values(realBuilds).every(path => !isInside(realOutput, path) && !isInside(path, realOutput)),
  "output 目录不得与被测构建目录互相嵌套");
const recovery = resolve(output, "starting-chat");
cpSync(target, recovery, { recursive: true });
const report = { plannedSamples: runs * profiles.length * 4, complete: false, builds, target,
  affinity: process.platform === "linux" ? readFileSync("/proc/self/status", "utf8").match(/^Cpus_allowed_list:.*$/mu)?.[0] : null,
  pairs: [], summary: {} };
const save = () => writeFileSync(resolve(output, "report.json"), JSON.stringify(report, null, 2));
const reports = new Map(), artifacts = {}, rows = [];
let frozen;

function copyBuild(source) {
  execFileSync("rsync", ["-a", "--delete", `${source}/`, `${target}/`]);
  function normalize(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = resolve(directory, entry.name);
      if (entry.isDirectory()) normalize(path);
      else utimesSync(path, 1767225600, 1767225600);
    }
  }
  normalize(target);
}

try {
  // 1. 每轮旋转网络顺序，A/B 顺序交替；不在采样期间构建或换代 Runtime。
  for (let run = 0; run < runs; run++) {
    for (let offset = 0; offset < profiles.length; offset++) {
      const profile = profiles[(run + offset) % profiles.length];
      const order = (run + offset) % 2 ? ["candidate", "baseline"] : ["baseline", "candidate"];
      const pair = { run, profile, order, reports: {} };
      report.pairs.push(pair);
      for (const kind of order) {
        copyBuild(builds[kind]);
        const directory = resolve(output, `${run}-${profile}-${kind}`);
        const beforeLoad = loadavg();
        const child = spawnSync(process.execPath, ["scripts/webui-performance/measure-startup.mjs",
          "--url", values.url, "--browser", values.browser, "--output", directory,
          "--runs", "1", "--profiles", profile, "--label", kind], { encoding: "utf8" });
        writeFileSync(`${directory}.log`, `${child.stdout ?? ""}${child.stderr ?? ""}`);
        if (child.error) throw child.error;
        const result = JSON.parse(readFileSync(resolve(directory, "report.json"), "utf8"));
        assert.ok(result.summary, `采样未完成：${directory}`);
        const inputs = [result.harnessSha256, result.lockSha256, result.bootstrapSha256,
          result.entrySha256, result.browserVersion];
        if (!frozen) frozen = inputs;
        else assert.deepEqual(inputs, frozen, "基准输入在采样期间变化");
        if (!artifacts[kind]) artifacts[kind] = result.chatEntrySha256;
        else assert.equal(result.chatEntrySha256, artifacts[kind], "聊天制品在采样期间变化");
        pair.reports[kind] = { directory, beforeLoad, afterLoad: loadavg(), exitCode: child.status };
        reports.set(`${run}/${profile}/${kind}`, result);
        rows.push(...result.runs);
        console.log(JSON.stringify({ run, profile, kind, results: result.runs.map(row => ({
          cache: row.cache, readyMs: row.readyMs, sockets: row.sockets, success: row.success,
        })) }));
        save();
      }
    }
  }
  // 2. 所有计划样本进入分母；同时报告整体中位数和每对变化的中位数。
  const median = nums => [...nums].sort((a, b) => a - b)[Math.floor(nums.length / 2)];
  for (const profile of profiles) for (const cache of ["cold", "warm"]) {
    const pairs = Array.from({ length: runs }, (_, run) => Object.fromEntries(["baseline", "candidate"].map(kind =>
      [kind, reports.get(`${run}/${profile}/${kind}`).runs.find(row => row.cache === cache)])));
    const passed = pairs.every(pair => pair.baseline.success && pair.candidate.success);
    report.summary[`${profile}/${cache}`] = {
      baselineMs: passed ? median(pairs.map(pair => pair.baseline.readyMs)) : null,
      candidateMs: passed ? median(pairs.map(pair => pair.candidate.readyMs)) : null,
      pairedChangeMs: passed ? median(pairs.map(pair => pair.candidate.readyMs - pair.baseline.readyMs)) : null,
      pairedChangePct: passed ? median(pairs.map(pair => (pair.candidate.readyMs / pair.baseline.readyMs - 1) * 100)) : null,
      baselineSockets: median(pairs.map(pair => pair.baseline.sockets)),
      candidateSockets: median(pairs.map(pair => pair.candidate.sockets)),
      successes: pairs.filter(pair => pair.baseline.success && pair.candidate.success).length,
      pairs: runs,
    };
  }
  report.complete = true;
  report.artifacts = artifacts;
  report.frozenInputs = frozen;
  save();
  console.log(JSON.stringify(report.summary, null, 2));
  if (rows.some(row => !row.success)) process.exitCode = 1;
} finally {
  // 不覆盖正式目录；仅恢复本次隔离服务进入实验前的构建。
  execFileSync("rsync", ["-a", "--delete", `${recovery}/`, `${target}/`]);
}
