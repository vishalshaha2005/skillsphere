const app = document.querySelector("#app");
const API = "/api";
const STATUSES = ["Applied", "Under Review", "Shortlisted", "Assessment Sent", "Assessment Started", "Assessment Completed", "Round 1 Passed", "Round 1 Failed", "Interview", "Accepted", "Rejected"];
const demoPassword = "Demo123!";

const state = {
  token: "",
  theme: window.SkillSphereTheme.get(),
  user: null,
  page: "Dashboard",
  jobs: [],
  applications: [],
  resume: null,
  analytics: null,
  adminJobs: [],
  match: null,
  query: "",
  location: "",
  jobType: "",
  experience: "",
  skill: "",
  sortBy: "newest",
  jobPage: 1,
  jobTotal: 0,
  modal: "",
  busy: false,
  interviews: [],
  upcomingInterviews: [],
  editingInterview: null,
  activeInterview: null,
  scheduleCandidate: "",
  interviewCode: "",
  interviewLanguage: "python",
  interviewStdin: "",
  interviewSocket: null,
  interviewReconnect: false,
  codeTimer: null,
  runResult: null,
  notifications: [],
  notificationUnread: 0,
  notificationsLoading: false,
  notificationsError: "",
  assessments: [],
  assessmentFilters: {},
  questionJobId: "",
  jobQuestions: [],
  questionBankSummary: null,
  questionBankImports: [],
  questionImportPreview: null,
  editingQuestion: null,
  assessmentReview: null,
  proctoringReview: null,
  proctoringData: null,
  proctoringFilters: {},
  analyticsRange: "this_week"
};

const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[char]);
const initials = name => String(name || "S").split(/\s+/).slice(0, 2).map(part => part[0] || "").join("").toUpperCase();
const dateLabel = value => value ? new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "Recently";
const iconPaths = {
  home: '<path d="m3 10 9-7 9 7"/><path d="M5 9v11h14V9M9 20v-6h6v6"/>',
  search: '<circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4.5 4.5"/>',
  files: '<path d="M8 7V4h12v14h-3"/><rect x="4" y="7" width="12" height="14" rx="2"/><path d="M7 11h6M7 15h6"/>',
  user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>',
  briefcase: '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V4h8v3M3 12h18M10 12v2h4v-2"/>',
  users: '<path d="M16 20v-1.5a4.5 4.5 0 0 0-4.5-4.5h-3A4.5 4.5 0 0 0 4 18.5V20"/><circle cx="10" cy="7.5" r="3.5"/><path d="M16 4.5a3.5 3.5 0 0 1 0 6.8M17 14h.5a4.5 4.5 0 0 1 4.5 4.5V20"/>',
  building: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M9 21v-4h6v4M8 7h1m6 0h1M8 11h1m6 0h1"/>',
  video: '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="m16 10 5-3v10l-5-3z"/>',
  clipboard: '<rect x="5" y="5" width="14" height="16" rx="2"/><path d="M9 5.5V4h6v1.5M8 10h8m-8 4h8m-8 4h5"/>',
  fileCheck: '<path d="M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10z"/><path d="M13 3v7h7m-12 5 2 2 4-4"/>',
  sparkles: '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z"/><path d="m19 14 .9 2.1L22 17l-2.1.9L19 20l-.9-2.1L16 17l2.1-.9L19 14z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/>',
  moon: '<path d="M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  logout: '<path d="M10 17l5-5-5-5m5 5H3"/><path d="M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6"/>',
  upload: '<path d="M12 16V4m-5 5 5-5 5 5"/><path d="M5 14v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5"/>',
  arrowUpRight: '<path d="M7 17 17 7M8 7h9v9"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/>'
};
const iconSvg = (name, className = "") => `<svg class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${iconPaths[name] || iconPaths.sparkles}</svg>`;
const icon = (name, label = "") => `<span class="nav-icon">${iconSvg(name)}</span>${label ? `<span>${label}</span>` : ""}`;

function themeToggle() {
  const nextTheme = state.theme === "dark" ? "light" : "dark";
  const iconName = nextTheme === "dark" ? "moon" : "sun";
  return `<button class="icon-button theme-toggle" type="button" data-action="toggle-theme" aria-label="Switch to ${nextTheme} mode" aria-pressed="${state.theme === "dark"}" title="Switch to ${nextTheme} mode">${iconSvg(iconName)}</button>`;
}

function syncThemeToggle() {
  state.theme = window.SkillSphereTheme.get();
  document.querySelectorAll(".theme-toggle").forEach(button => {
    const nextTheme = state.theme === "dark" ? "light" : "dark";
    const iconName = nextTheme === "dark" ? "moon" : "sun";
    button.setAttribute("aria-label", `Switch to ${nextTheme} mode`);
    button.setAttribute("aria-pressed", String(state.theme === "dark"));
    button.title = `Switch to ${nextTheme} mode`;
    button.innerHTML = iconSvg(iconName);
  });
}

window.addEventListener("storage", event => {
  if (event.key === "skillsphere_theme") syncThemeToggle();
});

