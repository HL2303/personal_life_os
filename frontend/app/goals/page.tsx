"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  Category,
  Goal,
  GoalInput,
  createGoalMilestone,
  deleteGoal,
  getCategories,
  getGoals,
  logout,
  saveGoal,
  updateGoalMilestone,
  updateGoalProgress,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import styles from "../page.module.css";

type GoalForm = {
  title: string;
  description: string;
  category_id: string;
  goal_type: GoalInput["goal_type"];
  target_value: string;
  current_value: string;
  unit: string;
  recurring_period: "weekly" | "monthly";
  start_date: string;
  deadline: string;
  status: GoalInput["status"];
};

const today = () => new Date().toISOString().slice(0, 10);

function blankGoal(): GoalForm {
  const date = today();
  return {
    title: "",
    description: "",
    category_id: "",
    goal_type: "measurable",
    target_value: "",
    current_value: "0",
    unit: "hours",
    recurring_period: "weekly",
    start_date: date,
    deadline: date,
    status: "active",
  };
}

function goalForm(goal?: Goal): GoalForm {
  if (!goal) return blankGoal();
  return {
    title: goal.title,
    description: goal.description ?? "",
    category_id: goal.category_id ? String(goal.category_id) : "",
    goal_type: goal.goal_type,
    target_value: goal.target_value === null ? "" : String(goal.target_value),
    current_value: goal.current_value === null ? "0" : String(goal.current_value),
    unit: goal.unit ?? "",
    recurring_period: goal.recurring_period ?? "weekly",
    start_date: goal.start_date,
    deadline: goal.deadline,
    status: goal.status,
  };
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(`${value}T12:00:00`));
}

function formatValue(value: number | null, unit: string | null) {
  if (value === null) return "Milestones";
  return `${Number.isInteger(value) ? value : value.toFixed(2)} ${unit ?? ""}`.trim();
}

