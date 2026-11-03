"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRouter } from "next/navigation";

import {
  ProjectDetail,
  createProjectMilestone,
  deleteProjectMilestone,
  getProject,
  logout,
  updateProjectMilestone,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import styles from "../../page.module.css";

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(`${value}T12:00:00`));
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function duration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours}h ${minutes % 60}m` : `${minutes}m`;
}

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const projectId = Number(params.id);
  const auth = useAuth();
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState("");
  const [milestoneTitle, setMilestoneTitle] = useState("");
  const [milestoneDue, setMilestoneDue] = useState("");

  async function loadProject() {
    try {
      setProject(await getProject(projectId));
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load this project.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (auth.status === "unauthenticated") router.replace("/");
  }, [auth.status, router]);

  useEffect(() => {
    if (auth.status === "authenticated" && Number.isInteger(projectId) && projectId > 0) {
      void loadProject();
    }
  // loadProject is scoped to the current route id.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.status, projectId]);

  async function addMilestone(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!project || !milestoneTitle.trim()) return;
    try {
      await createProjectMilestone(project.id, {
        title: milestoneTitle.trim(),
        due_date: milestoneDue || null,
      });
      setMilestoneTitle("");
      setMilestoneDue("");
      await loadProject();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not add milestone.");
    }
  }

  async function toggleMilestone(milestoneId: number, completed: boolean) {
    if (!project) return;
    try {
      await updateProjectMilestone(project.id, milestoneId, completed);
      await loadProject();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update milestone.");
    }
  }

  async function removeMilestone(milestoneId: number) {
    if (!project || !window.confirm("Delete this project milestone?")) return;
    try {
      await deleteProjectMilestone(project.id, milestoneId);
      await loadProject();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete milestone.");
    }
  }

  async function signOut() {
    let signOutError = "";
    try {
      await logout();
    } catch (cause) {
      signOutError = cause instanceof Error ? cause.message : "Could not sign out.";
    }
    auth.clearSession(signOutError);
    router.replace("/");
  }

  if (auth.status !== "authenticated" || loading) {
    return <main className={styles.loadingState}>{auth.status === "checking" ? "Checking your secure session…" : auth.status === "unauthenticated" ? "Redirecting…" : "Loading project…"}</main>;
  }

  return (
    <main className={styles.app}>
      <aside className={styles.sidebar}>
        <Link className={styles.brand} href="/" aria-label="Personal Life OS home"><span className={styles.brandMark}>p</span><span>personal<span className={styles.brandLight}>life</span></span></Link>
        <div className={styles.sideLabel}>YOUR SPACE</div>
        <Link className={styles.navItem} href="/">◷ Activity</Link>
        <Link className={styles.navItem} href="/analytics">▥ Analytics</Link>
        <Link className={styles.navItem} href="/goals">◎ Goals</Link>
        <Link className={`${styles.navItem} ${styles.navActive}`} href="/projects">▣ Projects</Link>
        <div className={styles.sidebarFoot}><span className={styles.avatar}>P</span><span className={styles.accountName}><strong>{auth.username}</strong><small>Personal space</small></span><button className={styles.logoutButton} onClick={signOut}>Sign out</button></div>
      </aside>
      <section className={styles.workspace}>
        <header className={styles.topbar}><span className={styles.breadcrumb}><Link href="/projects">Projects</Link><span>/</span>{project?.title ?? "Project"}</span><div className={styles.topbarActions}><Link className={styles.manageButton} href="/projects">All projects</Link></div></header>
        <div className={styles.content}>
          {error && <div className={styles.errorBanner} role="alert">{error}<button onClick={() => setError("")}>×</button></div>}
          {!project ? <section className={styles.moduleEmpty}><h2>Project unavailable</h2><p>{error || "This project could not be found."}</p><Link className={styles.secondaryButton} href="/projects">Back to projects</Link></section> : <>
            <div className={styles.headingRow}>
              <div><p className={styles.eyebrow}>PROJECT DETAIL · {project.priority.toUpperCase()} PRIORITY</p><h1>{project.title}</h1><p className={styles.subtitle}>{project.description || "A focused space for milestones and related activity."}</p></div>
              <span className={`${styles.statusBadge} ${styles[`status_${project.status}`]}`}>{project.status}</span>
            </div>
            <section className={styles.focusSummary}>
              <article><span>MILESTONE PROGRESS</span><strong>{project.progress_percent}%</strong></article>
              <article><span>COMPLETED</span><strong>{project.completed_milestone_count}/{project.milestone_count}</strong></article>
              <article><span>STARTED</span><strong>{formatDate(project.start_date)}</strong></article>
              <article><span>TARGET</span><strong>{project.target_date ? formatDate(project.target_date) : "Not set"}</strong></article>
            </section>
            <section className={styles.analyticsPanel}>
              <div className={styles.analyticsPanelHeading}><div><p className={styles.eyebrow}>DELIVERABLES</p><h2>Milestones</h2></div><span>Completed milestones ÷ all milestones</span></div>
              <div className={styles.milestoneSection}>
                {project.milestones.map((milestone) => <div className={styles.projectMilestoneRow} key={milestone.id}>
                  <label className={styles.milestoneRow}><input type="checkbox" checked={milestone.completed} onChange={(event) => void toggleMilestone(milestone.id, event.target.checked)} /><span>{milestone.title}{milestone.description && <small>{milestone.description}</small>}</span>{milestone.due_date && <small>{formatDate(milestone.due_date)}</small>}</label>
                  <button className={styles.textDanger} onClick={() => void removeMilestone(milestone.id)}>Delete</button>
                </div>)}
                {project.milestones.length === 0 && <p className={styles.analyticsEmpty}>No milestones yet. Progress is 0% until milestones are added.</p>}
                {project.status !== "archived" && <form className={styles.projectMilestoneForm} onSubmit={(event) => void addMilestone(event)}>
                  <input required maxLength={200} placeholder="Milestone title" value={milestoneTitle} onChange={(event) => setMilestoneTitle(event.target.value)} />
                  <label>Due date <input type="date" min={project.start_date} max={project.target_date ?? undefined} value={milestoneDue} onChange={(event) => setMilestoneDue(event.target.value)} /></label>
                  <button className={styles.primaryButton}>Add milestone</button>
                </form>}
              </div>
            </section>
            <section className={styles.analyticsPanel}>
              <div className={styles.analyticsPanelHeading}><div><p className={styles.eyebrow}>TIME LOG</p><h2>Associated activities</h2></div><Link className={styles.manageButton} href="/">Open activity log</Link></div>
              {project.activities.length ? <div className={styles.drilldownList}>{project.activities.map((activity) => <article className={styles.drilldownItem} key={activity.id}><div><strong>{activity.title}</strong><span>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(activity.started_at))} · {formatTime(activity.started_at)}–{formatTime(activity.ended_at)} · {activity.category.name}</span></div><small>{duration(activity.duration_seconds)}</small></article>)}</div> : <p className={styles.analyticsEmpty}>No activities are associated with this project yet. Choose the project when logging an activity.</p>}
              {project.activities.length === 100 && <p className={styles.analyticsNote}>Showing the latest 100 activities associated with this project.</p>}
            </section>
          </>}
          <footer className={styles.footer}>Your time, thoughtfully accounted for.</footer>
        </div>
      </section>
    </main>
  );
}