function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name.replace(/[.$?*|{}()[\]^+\\]/g, "\\$&")}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : "";
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  const method = String(options.method || "GET").toUpperCase();
  const csrfToken = getCookie("skillsphere_csrf");
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method) && !headers.has("Authorization") && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API}${path}`, { ...options, headers, credentials: "same-origin" });
  let payload = {};
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

function showToast(message, error = false) {
  document.querySelector(".toast")?.remove();
  const toast = document.createElement("div");
  toast.className = `toast${error ? " error" : ""}`;
  toast.setAttribute("role", "status");
  const text = document.createElement("span");
  text.textContent = message;
  toast.append(text);
  document.body.append(toast);
  setTimeout(() => toast.remove(), 3500);
}

function saveToken(token) {
  state.token = token || "";
}

function renderAuth(register = false) {
  app.innerHTML = `
    <main class="auth-page">
      ${themeToggle()}
      <section class="auth-copy">
        <a class="brand" href="#" aria-label="SkillSphere home"><span class="brand-mark">${iconSvg("sparkles")}</span><span>SkillSphere</span></a>
        <span class="eyebrow">A better kind of career platform</span>
        <h1>Find work that <em>feels right.</em></h1>
        <p>Bring your experience, discover opportunities that fit, and make your next move with confidence.</p>
        <div class="auth-note">${iconSvg("checkCircle")} Thoughtful matches. Real opportunities. One place.</div>
        <div class="preview-card" aria-hidden="true">
          <div class="preview-head"><strong>Your next move, made clearer</strong><span class="badge badge-green">Good fit</span></div>
          <div class="preview-lines"><span class="preview-line red"></span><span class="preview-line"></span><span class="preview-line"></span><span class="preview-line" style="width:72%"></span></div>
          <div class="preview-job"><strong>Product Designer · Northstar</strong><span style="color:var(--blue);font-weight:700">92% match</span></div>
          <div class="preview-job"><strong>Frontend Engineer · Layer</strong><span style="color:var(--blue);font-weight:700">84% match</span></div>
        </div>
      </section>
      <section class="auth-card">
        <span class="eyebrow">${register ? "Get started" : "Welcome back"}</span>
        <h2>${register ? "Create your account" : "Sign in to SkillSphere"}</h2>
        <p>${register ? "Set up your space and start finding your fit." : "Your next opportunity is closer than you think."}</p>
        <form class="auth-form" id="auth-form">
          ${register ? `<div class="field"><label for="auth-name">Full name</label><input class="input" id="auth-name" name="name" autocomplete="name" placeholder="Alex Morgan" required minlength="2" /></div>` : ""}
          <div class="field"><label for="auth-email">Email address</label><input class="input" id="auth-email" name="email" type="email" autocomplete="email" placeholder="you@example.com" required /></div>
          ${register ? `<div class="field"><label for="auth-role">I am a</label><select class="select" id="auth-role" name="role"><option value="candidate">Job seeker</option><option value="recruiter">Recruiter</option></select></div>` : ""}
          <div class="field"><label for="auth-password">Password</label><input class="input" id="auth-password" name="password" type="password" autocomplete="${register ? "new-password" : "current-password"}" placeholder="${register ? "At least 8 characters" : "Enter your password"}" minlength="${register ? "8" : "1"}" required /></div>
          <button class="btn btn-primary auth-submit" type="submit" ${state.busy ? "disabled" : ""}>${state.busy ? "Please wait…" : register ? "Create account →" : "Sign in →"}</button>
        </form>
        <div class="auth-switch">${register ? "Already have an account?" : "New to SkillSphere?"} <button type="button" data-action="toggle-auth">${register ? "Sign in" : "Create an account"}</button></div>
        ${register ? "" : `<div class="demo-logins"><span>Explore a demo workspace · password: ${demoPassword}</span><div class="demo-buttons"><button data-demo="candidate@skillsphere.dev">Job seeker</button><button data-demo="recruiter@skillsphere.dev">Recruiter</button><button data-demo="admin@skillsphere.dev">Admin</button></div></div>`}
      </section>
    </main>`;
  app.dataset.register = String(register);
}

function navItems() {
  const common = [["Dashboard", "home"], ["Find jobs", "search"], ["Applications", "files"], ["Assessments", "fileCheck"], ["Interviews", "video"], ["My profile", "user"], ["Notifications", "clock"]];
  if (state.user?.role === "recruiter") return [["Dashboard", "home"], ["My jobs", "briefcase"], ["Question banks", "clipboard"], ["Applicants", "users"], ["Assessments", "fileCheck"], ["Interviews", "video"], ["Company profile", "building"], ["Notifications", "clock"]];
  if (state.user?.role === "admin") return [["Dashboard", "home"], ["Users", "users"], ["Job listings", "clipboard"], ["Applications", "files"], ["Question banks", "clipboard"], ["Assessments", "fileCheck"], ["Proctoring", "fileCheck"], ["Notifications", "clock"]];
  return common;
}

function shell(content) {
  const active = name => state.page === name ? " active" : "";
  const nav = navItems().map(([name, glyph]) =>
    `<button class="nav-item${active(name)}" data-page="${esc(name)}">${icon(glyph, name)}${name === "Notifications" && state.notificationUnread ? `<span class="notification-count">${esc(state.notificationUnread)}</span>` : ""}</button>`).join("");
  app.innerHTML = `
    <div class="app-shell">
      <header class="topbar">
        <a class="brand" href="#" data-page="Dashboard"><span class="brand-mark">${iconSvg("sparkles")}</span><span>SkillSphere</span></a>
        <div class="topbar-right">
          <button class="top-link notification-bell" data-page="Notifications" aria-label="Notifications">Notifications${state.notificationUnread ? `<span class="notification-count">${esc(state.notificationUnread)}</span>` : ""}</button>
          <button class="top-link" data-page="${state.user?.role === "candidate" ? "Find jobs" : "Dashboard"}">${state.user?.role === "candidate" ? "Explore roles" : "Workspace"}</button>
          ${themeToggle()}
          <div class="user-chip"><div class="avatar">${esc(initials(state.user?.name))}</div><div class="user-copy"><strong>${esc(state.user?.name)}</strong><small>${esc(state.user?.role)}</small></div></div>
          <button class="icon-button" aria-label="Sign out" title="Sign out" data-action="logout">${iconSvg("logout")}</button>
        </div>
      </header>
      <div class="workspace">
        <aside class="sidebar">
          <div class="side-profile"><div class="avatar">${esc(initials(state.user?.name))}</div><div><strong>${esc(state.user?.name)}</strong><small>${esc(state.user?.role)} workspace</small></div></div>
          <div class="nav-caption">Workspace</div><nav class="nav-list" aria-label="Main navigation">${nav}</nav>
          <div class="sidebar-foot"><button data-action="logout">${iconSvg("logout")}<span>Sign out</span></button></div>
        </aside>
        <main class="main">${content}</main>
      </div>
    </div>
    ${state.modal ? renderModal() : ""}`;
}

function heading(kicker, title, description, action = "") {
  return `<div class="page-heading"><div><span class="eyebrow">${esc(kicker)}</span><h1>${title}</h1><p>${description}</p></div>${action}</div>`;
}

function stat(label, value, note, glyph) {
  return `<article class="stat-card"><span class="stat-icon">${iconSvg(glyph)}</span><span class="stat-label">${label}</span><div class="stat-value">${value}</div><span class="stat-note">${note}</span></article>`;
}

function empty(title, detail, glyph = "✳") {
  const iconName = ({ "↗": "arrowUpRight", "⌕": "search", "♙": "users", "✳": "sparkles", video: "video" })[glyph] || "sparkles";
  return `<div class="empty"><div class="empty-icon">${iconSvg(iconName)}</div><strong>${title}</strong><p>${detail}</p></div>`;
}

function jobRow(job, actionLabel = "View role") {
  const action = actionLabel === "Applicants" ? `data-page="Applicants"` : `data-job="${esc(job.id)}"`;
  return `<article class="job-row"><div class="company-mark">${esc(initials(job.company))}</div><div><h3>${esc(job.title)}</h3><p>${esc(job.company)} · ${esc(job.location)}</p><div class="job-meta"><span>${esc(job.job_type || "Full-time")}</span><span>${esc(job.experience || "All levels")}</span>${job.salary ? `<span>${esc(job.salary)}</span>` : ""}</div></div><button class="btn btn-quiet btn-small" ${action}>${actionLabel}</button></article>`;
}

function applicationRows(applications) {
  if (!applications.length) return empty("No applications yet", "Your next opportunity is only a search away.", "↗");
  return applications.slice(0, 5).map(item => `<div class="application-row"><div><strong>${esc(item.title)}</strong><small>${esc(item.company)} · Applied ${dateLabel(item.applied_at)}</small>${item.interview ? `<small>${esc(item.interview.status === "Cancelled" ? "Interview Cancelled" : item.interview.status === "Completed" ? "Interview Completed" : "Interview Scheduled")}</small>` : ""}</div><span class="badge ${["Accepted", "Selected"].includes(item.status) ? "badge-green" : item.status === "Rejected" ? "" : "badge-red"}">${esc(item.status)}</span></div>`).join("");
}

function interviewTimeLabel(interview) {
  return new Date(interview.starts_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function localTimeZoneLabel() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "local time";
}

function applicationInterviewCard(interview) {
  if (!interview) return "";
  const endTime = new Date(interview.starts_at).getTime() + Number(interview.duration_minutes) * 60_000;
  const ended = interview.status !== "Cancelled" && interview.status !== "Completed" && endTime <= Date.now();
  const statusLabel = interview.status === "Cancelled"
    ? "Interview Cancelled"
    : interview.status === "Completed"
      ? "Interview Completed"
      : ended ? "Interview Ended" : "Interview Scheduled";
  const joinAction = interview.status === "Scheduled" || interview.status === "Rescheduled";
  return `<section class="application-interview">
    <div class="card-heading"><div><span class="eyebrow">Interview</span><h3>${statusLabel}</h3></div><span class="badge ${joinAction && !ended ? "badge-blue" : ""}">${statusLabel}</span></div>
    <p><strong>${esc(interviewTimeLabel(interview))}</strong> · ${esc(interview.duration_minutes)} minutes · ${esc(interview.meeting_platform)} · ${esc(localTimeZoneLabel())}</p>
    ${interview.recruiter_message ? `<p class="form-hint">${esc(interview.recruiter_message)}</p>` : ""}
    ${joinAction && !ended && interview.meeting_url
      ? `<a class="btn btn-primary" href="${esc(interview.meeting_url)}" target="_blank" rel="noopener noreferrer" data-action="join-interview" data-id="${esc(interview.id)}">Join Interview ↗</a>`
      : joinAction && !ended
        ? `<p class="form-hint">The recruiter has not added a meeting link yet.</p>`
        : ""}
  </section>`;
}

function pipelineTimeline(history = []) {
  if (!history.length) return `<small class="muted">No status updates yet.</small>`;
  return `<ol class="pipeline-timeline">${history.map(item => `<li><span class="timeline-dot"></span><div><strong>${esc(item.status)}</strong><small>${esc(dateLabel(item.updated_at))}${item.actor_name ? ` · ${esc(item.actor_name)}` : ""}</small>${item.recruiter_note ? `<p>${esc(item.recruiter_note)}</p>` : ""}</div></li>`).join("")}</ol>`;
}

function candidateDashboard() {
  const candidateApps = state.applications;
  const latest = state.jobs.slice(0, 3);
  const nextInterview = state.upcomingInterviews[0];
  return `${heading("Your career, in motion", `Good to see you, ${esc(state.user.name.split(" ")[0])} ${iconSvg("sparkles", "heading-icon")}`, "A little progress today can open a big door tomorrow.", `<button class="btn btn-primary" data-page="Find jobs">Find your next role&nbsp; →</button>`)}
    <section class="grid stats-grid">
      ${stat("Active applications", candidateApps.filter(item => !["Rejected", "Withdrawn"].includes(item.status)).length, "Your opportunities in progress", "fileCheck")}
      ${stat("Roles to explore", state.jobs.length, "Open roles picked for you", "search")}
      ${stat("Resume status", state.resume ? "Ready" : "Add", state.resume ? "Your profile is on file" : "Upload to unlock matching", "files")}
      ${stat("Assessments", state.assessments.length, "Your private assessment history", "fileCheck")}
    </section>
    <section class="columns">
      <article class="card"><div class="card-heading"><div><h2>Roles to explore</h2><p>Thoughtful opportunities for your next chapter</p></div><button class="text-button" data-page="Find jobs">See all →</button></div><div class="job-list">${latest.length ? latest.map(job => jobRow(job)).join("") : empty("No open roles yet", "Check back soon for new opportunities.")}</div></article>
      <article class="card"><div class="card-heading"><div><h2>Your applications</h2><p>A quick look at where things stand</p></div><button class="text-button" data-page="Applications">View all →</button></div><div class="application-list">${applicationRows(candidateApps)}</div></article>
    </section>
    <section class="card upcoming-interview-card"><div class="card-heading"><div><span class="eyebrow">Coming up</span><h2>Upcoming interview</h2></div><button class="text-button" data-page="Interviews">All interviews →</button></div>
      ${nextInterview ? `<article class="upcoming-interview"><div><strong>${esc(nextInterview.title)} · ${esc(nextInterview.company)}</strong><p>${esc(interviewTimeLabel(nextInterview))} · ${esc(nextInterview.duration_minutes)} minutes</p></div>${nextInterview.meeting_url ? `<a class="btn btn-primary btn-small" href="${esc(nextInterview.meeting_url)}" target="_blank" rel="noopener noreferrer" data-action="join-interview" data-id="${esc(nextInterview.id)}">Join Interview ↗</a>` : `<span class="form-hint">The recruiter has not added a meeting link yet.</span>`}</article>` : empty("No upcoming interviews", "When a recruiter schedules an interview, it will appear here.", "video")}
    </section>
    <section class="card" style="margin-top:16px"><div class="card-heading"><div><h2>${state.resume ? "Your resume is ready" : "Take the guesswork out of your search"}</h2><p>${state.resume ? `${esc(state.resume.filename)} · ${esc(state.resume.processing_status)}` : "Upload a resume to discover which roles match your skills."}</p></div><button class="btn btn-quiet btn-small" data-page="My profile">${state.resume ? "View profile" : "Add your resume"}</button></div>
      <div class="progress-track"><div class="progress-fill" style="width:${state.resume ? "78%" : "36%"}"></div></div>
      ${state.resume?.processing_error ? `<p style="color:#aa3c40;font-size:10px;margin:9px 0 0">${esc(state.resume.processing_error)}</p>` : ""}
    </section>`;
}

function jobCard(job) {
  const skills = (job.skills || []).slice(0, 4).map(skill => `<span class="skill">${esc(skill)}</span>`).join("");
  return `<article class="job-card"><div class="job-card-top"><div><h3>${esc(job.title)}</h3><p>${esc(job.company)} · ${esc(job.location)}</p></div><span class="company-mark">${esc(initials(job.company))}</span></div><div class="job-meta"><span>${esc(job.job_type || "Full-time")}</span><span>${esc(job.experience || "All levels")}</span><span>${esc(dateLabel(job.created_at))}</span></div><div class="skills">${skills}</div><div class="job-card-bottom"><span class="salary">${esc(job.salary || "Salary not listed")}</span><button class="btn btn-primary btn-small" data-job="${esc(job.id)}">View details →</button></div></article>`;
}

function jobsPage() {
  const action = state.user.role === "recruiter" ? `<button class="btn btn-primary" data-action="new-job">＋ Post a role</button>` : "";
  return `${heading("Discover what's next", "Find your next <span style='color:var(--blue)'>great fit.</span>", "Explore open roles and focus on the ones that feel right.", action)}
    <section class="card"><div class="filters">
      <div class="filter-input"><input class="input" id="job-query" placeholder="⌕   Search role, company, or skill" value="${esc(state.query)}" aria-label="Search jobs" /></div>
      <div class="filter-field"><input class="input" id="job-location" placeholder="Location" value="${esc(state.location)}" aria-label="Filter by location" /></div>
      <div class="filter-field"><select class="select" id="job-type" aria-label="Filter by job type"><option value="">All job types</option>${["Full-time", "Part-time", "Contract", "Remote"].map(value => `<option ${state.jobType === value ? "selected" : ""}>${value}</option>`).join("")}</select></div>
      <div class="filter-field"><input class="input" id="job-experience" placeholder="Experience" value="${esc(state.experience)}" aria-label="Filter by experience" /></div>
      <div class="filter-field"><input class="input" id="job-skill" placeholder="Required skill" value="${esc(state.skill)}" aria-label="Filter by skill" /></div>
      <div class="filter-field"><select class="select" id="job-sort" aria-label="Sort job results"><option value="newest" ${state.sortBy === "newest" ? "selected" : ""}>Newest first</option><option value="company" ${state.sortBy === "company" ? "selected" : ""}>Company A–Z</option><option value="title" ${state.sortBy === "title" ? "selected" : ""}>Role A–Z</option></select></div>
      <button class="btn btn-quiet" data-action="filter-jobs">Search roles</button>
    </div>
    <div class="card-heading"><div><h2>Open opportunities <span class="badge">${state.jobs.length}</span></h2><p>Roles that match your search</p></div><span class="badge badge-green">Updated today</span></div>
    <div class="job-grid">${state.jobs.length ? state.jobs.map(jobCard).join("") : empty("No roles found", "Try a different search or clear your filters.", "⌕")}</div>
    ${state.jobTotal > 6 ? `<div class="job-card-bottom" style="margin-top:14px"><span class="stat-note">Page ${state.jobPage} of ${Math.ceil(state.jobTotal / 6)}</span><div style="display:flex;gap:7px"><button class="btn btn-quiet btn-small" data-action="prev-page" ${state.jobPage <= 1 ? "disabled" : ""}>← Previous</button><button class="btn btn-quiet btn-small" data-action="next-page" ${state.jobPage >= Math.ceil(state.jobTotal / 6) ? "disabled" : ""}>Next →</button></div></div>` : ""}
    </section>`;
}

function applicationsPage() {
  const rows = state.applications;
  return `${heading("Keep your momentum", "My applications", "See where every opportunity stands, all in one place.")}
    <section class="card"><div class="card-heading"><div><h2>Application history</h2><p>${rows.length} submitted application${rows.length === 1 ? "" : "s"}</p></div></div>
    ${rows.length ? `<div class="application-history-list">${rows.map(item => `<article class="application-history-card"><div class="card-heading"><div><h3>${esc(item.title)} · ${esc(item.company)}</h3><p>Applied ${dateLabel(item.applied_at)} · ${esc(item.match_percentage)}% match</p></div><span class="badge ${["Accepted", "Selected", "Round 1 Passed"].includes(item.status) ? "badge-green" : item.status === "Rejected" || item.status === "Round 1 Failed" ? "" : "badge-red"}">${esc(item.status === "Selected" ? "Accepted" : item.status)}</span></div><div class="skills">${(item.matched_skills || []).map(skill => `<span class="skill">${esc(skill)}</span>`).join("")}</div><div class="application-assessment-summary"><strong>Assessment:</strong> ${esc(item.assessment_name || "Round 1: Technical MCQ Test")} · ${esc(item.assessment_status || "Not sent")}${item.assessment_topic ? ` · ${esc(item.assessment_topic)}` : ""}${item.assessment_email_sent_at ? ` · Sent ${esc(dateLabel(item.assessment_email_sent_at))}` : ""}${item.assessment_score != null ? ` · Score ${esc(item.assessment_score)}% (${esc(item.assessment_correct_answer_count)}/20) · ${esc(item.assessment_result)}` : ""}${item.assessment_result_processed_at ? ` · Completed ${esc(dateLabel(item.assessment_result_processed_at))}` : ""}</div>${applicationInterviewCard(item.interview)}<details><summary>Status timeline</summary>${pipelineTimeline(item.status_history)}</details>${["Applied", "Under Review", "Shortlisted", "Assessment Sent"].includes(item.status) ? `<button class="text-button" data-action="withdraw" data-id="${esc(item.id)}">Withdraw application</button>` : ""}</article>`).join("")}</div>` : empty("Your story starts here", "Find a role that feels right and apply when you're ready.")}
    </section>`;
}

function profilePage() {
  const resume = state.resume;
  const parsed = { ...(resume?.parsed_profile || {}), ...(state.user.profile || {}) };
  return `${heading("Put your best foot forward", "My profile", "Your experience, on your terms. Review and update it whenever you like.")}
    <div class="profile-grid">
      <section class="card"><div class="card-heading"><div><h2>Your details</h2><p>Help employers understand what you bring</p></div></div>
        <form id="profile-form" class="profile-form">
          <div class="field"><label>Full name</label><input class="input" name="name" value="${esc(state.user.name)}" required /></div>
          <div class="field"><label>Email address</label><input class="input" type="email" value="${esc(state.user.email)}" disabled /></div>
          <div class="field"><label>Phone</label><input class="input" name="phone" value="${esc(parsed.phone || "")}" placeholder="Add a contact number" /></div>
          <div class="field"><label>Location</label><input class="input" name="location" value="${esc(parsed.location || "")}" placeholder="City, country" /></div>
          <div class="field span-2"><label>Skills</label><input class="input" name="skills" value="${esc((parsed.skills || []).join(", "))}" placeholder="e.g. React, product design, SQL" /></div>
          <div class="field span-2"><label>About you</label><textarea class="textarea" name="summary" placeholder="A short introduction about your experience and what you're looking for.">${esc(parsed.summary || "")}</textarea></div>
          <div class="field span-2"><label>Education</label><textarea class="textarea" name="education" placeholder="Degrees, institutions, and relevant training">${esc(parsed.education || "")}</textarea></div>
          <div class="field span-2"><label>Experience</label><textarea class="textarea" name="experience" placeholder="Roles, responsibilities, and achievements">${esc(parsed.experience || "")}</textarea></div>
          <div class="span-2"><button class="btn btn-primary" type="submit">Save changes</button></div>
        </form>
      </section>
      <aside class="card"><div class="card-heading"><div><h2>Your resume</h2><p>PDF or image, up to 10 MB</p></div></div>
        <form id="resume-form" class="resume-panel">
          <label class="upload-drop" for="resume-file"><span class="upload-mark">${iconSvg("upload")}</span><strong>${resume ? esc(resume.filename) : "Upload your resume"}</strong><p>${resume ? `Last updated ${dateLabel(resume.uploaded_at)}` : "PDF, JPG, JPEG, or PNG · Max 10 MB"}</p><span class="btn btn-quiet btn-small">Choose a file</span><input id="resume-file" name="file" type="file" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" hidden /></label>
        </form>
        ${resume ? `<div style="margin-top:16px"><span class="badge ${resume.processing_status === "completed" ? "badge-green" : "badge-amber"}">${esc(resume.processing_status)}</span>${resume.processing_error ? `<p style="margin:9px 0 0;color:#a33d40;font-size:10px">${esc(resume.processing_error)}</p>` : ""}</div>
        <button class="btn btn-quiet btn-small" style="margin-top:12px" data-action="download-own-resume">Download resume</button>
        <div style="margin-top:15px"><div class="card-heading"><div><h2 style="font-size:12px">Extracted details</h2></div></div>
          <div class="match-score"><div><strong>Name</strong><p>${esc(parsed.name || "Not provided")}</p></div></div>
          <div class="match-score"><div><strong>Email</strong><p>${esc(parsed.email || "Not provided")}</p></div></div>
          <div class="match-score"><div><strong>Phone</strong><p>${esc(parsed.phone || "Not provided")}</p></div></div>
          <div class="skills">${(parsed.skills || []).map(skill => `<span class="skill">${esc(skill)}</span>`).join("") || `<span class="skill">No skills detected</span>`}</div>
        </div>` : ""}
      </aside>
    </div>`;
}

function companyProfilePage() {
  const profile = state.user.profile || {};
  return `${heading("A little more about your team", "Company profile", "Share a few details to help candidates get to know you.")}
    <section class="card"><div class="card-heading"><div><h2>Company details</h2><p>These details make your job listings feel more personal.</p></div></div>
      <form id="company-form" class="profile-form">
        <div class="field"><label>Company name</label><input class="input" name="company" value="${esc(profile.company || "")}" placeholder="Your company" required /></div>
        <div class="field"><label>Contact name</label><input class="input" name="name" value="${esc(state.user.name)}" required /></div>
        <div class="field span-2"><label>About your team</label><textarea class="textarea" name="about" placeholder="What are you building? What makes your team a great place to grow?">${esc(profile.about || "")}</textarea></div>
        <div class="field"><label>Website</label><input class="input" name="website" type="url" value="${esc(profile.website || "")}" placeholder="https://example.com" /></div>
        <div class="field"><label>Location</label><input class="input" name="location" value="${esc(profile.location || "")}" placeholder="City, country or remote" /></div>
        <div class="span-2"><button class="btn btn-primary" type="submit">Save company details</button></div>
      </form>
    </section>`;
}

function recruiterDashboard() {
  const ownJobs = state.jobs;
  const applicants = state.applications;
  return `${heading("Your hiring workspace", `Welcome, ${esc(state.user.name.split(" ")[0])}`, "Build your team with people who are ready to make a difference.", `<button class="btn btn-primary" data-action="new-job">＋ Post a role</button>`)}
    <section class="grid stats-grid">${stat("Open roles", ownJobs.length, "Roles published by your team", "briefcase")}${stat("Applicants", applicants.length, "People interested in your roles", "users")}${stat("In review", applicants.filter(row => row.status === "Under Review").length, "Applications to look at", "clock")}${stat("Shortlisted", applicants.filter(row => row.status === "Shortlisted").length, "Strong profiles to revisit", "sparkles")}</section>
    <section class="columns"><article class="card"><div class="card-heading"><div><h2>Your open roles</h2><p>Manage the opportunities you’ve shared</p></div><button class="text-button" data-page="My jobs">Manage →</button></div><div class="job-list">${ownJobs.slice(0, 4).map(job => jobRow(job, "Applicants")).join("") || empty("No roles posted", "Create your first role to meet great candidates.")}</div></article>
      <article class="card"><div class="card-heading"><div><h2>Hiring snapshot</h2><p>A pulse check on your team’s pipeline</p></div></div><div class="application-list">${applicants.slice(0, 4).map(item => `<div class="application-row"><div><strong>${esc(item.candidate_name)}</strong><small>${esc(item.title)}</small></div><span class="badge badge-red">${esc(item.status)}</span></div>`).join("") || empty("Your applicant list is quiet", "New applicants will show up here.", "♙")}</div></article>
    </section>`;
}

function recruiterJobsPage() {
  return `${heading("Manage your openings", "My jobs", "Create, update, and keep track of the roles you’ve posted.", `<button class="btn btn-primary" data-action="new-job">＋ Post a role</button>`)}
    <section class="card"><div class="card-heading"><div><h2>Your job listings</h2><p>${state.jobs.length} listing${state.jobs.length === 1 ? "" : "s"} · includes closed jobs</p></div></div>
    ${state.jobs.length ? `<div class="managed-job-list">${state.jobs.map(job => `<article class="managed-job"><div><h3>${esc(job.title)}</h3><p>${esc(job.company)} · ${esc(job.location)} · <span class="badge ${job.status === "Open" ? "badge-green" : ""}">${esc(job.status)}</span></p><div class="job-meta">${(job.skills || []).map(skill => `<span>${esc(skill)}</span>`).join("")}</div></div><div class="job-actions"><button class="btn btn-quiet btn-small" data-action="edit-job" data-id="${esc(job.id)}">Edit</button><button class="btn btn-quiet btn-small" data-action="job-question-bank" data-id="${esc(job.id)}">Question bank</button><button class="btn btn-quiet btn-small" data-action="toggle-job-status" data-id="${esc(job.id)}" data-status="${job.status === "Open" ? "Closed" : "Open"}">${job.status === "Open" ? "Close" : "Reopen"}</button></div></article>`).join("")}</div>` : empty("Nothing posted yet", "Post a role and find the right person for your team.")}</section>`;
}

function interviewManagementCell(item) {
  const interview = item.interview;
  if (["Rejected", "Withdrawn", "Accepted", "Selected"].includes(item.status)) {
    return `<span class="badge">Not eligible for an interview</span>`;
  }
  if (!interview || ["Cancelled", "Completed"].includes(interview.status)) {
    return `<button class="btn btn-quiet btn-small" data-action="schedule-interview" data-id="${esc(item.id)}" data-candidate="${esc(item.candidate_name || "Candidate")}">Schedule Interview</button>`;
  }
  return `<div class="assessment-action-cell"><span class="badge badge-blue">${esc(interview.status)}</span><small>${esc(interviewTimeLabel(interview))} · ${esc(interview.duration_minutes)} min · ${esc(interview.meeting_platform)}</small>${interview.candidate_viewed_at ? `<small>Candidate viewed invitation</small>` : `<small>Invitation not viewed yet</small>`}<button class="btn btn-quiet btn-small" data-action="edit-interview" data-id="${esc(item.id)}" data-interview-id="${esc(interview.id)}" data-candidate="${esc(item.candidate_name || "Candidate")}">Reschedule Interview</button><div class="question-actions"><button class="text-button" data-action="cancel-interview" data-id="${esc(item.id)}" data-interview-id="${esc(interview.id)}">Cancel</button><button class="text-button" data-action="complete-interview" data-id="${esc(item.id)}" data-interview-id="${esc(interview.id)}">Mark completed</button></div></div>`;
}

function applicantsPage() {
  const rows = state.applications;
  const assessmentAction = item => {
    if (item.match_percentage < 70 || ["Rejected", "Withdrawn", "Accepted", "Selected"].includes(item.status)) {
      return `<span class="badge">Not eligible</span>`;
    }
    if (item.assessment_status === "Completed") return `<span class="badge badge-green">Completed</span>`;
    if (item.assessment_status === "Started") return `<span class="badge badge-blue">In progress</span>`;
    const isReissue = ["Sent", "Expired"].includes(item.assessment_status);
    const topicSelector = ["Manual Topic Required", "Question Bank Incomplete"].includes(item.assessment_status)
      ? `<select class="select assessment-topic-select" data-assessment-topic="${esc(item.id)}" aria-label="Choose assessment topic for ${esc(item.candidate_name)}" required><option value="">Choose topic</option>${(item.job_question_technologies || []).map(technology => `<option ${technology === item.assessment_topic ? "selected" : ""}>${esc(technology)}</option>`).join("")}</select>`
      : "";
    const bankAction = item.assessment_status === "Question Bank Incomplete" || item.assessment_status === "Manual Topic Required"
      ? `<button class="text-button" data-action="job-question-bank" data-id="${esc(item.job_id)}">Manage question bank</button>` : "";
    return `${topicSelector}${bankAction}<button class="btn btn-quiet btn-small" data-action="send-assessment" data-id="${esc(item.id)}">${isReissue ? "Re-send link" : "Send assessment"}</button>`;
  };
  return `${heading("Meet the people behind the profiles", "Applicants", "Review candidates and keep your hiring process moving.")}
    <section class="card"><div class="card-heading"><div><h2>Applications to review</h2><p>${rows.length} candidate${rows.length === 1 ? "" : "s"} across your open roles</p></div></div>
    ${rows.length ? `<div class="table-wrap"><table><thead><tr><th>Candidate</th><th>Role</th><th>Match</th><th>Applied</th><th>Resume</th><th>Hiring pipeline</th><th>Assessment review</th><th>Interview</th></tr></thead><tbody>${rows.map(item => {
      const proctoring = item.assessment_proctoring;
      return `<tr><td><strong>${esc(item.candidate_name)}</strong><small>${esc(item.candidate_email)}</small><div class="skills">${(item.matched_skills || []).slice(0, 4).map(skill => `<span class="skill">${esc(skill)}</span>`).join("")}</div></td><td>${esc(item.title)}</td><td><span class="badge ${item.match_percentage >= 70 ? "badge-green" : ""}">${esc(item.match_percentage)}%</span><small>Missing: ${esc((item.missing_skills || []).join(", ") || "none")}</small></td><td>${dateLabel(item.applied_at)}</td><td><button class="text-button" data-action="download-resume" data-id="${esc(item.id)}">Open resume ↗</button></td><td><select class="status-select" data-status="${esc(item.id)}" aria-label="Update status for ${esc(item.candidate_name)}">${STATUSES.map(status => `<option ${status === item.status ? "selected" : ""}>${esc(status)}</option>`).join("")}</select><details><summary>Timeline</summary>${pipelineTimeline(item.status_history)}</details><textarea class="textarea internal-note-input" data-note="${esc(item.id)}" placeholder="Internal recruiter note (private)">${esc(item.internal_notes || "")}</textarea><button class="text-button" data-action="save-note" data-id="${esc(item.id)}">Save note</button></td><td><div class="assessment-action-cell"><span class="badge">${esc(item.assessment_status || "Not Sent")}${item.assessment_topic ? ` · ${esc(item.assessment_topic)}` : ""}</span>${assessmentAction(item)}</div><small>${item.assessment_answered_count || 0}/20 answered${item.assessment_started_at ? ` · Started ${esc(dateLabel(item.assessment_started_at))}` : ""}${item.assessment_email_sent_at ? ` · Sent ${esc(dateLabel(item.assessment_email_sent_at))}` : ""}</small>${proctoring ? `<div class="proctoring-compact"><small>Camera ${proctoring.camera_permission_granted ? "granted" : "not granted"} · ${esc(proctoring.warning_count)} warnings · ${esc(proctoring.tab_switch_count)} tab switches · ${esc(proctoring.face_not_visible_incidents)} prolonged face warnings · ${proctoring.flagged_for_review ? "Flagged for Review" : "Not flagged"}</small><button class="text-button" data-action="review-proctoring" data-id="${esc(item.assessment_id)}">Proctoring timeline</button></div>` : ""}${item.assessment_status === "Completed" ? `<button class="text-button" data-action="review-assessment" data-id="${esc(item.assessment_id)}">View result · ${esc(item.assessment_score)}%</button>` : ""}</td><td>${interviewManagementCell(item)}</td></tr>`;
    }).join("")}</tbody></table></div>` : empty("No applicants yet", "Candidate applications for your jobs will appear here.", "♙")}
    </section>${state.assessmentReview ? renderAssessmentReview() : ""}${state.proctoringReview ? renderProctoringReview() : ""}`;
}

function questionBankPage() {
  const jobs = state.user.role === "admin" ? (state.adminJobs || []) : (state.jobs || []);
  const selectedJob = jobs.find(job => String(job.id) === String(state.questionJobId)) || jobs[0];
  if (!selectedJob) {
    return `${heading("Build a fair assessment", "Question banks", "Create a job-specific bank with 20 active questions for each assessment technology.")}<section class="card">${empty("Create a job first", "Your job-specific question banks will appear here.")}</section>`;
  }
  const topics = state.questionBankSummary?.technologies || [];
  const preview = state.questionImportPreview;
  const previewMarkup = preview ? `<section class="card import-preview-card"><div class="card-heading"><div><span class="eyebrow">Review before saving</span><h2>Import preview · ${esc(preview.filename)}</h2><p>${esc(preview.job_title)} · ${esc(preview.total_questions)} question block(s) found · ${esc(preview.valid_questions.length)} valid · ${esc(preview.invalid_questions.length)} skipped or invalid</p></div><div class="question-actions"><button class="btn btn-quiet btn-small" data-action="cancel-question-import" data-id="${esc(preview.import_id)}">Cancel import</button></div></div>
    <div class="import-counts"><div><strong>By technology · original parse</strong><p>${Object.entries(preview.technology_counts || {}).map(([technology, count]) => `${esc(technology)}: ${esc(count)}`).join(" · ") || "None"}</p></div><div><strong>By difficulty · original parse</strong><p>${Object.entries(preview.difficulty_counts || {}).map(([difficulty, count]) => `${esc(difficulty)}: ${esc(count)}`).join(" · ") || "None"}</p></div></div>
    ${preview.invalid_questions.length ? `<h3>Invalid or skipped blocks</h3><div class="import-preview-list">${preview.invalid_questions.map((item, index) => `<article class="import-preview-question"><div><strong>${item.question_number ? `Question ${esc(item.question_number)}` : "Unsupported content"}</strong>${item.question ? `<p>${esc(item.question)}</p>` : ""}<ul>${item.reasons.map(reason => `<li>${esc(reason)}</li>`).join("")}</ul></div><button class="text-button danger-text" data-action="remove-import-question" data-kind="invalid" data-index="${index}">Remove</button></article>`).join("")}</div>` : ""}
    ${preview.valid_questions.length ? `<form id="question-import-preview-form" data-import-id="${esc(preview.import_id)}"><h3>Valid questions · edit before import</h3><div class="import-preview-list">${preview.valid_questions.map((question, index) => `<article class="import-preview-question import-edit-question" data-question-index="${index}"><div class="job-meta"><span>Question ${esc(question.question_number || index + 1)}</span><span>${esc(question.source_type || "PDF preview")}</span></div><div class="import-edit-grid"><label>Technology<input class="input" name="technology_${index}" value="${esc(question.technology)}" required maxlength="40" /></label><label>Difficulty<select class="select" name="difficulty_${index}">${["Easy", "Medium", "Hard"].map(level => `<option ${question.difficulty === level ? "selected" : ""}>${level}</option>`).join("")}</select></label><label class="span-2">Question<textarea class="textarea" name="question_${index}" required minlength="5" maxlength="2000">${esc(question.question)}</textarea></label>${question.options.map((option, optionIndex) => `<label>Option ${String.fromCharCode(65 + optionIndex)}<input class="input" name="option_${index}_${optionIndex}" value="${esc(option)}" required maxlength="1000" /></label>`).join("")}<label>Correct answer<select class="select" name="correct_${index}">${question.options.map((_, optionIndex) => `<option value="${optionIndex}" ${question.correct_index === optionIndex ? "selected" : ""}>${String.fromCharCode(65 + optionIndex)}</option>`).join("")}</select></label></div><button class="text-button danger-text" type="button" data-action="remove-import-question" data-kind="valid" data-index="${index}">Remove question</button></article>`).join("")}</div><button class="btn btn-primary" type="submit">Confirm and import ${preview.valid_questions.length} question(s)</button></form>` : empty("No valid questions to import", "Remove or cancel this preview; malformed questions are never saved.")}</section>` : "";
  return `${heading("Build a fair assessment", "Question bank", "Each bank belongs to one job. Automatic assessments need 20 relevant questions across matched technologies; a manually chosen single-topic test needs 20 for that technology.", `<button class="btn btn-primary" data-action="new-question">＋ Add question</button>`)}
    <section class="card question-bank-controls"><div class="field"><label for="question-job">Job listing</label><select class="select" id="question-job">${jobs.map(job => `<option value="${esc(job.id)}" ${String(job.id) === String(selectedJob.id) ? "selected" : ""}>${esc(job.title)} · ${esc(job.company)} (${esc(job.status)})</option>`).join("")}</select></div>
      <div class="question-bank-summary"><strong>${esc(state.questionBankSummary?.total_valid_active_questions || 0)} valid active questions across this job</strong><div>${topics.length ? topics.map(item => `<span class="badge ${item.ready ? "badge-green" : ""}">${esc(item.technology)}: ${esc(item.valid_active_questions)} valid active${item.ready ? " · single-topic ready" : ` · ${esc(item.needed)} more for a single-topic test`}</span>`).join("") : `<span class="badge">No valid active questions yet.</span>`}</div></div>
      <div class="question-import-upload"><label class="field"><span>PDF question bank</span><input class="input" id="question-bank-pdf" type="file" accept=".pdf,application/pdf" /></label><button class="btn btn-quiet" data-action="upload-question-bank">Upload Question Bank PDF</button></div>
      <details class="question-format-help"><summary>PDF format and template</summary><p>Use a text-based PDF where each question is labeled and includes four options and an answer key. Difficulty is optional and defaults to Medium.</p><pre>Technology: SQL