export default function GoalsPage() {
  const auth = useAuth();
  const router = useRouter();
  const [goals, setGoals] = useState<Goal[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [editing, setEditing] = useState<Goal | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<GoalForm>(blankGoal());
  const [busy, setBusy] = useState(false);
  const [progressDrafts, setProgressDrafts] = useState<Record<number, string>>({});
  const [milestoneDrafts, setMilestoneDrafts] = useState<Record<number, string>>({});

  useEffect(() => {
    if (auth.status === "unauthenticated") router.replace("/");
  }, [auth.status, router]);

  useEffect(() => {
    if (auth.status !== "authenticated") return;
    getCategories()
      .then(setCategories)
      .catch((cause: unknown) =>
        setError(cause instanceof Error ? cause.message : "Could not load categories."),
      );
  }, [auth.status]);

  async function loadGoals() {
    setLoading(true);
    setError("");
    try {
      setGoals(await getGoals(includeArchived));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load goals.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (auth.status === "authenticated") void loadGoals();
  // loadGoals is intentionally refreshed by the archive filter.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.status, includeArchived]);

  const activeGoals = useMemo(() => goals.filter((goal) => goal.status === "active"), [goals]);
  const overdueGoals = activeGoals.filter((goal) => goal.overdue);
  const upcomingGoals = activeGoals.filter(
    (goal) => !goal.overdue && new Date(`${goal.deadline}T12:00:00`).getTime() - Date.now() <= 7 * 86400000,
  );
  const recurringDescription = form.goal_type === "recurring"
    ? `Target repeats every ${form.recurring_period === "weekly" ? "week" : "month"}. Progress is manually recorded for the current goal.`
    : form.goal_type === "milestone"
      ? "Progress is calculated from completed milestones; activities are never used automatically."
      : "Progress is updated manually; unrelated activity records are never counted.";

  function openCreate() {
    setEditing(null);
    setForm(blankGoal());
    setError("");
    setFormOpen(true);
  }

  function openEdit(goal: Goal) {
    setEditing(goal);
    setForm(goalForm(goal));
    setError("");
    setFormOpen(true);
  }

  async function submitGoal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const goalInput: GoalInput = {
      title: form.title.trim(),
      description: form.description.trim() || null,
      category_id: form.category_id ? Number(form.category_id) : null,
      goal_type: form.goal_type,
      target_value: form.goal_type === "milestone" ? null : Number(form.target_value),
      current_value: form.goal_type === "milestone" ? null : Number(form.current_value || 0),
      unit: form.goal_type === "milestone" ? null : form.unit.trim(),
      recurring_period: form.goal_type === "recurring" ? form.recurring_period : null,
      start_date: form.start_date,
      deadline: form.deadline,
      status: form.status,
    };
    try {
      await saveGoal(goalInput, editing?.id);
      setEditing(null);
      setFormOpen(false);
      await loadGoals();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save this goal.");
    } finally {
      setBusy(false);
    }
  }

  async function archiveGoal(goal: Goal) {
    try {
      await saveGoal({ status: "archived" }, goal.id);
      await loadGoals();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not archive this goal.");
    }
  }

  async function removeGoal(goal: Goal) {
    if (!window.confirm(`Permanently delete "${goal.title}" and its progress history?`)) return;
    try {
      await deleteGoal(goal.id);
      await loadGoals();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete this goal.");
    }
  }

  async function submitProgress(event: FormEvent<HTMLFormElement>, goal: Goal) {
    event.preventDefault();
    const value = Number(progressDrafts[goal.id] ?? goal.current_value ?? 0);
    try {
      const updated = await updateGoalProgress(goal.id, value);
      setGoals((current) => current.map((item) => item.id === goal.id ? updated : item));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update goal progress.");
    }
  }

  async function addMilestone(event: FormEvent<HTMLFormElement>, goal: Goal) {
    event.preventDefault();
    const title = milestoneDrafts[goal.id]?.trim();
    if (!title) return;
    try {
      const updated = await createGoalMilestone(goal.id, { title });
      setGoals((current) => current.map((item) => item.id === goal.id ? updated : item));
      setMilestoneDrafts((current) => ({ ...current, [goal.id]: "" }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not add milestone.");
    }
  }

  async function toggleMilestone(goal: Goal, milestoneId: number, completed: boolean) {
    try {
      const updated = await updateGoalMilestone(goal.id, milestoneId, completed);
      setGoals((current) => current.map((item) => item.id === goal.id ? updated : item));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update milestone.");
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

  if (auth.status !== "authenticated") {
    return <main className={styles.loadingState}>{auth.status === "checking" ? "Checking your secure session…" : "Redirecting…"}</main>;
  }

  return (
    <main className={styles.app}>
      <aside className={styles.sidebar}>
        <Link className={styles.brand} href="/" aria-label="Personal Life OS home"><span className={styles.brandMark}>p</span><span>personal<span className={styles.brandLight}>life</span></span></Link>
        <div className={styles.sideLabel}>YOUR SPACE</div>
        <Link className={styles.navItem} href="/">◷ Activity</Link>
        <Link className={styles.navItem} href="/analytics">▥ Analytics</Link>
        <Link className={`${styles.navItem} ${styles.navActive}`} href="/goals">◎ Goals</Link>
        <Link className={styles.navItem} href="/projects">▣ Projects</Link>
        <div className={styles.sidebarFoot}><span className={styles.avatar}>P</span><span className={styles.accountName}><strong>{auth.username}</strong><small>Personal space</small></span><button className={styles.logoutButton} onClick={signOut}>Sign out</button></div>
      </aside>
      <section className={styles.workspace}>
        <header className={styles.topbar}><span className={styles.breadcrumb}>My space <span>/</span> Goals</span><div className={styles.topbarActions}><Link className={styles.manageButton} href="/projects">Projects</Link></div></header>
        <div className={styles.content}>
          <div className={styles.headingRow}>
            <div><p className={styles.eyebrow}>MAKE PROGRESS INTENTIONAL</p><h1>Goals</h1><p className={styles.subtitle}>Track progress you choose to record. Activities are never inferred.</p></div>
            <button className={styles.primaryButton} onClick={openCreate}>＋ New goal</button>
          </div>
          {error && <div className={styles.errorBanner} role="alert">{error}<button onClick={() => setError("")}>×</button></div>}
          <section className={styles.focusSummary}>
            <article><span>ACTIVE GOALS</span><strong>{activeGoals.length}</strong></article>
            <article><span>OVERDUE</span><strong className={overdueGoals.length ? styles.overdueText : ""}>{overdueGoals.length}</strong></article>
            <article><span>DUE IN 7 DAYS</span><strong>{upcomingGoals.length}</strong></article>
            <Link href="/projects"><span>ACTIVE PROJECTS</span><strong>View projects →</strong></Link>
          </section>
          <div className={styles.moduleToolbar}>
            <p>{includeArchived ? "Including archived goals" : "Active, paused and completed goals"}</p>
            <label><input type="checkbox" checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} /> Show archived</label>
          </div>
          {loading ? <div className={styles.loadingState}>Loading your goals…</div> : goals.length === 0 ? (
            <section className={styles.moduleEmpty}><span>◎</span><h2>No goals yet</h2><p>Create a measurable, recurring, or milestone-based goal to get started.</p><button className={styles.primaryButton} onClick={openCreate}>Create a goal</button></section>
          ) : (
            <div className={styles.goalGrid}>
              {goals.map((goal) => (
                <article className={styles.moduleCard} key={goal.id}>
                  <div className={styles.moduleCardTop}>
                    <div><span className={`${styles.statusBadge} ${styles[`status_${goal.status}`]}`}>{goal.status}</span><span className={styles.goalType}>{goal.goal_type === "recurring" ? `Recurring · ${goal.recurring_period}` : goal.goal_type}</span></div>
                    <div className={styles.moduleCardActions}><button onClick={() => openEdit(goal)}>Edit</button>{goal.status !== "archived" && <button onClick={() => void archiveGoal(goal)}>Archive</button>}<button className={styles.textDanger} onClick={() => void removeGoal(goal)}>Delete</button></div>
                  </div>
                  <h2>{goal.title}</h2>
                  {goal.description && <p className={styles.moduleDescription}>{goal.description}</p>}
                  <div className={styles.progressLabel}><strong>{goal.progress_percent}%</strong><span>{goal.goal_type === "milestone" ? `${goal.milestones.filter((item) => item.completed).length}/${goal.milestones.length} milestones complete` : `${formatValue(goal.current_value, goal.unit)} of ${formatValue(goal.target_value, goal.unit)}`}</span></div>
                  <div className={styles.progressTrack}><i style={{ width: `${goal.progress_percent}%` }} /></div>
                  <div className={styles.goalMeta}><span>{goal.category_name ?? "Uncategorized"}</span><span className={goal.overdue ? styles.overdueText : ""}>{goal.overdue ? "Overdue · " : "Deadline · "}{formatDate(goal.deadline)}</span></div>
                  {goal.goal_type !== "milestone" && goal.status !== "archived" && (
                    <form className={styles.progressForm} onSubmit={(event) => void submitProgress(event, goal)}>
                      <label>Update progress <input type="number" min="0" max={goal.target_value ?? undefined} step="0.01" value={progressDrafts[goal.id] ?? goal.current_value ?? 0} onChange={(event) => setProgressDrafts((current) => ({ ...current, [goal.id]: event.target.value }))} /></label>
                      <button className={styles.secondaryButton}>Save</button>
                    </form>
                  )}
                  {goal.goal_type === "milestone" && goal.status !== "archived" && (
                    <div className={styles.milestoneSection}>
                      {goal.milestones.map((milestone) => <label className={styles.milestoneRow} key={milestone.id}><input type="checkbox" checked={milestone.completed} onChange={(event) => void toggleMilestone(goal, milestone.id, event.target.checked)} /><span>{milestone.title}</span>{milestone.due_date && <small>{formatDate(milestone.due_date)}</small>}</label>)}
                      <form className={styles.inlineAddForm} onSubmit={(event) => void addMilestone(event, goal)}><input required maxLength={200} placeholder="Add a milestone" value={milestoneDrafts[goal.id] ?? ""} onChange={(event) => setMilestoneDrafts((current) => ({ ...current, [goal.id]: event.target.value }))} /><button>＋</button></form>
                    </div>
                  )}
                  <details className={styles.historyDetails}><summary>Progress history ({goal.progress_history.length})</summary><div>{goal.progress_history.length ? goal.progress_history.map((item, index) => <p key={`${item.recorded_at}-${index}`}><span>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(item.recorded_at))}</span><strong>{formatValue(item.current_value, goal.unit)}</strong>{item.note && <small>{item.note}</small>}</p>) : <small>No progress updates yet.</small>}</div></details>
                </article>
              ))}
            </div>
          )}
          <footer className={styles.footer}>Your time, thoughtfully accounted for.</footer>
        </div>
      </section>
      {formOpen && (
        <div className={styles.modalBackdrop} role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget && !busy) setFormOpen(false);
        }}>
          <section className={styles.editor} role="dialog" aria-modal="true" aria-labelledby="goal-form-title">
            <div className={styles.modalHeader}><div><p className={styles.eyebrow}>{editing ? "UPDATE YOUR PLAN" : "SET YOUR INTENTION"}</p><h2 id="goal-form-title">{editing ? "Edit goal" : "Create a goal"}</h2></div><button className={styles.iconButton} onClick={() => { setEditing(null); setFormOpen(false); setError(""); }}>×</button></div>
            <form className={styles.activityForm} onSubmit={(event) => void submitGoal(event)}>
              <label className={styles.field}><span>Goal title</span><input required maxLength={200} autoFocus value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label>
              <label className={styles.field}><span>Description <small>Optional</small></span><textarea rows={2} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
              <div className={styles.formGrid}>
                <label className={styles.field}><span>Goal type</span><select value={form.goal_type} onChange={(event) => setForm({ ...form, goal_type: event.target.value as GoalForm["goal_type"] })}><option value="measurable">Measurable target</option><option value="recurring">Recurring target</option><option value="milestone">Milestone-based</option></select></label>
                <label className={styles.field}><span>Category <small>Optional</small></span><select value={form.category_id} onChange={(event) => setForm({ ...form, category_id: event.target.value })}><option value="">None</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
              </div>
              {form.goal_type !== "milestone" && <div className={styles.formGrid}>
                <label className={styles.field}><span>Target</span><input required type="number" min="0.01" step="0.01" value={form.target_value} onChange={(event) => setForm({ ...form, target_value: event.target.value })} /></label>
                <label className={styles.field}><span>Unit</span><input required maxLength={40} placeholder="hours, sessions…" value={form.unit} onChange={(event) => setForm({ ...form, unit: event.target.value })} /></label>
              </div>}
              {form.goal_type === "recurring" && <label className={styles.field}><span>Repeats</span><select value={form.recurring_period} onChange={(event) => setForm({ ...form, recurring_period: event.target.value as GoalForm["recurring_period"] })}><option value="weekly">Every week</option><option value="monthly">Every month</option></select></label>}
              {editing && <label className={styles.field}><span>Status</span><select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value as GoalForm["status"] })}><option value="active">Active</option><option value="paused">Paused</option><option value="archived">Archived</option>{editing.status === "completed" && <option value="completed">Completed</option>}</select></label>}
              <div className={styles.formGrid}>
                <label className={styles.field}><span>Start date</span><input required type="date" value={form.start_date} onChange={(event) => setForm({ ...form, start_date: event.target.value })} /></label>
                <label className={styles.field}><span>Deadline</span><input required type="date" value={form.deadline} onChange={(event) => setForm({ ...form, deadline: event.target.value })} /></label>
              </div>
              <div className={styles.formHint}>{recurringDescription}</div>
              <div className={styles.formActions}><button type="button" className={styles.secondaryButton} onClick={() => { setEditing(null); setFormOpen(false); setError(""); }}>Cancel</button><button className={styles.primaryButton} disabled={busy}>{busy ? "Saving…" : editing ? "Save changes" : "Create goal"}</button></div>
              {error && <div className={styles.dialogError} role="alert">{error}</div>}
            </form>
          </section>
        </div>
      )}
    </main>
  );
}
