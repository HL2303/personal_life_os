"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  Category,
  Project,
  ProjectInput,
  deleteProject,
  getAuthSession,
  getCategories,
  getProjects,
  logout,
  saveProject,
} from "@/lib/api";
import styles from "../page.module.css";

type ProjectForm = {
  title: string;
  description: string;
  category_id: string;
  status: ProjectInput["status"];
  priority: ProjectInput["priority"];
  start_date: string;
  target_date: string;
};

function blankProject(): ProjectForm {
  return {
    title: "",
    description: "",
    category_id: "",
    status: "active",
    priority: "medium",
    start_date: new Date().toISOString().slice(0, 10),
    target_date: "",
  };
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(`${value}T12:00:00`));
}

export default function ProjectsPage() {
  const [username, setUsername] = useState("");
  const [authenticated, setAuthenticated] = useState(false);
  const [authLoading, setAuthLoading] = useState(true);
  const [projects, setProjects] = useState<Project[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Project | null>(null);
  const [form, setForm] = useState<ProjectForm>(blankProject());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getAuthSession()
      .then((session) => {
        setUsername(session.username);
        setAuthenticated(true);
      })
      .catch(() => window.location.assign("/"))
      .finally(() => setAuthLoading(false));
    getCategories().then(setCategories).catch(() => undefined);
  }, []);

  async function loadProjects() {
    setLoading(true);
    try {
      setProjects(await getProjects(includeArchived));
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load projects.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (authenticated) void loadProjects();
  // loadProjects tracks the archive filter.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authenticated, includeArchived]);

  const active = useMemo(() => projects.filter((project) => project.status === "active"), [projects]);
  const overdue = active.filter(
    (project) => project.target_date && project.target_date < new Date().toISOString().slice(0, 10),
  );
  const upcoming = active.filter((project) => {
    if (!project.target_date || project.target_date < new Date().toISOString().slice(0, 10)) return false;
    return new Date(`${project.target_date}T12:00:00`).getTime() - Date.now() <= 7 * 86400000;
  });

  function openCreate() {
    setEditing(null);
    setForm(blankProject());
    setFormOpen(true);
    setError("");
  }

  function openEdit(project: Project) {
    setEditing(project);
    setForm({
      title: project.title,
      description: project.description ?? "",
      category_id: project.category_id ? String(project.category_id) : "",
      status: project.status,
      priority: project.priority,
      start_date: project.start_date,
      target_date: project.target_date ?? "",
    });
    setFormOpen(true);
    setError("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    const input: ProjectInput = {
      title: form.title.trim(),
      description: form.description.trim() || null,
      category_id: form.category_id ? Number(form.category_id) : null,
      status: form.status,
      priority: form.priority,
      start_date: form.start_date,
      target_date: form.target_date || null,
    };
    try {
      await saveProject(input, editing?.id);
      setFormOpen(false);
      setEditing(null);
      await loadProjects();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save this project.");
    } finally {
      setBusy(false);
    }
  }

  async function archive(project: Project) {
    try {
      await saveProject({ status: "archived" }, project.id);
      await loadProjects();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not archive this project.");
    }
  }

  async function remove(project: Project) {
    if (!window.confirm(`Delete "${project.title}"? Its linked activities will remain and be unassigned.`)) return;
    try {
      await deleteProject(project.id);
      await loadProjects();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete this project.");
    }
  }

  async function signOut() {
    try {
      await logout();
    } finally {
      window.location.assign("/");
    }
  }

  if (authLoading || !authenticated) {
    return <main className={styles.loadingState}>{authLoading ? "Checking your session…" : "Redirecting…"}</main>;
  }

  return (
    <main className={styles.app}>
      <aside className={styles.sidebar}>
        <a className={styles.brand} href="/" aria-label="Personal Life OS home"><span className={styles.brandMark}>p</span><span>personal<span className={styles.brandLight}>life</span></span></a>
        <div className={styles.sideLabel}>YOUR SPACE</div>
        <a className={styles.navItem} href="/">◷ Activity</a>
        <a className={styles.navItem} href="/analytics">▥ Analytics</a>
        <a className={styles.navItem} href="/goals">◎ Goals</a>
        <a className={`${styles.navItem} ${styles.navActive}`} href="/projects">▣ Projects</a>
        <div className={styles.sidebarFoot}><span className={styles.avatar}>P</span><span className={styles.accountName}><strong>{username}</strong><small>Personal space</small></span><button className={styles.logoutButton} onClick={signOut}>Sign out</button></div>
      </aside>
      <section className={styles.workspace}>
        <header className={styles.topbar}><span className={styles.breadcrumb}>My space <span>/</span> Projects</span><div className={styles.topbarActions}><a className={styles.manageButton} href="/goals">Goals</a></div></header>
        <div className={styles.content}>
          <div className={styles.headingRow}>
            <div><p className={styles.eyebrow}>TURN PLANS INTO MILESTONES</p><h1>Projects</h1><p className={styles.subtitle}>Project progress is completed milestones divided by all milestones.</p></div>
            <button className={styles.primaryButton} onClick={openCreate}>＋ New project</button>
          </div>
          {error && <div className={styles.errorBanner} role="alert">{error}<button onClick={() => setError("")}>×</button></div>}
          <section className={styles.focusSummary}>
            <article><span>ACTIVE PROJECTS</span><strong>{active.length}</strong></article>
            <article><span>OVERDUE TARGETS</span><strong className={overdue.length ? styles.overdueText : ""}>{overdue.length}</strong></article>
            <article><span>DUE IN 7 DAYS</span><strong>{upcoming.length}</strong></article>
            <a href="/goals"><span>ACTIVE GOALS</span><strong>View goals →</strong></a>
          </section>
          <div className={styles.moduleToolbar}><p>{includeArchived ? "Including archived projects" : "Current projects"}</p><label><input type="checkbox" checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} /> Show archived</label></div>
          {loading ? <div className={styles.loadingState}>Loading your projects…</div> : projects.length === 0 ? (
            <section className={styles.moduleEmpty}><span>▣</span><h2>No projects yet</h2><p>Bring a project into focus by adding milestones and associating related activities.</p><button className={styles.primaryButton} onClick={openCreate}>Create a project</button></section>
          ) : (
            <div className={styles.goalGrid}>
              {projects.map((project) => (
                <article className={styles.moduleCard} key={project.id}>
                  <div className={styles.moduleCardTop}><div><span className={`${styles.statusBadge} ${styles[`status_${project.status}`]}`}>{project.status}</span><span className={styles.goalType}>{project.priority} priority</span></div><div className={styles.moduleCardActions}><button onClick={() => openEdit(project)}>Edit</button>{project.status !== "archived" && <button onClick={() => void archive(project)}>Archive</button>}<button className={styles.textDanger} onClick={() => void remove(project)}>Delete</button></div></div>
                  <a className={styles.projectCardLink} href={`/projects/${project.id}`}><h2>{project.title}</h2></a>
                  {project.description && <p className={styles.moduleDescription}>{project.description}</p>}
                  <div className={styles.progressLabel}><strong>{project.progress_percent}%</strong><span>{project.completed_milestone_count} of {project.milestone_count} milestones</span></div>
                  <div className={styles.progressTrack}><i style={{ width: `${project.progress_percent}%` }} /></div>
                  <div className={styles.goalMeta}><span>{project.category_name ?? "Uncategorized"}</span><span>{project.target_date ? `Target · ${formatDate(project.target_date)}` : `Started · ${formatDate(project.start_date)}`}</span></div>
                  <p className={styles.analyticsNote}>Progress formula: completed milestones ÷ all milestones. With no milestones, progress is 0%.</p>
                  <a className={styles.projectDetailLink} href={`/projects/${project.id}`}>Open project details →</a>
                </article>
              ))}
            </div>
          )}
          <footer className={styles.footer}>Your time, thoughtfully accounted for.</footer>
        </div>
      </section>
      {formOpen && <div className={styles.modalBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setFormOpen(false); }}>
        <section className={styles.editor} role="dialog" aria-modal="true" aria-labelledby="project-form-title">
          <div className={styles.modalHeader}><div><p className={styles.eyebrow}>{editing ? "UPDATE YOUR PROJECT" : "START SOMETHING"} </p><h2 id="project-form-title">{editing ? "Edit project" : "Create a project"}</h2></div><button className={styles.iconButton} onClick={() => setFormOpen(false)}>×</button></div>
          <form className={styles.activityForm} onSubmit={(event) => void submit(event)}>
            <label className={styles.field}><span>Project title</span><input required maxLength={200} autoFocus value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label>
            <label className={styles.field}><span>Description <small>Optional</small></span><textarea rows={3} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
            <div className={styles.formGrid}>
              <label className={styles.field}><span>Category</span><select value={form.category_id} onChange={(event) => setForm({ ...form, category_id: event.target.value })}><option value="">None</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
              <label className={styles.field}><span>Priority</span><select value={form.priority} onChange={(event) => setForm({ ...form, priority: event.target.value as ProjectForm["priority"] })}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label>
            </div>
            <div className={styles.formGrid}>
              <label className={styles.field}><span>Start date</span><input type="date" required value={form.start_date} onChange={(event) => setForm({ ...form, start_date: event.target.value })} /></label>
              <label className={styles.field}><span>Target date <small>Optional</small></span><input type="date" value={form.target_date} onChange={(event) => setForm({ ...form, target_date: event.target.value })} /></label>
            </div>
            {editing && <label className={styles.field}><span>Status</span><select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value as ProjectForm["status"] })}><option value="active">Active</option><option value="paused">Paused</option><option value="completed">Completed</option><option value="archived">Archived</option></select></label>}
            <div className={styles.formActions}><button type="button" className={styles.secondaryButton} onClick={() => setFormOpen(false)}>Cancel</button><button className={styles.primaryButton} disabled={busy}>{busy ? "Saving…" : editing ? "Save changes" : "Create project"}</button></div>
            {error && <div className={styles.dialogError} role="alert">{error}</div>}
          </form>
        </section>
      </div>}
    </main>
  );
}