Difficulty: Medium

Question: Which SQL clause filters results after GROUP BY?
A. WHERE
B. HAVING
C. ORDER BY
D. DISTINCT
Answer: B</pre></details>
    </section>
    ${previewMarkup}
    <section class="card"><div class="card-heading"><div><h2>Import history</h2><p>Private PDFs are retained for audit and never served publicly.</p></div></div>${state.questionBankImports.length ? `<div class="import-history-list">${state.questionBankImports.map(item => `<article class="application-row"><div><strong>${esc(item.filename)}</strong><small>${esc(item.status)} · ${esc(item.valid_question_count)} valid · ${esc(item.invalid_question_count)} invalid · ${esc(dateLabel(item.created_at))}${item.error_summary ? ` · ${esc(item.error_summary)}` : ""}</small></div>${item.status === "pending_review" ? `<button class="text-button danger-text" data-action="cancel-question-import" data-id="${esc(item.id)}">Cancel</button>` : ""}</article>`).join("")}</div>` : `<p class="muted">No PDF imports yet.</p>`}</section>
    <section class="card"><div class="card-heading"><div><h2>${esc(selectedJob.title)} question bank</h2><p>${state.jobQuestions.length} matching question${state.jobQuestions.length === 1 ? "" : "s"}</p></div><div class="filters compact-filters"><select class="select" id="question-filter-technology"><option value="">All technologies</option>${[...new Set(state.jobQuestions.map(question => question.technology))].map(technology => `<option>${esc(technology)}</option>`).join("")}</select><select class="select" id="question-filter-difficulty"><option value="">All difficulties</option><option>Easy</option><option>Medium</option><option>Hard</option></select><select class="select" id="question-filter-active"><option value="">All states</option><option value="true">Active</option><option value="false">Inactive</option></select><button class="btn btn-quiet btn-small" data-action="filter-questions">Filter</button></div></div>
      ${state.jobQuestions.length ? `<div class="question-list">${state.jobQuestions.map(question => `<article class="question-row"><div><div class="job-meta"><span>${esc(question.technology)}</span><span>${esc(question.difficulty)}</span><span>${question.active ? "Active" : "Inactive"}</span><span>${esc(question.source_type || "manual")}</span></div><h3>${esc(question.question)}</h3><ol>${question.options.map((option, index) => `<li class="${index === question.correct_index ? "correct-option" : ""}">${esc(option)}${index === question.correct_index ? " · correct answer (recruiter only)" : ""}</li>`).join("")}</ol></div><div class="question-actions"><button class="btn btn-quiet btn-small" data-action="edit-question" data-id="${esc(question.id)}">Edit</button><select class="select" data-question-active="${esc(question.id)}" aria-label="Set question active status"><option value="true" ${question.active ? "selected" : ""}>Active</option><option value="false" ${question.active ? "" : "selected"}>Inactive</option></select><button class="text-button danger-text" data-action="delete-question" data-id="${esc(question.id)}">Delete</button></div></article>`).join("")}</div>` : empty("No questions match", "Add questions or change the filters.")}
    </section>`;
}

function assessmentsPage() {
  if (state.user.role === "candidate") {
    const assessments = state.assessments;
    return `${heading("Your technical assessments", "Assessment review", "Check assessment status and results. Secure test links are sent to your registered email address.")}
      <section class="card"><div class="card-heading"><div><h2>Your assessment history</h2><p>${assessments.length} assessment${assessments.length === 1 ? "" : "s"}</p></div></div>
      ${assessments.length ? `<div class="assessment-review-list">${assessments.map(item => `<article class="assessment-review-card"><div class="card-heading"><div><h3>${esc(item.assessment_name || "Round 1: Technical MCQ Test")}</h3><p>${esc(item.job_title)} · ${esc(item.company)} · ${esc(item.technology || "Technology not selected")}</p></div><span class="badge ${item.result === "Passed" ? "badge-green" : item.result === "Failed" ? "" : item.status === "Started" ? "badge-blue" : ""}">${esc(item.result || item.status)}</span></div><div class="assessment-review-meta"><span>Questions ${esc(item.total_questions)}</span><span>Time limit ${esc(item.duration_minutes)} min</span><span>Passing score ${esc(item.pass_percentage)}%</span><span>Sent ${esc(dateLabel(item.email_sent_at))}</span><span>${item.starts_at ? `Started ${esc(dateLabel(item.starts_at))}` : "Not started"}</span><span>${item.submitted_at ? `Completed ${esc(dateLabel(item.submitted_at))}` : "Not completed"}</span>${item.score == null ? "" : `<span>Score ${esc(item.score)}% · ${esc(item.correct_answer_count)}/${esc(item.total_questions)} correct</span>`}</div>${item.status === "Completed" ? `<p class="assessment-result">${item.result === "Passed" ? "Congratulations, you have cleared Round 1." : "Thank you for completing Round 1. You did not reach the required passing score."}</p>` : ""}${["Sent", "Started"].includes(item.status) ? `<p class="form-hint">Open the secure, single-use link from your registered email to ${item.status === "Started" ? "continue" : "start"} this assessment.</p>` : ""}${["Sent", "Expired", "Not Sent"].includes(item.status) && !item.starts_at ? `<button class="btn btn-quiet btn-small" data-action="resend-candidate-assessment" data-id="${esc(item.id)}">Email me a secure link</button>` : ""}</article>`).join("")}</div>` : empty("No assessments yet", "Eligible assessments will appear here after an invitation is sent.")}</section>`;
  }
  const rows = state.assessments;
  const jobs = state.user.role === "recruiter" ? state.jobs : state.adminJobs;
  return `${heading("Review candidate progress", "Assessment review", "Filter Round 1 results, review answers, and decide next steps for passed candidates.")}<section class="card"><div class="filters assessment-filters"><select class="select" id="assessment-filter-result"><option value="">Passed and failed</option><option>Passed</option><option>Failed</option></select><select class="select" id="assessment-filter-job"><option value="">All jobs</option>${jobs.map(job => `<option value="${esc(job.id)}">${esc(job.title)}</option>`).join("")}</select><input class="input" id="assessment-filter-candidate" placeholder="Candidate name or email" /><select class="select" id="assessment-filter-stage"><option value="">All pipeline stages</option>${STATUSES.map(status => `<option>${esc(status)}</option>`).join("")}</select><select class="select" id="assessment-filter-status"><option value="">All assessment states</option>${["Not Sent", "Sent", "Started", "Completed", "Expired", "Manual Topic Required"].map(status => `<option>${status}</option>`).join("")}</select><input class="input" id="assessment-filter-technology" placeholder="Technology" /><input class="input" type="date" id="assessment-filter-start" aria-label="Completed from date" /><input class="input" type="date" id="assessment-filter-end" aria-label="Completed through date" /><input class="input score-filter" type="number" id="assessment-filter-score-min" min="0" max="100" placeholder="Min score" /><input class="input score-filter" type="number" id="assessment-filter-score-max" min="0" max="100" placeholder="Max score" /><button class="btn btn-quiet" data-action="filter-assessments">Apply filters</button></div>
    ${rows.length ? `<div class="table-wrap"><table><thead><tr><th>Candidate</th><th>Job</th><th>Assessment / Score</th><th>Result</th><th>Completed</th><th>Pipeline / Actions</th><th>Question review</th></tr></thead><tbody>${rows.map(item => `<tr><td><strong>${esc(item.candidate_name)}</strong><small>${esc(item.candidate_email)}</small></td><td>${esc(item.job_title)}</td><td>${esc(item.assessment_name)}<small>${esc(item.score_percentage ?? "—")}% · ${esc(item.correct_answer_count ?? "—")}/${esc(item.total_questions)} correct</small></td><td>${esc(item.result || item.status)}</td><td>${item.submitted_at ? esc(dateLabel(item.submitted_at)) : "—"}<small>${item.time_taken_seconds == null ? "—" : `${Math.floor(item.time_taken_seconds / 60)} min`}</small></td><td>${esc(item.application_status)}${item.result === "Passed" ? `<select class="status-select" data-status="${esc(item.application_id)}" aria-label="Move passed candidate ${esc(item.candidate_name)} to next stage">${["Round 1 Passed", "Interview", "Accepted", "Rejected"].map(status => `<option ${status === item.application_status ? "selected" : ""}>${esc(status)}</option>`).join("")}</select>` : item.result === "Failed" ? `<select class="status-select" data-status="${esc(item.application_id)}" aria-label="Update failed candidate ${esc(item.candidate_name)}">${["Round 1 Failed", "Rejected"].map(status => `<option ${status === item.application_status ? "selected" : ""}>${esc(status)}</option>`).join("")}</select>` : ""}</td><td>${item.status === "Completed" ? `<button class="btn btn-quiet btn-small" data-action="review-assessment" data-id="${esc(item.id)}">Review questions</button><button class="text-button" data-action="review-proctoring" data-id="${esc(item.id)}">Proctoring timeline · ${esc(item.proctoring?.warning_count || 0)} warnings</button>` : "—"}</td></tr>`).join("")}</tbody></table></div>` : empty("No assessments found", "No assessments match the selected filters.")}</section>${state.assessmentReview ? renderAssessmentReview() : ""}${state.proctoringReview ? renderProctoringReview() : ""}`;
}

function renderAssessmentReview() {
  const review = state.assessmentReview;
  const proctoring = review.proctoring || {};
  return `<section class="card assessment-result-panel"><div class="card-heading"><div><span class="eyebrow">Assessment result</span><h2>${esc(review.candidate_name)} · ${esc(review.job_title)}</h2><p>${esc(review.company)} · ${esc(review.assessment_name)} · ${esc(review.score)}% · ${esc(review.correct_answer_count)}/${esc(review.total_questions)} correct · ${esc(review.result)}</p></div><button class="icon-button" data-action="close-assessment-review" aria-label="Close assessment result">×</button></div><p class="form-hint">Current pipeline stage: ${esc(review.application_status)} · Completed ${esc(dateLabel(review.result_processed_at || review.submitted_at))} · Time taken: ${review.time_taken_seconds == null ? "—" : `${Math.floor(review.time_taken_seconds / 60)}m ${review.time_taken_seconds % 60}s`}</p><p class="form-hint">Selected technologies: ${(review.selected_topics || []).map(esc).join(", ") || esc(review.technology)}</p><p class="form-hint">${esc(review.selection_reasoning || "")}</p><div class="proctoring-compact"><strong>Integrity summary:</strong> Camera ${proctoring.camera_permission_granted ? "granted" : "not granted"} · ${esc(proctoring.warning_count || 0)} warnings · ${esc(proctoring.tab_switch_count || 0)} tab switches · ${esc(proctoring.face_not_visible_incidents || 0)} prolonged face warnings · ${proctoring.flagged_for_review ? "Flagged for Review" : "Not flagged"} <button class="text-button" data-action="review-proctoring" data-id="${esc(review.id)}">View event timeline</button></div><div class="assessment-answer-list">${review.questions.map(question => `<article class="assessment-answer"><strong>${esc(question.number)}. ${esc(question.question)}</strong><ol>${question.options.map((option, index) => `<li class="${index === question.correct_answer ? "correct-option" : ""} ${index === question.selected_answer ? "selected-option" : ""}">${esc(option)}${index === question.selected_answer ? " · candidate choice" : ""}${index === question.correct_answer ? " · correct" : ""}</li>`).join("")}</ol></article>`).join("")}</div></section>`;
}

function renderProctoringReview() {
  const review = state.proctoringReview;
  if (!review) return "";
  const summary = review.summary || {};
  return `<section class="card assessment-result-panel proctoring-detail"><div class="card-heading"><div><span class="eyebrow">Assessment integrity</span><h2>Proctoring event timeline</h2><p>Camera footage is not stored. This timeline contains browser and face-presence event metadata only.</p></div><button class="icon-button" data-action="close-proctoring-review" aria-label="Close proctoring timeline">×</button></div><div class="proctoring-compact">Camera ${summary.camera_permission_granted ? "granted" : "not granted"} · ${esc(summary.warning_count || 0)} warnings · ${esc(summary.tab_switch_count || 0)} tab switches · ${esc(summary.face_not_visible_incidents || 0)} prolonged face warnings · ${summary.flagged_for_review ? "Flagged for Review" : "Not flagged"}</div>${review.events.length ? `<div class="table-wrap"><table><thead><tr><th>Date/time</th><th>Event</th><th>Severity</th><th>Description</th><th>Warning</th><th>Duration</th></tr></thead><tbody>${review.events.map(item => `<tr><td>${esc(new Date(item.occurred_at).toLocaleString())}</td><td>${esc(item.event_type.replaceAll("_", " "))}</td><td><span class="badge ${item.severity === "High" ? "badge-red" : item.severity === "Warning" ? "badge-blue" : ""}">${esc(item.severity)}</span></td><td>${esc(item.message)}</td><td>${item.warning_number == null ? "—" : esc(item.warning_number)}</td><td>${item.duration_seconds == null ? "—" : `${esc(item.duration_seconds)}s`}</td></tr>`).join("")}</tbody></table></div>` : empty("No proctoring events recorded", "No camera or browser activity events were recorded for this assessment.")}</section>`;
}

function proctoringPage() {
  const data = state.proctoringData || { summary: {}, items: [], jobs: [], recruiters: [], top_candidates: [], recent_activity: [] };
  const summary = data.summary;
  const filters = state.proctoringFilters;
  return `${heading("Assessment integrity", "Proctoring", "Review consented camera status, face-presence warnings, and browser activity. Video is not stored.")}<section class="card"><div class="filters assessment-filters"><select class="select" id="proctoring-filter-job"><option value="">All jobs</option>${data.jobs.map(job => `<option value="${esc(job.id)}" ${String(filters.job_id || "") === String(job.id) ? "selected" : ""}>${esc(job.title)}</option>`).join("")}</select><select class="select" id="proctoring-filter-recruiter"><option value="">All recruiters</option>${data.recruiters.map(recruiter => `<option value="${esc(recruiter.id)}" ${String(filters.recruiter_id || "") === String(recruiter.id) ? "selected" : ""}>${esc(recruiter.name)}</option>`).join("")}</select><input class="input" id="proctoring-filter-candidate" value="${esc(filters.candidate || "")}" placeholder="Candidate name or email" /><input class="input" type="date" id="proctoring-filter-start" value="${esc(filters.start_date || "")}" aria-label="Activity from date" /><input class="input" type="date" id="proctoring-filter-end" value="${esc(filters.end_date || "")}" aria-label="Activity through date" /><select class="select" id="proctoring-filter-status"><option value="">All assessment states</option>${["Not Sent", "Sent", "Started", "Completed", "Expired"].map(status => `<option ${filters.assessment_status === status ? "selected" : ""}>${status}</option>`).join("")}</select><select class="select" id="proctoring-filter-flagged"><option value="" ${filters.flagged == null ? "selected" : ""}>Flagged and unflagged</option><option value="true" ${filters.flagged === "true" ? "selected" : ""}>Flagged only</option><option value="false" ${filters.flagged === "false" ? "selected" : ""}>Not flagged</option></select><button class="btn btn-quiet" data-action="filter-proctoring">Apply filters</button></div></section><section class="grid stats-grid admin-weekly-cards">${stat("Proctored assessments", summary.proctored_assessments ?? 0, "Matching filters", "fileCheck")}${stat("Camera denied", summary.camera_permission_denied_assessments ?? 0, "Matching filters", "users")}${stat("Flagged for review", summary.flagged_assessments ?? 0, "Matching filters", "sparkles")}${stat("Tab switches", summary.tab_switch_events ?? 0, "Recorded hidden-page events", "clock")}${stat("Prolonged face warnings", summary.face_not_visible_warnings ?? 0, "At or above configured threshold", "user")}</section><section class="card"><div class="card-heading"><div><h2>Assessment integrity records</h2><p>${data.items.length} assessment record${data.items.length === 1 ? "" : "s"} shown (up to 200)</p></div></div>${data.items.length ? `<div class="table-wrap"><table><thead><tr><th>Candidate</th><th>Job / Recruiter</th><th>Assessment</th><th>Camera</th><th>Warnings</th><th>Flagged</th><th>Completed</th><th>Timeline</th></tr></thead><tbody>${data.items.map(item => `<tr><td><strong>${esc(item.candidate_name)}</strong><small>${esc(item.candidate_email)}</small></td><td>${esc(item.job_title)}<small>${esc(item.recruiter_name)}</small></td><td>${esc(item.assessment_status)}</td><td>${item.camera_permission_granted ? "Granted" : "Not granted"}</td><td>${esc(item.warning_count)}</td><td>${item.flagged_for_review ? `<span class="badge badge-red">Flagged for Review</span>` : "No"}</td><td>${item.submitted_at ? esc(dateLabel(item.submitted_at)) : "—"}</td><td><button class="text-button" data-action="review-proctoring" data-id="${esc(item.assessment_id)}">View timeline</button></td></tr>`).join("")}</tbody></table></div>` : empty("No proctored assessments", "Matching assessment records will appear here.")}</section><section class="grid admin-analytics-columns"><article class="card"><div class="card-heading"><div><h2>Highest warning counts</h2><p>Filtered candidates, ordered by maximum assessment warning count</p></div></div>${data.top_candidates.length ? data.top_candidates.map(item => `<div class="breakdown-row"><span>${esc(item.candidate_name)} · ${esc(item.candidate_email)}</span><strong>${esc(item.warning_count)} warnings</strong></div>`).join("") : `<p class="muted">No warning activity in this filter.</p>`}</article><article class="card"><div class="card-heading"><div><h2>Recent suspicious activity</h2><p>Latest recorded events</p></div></div>${data.recent_activity.length ? data.recent_activity.map(item => `<div class="application-row"><div><strong>${esc(item.candidate_name)} · ${esc(item.event_type.replaceAll("_", " "))}</strong><small>${esc(item.job_title)} · ${esc(new Date(item.occurred_at).toLocaleString())}${item.duration_seconds == null ? "" : ` · ${esc(item.duration_seconds)}s`}</small></div><button class="text-button" data-action="review-proctoring" data-id="${esc(item.assessment_id)}">Timeline</button></div>`).join("") : `<p class="muted">No recent events in this filter.</p>`}</article></section>${state.proctoringReview ? renderProctoringReview() : ""}`;
}

function notificationsPage() {
  return `${heading("Stay in the loop", "Notifications", "Application, assessment, and hiring updates for your account.", `<button class="btn btn-quiet" data-action="mark-all-read" ${state.notificationUnread ? "" : "disabled"}>Mark all read</button>`)}
    <section class="card">${state.notificationsLoading ? `<div class="loading-state">Loading notifications…</div>` : state.notificationsError ? `<div class="error-state">${esc(state.notificationsError)}</div>` : state.notifications.length ? `<div class="notification-list">${state.notifications.map(item => {
      const interviewLink = item.type.startsWith("interview_") && /^https:\/\//i.test(item.action_url || "");
      return `<article class="notification-item${item.is_read ? "" : " unread"}"><span class="notification-state" aria-label="${item.is_read ? "Read" : "Unread"}"></span><div><div class="notification-title"><strong>${esc(item.title)}</strong><span class="badge">${esc(item.type.replaceAll("_", " "))}</span></div><p>${esc(item.message)}</p><small>${esc(dateLabel(item.created_at))}${item.email_delivery_status && item.email_delivery_status !== "not_requested" ? ` · Email ${esc(item.email_delivery_status)}` : ""}</small>${item.action_url ? `<a class="text-button" href="${esc(item.action_url)}" ${interviewLink ? `target="_blank" rel="noopener noreferrer"` : ""}>${interviewLink ? "Join Interview ↗" : "Open related page →"}</a>` : ""}</div>${item.is_read ? "" : `<button class="btn btn-quiet btn-small" data-action="mark-notification-read" data-id="${esc(item.id)}">Mark read</button>`}</article>`;
    }).join("")}</div>` : empty("You’re all caught up", "New updates will show up here.")}</section>`;
}

function adminApplicationsPage() {
  const rows = state.applications;
  return `${heading("Platform-wide pipeline", "All applications", "Review candidates, recruiters, match scores, hiring stages, and assessment status.")}<section class="card">${rows.length ? `<div class="table-wrap"><table><thead><tr><th>Candidate</th><th>Job / Recruiter</th><th>Match</th><th>Pipeline</th><th>Assessment</th><th>Resume</th><th>Applied</th><th>Interview</th></tr></thead><tbody>${rows.map(item => `<tr><td><strong>${esc(item.candidate_name)}</strong><small>${esc(item.candidate_email)}</small></td><td>${esc(item.title)}<small>${esc(item.recruiter_name || "")}</small></td><td>${esc(item.match_percentage)}%</td><td><select class="status-select" data-status="${esc(item.id)}" aria-label="Update application status">${STATUSES.map(status => `<option ${status === item.status ? "selected" : ""}>${esc(status)}</option>`).join("")}</select><details><summary>Timeline</summary>${pipelineTimeline(item.status_history)}</details><textarea class="textarea internal-note-input" data-note="${esc(item.id)}" placeholder="Internal note">${esc(item.internal_notes || "")}</textarea><button class="text-button" data-action="save-note" data-id="${esc(item.id)}">Save note</button></td><td>${esc(item.assessment_status)}${item.assessment_score == null ? "" : ` · ${esc(item.assessment_score)}%`}${item.assessment_id ? `<button class="text-button" data-action="review-assessment" data-id="${esc(item.assessment_id)}">Review</button>` : ""}</td><td><button class="text-button" data-action="download-resume" data-id="${esc(item.id)}">Open</button></td><td>${esc(dateLabel(item.applied_at))}</td><td>${interviewManagementCell(item)}</td></tr>`).join("")}</tbody></table></div>` : empty("No applications", "Applications from all job listings appear here.")}</section>${state.assessmentReview ? renderAssessmentReview() : ""}`;
}

function interviewsPage() {
  const rows = state.interviews;
  return `${heading("Make time to connect", "Interviews", "Join upcoming conversations and shared coding sessions.")}
    <section class="card"><div class="card-heading"><div><h2>Your interview schedule</h2><p>${rows.length} scheduled interview${rows.length === 1 ? "" : "s"}</p></div></div>
      ${rows.length ? `<div class="interview-list">${rows.map(item => {
        const ended = new Date(item.starts_at).getTime() + Number(item.duration_minutes || 60) * 60_000 <= Date.now();
        const canJoin = !ended && !["Cancelled", "Completed"].includes(item.status) && Boolean(item.meeting_url || item.teams_url);
        const meetingUrl = item.meeting_url || item.teams_url;
        return `<article class="interview-card"><div class="interview-card-copy"><span class="badge ${canJoin ? "badge-blue" : ""}">${esc(item.status === "Cancelled" ? "Interview Cancelled" : item.status === "Completed" ? "Interview Completed" : ended ? "Interview Ended" : item.status)}</span><h3>${esc(item.title)}</h3><p>${esc(item.company)} · ${state.user.role === "candidate" ? `Interviewer: ${esc(item.recruiter_name)}` : `Candidate: ${esc(item.candidate_name)}`}</p><small>${esc(interviewTimeLabel(item))} · ${esc(item.duration_minutes || 60)} min · ${esc(item.meeting_platform || "Microsoft Teams")}</small></div><div class="interview-actions">${canJoin ? `<a class="btn btn-primary btn-small" href="${esc(meetingUrl)}" target="_blank" rel="noopener noreferrer" ${state.user.role === "candidate" ? `data-action="join-interview" data-id="${esc(item.id)}"` : ""}>Join Interview</a>` : item.status === "Cancelled" || item.status === "Completed" || ended ? "" : `<span class="form-hint">The recruiter has not added a meeting link yet.</span>`}${item.status !== "Cancelled" && item.status !== "Completed" ? `<button class="btn btn-quiet btn-small" data-action="open-interview" data-id="${esc(item.id)}">Open coding room</button>` : ""}</div></article>`;
      }).join("")}</div>` : empty("No interviews scheduled", state.user.role === "recruiter" ? "Schedule one from your Applicants page." : "Your recruiter will share an interview invitation here.", "video")}
    </section>`;
}

function interviewRoomPage() {
  const interview = state.activeInterview;
  if (!interview) return `${heading("Interview workspace", "Interview not found", "Return to your interview list and try again.")}`;
  const output = state.runResult
    ? `${state.runResult.stdout || ""}${state.runResult.stderr || ""}${state.runResult.compile_output || ""}${state.runResult.message || ""}`.trim()
    : "";
  const canJoin = !["Cancelled", "Completed"].includes(interview.status) && new Date(interview.starts_at).getTime() + Number(interview.duration_minutes || 60) * 60_000 > Date.now();
  return `${heading("Live interview workspace", esc(interview.title), `${esc(interview.company)} · ${esc(interviewTimeLabel(interview))}`, canJoin && (interview.meeting_url || interview.teams_url) ? `<a class="btn btn-primary" href="${esc(interview.meeting_url || interview.teams_url)}" target="_blank" rel="noopener noreferrer">${iconSvg("video")} Join Interview</a>` : "")}
    <section class="card interview-room">
      <div class="editor-toolbar"><div><strong>Shared coding session</strong><span id="interview-connection" class="connection-status">Connecting…</span></div>
        <div class="editor-actions"><select class="select language-select" id="interview-language" aria-label="Programming language">${[["python","Python"],["javascript","JavaScript"],["java","Java"],["cpp","C++"]].map(([value,label]) => `<option value="${value}" ${state.interviewLanguage === value ? "selected" : ""}>${label}</option>`).join("")}</select><button class="btn btn-primary btn-small" data-action="run-code">Run code</button></div>
      </div>
      <div class="editor-meta"><span>Edits are shared live with both interview participants.</span><span>Runs in your private isolated runner</span></div>
      <textarea class="code-editor" id="interview-code" spellcheck="false" autocapitalize="off" autocomplete="off" aria-label="Shared code editor" placeholder="// Write code together">${esc(state.interviewCode)}</textarea>
      <div class="stdin-control"><label for="interview-stdin">Program input <span>Optional · maximum 4 KB</span></label><textarea class="runner-stdin" id="interview-stdin" spellcheck="false" placeholder="Input passed to stdin">${esc(state.interviewStdin)}</textarea></div>
      <div class="runner-output"><div class="output-heading"><strong>Output</strong>${state.runResult ? `<span class="badge">${esc(state.runResult.status)}</span>` : ""}</div><pre id="run-output">${esc(output || (state.runResult ? "(no output)" : "Run your code to see output here."))}</pre>${state.runResult?.time ? `<small>Execution time: ${esc(state.runResult.time)}s · Memory: ${esc(state.runResult.memory ?? "—")} KB</small>` : ""}</div>
    </section>`;
}

function adminDashboard() {
  const data = state.analytics || {};
  const cards = [
    ["New candidates", data.new_candidates], ["New recruiters", data.new_recruiters],
    ["Jobs posted", data.jobs_posted], ["Applications received", data.applications_received],
    ["Shortlisted", data.candidates_shortlisted], ["Assessments sent", data.assessments_sent],
    ["Assessments started", data.assessments_started], ["Assessments completed", data.assessments_completed],
    ["Round 1 completed", data.round1_assessments_completed], ["Round 1 passed", data.round1_passed],
    ["Round 1 failed", data.round1_failed], ["Round 1 pass rate", `${data.round1_pass_rate ?? 0}%`],
    ["Average Round 1 score", data.round1_average_score == null ? "—" : `${data.round1_average_score}%`],
    ["Assessments expired", data.assessments_expired], ["Average score", data.average_assessment_score == null ? "—" : `${data.average_assessment_score}%`],
    ["In Interview", data.candidates_in_interview], ["Accepted", data.accepted_candidates], ["Rejected", data.rejected_candidates]
  ];
  const maxTrend = Math.max(1, ...(data.weekly_trend || []).flatMap(item => [item.applications, item.assessments_sent, item.assessments_started, item.assessments_completed]));
  return `${heading("Platform overview", "The whole picture", "A live snapshot of the SkillSphere community.")}
    <section class="card analytics-range-card"><div class="analytics-range-controls"><label for="analytics-range">Reporting range</label><select class="select" id="analytics-range"><option value="this_week" ${state.analyticsRange === "this_week" ? "selected" : ""}>This week</option><option value="last_week" ${state.analyticsRange === "last_week" ? "selected" : ""}>Last week</option><option value="custom" ${state.analyticsRange === "custom" ? "selected" : ""}>Custom</option></select>${state.analyticsRange === "custom" ? `<input class="input" type="date" id="analytics-start" aria-label="Start date" /><input class="input" type="date" id="analytics-end" aria-label="End date" />` : ""}<button class="btn btn-quiet btn-small" data-action="refresh-analytics">Update report</button></div><p class="form-hint">${esc(data.start_date || "")} – ${esc(data.end_date || "")}</p></section>
    <section class="grid stats-grid admin-weekly-cards">${cards.map(([label, value], index) => stat(label, value ?? "—", "Selected reporting range", index % 2 ? "fileCheck" : "users")).join("")}</section>
    <section class="grid admin-analytics-columns"><article class="card"><div class="card-heading"><div><h2>Weekly trend</h2><p>Applications and assessment activity by day</p></div></div><div class="trend-chart">${(data.weekly_trend || []).map(day => `<div class="trend-day"><strong>${esc(day.date.slice(5))}</strong><div class="trend-bars">${[["applications", "Applications"], ["assessments_sent", "Sent"], ["assessments_started", "Started"], ["assessments_completed", "Completed"]].map(([key, title]) => `<span title="${title}: ${day[key]}" class="trend-bar ${key}" style="height:${Math.max(3, day[key] / maxTrend * 100)}%"></span>`).join("")}</div><small>${esc(day.applications)} apps</small></div>`).join("")}</div><div class="trend-legend"><span>Applications</span><span>Sent</span><span>Started</span><span>Completed</span></div></article><article class="card"><div class="card-heading"><div><h2>Hiring pipeline</h2><p>Current application stages</p></div></div>${(data.pipeline_breakdown || []).map(item => `<div class="breakdown-row"><span>${esc(item.status === "Selected" ? "Accepted (legacy)" : item.status)}</span><strong>${esc(item.count)}</strong></div>`).join("") || empty("No pipeline data", "Application stages appear as candidates apply.")}</article></section>
    <section class="grid admin-analytics-columns"><article class="card"><div class="card-heading"><div><h2>Assessment status</h2><p>Completion rate ${esc(data.assessment_completion_rate ?? 0)}% · Round 1 pass rate ${esc(data.round1_pass_rate ?? 0)}%</p></div></div>${(data.assessment_breakdown || []).map(item => `<div class="breakdown-row"><span>${esc(item.status)}</span><strong>${esc(item.count)}</strong></div>`).join("") || empty("No assessments", "Assessment activity will appear here.")}<h3 class="subsection-title">Round 1 pass/fail distribution</h3>${(data.round1_score_distribution || []).map(item => `<div class="breakdown-row"><span>${esc(item.band)}</span><strong>${esc(item.count)}</strong></div>`).join("") || `<p class="muted">No completed Round 1 scores in this range.</p>`}<h3 class="subsection-title">Score ranges</h3>${(data.score_distribution || []).map(item => `<div class="breakdown-row"><span>${esc(item.band)}%</span><strong>${esc(item.count)}</strong></div>`).join("") || `<p class="muted">No completed scores in this range.</p>`}</article><article class="card"><div class="card-heading"><div><h2>Top jobs</h2><p>Applications, shortlists, and Round 1 outcomes</p></div></div><h3 class="subsection-title">Applications</h3>${(data.top_jobs_by_applications || []).map(item => `<div class="breakdown-row"><span>${esc(item.title)} · ${esc(item.company)}</span><strong>${esc(item.applications)}</strong></div>`).join("") || `<p class="muted">No applications in range.</p>`}<h3 class="subsection-title">Shortlisted</h3>${(data.top_jobs_by_shortlists || []).map(item => `<div class="breakdown-row"><span>${esc(item.title)} · ${esc(item.company)}</span><strong>${esc(item.shortlisted)}</strong></div>`).join("") || `<p class="muted">No shortlists in range.</p>`}<h3 class="subsection-title">Round 1 passed by job</h3>${(data.round1_passed_by_job || []).map(item => `<div class="breakdown-row"><span>${esc(item.title)} · ${esc(item.company)}</span><strong>${esc(item.candidates)}</strong></div>`).join("") || `<p class="muted">No passes in range.</p>`}<h3 class="subsection-title">Round 1 failed by job</h3>${(data.round1_failed_by_job || []).map(item => `<div class="breakdown-row"><span>${esc(item.title)} · ${esc(item.company)}</span><strong>${esc(item.candidates)}</strong></div>`).join("") || `<p class="muted">No failures in range.</p>`}</article></section>
    <section class="grid admin-analytics-columns"><article class="card"><div class="card-heading"><div><h2>Top technologies</h2><p>Question-bank and assessment usage</p></div></div>${(data.top_technologies || []).map(item => `<div class="breakdown-row"><span>${esc(item.technology)}</span><strong>${esc(item.assessments)}</strong></div>`).join("") || `<p class="muted">No assessment technologies in range.</p>`}</article><article class="card"><div class="card-heading"><div><h2>Recent platform activity</h2><p>Notifications created during this period</p></div></div>${(data.recent_activity || []).map(item => `<div class="application-row"><div><strong>${esc(item.title)}</strong><small>${esc(item.user_name)} · ${esc(dateLabel(item.created_at))}</small></div><span class="badge">${esc(item.type.replace(/_/g, " "))}</span></div>`).join("") || `<p class="muted">No recent platform activity.</p>`}</article></section>
    <section class="card"><div class="card-heading"><div><h2>Recent applications and assessment submissions</h2><p>Reporting-range activity</p></div></div><div class="columns"><div class="application-list">${(data.recent_applications || []).map(item => `<div class="application-row"><div><strong>${esc(item.candidate_name)} · ${esc(item.title)}</strong><small>${esc(item.company)} · ${esc(item.match_percentage)}% match · ${esc(dateLabel(item.applied_at))}</small></div><span class="badge">${esc(item.status)}</span></div>`).join("") || `<p class="muted">No applications in range.</p>`}</div><div class="application-list">${(data.recent_assessments || []).map(item => `<div class="application-row"><div><strong>${esc(item.candidate_name)} · ${esc(item.title)}</strong><small>${esc(item.technology)} · ${esc(dateLabel(item.submitted_at))}</small></div><span class="badge badge-green">${esc(item.score)}%</span></div>`).join("") || `<p class="muted">No submitted assessments in range.</p>`}</div></div></section>`;
}

function adminUsersPage() {
  const users = state.analytics?.users_list || [];
  return `${heading("Community management", "People on SkillSphere", "Review the members, employers, and teams in the community.")}
    <section class="card"><div class="card-heading"><div><h2>Registered members</h2><p>${users.length} accounts</p></div></div>
      ${users.length ? `<div class="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Joined</th><th>Recent activity</th><th>Account</th></tr></thead><tbody>${users.map(user => `<tr><td><strong>${esc(user.name)}</strong></td><td>${esc(user.email)}</td><td><span class="badge">${esc(user.role)}</span></td><td>${dateLabel(user.created_at)}</td><td>${user.last_activity ? dateLabel(user.last_activity) : "—"}</td><td>${user.id === state.user.id ? `<span class="badge badge-green">Your account</span>` : user.role === "admin" ? `<span class="badge">Protected admin</span>` : `<select class="status-select" data-user-status="${esc(user.id)}" aria-label="Update account for ${esc(user.name)}"><option value="true" ${user.active ? "selected" : ""}>Active</option><option value="false" ${user.active ? "" : "selected"}>Disabled</option></select>`}</td></tr>`).join("")}</tbody></table></div>` : empty("No members found", "There are no accounts to display.")}
    </section>`;
}

function adminJobListingsPage() {
  const jobs = state.adminJobs || [];
  return `${heading("Keep opportunities thoughtful", "Job listings", "Review open roles and close listings that are no longer active.")}
    <section class="card"><div class="card-heading"><div><h2>All listings</h2><p>${jobs.length} total listing${jobs.length === 1 ? "" : "s"}</p></div></div>
      ${jobs.length ? `<div class="table-wrap"><table><thead><tr><th>Role</th><th>Company</th><th>Location</th><th>Posted</th><th>Status</th></tr></thead><tbody>${jobs.map(job => `<tr><td><strong>${esc(job.title)}</strong></td><td>${esc(job.company)}</td><td>${esc(job.location)}</td><td>${dateLabel(job.created_at)}</td><td><select class="status-select" data-job-status="${esc(job.id)}" aria-label="Update listing for ${esc(job.title)}"><option ${job.status === "Open" ? "selected" : ""}>Open</option><option ${job.status === "Closed" ? "selected" : ""}>Closed</option></select></td></tr>`).join("")}</tbody></table></div>` : empty("No listings found", "New opportunities will appear here.")}
    </section>`;
}

function currentContent() {
  if (state.user.role === "recruiter") {
    if (state.page === "My jobs") return recruiterJobsPage();
    if (state.page === "Question banks") return questionBankPage();
    if (state.page === "Applicants") return applicantsPage();
    if (state.page === "Assessments") return assessmentsPage();
    if (state.page === "Notifications") return notificationsPage();
    if (state.page === "Interviews") return interviewsPage();
    if (state.page === "Interview room") return interviewRoomPage();
    if (state.page === "Company profile") return companyProfilePage();
    return recruiterDashboard();
  }
  if (state.user.role === "admin") {
    if (state.page === "Users") return adminUsersPage();
    if (state.page === "Job listings") return adminJobListingsPage();
    if (state.page === "Applications") return adminApplicationsPage();
    if (state.page === "Question banks") return questionBankPage();
    if (state.page === "Assessments") return assessmentsPage();
    if (state.page === "Proctoring") return proctoringPage();
    if (state.page === "Notifications") return notificationsPage();
    return adminDashboard();
  }
  if (state.page === "Assessments") return assessmentsPage();
  if (state.page === "Notifications") return notificationsPage();
  if (state.page === "Interviews") return interviewsPage();
  if (state.page === "Interview room") return interviewRoomPage();
  if (state.page === "Find jobs") return jobsPage();
  if (state.page === "Applications") return applicationsPage();
  if (state.page === "My profile") return profilePage();
  return candidateDashboard();
}

function renderModal() {
  if (state.modal === "question") {
    const question = state.editingQuestion || {};
    const options = question.options || ["", "", "", ""];
    return `<div class="modal-backdrop" data-action="close-modal"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-head"><div><span class="eyebrow">Job-specific assessment content</span><h2 id="modal-title">${question.id ? "Edit question" : "Add a question"}</h2><p>Correct answers are visible only to recruiters and admins.</p></div><button class="icon-button" aria-label="Close dialog" data-action="close-modal">×</button></div><form id="question-form" class="profile-form" data-question-id="${esc(question.id || "")}"><div class="field"><label>Technology</label><input class="input" name="technology" value="${esc(question.technology || "")}" placeholder="Python, Java, React…" required /></div><div class="field"><label>Difficulty</label><select class="select" name="difficulty">${["Easy", "Medium", "Hard"].map(level => `<option ${question.difficulty === level ? "selected" : ""}>${level}</option>`).join("")}</select></div><div class="field span-2"><label>Question</label><textarea class="textarea" name="question" required minlength="5">${esc(question.question || "")}</textarea></div>${options.map((option, index) => `<div class="field"><label>Option ${index + 1}</label><input class="input" name="option_${index}" value="${esc(option)}" required /></div>`).join("")}<div class="field"><label>Correct option</label><select class="select" name="correct_index">${options.map((_, index) => `<option value="${index}" ${question.correct_index === index ? "selected" : ""}>Option ${index + 1}</option>`).join("")}</select></div><div class="field"><label>Status</label><select class="select" name="active"><option value="true" ${question.active !== false ? "selected" : ""}>Active</option><option value="false" ${question.active === false ? "selected" : ""}>Inactive</option></select></div><div class="span-2"><button class="btn btn-primary" type="submit">${question.id ? "Save question" : "Add question"}</button></div></form></section></div>`;
  }
  if (state.modal?.startsWith("edit-job:")) {
    const job = state.jobs.find(item => String(item.id) === state.modal.slice("edit-job:".length));
    if (!job) return "";
    return `<div class="modal-backdrop" data-action="close-modal"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-head"><div><span class="eyebrow">Manage your opening</span><h2 id="modal-title">Edit job listing</h2><p>Updates to role skills affect future match calculations.</p></div><button class="icon-button" aria-label="Close dialog" data-action="close-modal">×</button></div><form id="job-form" class="profile-form" data-job-id="${esc(job.id)}"><div class="field span-2"><label>Role title</label><input class="input" name="title" value="${esc(job.title)}" required /></div><div class="field"><label>Company</label><input class="input" name="company" value="${esc(job.company)}" required /></div><div class="field"><label>Location</label><input class="input" name="location" value="${esc(job.location)}" required /></div><div class="field"><label>Experience</label><input class="input" name="experience" value="${esc(job.experience)}" required /></div><div class="field"><label>Job type</label><input class="input" name="job_type" value="${esc(job.job_type)}" required /></div><div class="field span-2"><label>Salary range</label><input class="input" name="salary" value="${esc(job.salary || "")}" /></div><div class="field span-2"><label>Required skills, comma-separated</label><input class="input" name="skills" value="${esc((job.skills || []).join(", "))}" required /></div><div class="field span-2"><label>Role description</label><textarea class="textarea" name="description" required>${esc(job.description)}</textarea></div><div class="span-2"><button class="btn btn-primary" type="submit">Save changes</button></div></form></section></div>`;
  }
  if (state.modal?.startsWith("schedule:") || state.modal?.startsWith("reschedule:")) {
    const editing = state.modal.startsWith("reschedule:");
    const [, applicationId, interviewId] = state.modal.split(":");
    const candidateName = state.scheduleCandidate || "Candidate";
    const interview = editing ? state.editingInterview : null;
    const localDate = interview ? new Date(interview.starts_at) : null;
    const dateValue = localDate ? `${localDate.getFullYear()}-${String(localDate.getMonth() + 1).padStart(2, "0")}-${String(localDate.getDate()).padStart(2, "0")}` : "";
    const timeValue = localDate ? `${String(localDate.getHours()).padStart(2, "0")}:${String(localDate.getMinutes()).padStart(2, "0")}` : "";
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    return `<div class="modal-backdrop" data-action="close-modal"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div class="modal-head"><div><span class="eyebrow">Meet your candidate</span><h2 id="modal-title">${editing ? "Reschedule Interview" : "Schedule Interview"}</h2><p>Invite ${esc(candidateName)} to a conversation.</p></div><button class="icon-button" aria-label="Close dialog" data-action="close-modal">×</button></div>
      <form id="interview-form" class="profile-form" data-application-id="${esc(applicationId)}" data-interview-id="${esc(interviewId || "")}">
        <div class="field"><label for="interview-date">Interview date</label><input class="input" id="interview-date" type="date" name="interview_date" value="${esc(dateValue)}" required /></div>
        <div class="field"><label for="interview-time">Start time</label><input class="input" id="interview-time" type="time" name="interview_time" value="${esc(timeValue)}" required /></div>
        <div class="field"><label for="interview-timezone">Time zone</label><input class="input" id="interview-timezone" name="timezone" value="${esc(interview?.timezone || timezone)}" required maxlength="100" /></div>
        <div class="field"><label for="interview-duration">Duration</label><input class="input" id="interview-duration" type="number" name="duration_minutes" min="15" max="480" step="15" value="${esc(interview?.duration_minutes || 60)}" required /></div>
        <div class="field"><label for="interview-platform">Meeting platform</label><select class="select" id="interview-platform" name="meeting_platform">${["Google Meet", "Microsoft Teams", "Zoom", "Other"].map(platform => `<option ${platform === (interview?.meeting_platform || "Microsoft Teams") ? "selected" : ""}>${platform}</option>`).join("")}</select></div>
        <div class="field span-2"><label for="interview-link">Secure meeting URL</label><input class="input" id="interview-link" type="url" name="meeting_url" value="${esc(interview?.meeting_url || "")}" placeholder="https://..." /></div>
        <div class="field span-2"><label for="interview-message">Optional recruiter message or instructions</label><textarea class="textarea" id="interview-message" name="recruiter_message" maxlength="2000">${esc(interview?.recruiter_message || "")}</textarea></div>
        <p class="span-2 form-hint">Use a full HTTPS meeting URL. The candidate will see the schedule and can join from My Applications.</p>
        <div class="span-2"><button class="btn btn-primary" type="submit">${editing ? "Save interview changes" : "Schedule Interview"}</button></div>
      </form>
    </section></div>`;
  }
  if (state.modal === "new-job") return `<div class="modal-backdrop" data-action="close-modal"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
    <div class="modal-head"><div><span class="eyebrow">Grow your team</span><h2 id="modal-title">Post a new role</h2><p>Share the details that help the right people find you.</p></div><button class="icon-button" aria-label="Close dialog" data-action="close-modal">×</button></div>
    <form id="job-form" class="profile-form"><div class="field span-2"><label>Role title</label><input class="input" name="title" placeholder="e.g. Product Designer" required /></div>
    <div class="field"><label>Company</label><input class="input" name="company" placeholder="Your company" required /></div><div class="field"><label>Location</label><input class="input" name="location" placeholder="Remote, New York..." required /></div>
    <div class="field"><label>Experience</label><input class="input" name="experience" placeholder="e.g. 2–4 years" required /></div><div class="field"><label>Job type</label><select class="select" name="job_type"><option>Full-time</option><option>Part-time</option><option>Contract</option><option>Remote</option></select></div>
    <div class="field span-2"><label>Salary range</label><input class="input" name="salary" placeholder="e.g. $90k – $120k" /></div>
    <div class="field span-2"><label>Required skills, comma-separated</label><input class="input" name="skills" placeholder="e.g. Figma, UX research, prototyping" required /></div>
    <div class="field span-2"><label>Role description</label><textarea class="textarea" name="description" required placeholder="What will this person do? What makes your team a great place to grow?"></textarea></div>
    <div class="span-2"><button class="btn btn-primary" type="submit">Publish role →</button></div></form>
    </section></div>`;
  if (state.modal?.startsWith("job:")) {
    const job = state.jobs.find(item => String(item.id) === state.modal.slice(4));
    if (!job) return "";
    return `<div class="modal-backdrop" data-action="close-modal"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div class="modal-head"><div><span class="eyebrow">${esc(job.company)} · ${esc(job.location)}</span><h2 id="modal-title">${esc(job.title)}</h2><p>${esc(job.experience)} · ${esc(job.job_type)} · ${esc(job.salary || "Salary not listed")}</p></div><button class="icon-button" aria-label="Close dialog" data-action="close-modal">×</button></div>
      <p style="color:#706966;font-size:12px;line-height:1.75">${esc(job.description)}</p><div class="skills">${(job.skills || []).map(skill => `<span class="skill">${esc(skill)}</span>`).join("")}</div>
      ${state.user.role === "candidate" ? `<div class="match-score"><div><strong>Ready to apply?</strong><p>${state.resume ? "Your resume is on file and ready to share." : "Upload a resume from your profile before applying."}</p></div><button class="btn btn-primary btn-small" data-action="apply-job" data-id="${esc(job.id)}">Apply now →</button></div>` : ""}
      ${state.user.role === "candidate" ? `<div class="match-score"><div><strong>See how your skills line up</strong><p>Compare your resume with this role’s requirements.</p></div><button class="btn btn-quiet btn-small" data-action="check-match" data-id="${esc(job.id)}">Check match</button></div>${state.match?.job_id === job.id ? `<div class="resume-panel"><div class="card-heading"><div><h2>Skills match</h2><p>${esc(state.match.recommendation)}</p></div><div class="score-ring">${esc(state.match.match_percentage)}%</div></div><strong style="font-size:10px">Matched skills</strong><div class="skills">${state.match.matched_skills.map(skill => `<span class="skill" style="background:#e9f7f0;color:#308366">${esc(skill)}</span>`).join("") || `<span class="skill">No exact matches found</span>`}</div><strong style="display:block;margin-top:12px;font-size:10px">Skills to explore</strong><div class="skills">${state.match.missing_skills.map(skill => `<span class="skill">${esc(skill)}</span>`).join("") || `<span class="skill">You match every listed skill</span>`}</div></div>` : ""}` : ""}
    </section></div>`;
  }
  return "";
}

