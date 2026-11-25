// 댓글 연상 및 자동화 프로젝트 — 화면 동작
"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  limits: { min_chars: 40, max_chars: 120, daily_max: 10, posted_today: 0, remaining: 10 },
  brand: "운명원",
  videos: [],
  selected: null,
  analysis: null,
  opened: false,
  risingRule: { min_views: 1000, max_views: 5000, min_vph: 150 },
};

// ---------- 공통 ----------

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `요청 실패 (${res.status})`);
  return body;
}

let toastTimer;
function toast(message, bad = false) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("bad", bad);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
}

function timeAgo(iso) {
  if (!iso) return "";
  const hours = (Date.now() - new Date(iso)) / 36e5;
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))}분 전`;
  if (hours < 24) return `${Math.round(hours)}시간 전`;
  return `${Math.round(hours / 24)}일 전`;
}

const nf = new Intl.NumberFormat("ko-KR");

// 채널명이 길면 시각·조회수가 잘린다. 판단에 더 필요한 건 숫자 쪽이다.
function shortChannel(name) {
  const s = String(name || "").replace(/\s*\[[^\]]*\]\s*/g, "").trim();
  return s.length > 9 ? s.slice(0, 9) + "…" : s;
}

// 목록이 좁으므로 큰 수는 만 단위로 줄인다 (27,326 -> 2.7만)
function views(n) {
  if (!n) return "";
  if (n >= 10000) {
    const man = n / 10000;
    return `${man >= 100 ? Math.round(man) : man.toFixed(1)}만회`;
  }
  return `${nf.format(n)}회`;
}

// ---------- 오늘 게시 칸 ----------
// 하루 상한만큼 칸을 그려두고, 게시한 수만큼 색을 채운다.

function renderTally(done, max) {
  let html = "";
  for (let i = 0; i < max; i++) {
    html += `<span class="cell${i < done ? " on" : ""}"></span>`;
  }
  $("tallyMarks").innerHTML = html;
  $("tallyMarks").setAttribute("aria-label", `오늘 ${done}개 게시, 상한 ${max}개`);
  $("tallyNum").textContent = done;
  $("tally").querySelector(".tally__of").textContent = `/${max}`;
  $("tally").classList.toggle("full", done >= max);
}

// ---------- 상태 ----------

// 계정 고르기 또는 자동 배정 (가점). 게시 방식에 따라 필요한 준비물이 달라서
// (자동 입력 게시 → 크롬 프로필, API → 인증 토큰) 방식이 바뀔 때마다 다시 그린다.
function profileReady(p, method) {
  return method === "api" ? p.has_token : p.has_browser;
}

function renderProfileSelect() {
  const sel = $("profileSelect");
  const method = $("methodSelect").value;
  const prev = sel.value || "auto";
  const next = state.nextProfile?.[method];
  const auto = next
    ? `<option value="auto">자동 배정 (영상마다 돌아가며) — 다음: ${escapeHtml(next)}</option>`
    : `<option value="auto" disabled>자동 배정 — 준비된 계정 없음</option>`;
  const each = (state.profiles || []).map((p) => {
    const ok = profileReady(p, method);
    return `<option value="${escapeHtml(p.name)}"${ok ? "" : " disabled"}>${escapeHtml(p.name)}${ok ? "" : " (준비 안 됨)"}</option>`;
  }).join("");
  sel.innerHTML = auto + each;
  const still = [...sel.options].find((o) => o.value === prev && !o.disabled);
  sel.value = still ? prev : (next ? "auto" : (sel.querySelector("option:not([disabled])")?.value || ""));
}

async function loadState() {
  const s = await api("/api/state");
  state.limits = s.limits;
  state.brand = s.brand;
  if (s.rising_rule) state.risingRule = s.rising_rule;

  renderTally(s.limits.posted_today, s.limits.daily_max);
  $("brandLine").textContent =
    `영상 속 연애 고민을 읽고, ${s.brand}으로 이어지는 댓글을 자동으로 남깁니다.`;
  // 모델 이름은 화면에 내지 않는다. 키가 없어 데모로 돌 때만 알린다.
  const flag = $("aiFlag");
  flag.hidden = !s.ai_is_demo;
  flag.textContent = "데모 데이터";

  state.profiles = s.profiles;
  state.nextProfile = s.next_profile;
  renderProfileSelect();

  $("postMeta").textContent = `오늘 ${s.limits.remaining}개 남음`;

  if (!s.channels_configured) {
    $("listMeta").textContent = "채널 미설정";
  }
  await loadLedger();
}

// ---------- 1. 영상 ----------

function renderVideos(all) {
  const list = $("videoList");
  const onlyDating = $("onlyDating").checked;
  const videos = sortVideos(onlyDating ? all.filter((v) => v.on_topic) : all);

  const rr = state.risingRule;
  const risingTip = `조회수 ${nf.format(rr.min_views)}~${nf.format(rr.max_views)}회이면서 `
    + `시간당 ${nf.format(rr.min_vph)}회 이상 (올라온 뒤 평균)`;

  const off = all.filter((v) => !v.on_topic).length;
  $("sieve").hidden = all.length === 0;
  $("sieveCount").textContent = off ? `(${off}개 숨김)` : "(숨긴 것 없음)";

  if (!videos.length) {
    list.innerHTML = `<p class="empty">${all.length ? "연애 주제 영상이 없습니다. 위 체크를 해제하면 전체가 보입니다." : "가져온 영상이 없습니다."}</p>`;
    return;
  }
  list.innerHTML = videos.map((v) => {
    const flags = [];
    if (v.rising) flags.push(
      `<span class="flag flag--rising" title="${escapeHtml(risingTip)}">뜨는 중 · 시간당 ${nf.format(Math.round(v.views_per_hour))}회</span>`);
    if (v.commented) flags.push(`<span class="flag flag--done">작성함</span>`);
    if (v.draft_only) flags.push(`<span class="flag flag--off" title="과제 기준: 뜨기 직전 영상은 초안까지만">초안 전용</span>`);
    if (!v.on_topic) flags.push(`<span class="flag flag--off">${escapeHtml(v.topic_label)}</span>`);
    return `
      <button class="row${v.on_topic ? "" : " row--off"}" role="option" aria-selected="${v.video_id === state.selected?.video_id}" data-id="${v.video_id}">
        <span class="row__thumb"><img src="${v.thumbnail}" alt="" loading="lazy"></span>
        <span>
          <span class="row__title">${escapeHtml(v.title)}</span>
          <span class="row__meta">${[escapeHtml(shortChannel(v.channel)), timeAgo(v.published), views(v.views)].filter(Boolean).join(" · ")}</span>
          ${flags.join(" ")}
        </span>
      </button>`;
  }).join("");

  list.querySelectorAll(".row").forEach((row) => {
    row.addEventListener("click", () => selectVideo(row.dataset.id));
  });
}

// 정렬. 링크로 직접 넣은 영상은 날짜·조회수를 모르므로(published 없음) 항상 맨 위에 둔다.
const SORTERS = {
  date: (a, b) => new Date(b.published) - new Date(a.published),
  views: (a, b) => b.views - a.views,
  vph: (a, b) => b.views_per_hour - a.views_per_hour,
};

function sortVideos(list) {
  const cmp = SORTERS[$("sortBy").value] || SORTERS.date;
  const linked = list.filter((v) => !v.published);
  const rest = list.filter((v) => v.published).sort(cmp);
  return [...linked, ...rest];
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function refreshVideos() {
  const btn = $("btnRefresh");
  btn.disabled = true;
  btn.textContent = "불러오는 중…";
  try {
    const data = await api("/api/videos/refresh", { method: "POST" });
    $("sortBy").value = "date";       // 채널 목록은 최신순이 기본
    $("onlyDating").checked = true;
    state.videos = data.videos;
    renderVideos(data.videos);
    const shown = data.videos.length - (data.off_topic_count || 0);
    $("listMeta").textContent = `${shown}/${data.videos.length}개 · 뜨는 중 ${data.rising_count}`;
    if (data.errors.length) {
      toast(`${data.errors.length}개 채널을 가져오지 못했습니다`, true);
    }
  } catch (e) {
    $("videoList").innerHTML = `<p class="empty">${escapeHtml(e.message)}</p>`;
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "영상 불러오기";
  }
}

// 가점: '연애' 키워드로 뜨기 직전 영상 찾기 (유튜브 전체 검색, 초안까지만)
async function findRising() {
  const btn = $("btnRising");
  btn.disabled = true;
  btn.textContent = "찾는 중…";
  try {
    const data = await api("/api/videos/rising", { method: "POST" });
    state.videos = data.videos;
    $("sortBy").value = "vph";        // 뜨는 속도 순으로 보여준다
    $("onlyDating").checked = false;  // 이미 '연애' 키워드로 찾은 결과다
    renderVideos(data.videos);
    const rr = state.risingRule;
    $("listMeta").textContent =
      `'${data.keyword}' ${data.hours}시간 내 ${data.searched}개 중 ${data.videos.length}개`;
    if (!data.videos.length) {
      $("videoList").innerHTML = `<p class="empty">지금은 기준(조회수 ${nf.format(rr.min_views)}~${nf.format(rr.max_views)}회 · 시간당 ${nf.format(rr.min_vph)}회 이상)에 맞는 영상이 없습니다. 잠시 뒤 다시 찾아보세요.</p>`;
    } else {
      toast(`뜨기 직전 영상 ${data.videos.length}개를 찾았습니다 (초안까지만)`);
    }
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "뜨는 연애 영상 찾기";
  }
}

// 게시 버튼을 막아야 하는 이유. 없으면 빈 문자열.
function postBlockReason(video) {
  if (!video) return "영상을 고르세요";
  if (video.commented) return "이 영상에는 이미 댓글을 달았습니다 (영상당 1개)";
  if (video.draft_only) return "키워드 검색으로 찾은 영상은 초안까지만 만듭니다 (과제 기준)";
  if (state.draftOk === false) return "초안이 규칙을 어겼습니다. STEP 2의 ✕ 항목을 고쳐주세요";
  return "";
}

function syncPostButton() {
  const reason = postBlockReason(state.selected);
  $("btnPost").disabled = Boolean(reason);
  if (state.selected && reason) {
    $("postNote").textContent = reason;
  } else {
    updateStepLabels();   // 기본 안내 문구로 되돌린다
  }
}

// ---------- 2. 분석 ----------

async function selectVideo(videoId) {
  const video = state.videos.find((v) => v.video_id === videoId);
  if (!video) return;
  state.selected = video;
  state.opened = false;
  state.draftOk = null;   // 새 영상의 초안 검사 결과가 올 때까지 판단 보류

  document.querySelectorAll(".row").forEach((r) => {
    r.setAttribute("aria-selected", String(r.dataset.id === videoId));
  });

  $("workEmpty").hidden = true;
  $("work").hidden = true;
  $("workLoading").hidden = false;
  $("workMeta").textContent = "읽는 중";
  resetSteps();
  $("btnPost").disabled = true;
  $("result").hidden = true;

  try {
    const a = await api(`/api/analyze/${videoId}`);
    state.analysis = a;
    showAnalysis(video, a);
  } catch (e) {
    $("workLoading").hidden = true;
    $("workEmpty").hidden = false;
    $("workEmpty").textContent = e.message;
    toast(e.message, true);
  }
}

function showAnalysis(video, a) {
  $("workLoading").hidden = true;
  $("work").hidden = false;

  $("chosenThumb").src = video.thumbnail;
  $("chosenTitle").textContent = video.title;
  $("chosenSub").textContent =
    [video.channel, timeAgo(video.published), views(video.views)].filter(Boolean).join(" · ");

  $("concern").textContent = a.concern;
  const basis = $("concernBasis");
  basis.hidden = false;
  basis.textContent = a.ai_error
    ? "AI 초안 실패 · 임시 문구"
    : a.is_demo
    ? (a.transcript.available ? "데모 · 제목 기반" : "데모 · 자막 없음")
    : a.transcript.available ? "자막 전체를 읽음"
    : a.watched_video ? "AI가 영상을 직접 봄"
    : "자막 없음 · 제목·설명 기반";

  if (a.quote) {
    // 시각이 없으면 자막에서 온 대목이 아니다 (제목·설명 기반)
    $("quoteTime").textContent = a.quote_timestamp || "근거";
    $("quoteBox").classList.toggle("quote--noscene", !a.quote_timestamp);
    // 자막 원문 인용과 AI가 영상에서 들은 말을 구분해 보여준다 (후자는 글자 대조 불가)
    $("quoteText").textContent = a.quote_source === "video"
      ? `"${a.quote}" — AI가 영상에서 들은 말`
      : `"${a.quote}"`;
    $("quoteBox").hidden = false;
  } else {
    $("quoteBox").hidden = true;
  }

  const t = a.transcript;
  $("workMeta").textContent = t.available
    ? `자막 ${t.language}${t.is_generated ? " (자동)" : ""} · ${t.snippets}줄`
    : a.watched_video ? "자막 대신 AI가 영상을 직접 보고 작성"
    : "자막 없음 — 제목·설명으로 작성";

  renderSource(a);
  renderTopComments(a);

  $("draftText").value = a.draft;
  if (a.ai_error) {
    // AI 가 실패하면 초안 칸에는 임시 문구가 들어간다. 이유를 크게 알린다.
    $("workMeta").textContent = a.ai_error;
    toast(a.ai_error, true);
  }
  checkDraft();
  syncPostButton();
  setStep("open");
}

// AI가 실제로 읽은 자막. 인용한 줄은 표시해 둔다.
function renderSource(a) {
  const box = $("sourceBox");
  const lines = a.transcript.lines || [];
  if (!lines.length) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  $("sourceCount").textContent =
    `${a.transcript.snippets}줄 중 ${lines.length}줄`;
  let marked = false;
  $("sourceLines").innerHTML = lines.map((l) => {
    const cited = !marked && a.quote && l.text.trim() === a.quote.trim();
    if (cited) marked = true;  // 같은 대사가 반복되면 첫 줄만 표시
    return `<p class="source__line${cited ? " cited" : ""}">
      <time>${escapeHtml(l.t)}</time><span>${escapeHtml(l.text)}</span></p>`;
  }).join("");
}

// AI가 함께 읽은 인기 댓글. 못 가져왔으면 이유를 보여준다.
function renderTopComments(a) {
  const tc = a.top_comments || { items: [], error: null };
  const items = tc.items || [];
  $("commentsCount").textContent = items.length
    ? `${items.length}개`
    : tc.error
      ? `— 못 가져옴 (${tc.error})`
      : "— 아직 공개된 댓글이 없는 영상 (자막만으로 작성)";
  $("commentsLines").innerHTML = items.map((c) =>
    `<p class="source__line"><time>♥ ${nf.format(c.likes)}</time><span>${escapeHtml(c.text)}</span></p>`
  ).join("");
}

let checkTimer;
function checkDraftSoon() {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(checkDraft, 250);
}

async function checkDraft() {
  const text = $("draftText").value;
  const n = text.trim().length;
  const { min_chars, max_chars } = state.limits;

  const counter = $("counter");
  counter.textContent = `${n}자 / ${min_chars}~${max_chars}`;
  counter.classList.toggle("bad", n < min_chars || n > max_chars);

  try {
    const r = await api("/api/validate", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    renderChecks(r);
  } catch (e) {
    // 검사 실패는 치명적이지 않다
  }
}

function renderChecks(r) {
  // 통과했을 때는 아무것도 띄우지 않는다. 어긴 규칙과 경고만 보여준다.
  // 어긴 게 있으면 게시 버튼도 끈다 (서버도 한 번 더 막는다).
  state.draftOk = r.ok;
  syncPostButton();
  const items = [];
  r.errors.forEach((e) =>
    items.push(`<li><span class="mark bad">✕</span><span>${escapeHtml(e)}</span></li>`));
  r.warnings.forEach((w) =>
    items.push(`<li><span class="mark warn">!</span><span>${escapeHtml(w)}</span></li>`));
  $("checks").innerHTML = items.join("");
}

// ---------- 3. 게시 ----------

function resetSteps() {
  document.querySelectorAll(".steps li").forEach((li) => {
    li.classList.remove("done", "active");
  });
}

function setStep(name) {
  const order = ["open", "post", "confirm", "log"];
  const idx = order.indexOf(name);
  document.querySelectorAll(".steps li").forEach((li, i) => {
    li.classList.toggle("done", i < idx);
    li.classList.toggle("active", i === idx);
  });
}

// 진행 단계 이름. 게시 방식에 따라 두 번째 단계 문구만 다르다.
const POST_STEP_LABEL = {
  typing: "입력 중",
  api: "게시 중 (API)",
};

function updateStepLabels() {
  const method = $("methodSelect").value;
  document.querySelector('.steps li[data-step="post"]').textContent = POST_STEP_LABEL[method];
  $("postNote").textContent = method === "typing"
    ? "버튼을 누르면 계정의 크롬 창이 열리고, 댓글 창에 한 글자씩 자동으로 입력해 게시한 뒤 내 댓글을 확인합니다."
    : "버튼을 누르면 계정의 크롬 창이 열리고, 유튜브 공식 API로 바로 게시한 뒤 내 댓글로 이동합니다.";
}

function postBody(video, profile) {
  return JSON.stringify({
    video_id: video.video_id,
    video_title: video.title,
    profile,
    text: $("draftText").value,
  });
}

// 공식 API: 창 열기 → 게시 → 그 댓글로 이동
async function runApiPost(video, profile) {
  setStep("open");
  await api("/api/open", { method: "POST", body: postBody(video, profile) });
  await pause(2500);   // 창이 뜨고 영상이 로드될 시간

  setStep("post");
  const r = await api("/api/post", { method: "POST", body: postBody(video, profile) });

  setStep("confirm");
  await api("/api/confirm", {
    method: "POST",
    body: JSON.stringify({ comment_url: r.comment_url, profile: r.profile }),
  });
  await pause(1200);
  return r;
}

// 브라우저 타이핑: 서버가 프로필 창에서 진행하고, 화면은 단계를 받아 와 표시한다
const JOB_STEP = { open: "open", typing: "post", submit: "post", verify: "confirm" };

async function runTypingPost(video, profile) {
  setStep("open");
  const { job_id, profile: used } = await api("/api/post-typing", { method: "POST", body: postBody(video, profile) });
  $("postMeta").textContent = `${used}로 진행 중`;
  for (;;) {
    await pause(500);
    const job = await api(`/api/jobs/${job_id}`);
    if (JOB_STEP[job.step]) setStep(JOB_STEP[job.step]);
    if (job.status === "done") return { profile: used, ...job.result };
    if (job.status === "failed") throw new Error(job.error || "게시 실패");
  }
}

async function postComment() {
  if (!state.selected) return;
  const btn = $("btnPost");
  const profile = $("profileSelect").value;
  const method = $("methodSelect").value;
  const video = state.selected;

  btn.disabled = true;
  btn.textContent = "진행 중…";
  $("methodSelect").disabled = true;
  $("result").hidden = true;
  resetSteps();

  try {
    const r = method === "typing"
      ? await runTypingPost(video, profile)
      : await runApiPost(video, profile);

    setStep("log");
    document.querySelectorAll(".steps li").forEach((li) => li.classList.add("done"));

    state.limits.posted_today = r.posted_today;
    state.limits.remaining = r.remaining;
    renderTally(r.posted_today, state.limits.daily_max);
    $("postMeta").textContent = `오늘 ${r.remaining}개 남음`;

    video.commented = true;
    renderVideos(state.videos);

    $("result").hidden = false;
    $("resultState").textContent = r.verified
      ? "게시 완료 · 내 댓글 확인됨"
      : (r.warnings && r.warnings[0]) || "게시했으나 공개 여부가 확인되지 않았습니다";
    $("resultState").className = "result__state" + (r.verified ? " ok" : " warn");
    const who = `${escapeHtml(r.profile || "")}${r.channel ? ` (${escapeHtml(r.channel)})` : ""}로 게시 · `;
    $("resultMeta").innerHTML =
      `${who}<a href="${escapeHtml(r.comment_url)}" target="_blank" rel="noopener">댓글 보기</a>`;

    toast(r.verified ? "댓글이 게시되고 확인됐습니다" : "게시했습니다 (확인 보류)");
    if (r.warnings && r.warnings.length) toast(r.warnings[0]);
    await loadState();
  } catch (e) {
    $("result").hidden = false;
    $("resultState").textContent = e.message;
    $("resultState").className = "result__state bad";
    $("resultMeta").textContent = "실패 이유와 화면 캡처를 기록에 남겼습니다";
    toast(e.message, true);
    await loadState();
  } finally {
    btn.textContent = "댓글 달기";
    $("methodSelect").disabled = false;
    syncPostButton();
  }
}

function pause(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function copyDraft(quiet = false) {
  const text = $("draftText").value;
  try {
    await navigator.clipboard.writeText(text);
    if (!quiet) toast("초안을 복사했습니다");
  } catch {
    if (!quiet) toast("복사하지 못했습니다. 직접 선택해 복사하세요.", true);
  }
}

// ---------- 대장 ----------

const STAMP = {
  posted: ["게시", ""],
  failed: ["실패", " stamp--failed"],
  draft: ["초안", " stamp--draft"],
  skipped: ["건너뜀", " stamp--draft"],
};

const METHOD_LABEL = { typing: "자동 입력 게시", api: "API 게시" };

// 기록에서 어느 계정이 달았는지 한눈에 보이게 계정마다 색을 다르게 한다
function accountChip(name) {
  const n = (String(name || "").match(/(\d+)$/) || [])[1] || "x";
  return `<span class="acct acct--${escapeHtml(n)}">${escapeHtml(name || "?")}</span>`;
}

async function loadLedger() {
  const { records } = await api("/api/log");
  $("ledgerCount").textContent = records.length ? `${records.length}건` : "";
  if (!records.length) {
    $("ledger").innerHTML = `<p class="empty empty--sm">아직 기록이 없습니다.</p>`;
    return;
  }
  $("ledger").innerHTML = records.map((r) => {
    const [label, cls] = STAMP[r.status] || STAMP.draft;
    const how = METHOD_LABEL[r.method] || "";
    const extra = [
      how,
      r.screenshot ? `<a class="entry__shot" href="${escapeHtml(r.screenshot)}" target="_blank" rel="noopener">화면 캡처</a>` : "",
    ].filter(Boolean).join(" · ");
    return `
      <div class="entry">
        <span class="entry__time">${escapeHtml(r.time)}</span>
        <span class="entry__title">${accountChip(r.profile)}${escapeHtml(r.video_title || r.video_id)}</span>
        <span class="stamp${cls}">${label}</span>
        <span class="entry__comment">${escapeHtml(r.comment)}</span>
        ${r.error ? `<span class="entry__error">사유: ${escapeHtml(r.error)}</span>` : ""}
        ${extra ? `<span class="entry__profile">${extra}</span>` : ""}
      </div>`;
  }).join("");
}

// ---------- 링크 직접 입력 ----------

async function addByLink(event) {
  event.preventDefault();
  const input = $("linkInput");
  const msg = $("linkMsg");
  msg.hidden = true;
  if (!input.value.trim()) return;

  try {
    const { video } = await api("/api/videos/by-link", {
      method: "POST",
      body: JSON.stringify({ url: input.value }),
    });
    if (!state.videos.some((v) => v.video_id === video.video_id)) {
      state.videos.unshift(video);
    }
    renderVideos(state.videos);
    $("listMeta").textContent = `${state.videos.length}개`;
    input.value = "";
    await selectVideo(video.video_id);
  } catch (e) {
    msg.textContent = e.message;
    msg.hidden = false;
  }
}

// ---------- 시작 ----------

$("btnRefresh").addEventListener("click", refreshVideos);
$("btnRising").addEventListener("click", findRising);
$("onlyDating").addEventListener("change", () => renderVideos(state.videos));
$("sortBy").addEventListener("change", () => renderVideos(state.videos));
$("linkForm").addEventListener("submit", addByLink);
$("draftText").addEventListener("input", checkDraftSoon);
$("btnCopy").addEventListener("click", () => copyDraft());
$("btnRegen").addEventListener("click", () => {
  if (state.selected) selectVideo(state.selected.video_id);
});
$("btnPost").addEventListener("click", postComment);
$("methodSelect").addEventListener("change", () => {
  renderProfileSelect();
  updateStepLabels();
  syncPostButton();
});
updateStepLabels();

loadState().catch((e) => toast(e.message, true));
