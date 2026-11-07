"use strict";
(() => {
  const TOKEN = document.querySelector('meta[name="shiftpatch-token"]').content;
  const ROOM = new URLSearchParams(location.search).get("room") || "local-demo";
  const $view = document.getElementById("view");
  let lang = localStorage.getItem("sp-lang") || "ko";
  let state = null;
  let timer = null;
  let actor = "minsu";
  let draft = null;

  // ------------------------------------------------------------ text
  const T = {
    ko: {
      nav_board: "담당 현황", nav_room: "시연 방", nav_import: "근무표 가져오기", nav_connect: "연결과 기록 방식",
      footer: "합성 예시 데이터 · 이 Mac(127.0.0.1)에서만 열리는 로컬 화면",
      land_kicker: "고객지원팀의 하루 근무 공백 조율",
      land_title: "11월 9일(월) 13–17시 담당자가 갑자기 빠졌다면",
      land_lede: "ShiftPatch는 팀 채팅방에서 동료들이 답한 가능 시간을 대체 근무안으로 묶고, 각자의 수락과 관리자 확정을 거쳐 담당 현황표에 반영하는 에이전트예요. 나중에 누가 또 빠지면 그 시간만 다시 비어 보입니다.",
      land_steps: ["동료가 채팅에 가능한 시간을 답합니다. 확실하지 않은 말은 에이전트가 먼저 되묻고요.",
                   "에이전트가 시간대별 대체안을 올리면 각자 자기 구간만 수락합니다.",
                   "관리자가 대체안을 확정하면 현황표와 CSV가 같은 판본으로 남습니다.",
                   "확정 뒤 누군가 못 나오게 되면 그 사람 시간만 미해결로 돌아갑니다."],
      land_who: "누가 쓰나요",
      who_lead: "팀 리드", who_lead_d: "초기 근무표를 올리고 대체안을 확정",
      who_staff: "직원", who_staff_d: "가능 시간 답하기, 자기 구간 수락·철회",
      who_agent: "에이전트", who_agent_d: "문장을 읽고 되묻기, 대체안 정리 — 확정은 사람이",
      land_start: "시작하려면 하루치 근무표가 필요해요",
      land_img: "근무표 이미지 올리기", land_csv: "CSV 올리기", land_sample: "합성 예시 CSV로 시작",
      land_note: "이 화면의 사람·근무·대화는 모두 합성 예시입니다. 실제 직원 시험이 아니에요.",
      scene_title: "채팅방에서는 이렇게",
      board_title: "고객지원 담당 현황", version: "판본", at: "반영",
      gap_none: "빈 시간이 없습니다", gap_has: "담당자가 없습니다",
      th_time: "시간", th_who: "담당", th_status: "상태",
      s_original: "원 근무", s_confirmed: "대체 확정", s_uncovered: "미해결", s_conflict: "중복 확인 필요",
      pend_wait: "수락 대기", pend_ok: "수락함",
      legend_orig: "원 근무", legend_conf: "대체 확정", legend_gap: "미해결", legend_pend: "대체안(확정 전)",
      proposals: "대체안", no_proposal: "아직 올라온 대체안이 없습니다. 동료가 가능한 시간을 답하면 여기에 생겨요.",
      history: "변경 기록", no_history: "아직 기록이 없습니다.",
      exports: "내보내기", csv: "CSV 내려받기", ics: "ICS(확정분만)", no_exports: "만든 파일이 없습니다.",
      export_fail: "파일을 만들지 못했습니다. 확정된 내용은 그대로입니다.",
      p_open: "확정 대기", p_confirmed: "확정됨", p_superseded: "새 안으로 대체",
      p_reopened: (r) => `앞서 확정 · ${r} 다시 모집`,
      carried: "이어받은 수락", step_accept: "본인 수락", step_confirm: "관리자 확정", step_cut: "이후 불가 통보",
      need_new: "비어 있는 시간은 새 대체안이 필요합니다.",
      dl_title: "채팅방에 전달되지 않은 답장",
      dl_failed: (n) => `ShiftPatch 답장 ${n}개가 채팅방에 전달되지 않았습니다. 근무 기록은 이미 반영돼 있고, 다시 보내도 기록은 바뀌지 않습니다.`,
      dl_waiting: (n) => `답장 ${n}개를 다시 보내는 중입니다. 앞선 답장이 전달될 때까지 뒤의 답장은 기다립니다.`,
      dl_retry: "답장 다시 보내기", dl_retried: (n) => `${n}개를 다시 보낼 차례에 넣었습니다.`,
      dl_in: (s) => `${s}초 뒤 다시 시도`,
      room_kind_local: "로컬 합성 시연 방", room_kind_switch: "Switch 방",
      avail: "가능하다고 답한 사람", no_avail: "가능 응답 없음",
      no_roster_title: "아직 근무표가 없습니다",
      no_roster_body: "초기 근무표를 등록하면 시간대별 담당과 빈 시간이 여기에 표시됩니다.",
      go_import: "근무표 가져오기",
      room_notice: "로컬 합성 시연 방입니다. Switch 연결이 아니며, 한 사람이 같은 Mac에서 네 개의 가상 계정을 번갈아 조작합니다.",
      room_clock: "시연 시각(가상)", as: "보내는 사람", send: "보내기", script: "시연 순서",
      script_hint: "누르면 입력창에 채워집니다. 보내기는 직접 누르세요.",
      room_empty: "아직 대화가 없습니다. 오른쪽 시연 순서에서 첫 메시지를 골라 보세요.",
      room_restart: "서버를 다시 시작하면 대화 원문은 사라집니다. 원문은 디스크에 저장하지 않고, 구조화된 기록만 남겨요.",
      reset: "시연 초기화", reset_q: "시연 방의 근무표·기록·파일 목록을 모두 지우고 처음 상태로 돌릴까요?",
      manager: "관리자",
      imp_title: "초기 근무표 가져오기",
      imp_lede: "한 날짜, 한 업무의 단순한 표를 지원합니다. 이미지는 이 Mac 안에서 Apple Vision으로 읽고, 검토가 끝나면 임시 파일을 지웁니다.",
      imp_img: "이미지 선택 (PNG·JPEG, 8MB 이하)", imp_csv: "CSV 선택 (name,date,start,end,duty)", imp_sample: "합성 예시 CSV",
      imp_reading: "이미지를 읽는 중… (처음 실행은 20초 정도 걸릴 수 있어요)",
      imp_locked: "조율이 이미 시작돼 근무표를 다시 가져올 수 없습니다. 진행 중인 기록을 덮어쓰지 않기 위해서예요.",
      src: "원본", extracted: "읽어낸 표 (고칠 수 있어요)", mapping: "이름과 계정 연결",
      map_hint: "같은 이름이라도 자동으로 연결하지 않습니다. 계정을 고르고 확인 표시를 해 주세요. 역할은 관리자 설정에서 정해집니다.",
      map_hint_switch: "목록의 ID는 이 Switch 방에서 해당 직원으로 행동할 참가자 ID입니다. manage.py import-links로 들여온 값이며 이 화면에서는 바꿀 수 없습니다.",
      map_hint_local: "로컬 시연 방의 계정은 고정된 합성 계정(local:…)입니다. 실제 채팅 계정이 아닙니다.",
      map_none: "연결 안 함", map_ok: "확인함", map_unlinked: "Switch 계정 연결 없음",
      imp_into: "가져올 방",
      checks: "확인할 항목", checks_none: "막는 항목이 없습니다.",
      approve_box: "날짜·시간·업무·직원 연결을 원본과 대조해 확인했습니다",
      approve: "초기 근무표 등록", discard: "버리기", revalidate: "다시 검사",
      imported: "초기 근무표를 등록했습니다.",
      unsupported: "이 표 모양은 아직 읽지 못합니다. 이름·날짜·시작·종료·업무 다섯 열 표이거나, CSV로 올려 주세요.",
      ocr_meta: "인식", score_note: "인식 점수는 정확도가 아니라 다시 볼 곳을 알려 주는 신호입니다.",
      con_title: "연결과 기록 방식",
      con_switch: "Switch 연결", con_ai: "AI 해석", con_ocr: "근무표 이미지 인식", con_data: "기록 방식",
      blocked: "막힘(BLOCKED)",
      data_points: ["대화 원문은 앱 디스크에 쓰지 않습니다. 구조화된 행동(누가·어느 시간·무엇)과 원본 메시지 ID만 남겨요.",
                    "사유는 묻지 않습니다. 채팅 원문은 채팅 플랫폼에 그대로 남고, AI 해석을 쓰면 해당 문장이 모델 제공자에게 전달됩니다.",
                    "현황표는 127.0.0.1에만 열립니다. 다른 직원 기기에서 여는 기능은 아직 없습니다.",
                    "CSV는 한 시점의 판본으로 만들고, 수식으로 실행될 수 있는 셀은 무력화합니다."],
    },
    en: {
      nav_board: "Coverage", nav_room: "Demo room", nav_import: "Import roster", nav_connect: "Connection & data",
      footer: "Synthetic example data · local screen, opens on this Mac (127.0.0.1) only",
      land_kicker: "Filling a sudden gap in one day's support shifts",
      land_title: "Minsu can't cover Monday 13:00–17:00",
      land_lede: "ShiftPatch is an agent in the team chat room. It turns colleagues' replies into a replacement proposal; each person accepts their own hours and the manager confirms. If someone drops out later, only their hours reopen.",
      land_steps: ["Colleagues reply with the hours they can take. Hedged wording gets a question first.",
                   "The agent posts a proposal by time slot; each person accepts only their own part.",
                   "The manager confirms, and the board and CSV share one version.",
                   "If someone cannot make it after confirmation, only their hours become uncovered."],
      land_who: "Who uses it",
      who_lead: "Team lead", who_lead_d: "imports the day's roster, confirms proposals",
      who_staff: "Staff", who_staff_d: "replies with hours, accepts or withdraws their own part",
      who_agent: "Agent", who_agent_d: "reads messages, asks back, drafts proposals — people decide",
      land_start: "Start with one day's roster",
      land_img: "Upload a roster image", land_csv: "Upload CSV", land_sample: "Start with the synthetic CSV",
      land_note: "Every person, shift and message here is synthetic. This is not a test with real staff.",
      scene_title: "In the chat room",
      board_title: "Support coverage", version: "version", at: "updated",
      gap_none: "No gaps", gap_has: "has nobody assigned",
      th_time: "Time", th_who: "Who", th_status: "Status",
      s_original: "original", s_confirmed: "confirmed", s_uncovered: "uncovered", s_conflict: "conflict",
      pend_wait: "waiting", pend_ok: "accepted",
      legend_orig: "original", legend_conf: "confirmed replacement", legend_gap: "uncovered", legend_pend: "proposal (not confirmed)",
      proposals: "Proposals", no_proposal: "No proposal yet. It appears when a colleague replies with hours they can take.",
      history: "History", no_history: "Nothing recorded yet.",
      exports: "Export", csv: "Download CSV", ics: "ICS (confirmed only)", no_exports: "No files yet.",
      export_fail: "Export failed. Confirmed coverage is unchanged.",
      p_open: "waiting for confirmation", p_confirmed: "confirmed", p_superseded: "replaced by a newer proposal",
      p_reopened: (r) => `confirmed earlier · ${r} reopened`,
      carried: "acceptance carried", step_accept: "accepted", step_confirm: "confirmed", step_cut: "later unavailable",
      need_new: "The reopened hours need a new proposal.",
      dl_title: "Replies that did not reach the chat room",
      dl_failed: (n) => `${n} ShiftPatch ${n === 1 ? "reply" : "replies"} did not reach the chat room. The record already changed; sending again does not change it.`,
      dl_waiting: (n) => `Retrying ${n} ${n === 1 ? "reply" : "replies"}. Later replies wait until the earlier one gets through.`,
      dl_retry: "Send replies again", dl_retried: (n) => `${n} queued to send again.`,
      dl_in: (s) => `next try in ${s} s`,
      room_kind_local: "Local synthetic demo room", room_kind_switch: "Switch room",
      avail: "Said they are available", no_avail: "no availability replies",
      no_roster_title: "No roster yet",
      no_roster_body: "Import the initial roster and this board shows who covers each interval and where the gap is.",
      go_import: "Import roster",
      room_notice: "Local synthetic demo room. This is not a Switch connection: one person operates four synthetic accounts on one Mac.",
      room_clock: "Demo clock (synthetic)", as: "Sending as", send: "Send", script: "Demo script",
      script_hint: "Click to fill the input. You press Send yourself.",
      room_empty: "No messages yet. Pick the first line from the demo script.",
      room_restart: "A server restart clears message text. Message bodies are not written to disk; only the structured record stays.",
      reset: "Reset demo", reset_q: "Clear the demo room's roster, history and file list?",
      manager: "manager",
      imp_title: "Import the initial roster",
      imp_lede: "One date, one duty, a simple table. Images are read on this Mac with Apple Vision; the temp file is removed after review.",
      imp_img: "Choose image (PNG/JPEG, up to 8 MB)", imp_csv: "Choose CSV (name,date,start,end,duty)", imp_sample: "Synthetic CSV",
      imp_reading: "Reading the image… (the first run can take about 20 seconds)",
      imp_locked: "Coordination has started, so the roster cannot be imported again. Live records are never overwritten.",
      src: "Source", extracted: "Extracted table (editable)", mapping: "Names and accounts",
      map_hint: "Matching names are never linked automatically. Pick an account and tick to confirm. Roles come from the manager's settings.",
      map_hint_switch: "The IDs listed are the Switch participants who will act as each person in this room. They come from manage.py import-links and cannot be changed here.",
      map_hint_local: "Local demo accounts are fixed synthetic accounts (local:…), not real chat accounts.",
      map_none: "not linked", map_ok: "confirmed", map_unlinked: "no Switch account linked",
      imp_into: "Importing into",
      checks: "To check", checks_none: "Nothing is blocking.",
      approve_box: "I checked dates, times, duty and account links against the source",
      approve: "Import initial roster", discard: "Discard", revalidate: "Check again",
      imported: "Initial roster imported.",
      unsupported: "This layout is not supported yet. Use a five-column table (name, date, start, end, duty) or upload CSV.",
      ocr_meta: "Recognition", score_note: "Recognition scores flag cells to re-check; they are not accuracy.",
      con_title: "Connection & data handling",
      con_switch: "Switch connection", con_ai: "AI reading", con_ocr: "Roster image recognition", con_data: "Data handling",
      blocked: "BLOCKED",
      data_points: ["Message text is not written to the app's disk. Only structured actions (who, which hours, what) and source message IDs are kept.",
                    "No reason is asked for. Chat text stays on the chat platform; with AI reading on, the sentence is sent to the model provider.",
                    "The board opens on 127.0.0.1 only. Opening it on other staff devices is not built.",
                    "CSV files are one frozen version, and formula-like cells are neutralised."],
    },
  };
  const t = (k) => (T[lang][k] !== undefined ? T[lang][k] : k);
  const ISSUE = {
    ko: {
      DATE_YEAR_OR_FORMAT_NEEDS_REVIEW: "날짜에 연도가 없거나 형식이 다릅니다 (예: 2026-11-09)",
      DATE_NOT_ROOM_DATE: "이 방의 날짜(2026-11-09)와 다릅니다",
      START_NEEDS_EXPLICIT_24H_TIME: "시작 시각을 24시 표기로 (예: 13:00)", END_NEEDS_EXPLICIT_24H_TIME: "종료 시각을 24시 표기로 (예: 17:00)",
      AMBIGUOUS_AM_PM: "오전·오후가 분명하지 않습니다", NON_POSITIVE_OR_OVERNIGHT: "종료가 시작보다 늦어야 합니다",
      NOT_30_MIN_BOUNDARY: "30분 단위가 아닙니다", DUTY_MISMATCH: "행마다 업무가 다릅니다 (한 업무만 지원)",
      UNMAPPED_NAME: "명단에 연결되지 않은 이름", MAPPING_NOT_CONFIRMED: "계정 연결을 확인하지 않았습니다",
      TWO_NAMES_ONE_ACCOUNT: "서로 다른 이름이 한 계정에 연결됐습니다", COLLISION: "다른 행과 시간이 겹칩니다",
      EMPTY_CELL: "빈 칸이 있습니다", OCR_SCORE_REVIEW_SIGNAL_NOT_ACCURACY: "인식 점수가 낮아 원본과 대조가 필요합니다",
      FORMULA_LIKE_TEXT: "수식처럼 보이는 글자 (내보낼 때 무력화)", NO_ROWS: "행이 없습니다",
      STAFF_HAS_NO_SWITCH_ACCOUNT: "이 직원에게 연결된 Switch 계정이 없습니다 (manage.py import-links 먼저)",
    },
    en: {
      DATE_YEAR_OR_FORMAT_NEEDS_REVIEW: "Date lacks a year or has another format (e.g. 2026-11-09)",
      DATE_NOT_ROOM_DATE: "Not this room's date (2026-11-09)",
      START_NEEDS_EXPLICIT_24H_TIME: "Start needs 24-hour time (e.g. 13:00)", END_NEEDS_EXPLICIT_24H_TIME: "End needs 24-hour time (e.g. 17:00)",
      AMBIGUOUS_AM_PM: "AM/PM is unclear", NON_POSITIVE_OR_OVERNIGHT: "End must be after start",
      NOT_30_MIN_BOUNDARY: "Not on a 30-minute boundary", DUTY_MISMATCH: "Rows have different duties (one duty supported)",
      UNMAPPED_NAME: "Name not linked to the staff list", MAPPING_NOT_CONFIRMED: "Account link not confirmed",
      TWO_NAMES_ONE_ACCOUNT: "Two names linked to one account", COLLISION: "Overlaps another row",
      EMPTY_CELL: "Empty cell", OCR_SCORE_REVIEW_SIGNAL_NOT_ACCURACY: "Low recognition score: compare with the source",
      FORMULA_LIKE_TEXT: "Looks like a formula (neutralised on export)", NO_ROWS: "No rows",
      STAFF_HAS_NO_SWITCH_ACCOUNT: "No Switch account is linked to this person (run manage.py import-links first)",
    },
  };
  const issueText = (c) => ISSUE[lang][c] || c;

  // ------------------------------------------------------------ dom helpers
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") n.className = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (k === "style") {
        for (const decl of v.split(";")) {
          const i = decl.indexOf(":");
          if (i > 0) n.style.setProperty(decl.slice(0, i).trim(), decl.slice(i + 1).trim());
        }
      }
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return n;
  }
  const hm = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  const rng = (s, e) => `${hm(s)}–${hm(e)}`;
  const nm = (o) => (lang === "en" ? o.name_en : o.name) || "—";
  const staffName = (id) => {
    const s = (state && state.staff || []).find((x) => x.staff_id === id);
    return s ? (lang === "en" ? s.display_name_en : s.display_name) : id;
  };
  // Subject particle from the last syllable's final consonant (지안이, 태오가); non-Hangul such as ShiftPatch reads with 가.
  const iga = (w) => { const c = w.charCodeAt(w.length - 1) - 0xac00; return w + (c >= 0 && c < 11172 && c % 28 ? "이" : "가"); };
  const WD = { ko: "일월화수목금토", en: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] };
  // The roster's duty text is Korean in the fixtures; show the English name on the English screen.
  const DUTY_EN = { "일반 고객문의 응대": "General customer support", "일반 문의": "General customer support" };
  const duty = (d) => (lang === "en" ? DUTY_EN[d] || d : d);
  const managerName = () => { const m = (state.staff || []).find((x) => x.role === "manager"); return m ? staffName(m.staff_id) : (lang === "en" ? "the manager" : "관리자"); };
  function roomBadge(s) {
    const local = s.room.kind === "local_demo";
    const conn = !local && s.switch && s.switch.room_id === s.room.room_id ? ` · ${s.switch.state}` : "";
    return el("span", { class: "tag" + (local ? "" : " okk"), title: s.room.room_id },
      (local ? t("room_kind_local") : `${t("room_kind_switch")} ${s.room.room_id.slice(0, 8)}…`) + conn);
  }
  function dateLabel(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
    return lang === "en" ? `${WD.en[wd]} ${m}/${d}` : `${m}/${d} ${WD.ko[wd]}`;
  }
  function clock(ms) {
    const d = new Date(ms + 9 * 3600e3);
    return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      method: opts.method || "GET",
      headers: { "X-ShiftPatch-Token": TOKEN, ...(opts.json ? { "Content-Type": "application/json" } : {}), ...(opts.headers || {}) },
      body: opts.json ? JSON.stringify(opts.json) : opts.body,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error(data.error || res.status), { data, status: res.status });
    return data;
  }
  async function load() {
    state = await api(`/api/state?room=${encodeURIComponent(ROOM)}`);
    return state;
  }

  // ------------------------------------------------------------ router
  function route() { return (location.hash.replace(/^#\//, "") || "").split("?")[0]; }
  async function render() {
    clearInterval(timer);
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
    document.querySelectorAll("[data-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
    let r = route();
    try { await load(); } catch (e) { $view.replaceChildren(el("p", { class: "err" }, String(e.message))); return; }
    const ready = state.room.roster_version > 0;
    if (!r) r = ready ? "board" : "welcome";
    document.querySelectorAll("[data-nav]").forEach((a) => { if (a.dataset.nav !== r) a.removeAttribute("aria-current"); else a.setAttribute("aria-current", "page"); });
    const views = { welcome: viewWelcome, board: viewBoard, room: viewRoom, import: viewImport, connect: viewConnect };
    (views[r] || viewBoard)();
    if (r === "board" || r === "room") {
      timer = setInterval(async () => {
        if (document.activeElement && document.activeElement.tagName === "INPUT") { await load(); patchLive(r); return; }
        await load(); patchLive(r);
      }, 1500);
    }
  }
  function patchLive(r) {
    const live = document.getElementById("live");
    if (r === "board" && live) live.replaceChildren(boardBody());
    if (r === "room") {
      const log = document.getElementById("chatlog");
      if (log) { const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40; log.replaceChildren(...chatItems()); if (atBottom) log.scrollTop = log.scrollHeight; }
      const side = document.getElementById("roomside");
      if (side) side.replaceChildren(roomSide());
    }
  }

  // ------------------------------------------------------------ welcome
  function viewWelcome() {
    const scene = lang === "en"
      ? [["Minsu", "@ShiftPatch I might be unable to cover Monday 13-17."], ["ShiftPatch", "Minsu, should I mark Mon 11/9 13:00–17:00 unavailable? Reply yes or no.", 1],
         ["Jian", "@ShiftPatch available 13-15"], ["Taeo", "@ShiftPatch available 15-17"], ["ShiftPatch", "New proposal P2: Jian 13:00–15:00, Taeo 15:00–17:00. Jian: accept P2-a · Taeo: accept P2-b", 1]]
      : [["민수", "@ShiftPatch 월요일 13~17시 못 할 것 같아요"], ["ShiftPatch", "민수님, 11/9(월) 13:00–17:00을 '불가'로 기록할까요? 맞으면 `네`라고 답해 주세요.", 1],
         ["지안", "@ShiftPatch 점심 먹고 두 시간은 돼요"], ["태오", "@ShiftPatch 가능 15-17"], ["ShiftPatch", "새 대체안 P2: 지안 13:00–15:00, 태오 15:00–17:00. 지안: 수락 P2-a · 태오: 수락 P2-b", 1]];
    $view.replaceChildren(el("section", { class: "landing" },
      el("div", {},
        el("p", { class: "muted" }, t("land_kicker")),
        el("h1", {}, t("land_title")),
        el("p", { class: "lede" }, t("land_lede")),
        el("ol", {}, t("land_steps").map((s) => el("li", {}, s))),
        el("h2", {}, t("land_start")),
        el("div", { class: "actions" },
          el("a", { class: "btn", href: "#/import?mode=image" }, t("land_img")),
          el("a", { class: "btn ghost", href: "#/import?mode=csv" }, t("land_csv")),
          el("button", { class: "btn ghost", type: "button", onclick: startSample }, t("land_sample"))),
        el("p", { class: "muted small", style: "margin-top:16px" }, t("land_note"))),
      el("aside", { class: "panel scene" },
        el("h3", {}, t("scene_title")),
        scene.map(([w, m, a]) => el("div", { class: "msg" + (a ? " agent" : "") }, el("b", {}, w), m)),
        el("h3", { style: "margin-top:20px" }, t("land_who")),
        el("dl", { class: "who" },
          el("dt", {}, t("who_lead")), el("dd", {}, t("who_lead_d")),
          el("dt", {}, t("who_staff")), el("dd", {}, t("who_staff_d")),
          el("dt", {}, t("who_agent")), el("dd", {}, t("who_agent_d"))))));
  }
  async function startSample() {
    draft = await api(`/api/roster/sample?room=${encodeURIComponent(ROOM)}`, { method: "POST", json: {} });
    location.hash = "#/import";
  }

  // ------------------------------------------------------------ board
  function viewBoard() {
    if (state.room.roster_version === 0) {
      $view.replaceChildren(el("section", { class: "panel" }, el("h1", {}, t("no_roster_title")), el("p", {}, t("no_roster_body")),
        el("a", { class: "btn", href: "#/import" }, t("go_import"))));
      return;
    }
    $view.replaceChildren(el("div", { id: "live" }, boardBody()));
  }
  function lastEventLine() {
    const h = state.history.find((x) => ["inability", "confirmed", "accepted", "availability", "proposal_created", "acceptance_revoked"].includes(x.kind));
    return h ? historyText(h) : null;
  }
  function boardBody() {
    const s = state;
    const gaps = s.gaps;
    const frag = el("div", { class: "stack" });
    frag.append(el("div", { class: "boardhead" },
      el("div", {}, el("div", { class: "muted" }, t("board_title") + " · " + duty(s.room.duty), " ", roomBadge(s)), el("div", { class: "date" }, dateLabel(s.room.date))),
      el("div", { class: "meta" }, el("div", { class: "ver" }, `${t("version")} #${s.room.version}`),
        el("div", {}, `${t("at")} ${clock(s.clock.now_ms)}${s.clock.synthetic ? (lang === "en" ? " (synthetic clock)" : " (가상 시각)") : ""}`))));
    const line = lastEventLine();
    if (gaps.length) {
      frag.append(el("div", { class: "banner gap", role: "status" },
        el("div", { class: "big num" }, gaps.map(([a, b]) => rng(a, b)).join(", ") + " " + t("gap_has")),
        line && el("p", {}, line),
        s.proposal ? el("p", {}, proposalSummary(s.proposal)) : el("p", {}, s.availability.length ? "" : (lang === "en" ? "Nobody has said they can take it yet." : "지금 이 시간을 맡을 수 있다고 답한 사람은 없습니다."))));
    } else {
      frag.append(el("div", { class: "banner clear", role: "status" }, el("div", { class: "big" }, t("gap_none")), line && el("p", {}, line)));
    }
    const dl = deliveryBox(s);
    if (dl) frag.append(dl);
    frag.append(el("section", { class: "panel" }, timeline(s), coverageTable(s)));
    frag.append(el("div", { class: "row" },
      el("section", { class: "panel grow" }, el("h2", {}, t("proposals")), proposalsList(s)),
      el("section", { class: "panel grow" }, el("h2", {}, t("history")), historyList(s))));
    frag.append(el("section", { class: "panel" }, exportsBox(s)));
    return frag;
  }
  function proposalSummary(p) {
    const parts = p.parts.map((x) => `${nm(x)} ${rng(x.start, x.end)} ${x.accepted ? "✓" : "…"}`).join(" · ");
    const waiting = p.parts.filter((x) => !x.accepted);
    const tail = waiting.length ? (lang === "en" ? `Waiting for ${waiting.map(nm).join(", ")} to accept.` : `${waiting.map(nm).join(", ")}님 수락 대기.`)
      : (lang === "en" ? `All accepted. Waiting for ${managerName()} to confirm.` : `모두 수락했습니다. ${managerName()}님이 확정하면 근무표에 반영됩니다.`);
    return `${p.proposal_id}: ${parts}. ${tail}`;
  }
  // Replies are delivered after the record changes. If the chat server keeps
  // refusing one, say so here; "send again" moves only the reply.
  function deliveryBox(s) {
    const rows = s.delivery || [];
    if (!rows.length) return null;
    const failed = rows.filter((r) => r.state === "failed");
    const waiting = rows.filter((r) => r.state === "pending");
    const msg = el("p", { class: "small", role: "status" });
    const retry = async () => {
      try { const r = await api(`/api/outbox/retry?room=${encodeURIComponent(ROOM)}`, { method: "POST", json: {} }); msg.textContent = t("dl_retried")(r.retried); }
      catch (e) { msg.textContent = String(e.message); }
      await load(); patchLive("board");
    };
    return el("section", { class: "panel delivery", id: "delivery" },
      el("h2", {}, t("dl_title")),
      failed.length ? el("p", { class: "err" }, t("dl_failed")(failed.length)) : null,
      waiting.length ? el("p", { class: "muted" }, t("dl_waiting")(waiting.length)) : null,
      el("ul", { class: "small" }, rows.map((r) => el("li", {},
        el("span", { class: "tag" + (r.state === "failed" ? " warn" : "") }, r.state === "failed" ? "failed" : t("dl_in")(Math.ceil((r.retry_in_ms || 0) / 1000))),
        " ", el("span", {}, r.excerpt), " ", el("span", { class: "muted num" }, `· ${r.attempts}× · ${r.last_error || ""}`)))),
      failed.length ? el("button", { class: "btn", type: "button", onclick: retry }, t("dl_retry")) : null, msg);
  }
  function timeline(s) {
    const cov = s.coverage;
    const lo = Math.min(...cov.map((c) => c.start)), hi = Math.max(...cov.map((c) => c.end));
    const pct = (m) => ((m - lo) / (hi - lo)) * 100;
    const track = el("div", { class: "track", role: "img", "aria-label": cov.map((c) => `${rng(c.start, c.end)} ${c.name ? nm(c) : "—"} ${t("s_" + c.status)}`).join("; ") });
    for (const c of cov) {
      track.append(el("div", { class: `seg ${c.status}`, style: `left:${pct(c.start)}%;width:${pct(c.end) - pct(c.start)}%`, title: `${rng(c.start, c.end)} ${t("s_" + c.status)}` },
        el("span", { class: "nm" }, c.status === "uncovered" ? t("s_uncovered") : nm(c)), el("span", { class: "rg num" }, rng(c.start, c.end))));
    }
    const pend = el("div", { class: "pendrow" });
    if (s.proposal) for (const p of s.proposal.parts) {
      pend.append(el("div", { class: "pend" + (p.accepted ? " accepted" : ""), style: `left:${pct(p.start)}%;width:${pct(p.end) - pct(p.start)}%` },
        el("b", {}, p.part_id), nm(p), " ", p.accepted ? t("pend_ok") : t("pend_wait")));
    }
    const ticks = el("div", { class: "ticks" });
    for (let m = Math.ceil(lo / 60) * 60; m <= hi; m += 60) ticks.append(el("span", { class: "tick", style: `left:${pct(m)}%` }, String(m / 60).padStart(2, "0")));
    return el("div", { class: "timeline" }, track, s.proposal ? pend : null, ticks,
      el("div", { class: "legend" }, el("span", {}, el("i", { class: "l-orig" }), t("legend_orig")), el("span", {}, el("i", { class: "l-conf" }), t("legend_conf")),
        el("span", {}, el("i", { class: "l-gap" }), t("legend_gap")), el("span", {}, el("i", { class: "l-pend" }), t("legend_pend"))));
  }
  function coverageTable(s) {
    return el("table", { style: "margin-top:20px" },
      el("thead", {}, el("tr", {}, el("th", {}, t("th_time")), el("th", {}, t("th_who")), el("th", {}, t("th_status")))),
      el("tbody", {}, s.coverage.map((c) => el("tr", { class: c.status },
        el("td", { class: "t" }, rng(c.start, c.end)), el("td", { class: "assignee" }, c.status === "uncovered" ? "—" : nm(c)),
        el("td", {}, el("span", { class: `st ${c.status}` }, t("s_" + c.status)),
          c.pending && c.pending.length ? el("span", { class: "muted small" }, " · " + c.pending.map((p) => `${p.part_id} ${nm(p)} ${p.accepted ? t("pend_ok") : t("pend_wait")}`).join(", ")) : null)))));
  }
  function proposalsList(s) {
    if (!s.proposals.length) return el("p", { class: "muted" }, t("no_proposal"));
    // A confirmed proposal stays "confirmed" in history; what changed since is
    // derived from its cuts and shown next to it, not written over it.
    return el("div", {}, s.proposals.map((p) => el("div", { class: `prop ${p.state}` },
      el("h3", {}, p.proposal_id, el("span", { class: "tag" + (p.state === "open" ? " warn" : p.state === "confirmed" ? " okk" : "") }, t("p_" + p.state)),
        p.state === "confirmed" && (p.cuts || []).length ? el("span", { class: "tag warn reopened" }, t("p_reopened")(p.cuts.map((c) => rng(c.start, c.end)).join(", "))) : null),
      el("ul", {}, p.parts.map((x) => {
        const cut = (p.cuts || []).some((c) => c.staff_id === x.staff_id && c.start < x.end && x.start < c.end);
        const steps = [x.accepted || x.confirmed ? t("step_accept") : t("pend_wait")];
        if (x.confirmed) steps.push(t("step_confirm"));
        if (cut) steps.push(t("step_cut"));
        return el("li", {}, el("b", {}, x.part_id), el("span", {}, nm(x)), el("span", { class: "num" }, rng(x.start, x.end)),
          el("span", { class: "steps" }, steps.join(" → ")),
          x.carried_from ? el("span", { class: "tag" }, `${t("carried")} ← ${x.carried_from}`) : null);
      })),
      (p.cuts || []).length ? el("p", { class: "small muted", style: "margin:6px 0 0" }, t("need_new")) : null)));
  }
  function historyText(h) {
    const d = h.detail, who = h.actor_staff ? staffName(h.actor_staff) : "ShiftPatch";
    const en = lang === "en";
    switch (h.kind) {
      case "roster_imported": return en ? `${who} imported the initial roster (${d.rows} rows, ${d.source})` : `${iga(who)} 초기 근무표 등록 (${d.rows}행, ${d.source})`;
      case "availability": return en ? `${who} available ${rng(d.start, d.end)}` : `${who} ${rng(d.start, d.end)} 가능`;
      case "availability_withdrawn": {
        const r = d.start !== undefined && d.start !== null ? " " + rng(d.start, d.end) : "";
        return en ? `${who} withdrew availability${r}` : `${who}${r} 가능 기록 철회`;
      }
      case "links_changed": return en ? `Chat account changed for ${d.staff.map(staffName).join(", ")}${d.closed_questions.length ? "; closed " + d.closed_questions.join(", ") : ""}`
        : `${d.staff.map(staffName).join(", ")} 채팅 계정 변경${d.closed_questions.length ? " — " + d.closed_questions.join(", ") + " 확인 닫음" : ""}`;
      case "inability": return en ? `${who} cannot do ${rng(d.start, d.end)}` : `${who}의 ${rng(d.start, d.end)} 불가 반영`;
      case "proposal_created": return (en ? `Proposal ${d.proposal_id}: ` : `대체안 ${d.proposal_id}: `) + d.parts.map((p) => `${staffName(p.staff_id)} ${rng(p.start, p.end)}`).join(", ") + (d.carried && d.carried.length ? (en ? " (acceptance carried)" : " (수락 이어받음)") : "");
      case "proposal_superseded": return en ? `Proposal ${d.proposal_id} replaced` : `대체안 ${d.proposal_id} 새 안으로 대체`;
      case "accepted": return en ? `${who} accepted ${d.part_id} ${rng(d.start, d.end)}` : `${iga(who)} ${d.part_id} ${rng(d.start, d.end)} 수락`;
      case "acceptance_revoked": return en ? `${who} withdrew acceptance of ${d.part_id}` : `${iga(who)} ${d.part_id} 수락 취소`;
      case "confirmed": return en ? `${who} confirmed ${d.proposal_id}` : `${iga(who)} ${d.proposal_id} 확정`;
      case "confirm_rejected": {
        const why = {
          ALREADY_CONFIRMED_CHANGED: ["re-confirm of an older plan refused, state unchanged", "이전 대체안 재확정 거부, 상태 유지"],
          ALREADY_CONFIRMED: ["already confirmed, nothing changed", "이미 확정됨, 변경 없음"],
          ACCEPTANCE_MISSING: ["confirmation on hold until every part is accepted", "확정 보류 — 본인 수락이 다 모이지 않음"],
          PROPOSAL_STALE: ["confirmation refused, facts changed", "확정 거부 — 조건이 달라짐"],
          NOT_MANAGER: ["confirmation refused, not the manager", "확정 거부 — 관리자만 확정"],
        }[d.reason] || [d.reason, d.reason];
        return `${d.proposal_id || ""} ${en ? why[0] : why[1]}`.trim();
      }
      case "exported": return en ? `${d.fmt.toUpperCase()} created from version #${d.snapshot_version}` : `판본 #${d.snapshot_version} ${d.fmt.toUpperCase()} 생성`;
      default: return h.kind;
    }
  }
  function historyList(s) {
    if (!s.history.length) return el("p", { class: "muted" }, t("no_history"));
    return el("ul", { class: "hist" }, s.history.map((h) => el("li", {}, el("time", {}, clock(h.at_ms)),
      el("span", { class: h.kind === "confirm_rejected" ? "rej" : "" }, historyText(h)))));
  }
  function exportsBox(s) {
    const msg = el("p", { class: "err", role: "alert" });
    const doExport = (kind) => async () => {
      msg.textContent = "";
      try { const r = await api(`/api/export?room=${encodeURIComponent(ROOM)}`, { method: "POST", json: { kind } }); if (!r.ok) msg.textContent = t("export_fail"); await load(); patchLive("board"); }
      catch (e) { msg.textContent = t("export_fail"); }
    };
    return el("div", { class: "exports" },
      el("div", { class: "boardhead" }, el("h2", {}, t("exports")),
        el("div", { class: "actions" }, el("button", { class: "btn", type: "button", onclick: doExport("csv") }, t("csv")),
          el("button", { class: "btn ghost", type: "button", onclick: doExport("ics") }, t("ics")))),
      msg,
      s.exports.length ? el("ul", {}, s.exports.map((x) => el("li", {},
        x.state === "published" ? el("a", { href: `/exports/${x.file_name}` }, x.file_name) : el("span", { class: "err" }, `${x.kind} ${t("export_fail")}`),
        el("span", { class: "muted num" }, `#${x.version} · ${clock(x.created_ms + 0)}`)))) : el("p", { class: "muted" }, t("no_exports")));
  }

  // ------------------------------------------------------------ demo room
  const ACTORS = ["seoyeon", "minsu", "jian", "taeo"];
  // Lines that need a proposal or part ID stay disabled until the agent has
  // posted one, so the script never shows a placeholder like "P?-?".
  function scriptLines() {
    const p = state.proposal || state.proposals[0];
    const part = (who) => (p && p.parts.find((x) => x.staff_id === who) || {}).part_id || null;
    const pid = p ? p.proposal_id : null;
    const confirmed = state.proposals.find((x) => x.state === "confirmed");
    const old = confirmed ? confirmed.proposal_id : pid;
    const en = lang === "en";
    const L = (who, text, need) => [who, need === null ? null : text, need === null ? (en ? "after the proposal reply" : "대체안 답장이 온 뒤") : null];
    if (en) return [
      L("minsu", "@ShiftPatch I might be unable to cover Monday 13-17"), L("minsu", "@ShiftPatch yes"),
      L("jian", "@ShiftPatch I can do two hours after lunch"), L("jian", "@ShiftPatch yes"),
      L("taeo", "@ShiftPatch available 2026-11-09 15:00-17:00"),
      L("jian", `@ShiftPatch accept ${part("jian")}`, part("jian")), L("taeo", `@ShiftPatch accept ${part("taeo")}`, part("taeo")),
      L("seoyeon", "@ShiftPatch both of them said yes"), L("seoyeon", `@ShiftPatch confirm ${pid}`, pid),
      L("seoyeon", "@ShiftPatch export"), L("jian", "@ShiftPatch unavailable 2026-11-09 13:00-15:00"),
      L("seoyeon", `@ShiftPatch confirm ${old}`, old), L("seoyeon", "@ShiftPatch status")];
    return [
      L("minsu", "@ShiftPatch 월요일 13~17시 고객문의 응대 못 할 것 같아요"), L("minsu", "@ShiftPatch 네"),
      L("jian", "@ShiftPatch 점심 먹고 두 시간은 돼요"), L("jian", "@ShiftPatch 네"),
      L("taeo", "@ShiftPatch 가능 2026-11-09 15:00-17:00"),
      L("jian", `@ShiftPatch 수락 ${part("jian")}`, part("jian")), L("taeo", `@ShiftPatch 수락 ${part("taeo")}`, part("taeo")),
      L("seoyeon", "@ShiftPatch 둘 다 된대요"), L("seoyeon", `@ShiftPatch 확정 ${pid}`, pid),
      L("seoyeon", "@ShiftPatch 내보내기"), L("jian", "@ShiftPatch 불가 2026-11-09 13:00-15:00"),
      L("seoyeon", `@ShiftPatch 확정 ${old}`, old), L("seoyeon", "@ShiftPatch 표")];
  }
  function chatItems() {
    const msgs = state.transcript || [];
    if (!msgs.length) return [el("p", { class: "empty" }, t("room_empty"))];
    return msgs.map((m) => el("div", { class: "bubble " + m.kind },
      el("div", { class: "by" }, m.kind === "agent" ? "ShiftPatch" : staffName(m.who), " · ", el("time", {}, clock(m.at))),
      el("div", { class: "tx" }, m.body)));
  }
  function viewRoom() {
    if (state.room.roster_version === 0) { viewBoard(); return; }
    if (state.room.kind !== "local_demo") {
      $view.replaceChildren(el("p", { class: "notice" }, lang === "en"
        ? "This is a Switch room. People write in the Switch room itself; this screen has no actor picker for it."
        : "Switch 방입니다. 메시지는 Switch 방에서 직접 보내야 하며, 이 화면에서 대신 보낼 수 없습니다."));
      return;
    }
    const input = el("input", { type: "text", value: "@ShiftPatch ", "aria-label": "message", id: "msg", maxlength: "1000" });
    const actorBox = el("div", { class: "actors", role: "group", "aria-label": t("as") });
    const drawActors = () => actorBox.replaceChildren(el("span", { class: "muted small", style: "align-self:center" }, t("as")),
      ...ACTORS.map((a) => el("button", { type: "button", "aria-pressed": String(a === actor), onclick: () => { actor = a; drawActors(); input.focus(); } },
        staffName(a) + (a === "seoyeon" ? ` (${t("manager")})` : ""))));
    drawActors();
    const status = el("p", { class: "err small", role: "alert" });
    const send = async (ev) => {
      ev && ev.preventDefault();
      const body = input.value.trim();
      if (!body || body === "@ShiftPatch") return;
      status.textContent = "";
      try { await api(`/api/demo/message?room=${encodeURIComponent(ROOM)}`, { method: "POST", json: { actor, body } }); input.value = "@ShiftPatch "; }
      catch (e) { status.textContent = e.message; }
      await load(); patchLive("room");
    };
    const log = el("div", { class: "log", id: "chatlog", "aria-live": "polite" }, ...chatItems());
    $view.replaceChildren(
      el("p", { class: "notice" }, t("room_notice"), " ", el("span", { class: "muted" }, `${t("room_clock")}: ${state.clock.label}`)),
      el("div", { class: "room" },
        el("section", { class: "chat" }, log,
          el("form", { class: "compose", onsubmit: send }, actorBox, el("div", { class: "sendrow" }, input, el("button", { class: "btn", type: "submit" }, t("send"))), status)),
        el("aside", { id: "roomside" }, roomSide())));
    log.scrollTop = log.scrollHeight;
    window.__fill = (who, text) => { actor = who; drawActors(); input.value = text; input.focus(); };
  }
  function roomSide() {
    const s = state;
    return el("div", { class: "stack" },
      el("section", { class: "panel" },
        el("div", { class: "boardhead" }, el("h2", {}, dateLabel(s.room.date)), el("span", { class: "ver muted" }, `${t("version")} #${s.room.version}`)),
        s.gaps.length ? el("p", { class: "err" }, s.gaps.map(([a, b]) => rng(a, b)).join(", ") + " " + t("gap_has")) : el("p", { style: "color:var(--ok);font-weight:600" }, t("gap_none")),
        timeline(s),
        el("p", { class: "small muted" }, el("a", { href: "#/board" }, t("nav_board") + " →"))),
      el("section", { class: "panel" }, el("h3", {}, t("script")), el("p", { class: "small muted" }, t("script_hint")),
        el("ol", { class: "script" }, scriptLines().map(([who, text, later], i) => el("li", {}, el("span", { class: "n" }, i + 1),
          text ? el("button", { type: "button", onclick: () => window.__fill(who, text) }, `${staffName(who)}: ${text.replace("@ShiftPatch ", "")}`)
            : el("button", { type: "button", disabled: true }, `${staffName(who)}: ${later}`)))),
        el("p", { class: "small muted", style: "margin-top:12px" }, t("room_restart")),
        el("button", { class: "btn ghost", type: "button", onclick: async () => { if (confirm(t("reset_q"))) { await api("/api/demo/reset", { method: "POST", json: {} }); location.hash = "#/"; render(); } } }, t("reset"))));
  }

  // ------------------------------------------------------------ import / review
  function viewImport() {
    const locked = state.room.events_started;
    const msg = el("p", { class: "err", role: "alert" });
    const reading = el("p", { class: "muted", hidden: true }, t("imp_reading"));
    const imgInput = el("input", { type: "file", accept: "image/png,image/jpeg", id: "imgfile" });
    const csvInput = el("input", { type: "file", accept: ".csv,text/csv", id: "csvfile" });
    imgInput.addEventListener("change", async () => {
      const f = imgInput.files[0]; if (!f) return;
      msg.textContent = ""; reading.hidden = false;
      try { draft = await api(`/api/roster/image?room=${encodeURIComponent(ROOM)}`, { method: "POST", body: f, headers: { "Content-Type": f.type || "application/octet-stream" } }); drawReview(); }
      catch (e) { msg.textContent = issueText(e.message) + (lang === "en" ? "" : ""); }
      finally { reading.hidden = true; }
    });
    csvInput.addEventListener("change", async () => {
      const f = csvInput.files[0]; if (!f) return;
      msg.textContent = "";
      try { draft = await api(`/api/roster/csv?room=${encodeURIComponent(ROOM)}`, { method: "POST", body: f, headers: { "Content-Type": "text/csv" } }); drawReview(); }
      catch (e) { msg.textContent = e.message; }
    });
    const reviewHost = el("div", { id: "review" });
    $view.replaceChildren(el("div", { class: "stack" },
      el("section", {}, el("h1", {}, t("imp_title")), el("p", { class: "muted" }, t("imp_lede")),
        el("p", { class: "small" }, t("imp_into") + ": ", roomBadge(state))),
      locked ? el("section", { class: "panel" }, el("p", { class: "err" }, t("imp_locked"))) :
        el("section", { class: "panel" },
          el("div", { class: "row" },
            el("label", { class: "drop grow" }, el("div", { style: "font-weight:600;margin-bottom:8px" }, t("imp_img")), imgInput),
            el("label", { class: "drop grow" }, el("div", { style: "font-weight:600;margin-bottom:8px" }, t("imp_csv")), csvInput)),
          el("div", { class: "actions", style: "margin-top:12px" }, el("button", { class: "btn ghost", type: "button", onclick: async () => { draft = await api(`/api/roster/sample?room=${encodeURIComponent(ROOM)}`, { method: "POST", json: {} }); drawReview(); } }, t("imp_sample"))),
          reading, msg),
      reviewHost));
    if (draft && !locked) drawReview();
  }
  function drawReview() {
    const host = document.getElementById("review");
    if (!host || !draft) return;
    const d = draft;
    if (d.status === "UNSUPPORTED_LAYOUT") {
      host.replaceChildren(el("section", { class: "panel" }, el("p", { class: "err" }, t("unsupported")),
        d.has_image ? el("div", { class: "src", style: "max-width:520px" }, el("img", { src: `/api/roster/draft/${d.draft_id}/image`, alt: t("src") })) : null,
        el("button", { class: "btn ghost", type: "button", onclick: discardDraft }, t("discard"))));
      return;
    }
    const fields = ["name", "date", "start", "end", "duty"];
    const head = lang === "en" ? ["Name", "Date", "Start", "End", "Duty"] : ["이름", "날짜", "시작", "종료", "업무"];
    const srcBox = d.has_image ? el("div", { class: "src" }, el("img", { src: `/api/roster/draft/${d.draft_id}/image`, alt: t("src") })) : null;
    if (srcBox) d.rows.forEach((r, i) => fields.forEach((f) => {
      const c = r.cells && r.cells[f]; if (!c) return;
      const b = c.bbox;
      srcBox.append(el("div", { class: "box" + (c.confidence < 0.8 ? " low" : ""), id: `box-${i}-${f}`,
        style: `left:${b.x * 100}%;top:${(1 - b.y - b.height) * 100}%;width:${b.width * 100}%;height:${b.height * 100}%` }));
    }));
    const grid = el("table", { class: "grid" }, el("thead", {}, el("tr", {}, head.map((h) => el("th", {}, h)))),
      el("tbody", {}, d.rows.map((r, i) => el("tr", {}, fields.map((f) => el("td", {},
        el("input", { value: r[f], "data-row": i, "data-field": f, "aria-label": `${head[fields.indexOf(f)]} ${i + 1}`,
          class: (d.row_issues[i] || []).some((x) => fieldOf(x) === f) ? "bad" : "",
          onfocus: () => { const bx = document.getElementById(`box-${i}-${f}`); bx && bx.classList.add("hl"); },
          onblur: () => { const bx = document.getElementById(`box-${i}-${f}`); bx && bx.classList.remove("hl"); },
          onchange: (e) => { d.rows[i][f] = e.target.value; } })))))));
    const names = [...new Set(d.rows.map((r) => r.name).filter(Boolean))];
    const mapBox = el("div", {}, names.map((n) => {
      const sel = el("select", { "aria-label": `${n} account`, onchange: (e) => { d.mapping[n] = e.target.value || null; revalidate(); } },
        el("option", { value: "" }, t("map_none")),
        // The label is the account that will really act as this person in the draft's room.
        d.directory.map((u) => el("option", { value: u.staff_id, selected: d.mapping[n] === u.staff_id, disabled: !u.account },
          `${lang === "en" ? u.name_en : u.name} · ${u.account || t("map_unlinked")}${u.role === "manager" ? " (" + t("manager") + ")" : ""}`)));
      const cb = el("input", { type: "checkbox", checked: d.confirmed.includes(n), "aria-label": `${n} ${t("map_ok")}`,
        onchange: (e) => { d.confirmed = e.target.checked ? [...new Set([...d.confirmed, n])] : d.confirmed.filter((x) => x !== n); revalidate(); } });
      return el("div", { class: "maprow" }, el("span", { class: "src-name" }, n), el("span", { class: "muted" }, "→"), sel, el("label", {}, cb, " ", t("map_ok")));
    }));
    // One line per row, blocking items first; start/end time notes merged.
    const blockingSet = new Set(d.blocking);
    const lines = [];
    if (d.global_issues.length) lines.push([null, d.global_issues]);
    d.row_issues.forEach((ri, i) => { if (ri.length) lines.push([i, ri]); });
    const merge = (codes) => {
      const cs = codes.filter((c) => c !== "END_NEEDS_EXPLICIT_24H_TIME" || !codes.includes("START_NEEDS_EXPLICIT_24H_TIME"));
      return cs.sort((a, b) => blockingSet.has(b) - blockingSet.has(a)).map((c) =>
        c === "START_NEEDS_EXPLICIT_24H_TIME" && codes.includes("END_NEEDS_EXPLICIT_24H_TIME")
          ? (lang === "en" ? "Start and end need 24-hour time (e.g. 13:00)" : "시작·종료를 24시 표기로 (예: 13:00)") : issueText(c));
    };
    const checks = lines.length ? el("ul", { class: "checks" }, lines.map(([i, codes]) => el("li", {},
      el("span", { class: "tag" + (codes.some((c) => blockingSet.has(c)) ? " warn" : "") },
        i === null ? (lang === "en" ? "table" : "표 전체") : (lang === "en" ? `row ${i + 1}` : `${i + 1}행`)),
      el("span", {}, merge(codes).join(" · "))))) : el("p", { class: "muted" }, t("checks_none"));
    const approveBox = el("input", { type: "checkbox", id: "approve" });
    const approveBtn = el("button", { class: "btn", type: "button", disabled: d.blocking.length > 0 }, t("approve"));
    const out = el("p", { role: "alert" });
    approveBtn.addEventListener("click", async () => {
      out.textContent = "";
      if (!approveBox.checked) { out.className = "err"; out.textContent = t("approve_box"); return; }
      try {
        await api(`/api/roster/draft/${d.draft_id}/approve`, { method: "POST", json: { rows: d.rows, mapping: d.mapping, confirmed: d.confirmed, approved: true } });
        draft = null; out.className = ""; location.hash = "#/board";
      } catch (e) { out.className = "err"; out.textContent = (e.data && e.data.issues ? e.data.issues.map(issueText).join(", ") : e.message); }
    });
    host.replaceChildren(el("section", { class: "panel stack" },
      el("div", { class: "review" },
        srcBox ? el("div", {}, el("h3", {}, t("src")), srcBox,
          el("p", { class: "small muted", style: "margin-top:8px" }, `${t("ocr_meta")}: ${d.engine || ""} · ${d.width}×${d.height}px · ${d.seconds}s. ${t("score_note")}`)) : null,
        el("div", {}, el("h3", {}, t("extracted")), grid,
          el("div", { class: "actions", style: "margin-top:8px" }, el("button", { class: "btn ghost", type: "button", onclick: revalidate }, t("revalidate"))))),
      el("div", {}, el("h3", {}, t("mapping")), el("p", { class: "small muted" }, t("map_hint")),
        el("p", { class: "small muted" }, d.room_kind === "switch" ? t("map_hint_switch") : t("map_hint_local")), mapBox),
      el("div", {}, el("h3", {}, t("checks")), checks),
      el("div", { class: "actions", style: "align-items:center" }, el("label", {}, approveBox, " ", t("approve_box")), approveBtn,
        el("button", { class: "btn ghost", type: "button", onclick: discardDraft }, t("discard"))), out));
  }
  function fieldOf(issue) {
    if (issue.startsWith("DATE")) return "date";
    if (issue.startsWith("START")) return "start";
    if (issue.startsWith("END")) return "end";
    if (issue === "UNMAPPED_NAME" || issue === "MAPPING_NOT_CONFIRMED" || issue === "FORMULA_LIKE_TEXT") return "name";
    if (issue === "AMBIGUOUS_AM_PM" || issue === "COLLISION" || issue === "NON_POSITIVE_OR_OVERNIGHT") return "start";
    return null;
  }
  async function revalidate() {
    document.querySelectorAll("#review input[data-row]").forEach((n) => { draft.rows[+n.dataset.row][n.dataset.field] = n.value; });
    const v = await api(`/api/roster/draft/${draft.draft_id}/validate`, { method: "POST", json: { rows: draft.rows, mapping: draft.mapping, confirmed: draft.confirmed } });
    draft = v; drawReview();
  }
  async function discardDraft() {
    if (draft) await api(`/api/roster/draft/${draft.draft_id}/discard`, { method: "POST", json: {} }).catch(() => {});
    draft = null; const host = document.getElementById("review"); host && host.replaceChildren();
  }

  // ------------------------------------------------------------ connect
  function viewConnect() {
    const sw = state.switch, ai = state.ai;
    const reasons = { docker_not_found: lang === "en" ? "Docker is not installed on this Mac (Switch runs its local server in Docker)" : "이 Mac에 Docker가 없습니다 (Switch 로컬 서버는 Docker로 실행)",
      docker_unverified: lang === "en" ? "A Docker CLI is on PATH, but no running Switch server has been verified" : "Docker 명령은 있지만 실행 중인 Switch 서버는 확인되지 않았습니다",
      no_server_url: lang === "en" ? "No Switch server address configured" : "Switch 서버 주소가 설정되지 않았습니다",
      no_agent_credential: lang === "en" ? "No agent id / API key configured" : "에이전트 ID·API 키가 설정되지 않았습니다",
      no_room_id: lang === "en" ? "No room id configured" : "방 ID가 설정되지 않았습니다" };
    $view.replaceChildren(el("div", { class: "stack" }, el("h1", {}, t("con_title")),
      el("section", { class: "panel" }, el("h2", {}, t("con_switch")),
        sw.state === "BLOCKED" ? el("div", {},
          el("p", {}, el("span", { class: "tag warn" }, t("blocked")), " ", lang === "en" ? "This instance has no Switch configuration, so the bridge is off." : "이 인스턴스에는 Switch 설정이 없어 연결이 꺼져 있어요."),
          el("ul", {}, sw.reasons.map((r) => el("li", {}, reasons[r] || r))),
          el("p", { class: "small muted" }, lang === "en" ? "The adapter has run against a local self-hosted Switch 0.31 server with a synthetic team (qa/LIVE_SWITCH_REPORT.md). Setup steps: README › Switch." : "어댑터는 로컬 자체 호스팅 Switch 0.31 서버에서 합성 팀으로 실행해 봤어요(qa/LIVE_SWITCH_REPORT.md). 설정 방법은 README의 Switch 절에 있어요."))
          : el("dl", { class: "kv" }, Object.entries(sw).map(([k, v]) => [el("dt", {}, k), el("dd", { class: "num" }, typeof v === "object" ? JSON.stringify(v) : String(v))]).flat())),
      el("section", { class: "panel" }, el("h2", {}, t("con_ai")),
        el("dl", { class: "kv" }, el("dt", {}, "status"), el("dd", {}, ai.enabled ? `${ai.engine} · ${ai.model_alias} · ${ai.status}` : (lang === "en" ? "unavailable — exact commands and rule-based questions still work" : "꺼짐 — 정확한 명령과 규칙 기반 확인 질문은 계속 동작")),
          el("dt", {}, lang === "en" ? "what it may do" : "할 수 있는 일"), el("dd", {}, lang === "en" ? "suggest one action for the sender; the sender must reply yes before anything changes" : "보낸 사람 본인의 행동 하나를 제안 — 본인이 `네`라고 답해야 반영"),
          el("dt", {}, lang === "en" ? "limits" : "제한"), el("dd", {}, lang === "en" ? "no tools, JSON schema output, 45 s timeout, 2 at a time, no session saved" : "도구 없음, JSON 스키마 출력, 45초 제한, 동시 2개, 세션 저장 안 함"))),
      el("section", { class: "panel" }, el("h2", {}, t("con_ocr")),
        el("p", {}, lang === "en" ? "Apple Vision VNRecognizeTextRequest via the local Swift helper (ocr/roster_ocr.swift). Five fixed columns, one date, one duty. Photos with perspective, handwriting and merged cells are not verified." : "로컬 Swift 보조 프로그램(ocr/roster_ocr.swift)의 Apple Vision VNRecognizeTextRequest. 다섯 열 고정, 한 날짜·한 업무. 기울어진 사진·손글씨·병합 셀은 검증하지 않았습니다.")),
      el("section", { class: "panel" }, el("h2", {}, t("con_data")), el("ul", {}, t("data_points").map((x) => el("li", {}, x))))));
  }

  // ------------------------------------------------------------ boot
  document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => { lang = b.dataset.lang; localStorage.setItem("sp-lang", lang); render(); }));
  window.addEventListener("hashchange", () => {
    if (route() === "import" && location.hash.includes("mode=")) { render(); return; }
    render();
  });
  render();
})();