async function loadWorkspace() {
  if (!state.user) return;
  try {
    const jobsPath = state.user.role === "recruiter" ? "/jobs?mine=true&page_size=100" : "/jobs?page_size=6";
    const [jobData, applicationData] = await Promise.all([
      api(jobsPath),
      api("/applications")
    ]);
    state.jobs = jobData.items || [];
    state.jobTotal = jobData.total ?? state.jobs.length;
    state.applications = applicationData.items || [];
    state.notificationsLoading = true;
    state.notificationsError = "";
    const [notificationData, unreadData, assessmentData] = await Promise.all([
      api("/notifications?page_size=50"),
      api("/notifications/unread-count"),
      api("/assessments")
    ]);
    state.notifications = notificationData.items || [];
    state.notificationUnread = unreadData.unread_count || 0;
    state.assessments = assessmentData.items || [];
    state.notificationsLoading = false;
    if (state.user.role !== "admin") {
      const interviewData = await api("/interviews");
      state.interviews = interviewData.items || [];
    } else {
      state.interviews = [];
    }
    if (state.user.role === "candidate") {
      const [resume, upcoming] = await Promise.all([
        api("/resume"),
        api("/interviews/upcoming")
      ]);
      state.resume = resume;
      state.upcomingInterviews = upcoming.items || [];
    } else {
      state.upcomingInterviews = [];
    }
    if (state.user.role === "admin") {
      const [analytics, adminJobs] = await Promise.all([
        api(`/admin/analytics?range=${encodeURIComponent(state.analyticsRange)}`),
        api("/admin/jobs")
      ]);
      state.analytics = analytics;
      state.adminJobs = adminJobs.items || [];
    }
  } catch (error) {
    state.notificationsLoading = false;
    state.notificationsError = error.message;
    showToast(error.message, true);
    if (/token|authentication|authorization/i.test(error.message)) signOut(false);
  }
  renderWorkspace();
}

async function loadQuestionBank(jobId, filters = {}) {
  if (!jobId) return;
  state.questionJobId = String(jobId);
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== "") params.set(key, value);
  }
  try {
    const [questions, summary, imports] = await Promise.all([
      api(`/jobs/${encodeURIComponent(jobId)}/questions${params.toString() ? `?${params}` : ""}`),
      api(`/jobs/${encodeURIComponent(jobId)}/question-bank-summary`),
      api(`/jobs/${encodeURIComponent(jobId)}/question-bank/imports`)
    ]);
    state.jobQuestions = questions.items || [];
    state.questionBankSummary = summary;
    state.questionBankImports = imports.items || [];
    renderWorkspace();
  } catch (error) { showToast(error.message, true); }
}

async function loadAssessmentList(filters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== "") params.set(key, value);
  }
  try {
    const result = await api(`/assessments${params.toString() ? `?${params}` : ""}`);
    state.assessments = result.items || [];
    renderWorkspace();
  } catch (error) { showToast(error.message, true); }
}

async function loadAdminAnalytics() {
  const params = new URLSearchParams({ range: state.analyticsRange });
  if (state.analyticsRange === "custom") {
    const startDate = document.querySelector("#analytics-start")?.value;
    const endDate = document.querySelector("#analytics-end")?.value;
    if (!startDate || !endDate) {
      showToast("Choose both a start and end date for the custom report.", true);
      return;
    }
    if (target.dataset.action === "join-interview") {
      api(`/interviews/${encodeURIComponent(target.dataset.id)}/viewed`, { method: "POST" })
        .then(() => {
          const application = state.applications.find(item => String(item.interview?.id) === String(target.dataset.id));
          if (application?.interview) application.interview.candidate_viewed_at = new Date().toISOString();
        })
        .catch(error => showToast(error.message, true));
      return;
    }
    params.set("start_date", startDate);
    params.set("end_date", endDate);
  }
  try {
    state.analytics = await api(`/admin/analytics?${params}`);
    renderWorkspace();
  } catch (error) { showToast(error.message, true); }
}

async function openAssessmentReview(id) {
  try {
    state.assessmentReview = await api(`/assessments/${encodeURIComponent(id)}/review`);
    renderWorkspace();
  } catch (error) { showToast(error.message, true); }
}

async function loadAdminProctoring(filters = state.proctoringFilters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters || {})) {
    if (value !== "" && value != null) params.set(key, value);
  }
  try {
    state.proctoringFilters = { ...(filters || {}) };
    state.proctoringData = await api(`/admin/proctoring${params.toString() ? `?${params}` : ""}`);
    renderWorkspace();
  } catch (error) { showToast(error.message, true); }
}

async function openProctoringReview(id) {
  try {
    state.proctoringReview = await api(`/assessments/${encodeURIComponent(id)}/proctoring`);
    renderWorkspace();
  } catch (error) { showToast(error.message, true); }
}

function renderWorkspace() {
  if (!state.user) return;
  shell(currentContent());
  if (state.page === "Interview room" && state.activeInterview) connectInterviewSocket(state.activeInterview.id);
  else stopInterviewSocket();
}

function stopInterviewSocket() {
  state.interviewReconnect = false;
  clearTimeout(state.codeTimer);
  if (state.interviewSocket) {
    const socket = state.interviewSocket;
    state.interviewSocket = null;
    const editor = document.querySelector("#interview-code");
    if (socket.readyState === WebSocket.OPEN && editor && state.activeInterview) {
      socket.send(JSON.stringify({ type: "code", code: editor.value }));
    }
    socket.close();
  }
}

function connectInterviewSocket(interviewId) {
  if (state.interviewSocket && state.interviewSocket.interviewId === interviewId
      && [WebSocket.CONNECTING, WebSocket.OPEN].includes(state.interviewSocket.readyState)) return;
  stopInterviewSocket();
  state.interviewReconnect = true;
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${scheme}//${location.host}/api/interviews/${encodeURIComponent(interviewId)}/code`);
  socket.interviewId = interviewId;
  state.interviewSocket = socket;
  socket.addEventListener("open", () => {
    socket.send(JSON.stringify({ type: "auth", token: state.token }));
  });
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    const editor = document.querySelector("#interview-code");
    if (message.type === "snapshot" || message.type === "code") {
      state.interviewCode = message.code;
      if (editor && document.activeElement !== editor) editor.value = message.code;
      if (message.type === "snapshot") state.interviewLanguage = message.language;
    }
    if (message.type === "snapshot" || message.type === "language") {
      state.interviewLanguage = message.language;
      const language = document.querySelector("#interview-language");
      if (language) language.value = message.language;
    }
    if (message.type === "error") showToast(message.message, true);
    const status = document.querySelector("#interview-connection");
    if (status) {
      status.textContent = message.type === "snapshot" ? "Live · interviewer can see your edits" : "Live";
      status.classList.add("connected");
    }
  });
  socket.addEventListener("close", () => {
    if (state.interviewSocket === socket) state.interviewSocket = null;
    const status = document.querySelector("#interview-connection");
    if (status) {
      status.textContent = "Reconnecting…";
      status.classList.remove("connected");
    }
    if (state.interviewReconnect && state.page === "Interview room"
        && String(state.activeInterview?.id) === String(interviewId)) {
      setTimeout(() => connectInterviewSocket(interviewId), 1500);
    }
  });
}

async function openInterview(id) {
  try {
    state.activeInterview = await api(`/interviews/${encodeURIComponent(id)}`);
    state.interviewCode = state.activeInterview.code || "";
    state.interviewLanguage = state.activeInterview.language || "python";
    state.runResult = null;
    state.page = "Interview room";
    renderWorkspace();
  } catch (error) { showToast(error.message, true); }
}

async function runInterviewCode() {
  if (!state.activeInterview) return;
  const code = document.querySelector("#interview-code")?.value || state.interviewCode;
  state.interviewStdin = document.querySelector("#interview-stdin")?.value || "";
  state.interviewCode = code;
  try {
    const result = await api(`/interviews/${encodeURIComponent(state.activeInterview.id)}/run`, {
      method: "POST",
      body: JSON.stringify({ code, language: state.interviewLanguage, stdin: state.interviewStdin })
    });
    state.runResult = result;
    renderWorkspace();
  } catch (error) { showToast(error.message, true); }
}

async function signOut(announce = true) {
  stopInterviewSocket();
  state.activeInterview = null;
  try {
    await api("/auth/logout", { method: "POST" });
  } catch {
    // ignore server-side logout failures to keep the UI responsive
  }
  saveToken("");
  state.user = null;
  state.busy = false;
  state.jobs = [];
  state.applications = [];
  state.resume = null;
  state.analytics = null;
  state.adminJobs = [];
  state.interviews = [];
  state.notifications = [];
  state.notificationUnread = 0;
  state.assessments = [];
  state.jobQuestions = [];
  state.questionBankSummary = null;
  if (announce) showToast("You’ve signed out. See you soon!");
  renderAuth();
}

async function authenticate(email, password, register, name, role) {
  state.busy = true;
  renderAuth(register);
  try {
    const result = await api(register ? "/auth/register" : "/auth/login", {
      method: "POST",
      body: JSON.stringify(register ? { name, email, password, role } : { email, password })
    });
    if (result.access_token) {
      await api("/auth/session", {
        method: "POST",
        body: JSON.stringify({ access_token: result.access_token })
      });
    }
    state.busy = false;
    saveToken("");
    state.user = result.user;
    state.page = "Dashboard";
    await loadWorkspace();
    showToast(register ? "Your SkillSphere account is ready." : "Welcome back!");
  } catch (error) {
    state.busy = false;
    renderAuth(register);
    showToast(error.message, true);
  }
}

async function searchJobs() {
  state.query = document.querySelector("#job-query")?.value.trim() || "";
  state.location = document.querySelector("#job-location")?.value.trim() || "";
  state.jobType = document.querySelector("#job-type")?.value || "";
  state.experience = document.querySelector("#job-experience")?.value.trim() || "";
  state.skill = document.querySelector("#job-skill")?.value.trim() || "";
  state.sortBy = document.querySelector("#job-sort")?.value || "newest";
  state.jobPage = 1;
  await loadJobsPage();
}

async function loadJobsPage() {
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (state.location) params.set("location", state.location);
  if (state.jobType) params.set("job_type", state.jobType);
  if (state.experience) params.set("experience", state.experience);
  if (state.skill) params.set("skill", state.skill);
  params.set("sort_by", state.sortBy);
  params.set("page", String(state.jobPage));
  params.set("page_size", "6");
  try {
    const result = await api(`/jobs?${params}`);
    state.jobs = result.items || [];
    state.jobTotal = result.total;
    renderWorkspace();
  } catch (error) { showToast(error.message, true); }
}

async function openJob(id) {
  state.modal = `job:${id}`;
  renderWorkspace();
  try {
    const job = await api(`/jobs/${encodeURIComponent(id)}`);
    const index = state.jobs.findIndex(item => String(item.id) === String(id));
    if (index >= 0) state.jobs[index] = job;
    renderWorkspace();
  } catch (error) { showToast(error.message, true); }
}

async function applyToJob(id) {
  try {
    const result = await api(`/jobs/${encodeURIComponent(id)}/apply`, { method: "POST" });
    state.applications.unshift(result);
    state.modal = "";
    state.editingInterview = null;
    renderWorkspace();
    const inviteSent = result.assessment_status === "Sent";
    const message = result.assessment_delivery_error
      ? `Application submitted, but the assessment invitation could not be sent: ${result.assessment_delivery_error}`
      : inviteSent
        ? `Application submitted and shortlisted at ${result.match_percentage}% match.`
        : result.assessment_status === "Manual Topic Required"
          ? `Application submitted at ${result.match_percentage}% match. A recruiter will choose your assessment topic.`
          : result.assessment_status === "Question Bank Incomplete"
            ? `Application submitted and shortlisted at ${result.match_percentage}% match. The recruiter needs to finish the job question bank before sending an assessment.`
          : "Application submitted. Good luck!";
    showToast(message, Boolean(result.assessment_delivery_error));
  } catch (error) { showToast(error.message, true); }
}

async function downloadPrivateResume(path, filenameFallback) {
  const headers = new Headers({ Authorization: `Bearer ${state.token}` });
  try {
    const response = await fetch(`${API}${path}`, { headers });
    if (!response.ok) {
      let payload = {};
      try { payload = await response.json(); } catch { payload = {}; }
      throw new Error(payload.detail || `Resume download failed (${response.status})`);
    }
    const disposition = response.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || filenameFallback;
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  } catch (error) { showToast(error.message, true); }
}

async function downloadApplicantResume(id) {
  await downloadPrivateResume(`/applications/${encodeURIComponent(id)}/resume`, "candidate-resume");
}

async function uploadResume(file) {
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    showToast("Uploading and reviewing your resume…");
    const result = await api("/resume/upload", { method: "POST", body: form });
    state.resume = result;
    state.page = "My profile";
    await loadWorkspace();
    showToast(result.processing_error || "Your resume was uploaded.");
  } catch (error) { showToast(error.message, true); }
}

app.addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.target;
  if (form.id === "auth-form") {
    const values = new FormData(form);
    await authenticate(values.get("email"), values.get("password"), app.dataset.register === "true", values.get("name"), values.get("role"));
  }
  if (form.id === "job-form") {
    const values = Object.fromEntries(new FormData(form));
    values.skills = values.skills.split(",").map(skill => skill.trim()).filter(Boolean);
    try {
      await api(form.dataset.jobId ? `/jobs/${encodeURIComponent(form.dataset.jobId)}` : "/jobs", {
        method: form.dataset.jobId ? "PATCH" : "POST",
        body: JSON.stringify(values)
      });
      state.modal = "";
      await loadWorkspace();
      showToast(form.dataset.jobId ? "Job listing updated." : "Your role is live. Here’s to finding a great fit!");
    } catch (error) { showToast(error.message, true); }
  }
  if (form.id === "question-form") {
    const values = Object.fromEntries(new FormData(form));
    const question = {
      technology: values.technology,
      question: values.question,
      options: [0, 1, 2, 3].map(index => values[`option_${index}`]),
      correct_index: Number(values.correct_index),
      difficulty: values.difficulty,
      active: values.active === "true"
    };
    const questionId = form.dataset.questionId;
    try {
      await api(`/jobs/${encodeURIComponent(state.questionJobId)}/questions${questionId ? `/${encodeURIComponent(questionId)}` : ""}`, {
        method: questionId ? "PATCH" : "POST",
        body: JSON.stringify(question)
      });
      state.modal = "";
      state.editingQuestion = null;
      await loadQuestionBank(state.questionJobId);
      showToast(questionId ? "Question updated." : "Question added.");
    } catch (error) { showToast(error.message, true); }
  }
  if (form.id === "question-import-preview-form") {
    const questions = [...form.querySelectorAll(".import-edit-question")].map((row, index) => {
      const field = name => row.querySelector(`[name="${name}_${index}"]`);
      return {
        technology: field("technology").value.trim(),
        difficulty: field("difficulty").value,
        question: field("question").value.trim(),
        options: [0, 1, 2, 3].map(optionIndex => row.querySelector(`[name="option_${index}_${optionIndex}"]`).value.trim()),
        correct_index: Number(row.querySelector(`[name="correct_${index}"]`).value),
        active: true
      };
    });
    try {
      const result = await api(
        `/jobs/${encodeURIComponent(state.questionImportPreview.job_id)}/question-bank/imports/${encodeURIComponent(form.dataset.importId)}/confirm`,
        { method: "POST", body: JSON.stringify({ questions }) }
      );
      state.questionImportPreview = null;
      await loadQuestionBank(state.questionJobId);
      showToast(`Imported ${result.imported_count} questions; skipped ${result.skipped_duplicate_count} duplicates.`);
    } catch (error) { showToast(error.message, true); }
  }
  if (form.id === "interview-form") {
    const values = Object.fromEntries(new FormData(form));
    try {
      const startsAt = new Date(`${values.interview_date}T${values.interview_time}`);
      if (Number.isNaN(startsAt.getTime())) throw new Error("Choose a valid interview date and start time.");
      const payload = {
        starts_at: startsAt.toISOString(),
        timezone: values.timezone,
        duration_minutes: Number(values.duration_minutes),
        meeting_platform: values.meeting_platform,
        meeting_url: values.meeting_url.trim(),
        recruiter_message: values.recruiter_message.trim()
      };
      const interviewId = form.dataset.interviewId;
      const endpoint = `/applications/${encodeURIComponent(form.dataset.applicationId)}/interviews${interviewId ? `/${encodeURIComponent(interviewId)}` : ""}`;
      await api(endpoint, {
        method: interviewId ? "PATCH" : "POST",
        body: JSON.stringify(payload)
      });
      state.modal = "";
      state.scheduleCandidate = "";
      state.editingInterview = null;
      await loadWorkspace();
      showToast(interviewId ? "Interview updated. The candidate has been notified." : "Interview scheduled. The candidate has been notified.");
    } catch (error) { showToast(error.message, true); }
  }
  if (form.id === "profile-form") {
    const values = Object.fromEntries(new FormData(form));
    values.skills = values.skills.split(",").map(skill => skill.trim()).filter(Boolean);
    try {
      state.user = await api("/profile", { method: "PATCH", body: JSON.stringify({ name: values.name, profile: values }) });
      renderWorkspace();
      showToast("Your profile has been updated.");
    } catch (error) { showToast(error.message, true); }
  }
  if (form.id === "company-form") {
    const values = Object.fromEntries(new FormData(form));
    const { name, ...profile } = values;
    try {
      state.user = await api("/profile", { method: "PATCH", body: JSON.stringify({ name, profile }) });
      renderWorkspace();
      showToast("Your company profile has been updated.");
    } catch (error) { showToast(error.message, true); }
  }
});

app.addEventListener("change", async event => {
  if (event.target.id === "resume-file") await uploadResume(event.target.files[0]);
  if (event.target.id === "analytics-range") {
    state.analyticsRange = event.target.value;
    if (state.analyticsRange === "custom") renderWorkspace();
    else await loadAdminAnalytics();
  }
  if (event.target.id === "question-job") {
    if (state.questionImportPreview && String(state.questionImportPreview.job_id) !== String(event.target.value)) {
      state.questionImportPreview = null;
    }
    await loadQuestionBank(event.target.value);
  }
  if (event.target.matches("[data-question-active]")) {
    const question = state.jobQuestions.find(item => String(item.id) === String(event.target.dataset.questionActive));
    if (!question) return;
    try {
      await api(`/jobs/${encodeURIComponent(state.questionJobId)}/questions/${encodeURIComponent(question.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ active: event.target.value === "true" })
      });
      await loadQuestionBank(state.questionJobId);
      showToast("Question status updated.");
    } catch (error) { showToast(error.message, true); await loadQuestionBank(state.questionJobId); }
  }
  if (event.target.id === "interview-language") {
    state.interviewLanguage = event.target.value;
    state.runResult = null;
    if (state.interviewSocket?.readyState === WebSocket.OPEN) {
      state.interviewSocket.send(JSON.stringify({ type: "language", language: state.interviewLanguage }));
    }
    renderWorkspace();
  }
  if (event.target.matches("[data-status]")) {
    try {
      const result = await api(`/applications/${encodeURIComponent(event.target.dataset.status)}/status`, {
        method: "PATCH", body: JSON.stringify({ status: event.target.value })
      });
      const index = state.applications.findIndex(item => String(item.id) === String(result.id));
      if (index >= 0) state.applications[index].status = result.status;
      await loadWorkspace();
      showToast("Application status updated.");
    } catch (error) { showToast(error.message, true); await loadWorkspace(); }
  }
  if (event.target.matches("[data-user-status]")) {
    try {
      const user = await api(`/admin/users/${encodeURIComponent(event.target.dataset.userStatus)}/status`, {
        method: "PATCH", body: JSON.stringify({ active: event.target.value === "true" })
      });
      const row = state.analytics.users_list.find(item => String(item.id) === String(user.id));
      if (row) row.active = Number(user.active);
      renderWorkspace();
      showToast(user.active ? "Account enabled." : "Account disabled.");
    } catch (error) { showToast(error.message, true); await loadWorkspace(); }
  }
  if (event.target.matches("[data-job-status]")) {
    try {
      const job = await api(`/admin/jobs/${encodeURIComponent(event.target.dataset.jobStatus)}/status`, {
        method: "PATCH", body: JSON.stringify({ status: event.target.value })
      });
      const row = state.adminJobs.find(item => String(item.id) === String(job.id));
      if (row) row.status = job.status;
      renderWorkspace();
      showToast(`Listing ${job.status.toLowerCase()}.`);
    } catch (error) { showToast(error.message, true); await loadWorkspace(); }
  }
});

app.addEventListener("input", event => {
  if (event.target.id !== "interview-code") return;
  state.interviewCode = event.target.value;
  clearTimeout(state.codeTimer);
  state.codeTimer = setTimeout(() => {
    if (state.interviewSocket?.readyState === WebSocket.OPEN) {
      state.interviewSocket.send(JSON.stringify({ type: "code", code: state.interviewCode }));
    }
  }, 120);
});

app.addEventListener("click", async event => {
  const target = event.target.closest("[data-action],[data-page],[data-job],[data-demo]");
  if (!target) return;
  if (target.dataset.action === "toggle-theme") {
    window.SkillSphereTheme.toggle();
    syncThemeToggle();
    return;
  }
  if (target.dataset.demo) {
    document.querySelector("#auth-email").value = target.dataset.demo;
    document.querySelector("#auth-password").value = demoPassword;
    document.querySelector("#auth-password").focus();
    return;
  }
  if (target.dataset.page) {
    event.preventDefault();
    state.page = target.dataset.page;
    state.modal = "";
    state.activeInterview = null;
    if (state.page === "Find jobs" && state.user.role === "candidate") {
      state.query = ""; state.location = ""; state.jobType = ""; state.experience = ""; state.skill = ""; state.jobPage = 1;
      try {
        const result = await api("/jobs?page_size=6");
        state.jobs = result.items || [];
        state.jobTotal = result.total;
      } catch (error) { showToast(error.message, true); }
    }
    if (state.page === "Question banks") {
      const availableJobs = state.user.role === "admin" ? state.adminJobs : state.jobs;
      state.questionJobId = state.questionJobId || String(availableJobs[0]?.id || "");
      if (state.questionJobId) {
        await loadQuestionBank(state.questionJobId);
        return;
      }
    }
    if (state.page === "Assessments") {
      await loadAssessmentList();
      return;
    }
    if (state.page === "Proctoring" && state.user.role === "admin") {
      await loadAdminProctoring({});
      return;
    }
    if (state.page === "Notifications") {
      state.notificationsLoading = true;
      state.notificationsError = "";
      renderWorkspace();
      try {
        const [notifications, unread] = await Promise.all([
          api("/notifications?page_size=50"),
          api("/notifications/unread-count")
        ]);
        state.notifications = notifications.items || [];
        state.notificationUnread = unread.unread_count || 0;
        state.notificationsLoading = false;
      } catch (error) {
        state.notificationsLoading = false;
        state.notificationsError = error.message;
      }
    }
    renderWorkspace();
    return;
  }
  if (target.dataset.job) { await openJob(target.dataset.job); return; }
  if (target.dataset.action === "schedule-interview") {
    state.scheduleCandidate = target.dataset.candidate || "Candidate";
    state.editingInterview = null;
    state.modal = `schedule:${target.dataset.id}`;
    renderWorkspace();
    return;
  }
  if (target.dataset.action === "edit-interview") {
    const application = state.applications.find(item => String(item.id) === String(target.dataset.id));
    state.scheduleCandidate = target.dataset.candidate || "Candidate";
    state.editingInterview = application?.interview || null;
    state.modal = `reschedule:${target.dataset.id}:${target.dataset.interviewId}`;
    renderWorkspace();
    return;
  }
  if (target.dataset.action === "cancel-interview" || target.dataset.action === "complete-interview") {
    const action = target.dataset.action === "cancel-interview" ? "cancel" : "complete";
    if (action === "cancel" && !window.confirm("Cancel this interview and notify the candidate?")) return;
    try {
      await api(`/applications/${encodeURIComponent(target.dataset.id)}/interviews/${encodeURIComponent(target.dataset.interviewId)}/${action}`, { method: "POST" });
      await loadWorkspace();
      showToast(action === "cancel" ? "Interview cancelled and the candidate notified." : "Interview marked completed and the candidate notified.");
    } catch (error) { showToast(error.message, true); }
    return;
  }
  if (target.dataset.action === "open-interview") { await openInterview(target.dataset.id); return; }
  if (target.dataset.action === "run-code") { await runInterviewCode(); return; }
  if (target.dataset.action === "toggle-auth") { renderAuth(app.dataset.register !== "true"); return; }
  if (target.dataset.action === "logout") { await signOut(); return; }
  if (target.dataset.action === "filter-jobs") { await searchJobs(); return; }
  if (target.dataset.action === "prev-page" || target.dataset.action === "next-page") {
    state.jobPage += target.dataset.action === "next-page" ? 1 : -1;
    await loadJobsPage();
    return;
  }
  if (target.dataset.action === "new-job") { state.modal = "new-job"; renderWorkspace(); return; }
  if (target.dataset.action === "edit-job") { state.modal = `edit-job:${target.dataset.id}`; renderWorkspace(); return; }
  if (target.dataset.action === "toggle-job-status") {
    try {
      const result = await api(`/jobs/${encodeURIComponent(target.dataset.id)}/status`, {
        method: "PATCH", body: JSON.stringify({ status: target.dataset.status })
      });
      const item = state.jobs.find(job => String(job.id) === String(result.id));
      if (item) item.status = result.status;
      renderWorkspace();
      showToast(`Listing ${result.status.toLowerCase()}.`);
    } catch (error) { showToast(error.message, true); }
    return;
  }
  if (target.dataset.action === "job-question-bank") {
    state.page = "Question banks";
    state.questionImportPreview = null;
    await loadQuestionBank(target.dataset.id);
    return;
  }
  if (target.dataset.action === "upload-question-bank") {
    const file = document.querySelector("#question-bank-pdf")?.files?.[0];
    if (!file) {
      showToast("Choose a PDF question bank to upload.", true);
      return;
    }
    const form = new FormData();
    form.set("file", file);
    try {
      state.questionImportPreview = await api(
        `/jobs/${encodeURIComponent(state.questionJobId)}/question-bank/imports`,
        { method: "POST", body: form }
      );
      await loadQuestionBank(state.questionJobId);
      showToast("Review the parsed questions before importing them.");
    } catch (error) { showToast(error.message, true); }
    return;
  }
  if (target.dataset.action === "remove-import-question") {
    const preview = state.questionImportPreview;
    if (!preview) return;
    const collection = target.dataset.kind === "valid" ? preview.valid_questions : preview.invalid_questions;
    collection.splice(Number(target.dataset.index), 1);
    renderWorkspace();
    return;
  }
  if (target.dataset.action === "cancel-question-import") {
    const preview = state.questionImportPreview;
    const importId = target.dataset.id;
    const jobId = preview?.import_id === Number(importId) ? preview.job_id : state.questionJobId;
    try {
      await api(
        `/jobs/${encodeURIComponent(jobId)}/question-bank/imports/${encodeURIComponent(importId)}`,
        { method: "DELETE" }
      );
      if (preview && String(preview.import_id) === String(importId)) state.questionImportPreview = null;
      await loadQuestionBank(jobId);
      showToast("Question-bank import cancelled.");
    } catch (error) { showToast(error.message, true); }
    return;
  }
  if (target.dataset.action === "new-question") {
    state.editingQuestion = null;
    state.modal = "question";
    renderWorkspace();
    return;
  }
  if (target.dataset.action === "edit-question") {
    state.editingQuestion = state.jobQuestions.find(question => String(question.id) === String(target.dataset.id)) || null;
    state.modal = "question";
    renderWorkspace();
    return;
  }
  if (target.dataset.action === "delete-question") {
    if (!window.confirm("Delete this question? Active and in-progress assessments retain their saved question snapshots.")) return;
    try {
      await api(`/jobs/${encodeURIComponent(state.questionJobId)}/questions/${encodeURIComponent(target.dataset.id)}`, { method: "DELETE" });
      await loadQuestionBank(state.questionJobId);
      showToast("Question deleted.");
    } catch (error) { showToast(error.message, true); }
    return;
  }
  if (target.dataset.action === "filter-questions") {
    const active = document.querySelector("#question-filter-active")?.value;
    await loadQuestionBank(state.questionJobId, {
      technology: document.querySelector("#question-filter-technology")?.value || "",
      difficulty: document.querySelector("#question-filter-difficulty")?.value || "",
      active
    });
    return;
  }
  if (target.dataset.action === "filter-assessments") {
    await loadAssessmentList({
      job_id: document.querySelector("#assessment-filter-job")?.value || "",
      candidate: document.querySelector("#assessment-filter-candidate")?.value.trim() || "",
      status: document.querySelector("#assessment-filter-status")?.value || "",
      application_stage: document.querySelector("#assessment-filter-stage")?.value || "",
      technology: document.querySelector("#assessment-filter-technology")?.value.trim() || "",
      start_date: document.querySelector("#assessment-filter-start")?.value || "",
      end_date: document.querySelector("#assessment-filter-end")?.value || "",
      result: document.querySelector("#assessment-filter-result")?.value || "",
      score_min: document.querySelector("#assessment-filter-score-min")?.value || "",
      score_max: document.querySelector("#assessment-filter-score-max")?.value || ""
    });
    return;
  }
  if (target.dataset.action === "filter-proctoring") {
    await loadAdminProctoring({
      job_id: document.querySelector("#proctoring-filter-job")?.value || "",
      recruiter_id: document.querySelector("#proctoring-filter-recruiter")?.value || "",
      candidate: document.querySelector("#proctoring-filter-candidate")?.value.trim() || "",
      start_date: document.querySelector("#proctoring-filter-start")?.value || "",
      end_date: document.querySelector("#proctoring-filter-end")?.value || "",
      assessment_status: document.querySelector("#proctoring-filter-status")?.value || "",
      flagged: document.querySelector("#proctoring-filter-flagged")?.value ?? ""
    });
    return;
  }
  if (target.dataset.action === "refresh-analytics") { await loadAdminAnalytics(); return; }
  if (target.dataset.action === "review-assessment") { await openAssessmentReview(target.dataset.id); return; }
  if (target.dataset.action === "close-assessment-review") { state.assessmentReview = null; renderWorkspace(); return; }
  if (target.dataset.action === "review-proctoring") { await openProctoringReview(target.dataset.id); return; }
  if (target.dataset.action === "close-proctoring-review") { state.proctoringReview = null; renderWorkspace(); return; }
  if (target.dataset.action === "save-note") {
    const note = document.querySelector(`[data-note="${CSS.escape(target.dataset.id)}"]`)?.value || "";
    try {
      await api(`/applications/${encodeURIComponent(target.dataset.id)}/notes`, {
        method: "PATCH", body: JSON.stringify({ note })
      });
      await loadWorkspace();
      showToast("Internal note saved; candidates cannot see it.");
    } catch (error) { showToast(error.message, true); }
    return;
  }
  if (target.dataset.action === "mark-notification-read") {
    try {
      await api(`/notifications/${encodeURIComponent(target.dataset.id)}/read`, { method: "PATCH" });
      state.notifications = state.notifications.map(item => String(item.id) === String(target.dataset.id) ? { ...item, is_read: 1 } : item);
      state.notificationUnread = Math.max(0, state.notificationUnread - 1);
      renderWorkspace();
    } catch (error) { showToast(error.message, true); }
    return;
  }
  if (target.dataset.action === "mark-all-read") {
    try {
      await api("/notifications/read-all", { method: "PATCH" });
      state.notifications = state.notifications.map(item => ({ ...item, is_read: 1 }));
      state.notificationUnread = 0;
      renderWorkspace();
    } catch (error) { showToast(error.message, true); }
    return;
  }
  if (target.dataset.action === "close-modal") {
    if (target.classList.contains("modal-backdrop") && event.target !== target) return;
    state.modal = "";
    renderWorkspace();
    return;
  }
  if (target.dataset.action === "apply-job") { await applyToJob(target.dataset.id); }
  if (target.dataset.action === "download-resume") { await downloadApplicantResume(target.dataset.id); }
  if (target.dataset.action === "download-own-resume") {
    await downloadPrivateResume("/resume/download", "my-resume");
    return;
  }
  if (target.dataset.action === "send-assessment") {
    if (target.textContent.trim() === "Re-send link" && !window.confirm("Send a new link and invalidate the previous unused link?")) return;
    const topicSelect = document.querySelector(`[data-assessment-topic="${CSS.escape(target.dataset.id)}"]`);
    const technology = topicSelect?.value || "";
    if (topicSelect && !technology) {
      topicSelect.focus();
      showToast("Choose an assessment topic before sending the invitation.", true);
      return;
    }
    try {
      const invitation = await api(`/applications/${encodeURIComponent(target.dataset.id)}/assessment/send`, {
        method: "POST",
        body: JSON.stringify(technology ? { technology } : {})
      });
      await loadWorkspace();
      showToast(
        invitation.delivery === "development_console"
          ? `Assessment link sent to the candidate’s registered email and logged in the backend console.`
          : `Assessment invitation sent for ${invitation.technology}.`,
        false
      );
    } catch (error) { showToast(error.message, true); }
  }
  if (target.dataset.action === "resend-candidate-assessment") {
    if (!window.confirm("Send a fresh assessment link to your registered email? Any previous unused link will stop working.")) return;
    try {
      const result = await api(`/assessments/${encodeURIComponent(target.dataset.id)}/resend-link`, { method: "POST" });
      await loadWorkspace();
      showToast(result.delivery === "development_console"
        ? "A new link was logged in the backend console for delivery to your registered email."
        : "A new assessment link was emailed to your registered address.");
    } catch (error) { showToast(error.message, true); }
    return;
  }
  if (target.dataset.action === "withdraw") {
    try {
      const result = await api(`/applications/${encodeURIComponent(target.dataset.id)}/withdraw`, { method: "PATCH" });
      const row = state.applications.find(item => String(item.id) === String(result.id));
      if (row) row.status = result.status;
      renderWorkspace();
      showToast("Application withdrawn.");
    } catch (error) { showToast(error.message, true); }
  }
  if (target.dataset.action === "check-match") {
    try {
      state.match = await api(`/matches/${encodeURIComponent(target.dataset.id)}`);
      renderWorkspace();
    } catch (error) { showToast(error.message, true); }
  }
});

app.addEventListener("keydown", event => {
  if (event.target.id === "job-query" && event.key === "Enter") searchJobs();
  if (event.key === "Escape" && state.modal) { state.modal = ""; renderWorkspace(); }
});

async function start() {
  try {
    const result = await api("/me");
    state.user = result;
    await loadWorkspace();
  } catch (error) {
    saveToken("");
    renderAuth();
    if (!/sign in|token|authentication|authorization|expired/i.test(error.message)) {
      showToast(`Could not restore your session: ${error.message}`, true);
    }
  }
}

start();
