"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";

import {
  Activity,
  ActivityInput,
  ActivitySummary,
  Category,
  Goal,
  Project,
  createTelegramLinkCode,
  createCategory,
  createSubcategory,
  deleteActivity,
  deleteCategory,
  deleteSubcategory,
  getActivities,
  getActivitySummary,
  getCategories,
  getGoals,
  getProjects,
  getTelegramSettings,
  getSetupStatus,
  login,
  logout,
  saveActivity,
  setupAccount,
  saveTelegramSettings,
  TelegramLinkCode,
  TelegramSettings,
  updateCategory,
  updateSubcategory,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import styles from "./page.module.css";

type ActivityDraft = {
  title: string;
  description: string;
  category_id: string;
  subcategory_id: string;
  started_at: string;
  ended_at: string;
  notes: string;
  tags: string;
  source: string;
  project_id: string;
};

const EMPTY_DRAFT: ActivityDraft = {
  title: "",
  description: "",
  category_id: "",
  subcategory_id: "",
  started_at: "",
  ended_at: "",
  notes: "",
  tags: "",
  source: "manual",
  project_id: "",
};

function localDateKey(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function localInputValue(date: Date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function localDayRange(dateKey: string) {
  const [year, month, day] = dateKey.split("-").map(Number);
  const start = new Date(year, month - 1, day);
  const end = new Date(year, month - 1, day + 1);
  return { start: start.toISOString(), end: end.toISOString() };
}

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (hours === 0) return `${remainingMinutes}m`;
  if (remainingMinutes === 0) return `${hours}h`;
  return `${hours}h ${remainingMinutes}m`;
}

function getDraftDuration(draft: ActivityDraft) {
  const start = new Date(draft.started_at).getTime();
  const end = new Date(draft.ended_at).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "Choose start and end times";
  if (end <= start) return "End time must be after start time";
  return formatDuration(Math.floor((end - start) / 1000));
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(
    new Date(value),
  );
}

function formatDateHeading(dateKey: string) {
  const [year, month, day] = dateKey.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(new Date(year, month - 1, day, 12));
}

function getDefaultDraft(categoryId: number | undefined): ActivityDraft {
  const start = new Date();
  start.setSeconds(0, 0);
  start.setMinutes(Math.floor(start.getMinutes() / 15) * 15);
  const end = new Date(start.getTime() + 60 * 60_000);
  return {
    ...EMPTY_DRAFT,
    category_id: categoryId ? String(categoryId) : "",
    started_at: localInputValue(start),
    ended_at: localInputValue(end),
  };
}

function draftFromActivity(activity: Activity): ActivityDraft {
  return {
    title: activity.title,
    description: activity.description ?? "",
    category_id: String(activity.category_id),
    subcategory_id: activity.subcategory_id ? String(activity.subcategory_id) : "",
    project_id: activity.project_id ? String(activity.project_id) : "",
    started_at: localInputValue(new Date(activity.started_at)),
    ended_at: localInputValue(new Date(activity.ended_at)),
    notes: activity.notes ?? "",
    tags: activity.tags.join(", "),
    source: activity.source,
  };
}

function toActivityInput(draft: ActivityDraft): ActivityInput {
  return {
    title: draft.title.trim(),
    description: draft.description.trim() || null,
    category_id: Number(draft.category_id),
    subcategory_id: draft.subcategory_id ? Number(draft.subcategory_id) : null,
    project_id: draft.project_id ? Number(draft.project_id) : null,
    started_at: new Date(draft.started_at).toISOString(),
    ended_at: new Date(draft.ended_at).toISOString(),
    notes: draft.notes.trim() || null,
    tags: draft.tags
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean),
    source: draft.source.trim() || "manual",
  };
}

export default function Home() {
  const auth = useAuth();
  const [selectedDate, setSelectedDate] = useState("");
  const [categories, setCategories] = useState<Category[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [focusGoals, setFocusGoals] = useState<Goal[]>([]);
  const [activities, setActivities] = useState<Activity[]>([]);
  const [summary, setSummary] = useState<ActivitySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingActivity, setEditingActivity] = useState<Activity | null>(null);
  const [draft, setDraft] = useState<ActivityDraft>(EMPTY_DRAFT);
  const [categoryManagerOpen, setCategoryManagerOpen] = useState(false);
  const [newCategoryName, setNewCategoryName] = useState("");
  const [newCategoryColor, setNewCategoryColor] = useState("#64748b");
  const [newSubcategory, setNewSubcategory] = useState<Record<number, string>>({});
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [editingCategoryName, setEditingCategoryName] = useState("");
  const [editingSubcategoryId, setEditingSubcategoryId] = useState<number | null>(null);
  const [editingSubcategoryName, setEditingSubcategoryName] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [setupRequired, setSetupRequired] = useState(true);
  const [setupStatusLoading, setSetupStatusLoading] = useState(true);
  const [authUsername, setAuthUsername] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [telegramSettingsOpen, setTelegramSettingsOpen] = useState(false);
  const [telegramSettings, setTelegramSettings] = useState<TelegramSettings | null>(null);
  const [telegramLinkCode, setTelegramLinkCode] = useState<TelegramLinkCode | null>(null);
  const [telegramSettingsBusy, setTelegramSettingsBusy] = useState(false);
  const [telegramSettingsError, setTelegramSettingsError] = useState("");

  useEffect(() => {
    setSelectedDate(localDateKey(new Date()));
  }, []);

  useEffect(() => {
    let active = true;
    if (auth.status !== "unauthenticated") return;
    getSetupStatus()
      .then((status) => {
        if (active) setSetupRequired(status.setup_required);
      })
      .catch((cause: unknown) => {
        if (active) {
          setAuthError(cause instanceof Error ? cause.message : "Could not connect to the authentication service.");
        }
      })
      .finally(() => {
        if (active) setSetupStatusLoading(false);
      });
    return () => {
      active = false;
    };
  }, [auth.status]);

  const loadCategories = useCallback(async () => {
    const result = await getCategories();
    setCategories(result);
  }, []);

  useEffect(() => {
    if (auth.status !== "authenticated") return;
    let active = true;
    Promise.all([getCategories(), getProjects(true), getGoals()])
      .then(([categoryResult, projectResult, goalResult]) => {
        if (!active) return;
        setCategories(categoryResult);
        setProjects(projectResult);
        setFocusGoals(goalResult);
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load categories.");
      });
    return () => {
      active = false;
    };
  }, [auth.status]);

  useEffect(() => {
    if (auth.status !== "authenticated" || !selectedDate) return;
    let active = true;
    const range = localDayRange(selectedDate);
    setLoading(true);
    setError("");
    Promise.all([getActivities(range.start, range.end), getActivitySummary(range.start, range.end)])
      .then(([dayActivities, daySummary]) => {
        if (!active) return;
        setActivities(dayActivities);
        setSummary(daySummary);
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : "Could not load your activity log.");
          setActivities([]);
          setSummary(null);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [auth.status, selectedDate, refresh]);

  const selectedCategory = useMemo(
    () => categories.find((category) => String(category.id) === draft.category_id),
    [categories, draft.category_id],
  );

  function openCreateEditor() {
    setEditingActivity(null);
    setDraft(getDefaultDraft(categories[0]?.id));
    setError("");
    setEditorOpen(true);
  }

  function openEditEditor(activity: Activity) {
    setEditingActivity(activity);
    setDraft(draftFromActivity(activity));
    setError("");
    setEditorOpen(true);
  }

  function changeDate(days: number) {
    const current = new Date(`${selectedDate}T12:00:00`);
    current.setDate(current.getDate() + days);
    setSelectedDate(localDateKey(current));
  }

  async function submitActivity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.category_id) {
      setError("Create or choose a category before saving an activity.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const saved = await saveActivity(toActivityInput(draft), editingActivity?.id);
      const savedDate = localDateKey(new Date(saved.started_at));
      setEditorOpen(false);
      setSelectedDate(savedDate);
      setRefresh((value) => value + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save this activity.");
    } finally {
      setSaving(false);
    }
  }

  async function removeActivity(activity: Activity) {
    if (!window.confirm(`Delete "${activity.title}" from your activity log?`)) return;
    setError("");
    try {
      await deleteActivity(activity.id);
      setRefresh((value) => value + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete this activity.");
    }
  }

  async function addCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      const category = await createCategory({
        name: newCategoryName.trim(),
        color: newCategoryColor,
      });
      await loadCategories();
      setNewCategoryName("");
      setDraft((current) => ({ ...current, category_id: String(category.id), subcategory_id: "" }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not add this category.");
    }
  }

  async function addSubcategory(categoryId: number) {
    const name = newSubcategory[categoryId]?.trim();
    if (!name) return;
    setError("");
    try {
      await createSubcategory(categoryId, name);
      await loadCategories();
      setNewSubcategory((current) => ({ ...current, [categoryId]: "" }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not add this subcategory.");
    }
  }

  async function removeCategory(category: Category) {
    setError("");
    try {
      await deleteCategory(category.id);
      await loadCategories();
      if (draft.category_id === String(category.id)) {
        setDraft((current) => ({ ...current, category_id: "", subcategory_id: "" }));
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete this category.");
    }
  }

  async function renameCategory(categoryId: number) {
    setError("");
    try {
      await updateCategory(categoryId, { name: editingCategoryName.trim() });
      await loadCategories();
      setEditingCategoryId(null);
      setEditingCategoryName("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not rename this category.");
    }
  }

  async function removeSubcategory(subcategoryId: number) {
    setError("");
    try {
      await deleteSubcategory(subcategoryId);
      await loadCategories();
      setDraft((current) =>
        current.subcategory_id === String(subcategoryId)
          ? { ...current, subcategory_id: "" }
          : current,
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete this subcategory.");
    }
  }

  async function renameSubcategory(subcategoryId: number) {
    setError("");
    try {
      await updateSubcategory(subcategoryId, editingSubcategoryName.trim());
      await loadCategories();
      setEditingSubcategoryId(null);
      setEditingSubcategoryName("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not rename this subcategory.");
    }
  }

  async function submitAuthentication(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthBusy(true);
    setAuthError("");
    try {
      const session = setupRequired
        ? await setupAccount({ username: authUsername, password: authPassword })
        : await login({ username: authUsername, password: authPassword });
      auth.setAuthenticated(session.username);
      setSetupRequired(false);
      setSetupStatusLoading(false);
      setAuthPassword("");
    } catch (cause) {
      setAuthError(cause instanceof Error ? cause.message : "Could not authenticate.");
    } finally {
      setAuthBusy(false);
    }
  }

  async function signOut() {
    setAuthError("");
    let signOutError = "";
    try {
      await logout();
    } catch (cause) {
      signOutError = cause instanceof Error ? cause.message : "Could not sign out.";
    }
    auth.clearSession(signOutError);
    setAuthPassword("");
    setSetupStatusLoading(true);
  }

  async function openTelegramSettings() {
    setTelegramSettingsOpen(true);
    setTelegramSettingsError("");
    setTelegramLinkCode(null);
    setTelegramSettingsBusy(true);
    try {
      const current = await getTelegramSettings();
      if (!current.connected) {
        current.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      }
      setTelegramSettings(current);
    } catch (cause) {
      setTelegramSettingsError(
        cause instanceof Error ? cause.message : "Could not load Telegram settings.",
      );
    } finally {
      setTelegramSettingsBusy(false);
    }
  }

  async function generateTelegramLinkCode() {
    setTelegramSettingsError("");
    setTelegramSettingsBusy(true);
    try {
      setTelegramLinkCode(await createTelegramLinkCode());
    } catch (cause) {
      setTelegramSettingsError(
        cause instanceof Error ? cause.message : "Could not create a Telegram link code.",
      );
    } finally {
      setTelegramSettingsBusy(false);
    }
  }

  async function saveTelegramPreferences(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!telegramSettings) return;
    setTelegramSettingsError("");
    setTelegramSettingsBusy(true);
    try {
      const saved = await saveTelegramSettings({
        interval_minutes: telegramSettings.interval_minutes,
        timezone: telegramSettings.timezone,
        active_start: telegramSettings.active_start,
        active_end: telegramSettings.active_end,
        quiet_start: telegramSettings.quiet_start,
        quiet_end: telegramSettings.quiet_end,
      });
      setTelegramSettings(saved);
      setTelegramSettingsError("Check-in preferences saved.");
    } catch (cause) {
      setTelegramSettingsError(
        cause instanceof Error ? cause.message : "Could not save Telegram preferences.",
      );
    } finally {
      setTelegramSettingsBusy(false);
    }
  }

  const todayKey = selectedDate ? localDateKey(new Date()) : "";
  const categoryMax = Math.max(1, summary?.total_duration_seconds ?? 0);

  if (auth.status === "checking" || (auth.status === "unauthenticated" && setupStatusLoading)) {
    return (
      <main className={styles.authScreen}>
        <div className={styles.authCard}>Checking your secure session…</div>
      </main>
    );
  }

  if (auth.status !== "authenticated") {
    return (
      <main className={styles.authScreen}>
        <section className={styles.authCard}>
          <Link className={styles.brand} href="/" aria-label="Personal Life OS home">
            <span className={styles.brandMark}>p</span>
            <span>personal<span className={styles.brandLight}>life</span></span>
          </Link>
          <p className={styles.eyebrow}>{setupRequired ? "PRIVATE BY DESIGN" : "WELCOME BACK"}</p>
          <h1>{setupRequired ? "Create your private workspace" : "Sign in to your space"}</h1>
          <p className={styles.authDescription}>
            {setupRequired
              ? "Set up the first and only account. Public registration is disabled after setup."
              : "Your activity log is private. Sign in to pick up where you left off."}
          </p>
          {(authError || auth.error) && <div className={styles.dialogError} role="alert">{authError || auth.error}</div>}
          <form className={styles.activityForm} onSubmit={submitAuthentication}>
            <label className={styles.field}>
              <span>Username</span>
              <input
                autoComplete="username"
                autoFocus
                required
                minLength={3}
                maxLength={64}
                value={authUsername}
                onChange={(event) => setAuthUsername(event.target.value)}
              />
            </label>
            <label className={styles.field}>
              <span>Password <small>{setupRequired ? "At least 12 characters" : ""}</small></span>
              <input
                type="password"
                autoComplete={setupRequired ? "new-password" : "current-password"}
                required
                minLength={12}
                maxLength={128}
                value={authPassword}
                onChange={(event) => setAuthPassword(event.target.value)}
              />
            </label>
            <button className={styles.primaryButton} disabled={authBusy}>
              {authBusy ? "Please wait…" : setupRequired ? "Create account" : "Sign in"}
            </button>
          </form>
          <p className={styles.authFootnote}>Secure session · Passwords are never stored in plain text</p>
        </section>
      </main>
    );
  }

  return (
    <main className={styles.app}>
      <aside className={styles.sidebar}>
        <Link className={styles.brand} href="/" aria-label="Personal Life OS home">
          <span className={styles.brandMark}>p</span>
          <span>personal<span className={styles.brandLight}>life</span></span>
        </Link>
        <div className={styles.sideLabel}>YOUR SPACE</div>
        <Link className={`${styles.navItem} ${styles.navActive}`} href="/">
          <span className={styles.navIcon}>◷</span> Activity
        </Link>
        <Link className={styles.navItem} href="/analytics">
          <span className={styles.navIcon}>▥</span> Analytics
        </Link>
        <Link className={styles.navItem} href="/goals">
          <span className={styles.navIcon}>◎</span> Goals
        </Link>
        <Link className={styles.navItem} href="/projects">
          <span className={styles.navIcon}>▣</span> Projects
        </Link>
        <div className={styles.sidebarFoot}>
          <span className={styles.avatar}>P</span>
          <span className={styles.accountName}><strong>{auth.username}</strong><small>Personal space</small></span>
          <button className={styles.logoutButton} onClick={signOut}>Sign out</button>
        </div>
      </aside>

      <section className={styles.workspace}>
        <header className={styles.topbar}>
          <span className={styles.breadcrumb}>My space <span>/</span> Activity</span>
          <div className={styles.topbarActions}>
            <Link className={styles.manageButton} href="/analytics">Analytics</Link>
            <button className={styles.manageButton} onClick={openTelegramSettings}>
              <span aria-hidden="true">✉</span> Telegram
            </button>
            <button className={styles.manageButton} onClick={() => setCategoryManagerOpen(true)}>
              <span aria-hidden="true">☷</span> Manage categories
            </button>
          </div>
        </header>

        <div className={styles.content}>
          <div className={styles.headingRow}>
            <div>
              <p className={styles.eyebrow}>MAKE YOUR TIME VISIBLE</p>
              <h1>Activity log</h1>
              <p className={styles.subtitle}>A clear picture of where your day goes.</p>
            </div>

            <section className={styles.focusSummary}>
              <Link href="/goals"><span>ACTIVE GOALS</span><strong>{focusGoals.filter((goal) => goal.status === "active").length}</strong></Link>
              <Link href="/goals"><span>OVERDUE GOALS</span><strong className={focusGoals.some((goal) => goal.overdue) ? styles.overdueText : ""}>{focusGoals.filter((goal) => goal.overdue).length}</strong></Link>
              <Link href="/goals"><span>UPCOMING DEADLINES</span><strong>{focusGoals.filter((goal) => goal.status === "active" && !goal.overdue && new Date(`${goal.deadline}T12:00:00`).getTime() - Date.now() <= 7 * 86400000).length}</strong></Link>
              <Link href="/projects"><span>ACTIVE PROJECTS</span><strong>{projects.filter((project) => project.status === "active").length}</strong></Link>
            </section>
            <button className={styles.primaryButton} onClick={openCreateEditor}>
              <span aria-hidden="true">＋</span> Log activity
            </button>
          </div>

          {error && (
            <div className={styles.errorBanner} role="alert">
              <span>{error}</span>
              <button onClick={() => setError("")} aria-label="Dismiss error">×</button>
            </div>
          )}

          <section className={styles.statsGrid} aria-label="Daily activity summary">
            <article className={styles.statCard}>
              <span className={styles.statIcon}>◷</span>
              <span className={styles.statLabel}>TRACKED TIME</span>
              <strong>{summary ? formatDuration(summary.total_duration_seconds) : "—"}</strong>
              <span className={styles.statHint}>Across your logged activities</span>
            </article>
            <article className={styles.statCard}>
              <span className={`${styles.statIcon} ${styles.statIconLavender}`}>▤</span>
              <span className={styles.statLabel}>ACTIVITIES</span>
              <strong>{summary ? summary.activity_count : "—"}</strong>
              <span className={styles.statHint}>Logged for this day</span>
            </article>
            <article className={`${styles.statCard} ${styles.distributionCard}`}>
              <span className={styles.statLabel}>TIME BY CATEGORY</span>
              {summary && summary.categories.length > 0 ? (
                <div className={styles.distributionList}>
                  {summary.categories.map((category) => (
                    <div className={styles.distributionItem} key={category.category_id}>
                      <span className={styles.distributionName}>
                        <i style={{ backgroundColor: category.color }} />
                        {category.category_name}
                      </span>
                      <div className={styles.barTrack}>
                        <span
                          className={styles.bar}
                          style={{
                            width: `${Math.max(4, (category.duration_seconds / categoryMax) * 100)}%`,
                            backgroundColor: category.color,
                          }}
                        />
                      </div>
                      <strong>{formatDuration(category.duration_seconds)}</strong>
                    </div>
                  ))}
                </div>
              ) : (
                <span className={styles.statHint}>Your category breakdown will appear here.</span>
              )}
            </article>
          </section>

          <section className={styles.timelinePanel}>
            <div className={styles.timelineHeader}>
              <div>
                <p className={styles.eyebrow}>YOUR TIMELINE</p>
                <h2>{selectedDate ? formatDateHeading(selectedDate) : "Loading your day…"}</h2>
              </div>
              <div className={styles.dateControls}>
                <button className={styles.iconButton} onClick={() => changeDate(-1)} aria-label="Previous day">
                  ‹
                </button>
                <button className={styles.todayButton} onClick={() => setSelectedDate(todayKey)}>Today</button>
                <button className={styles.iconButton} onClick={() => changeDate(1)} aria-label="Next day">
                  ›
                </button>
                <label className={styles.datePicker} aria-label="Choose a date">
                  <span aria-hidden="true">▦</span>
                  <input
                    type="date"
                    value={selectedDate}
                    onChange={(event) => setSelectedDate(event.target.value)}
                  />
                </label>
              </div>
            </div>

            {loading ? (
              <div className={styles.loadingState}>Loading your timeline…</div>
            ) : activities.length === 0 ? (
              <div className={styles.emptyState}>
                <span className={styles.emptyIcon}>◷</span>
                <h3>No activities logged yet</h3>
                <p>Start with one thing you did. You can also add activities from earlier in the day.</p>
                <button className={styles.secondaryButton} onClick={openCreateEditor}>Log your first activity</button>
              </div>
            ) : (
              <div className={styles.timeline}>
                {activities.map((activity) => (
                  <article className={styles.activityRow} key={activity.id}>
                    <div className={styles.timeColumn}>
                      <strong>{formatTime(activity.started_at)}</strong>
                      <span>{formatDuration(activity.duration_seconds)}</span>
                    </div>
                    <div className={styles.timelineRail}>
                      <i style={{ backgroundColor: activity.category.color }} />
                    </div>
                    <div className={styles.activityCard}>
                      <div className={styles.activityTopline}>
                        <div>
                          <span className={styles.categoryPill}>
                            <i style={{ backgroundColor: activity.category.color }} />
                            {activity.category.name}
                            {activity.subcategory && <span> / {activity.subcategory.name}</span>}
                          </span>
                          <h3>{activity.title}</h3>
                        </div>
                        <div className={styles.activityActions}>
                          <button onClick={() => openEditEditor(activity)} aria-label={`Edit ${activity.title}`}>
                            Edit
                          </button>
                          <button onClick={() => removeActivity(activity)} aria-label={`Delete ${activity.title}`}>
                            Delete
                          </button>
                        </div>
                      </div>
                      {activity.description && <p className={styles.activityDescription}>{activity.description}</p>}
                      {activity.notes && <p className={styles.activityNotes}>{activity.notes}</p>}
                      {activity.tags.length > 0 && (
                        <div className={styles.tagList}>
                          {activity.tags.map((tag) => <span key={tag}>#{tag}</span>)}
                        </div>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
          <footer className={styles.footer}>Your time, thoughtfully accounted for.</footer>
        </div>
      </section>

      {editorOpen && (
        <div className={styles.modalBackdrop} role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setEditorOpen(false);
        }}>
          <section className={styles.editor} role="dialog" aria-modal="true" aria-labelledby="editor-title">
            <div className={styles.modalHeader}>
              <div>
                <p className={styles.eyebrow}>{editingActivity ? "UPDATE YOUR LOG" : "ADD TO YOUR DAY"}</p>
                <h2 id="editor-title">{editingActivity ? "Edit activity" : "Log an activity"}</h2>
              </div>
              <button className={styles.iconButton} onClick={() => setEditorOpen(false)} aria-label="Close form">×</button>
            </div>
            {error && <div className={styles.dialogError} role="alert">{error}</div>}
            <form className={styles.activityForm} onSubmit={submitActivity}>
              <label className={styles.field}>
                <span>Activity name</span>
                <input
                  required
                  maxLength={200}
                  autoFocus
                  placeholder="What did you spend time on?"
                  value={draft.title}
                  onChange={(event) => setDraft({ ...draft, title: event.target.value })}
                />
              </label>
              <label className={styles.field}>
                <span>Description <small>Optional</small></span>
                <textarea
                  rows={2}
                  maxLength={10000}
                  placeholder="Add a little more context"
                  value={draft.description}
                  onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                />
              </label>
              <div className={styles.formGrid}>
                <label className={styles.field}>
                  <span>Category</span>
                  <select
                    required
                    value={draft.category_id}
                    onChange={(event) => setDraft({ ...draft, category_id: event.target.value, subcategory_id: "" })}
                  >
                    <option value="">Choose a category</option>
                    {categories.map((category) => (
                      <option key={category.id} value={category.id}>{category.name}</option>
                    ))}
                  </select>
                </label>
                <label className={styles.field}>
                  <span>Subcategory <small>Optional</small></span>
                  <select
                    disabled={!selectedCategory || selectedCategory.subcategories.length === 0}
                    value={draft.subcategory_id}
                    onChange={(event) => setDraft({ ...draft, subcategory_id: event.target.value })}
                  >
                    <option value="">None</option>
                    {selectedCategory?.subcategories.map((subcategory) => (
                      <option key={subcategory.id} value={subcategory.id}>{subcategory.name}</option>
                    ))}
                  </select>
                </label>
              </div>
              <label className={styles.field}>
                <span>Project <small>Optional</small></span>
                <select
                  value={draft.project_id}
                  onChange={(event) => setDraft({ ...draft, project_id: event.target.value })}
                >
                  <option value="">No project</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.title}{project.status === "archived" ? " · archived" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <div className={styles.formGrid}>
                <label className={styles.field}>
                  <span>Start time</span>
                  <input
                    type="datetime-local"
                    required
                    value={draft.started_at}
                    onChange={(event) => setDraft({ ...draft, started_at: event.target.value })}
                  />
                </label>
                <label className={styles.field}>
                  <span>End time</span>
                  <input
                    type="datetime-local"
                    required
                    value={draft.ended_at}
                    onChange={(event) => setDraft({ ...draft, ended_at: event.target.value })}
                  />
                </label>
              </div>
              <div className={styles.durationPreview}>
                <span>Duration</span>
                <strong>{getDraftDuration(draft)}</strong>
              </div>
              <label className={styles.field}>
                <span>Tags <small>Separate with commas</small></span>
                <input
                  placeholder="focus, personal"
                  value={draft.tags}
                  onChange={(event) => setDraft({ ...draft, tags: event.target.value })}
                />
              </label>
              <label className={styles.field}>
                <span>Source</span>
                <input
                  required
                  maxLength={50}
                  value={draft.source}
                  onChange={(event) => setDraft({ ...draft, source: event.target.value })}
                />
              </label>
              <label className={styles.field}>
                <span>Notes <small>Optional</small></span>
                <textarea
                  rows={3}
                  maxLength={10000}
                  placeholder="Anything worth remembering?"
                  value={draft.notes}
                  onChange={(event) => setDraft({ ...draft, notes: event.target.value })}
                />
              </label>
              <div className={styles.formHint}>Log something from earlier by choosing its original start and end time.</div>
              <div className={styles.formActions}>
                <button type="button" className={styles.secondaryButton} onClick={() => setEditorOpen(false)}>Cancel</button>
                <button className={styles.primaryButton} disabled={saving || categories.length === 0}>
                  {saving ? "Saving…" : editingActivity ? "Save changes" : "Save activity"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {categoryManagerOpen && (
        <div className={styles.modalBackdrop} role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setCategoryManagerOpen(false);
        }}>
          <section className={`${styles.editor} ${styles.categoryEditor}`} role="dialog" aria-modal="true" aria-labelledby="category-title">
            <div className={styles.modalHeader}>
              <div>
                <p className={styles.eyebrow}>MAKE IT YOURS</p>
                <h2 id="category-title">Categories</h2>
              </div>
              <button className={styles.iconButton} onClick={() => setCategoryManagerOpen(false)} aria-label="Close categories">×</button>
            </div>
            {error && <div className={styles.dialogError} role="alert">{error}</div>}
            <p className={styles.managerIntro}>Organize activities into categories and optional subcategories.</p>
            <form className={styles.newCategoryForm} onSubmit={addCategory}>
              <label className={styles.field}>
                <span>New category</span>
                <div className={styles.categoryInputRow}>
                  <input
                    required
                    maxLength={80}
                    placeholder="e.g. Family"
                    value={newCategoryName}
                    onChange={(event) => setNewCategoryName(event.target.value)}
                  />
                  <input
                    type="color"
                    aria-label="Category color"
                    value={newCategoryColor}
                    onChange={(event) => setNewCategoryColor(event.target.value)}
                  />
                  <button className={styles.primaryButton}>Add</button>
                </div>
              </label>
            </form>
            <div className={styles.categoryList}>
              {categories.map((category) => (
                <article className={styles.categoryManagerItem} key={category.id}>
                  <div className={styles.categoryManagerHeading}>
                    {editingCategoryId === category.id ? (
                      <form className={styles.renameCategoryForm} onSubmit={(event) => {
                        event.preventDefault();
                        void renameCategory(category.id);
                      }}>
                        <input
                          autoFocus
                          required
                          maxLength={80}
                          value={editingCategoryName}
                          onChange={(event) => setEditingCategoryName(event.target.value)}
                        />
                        <button type="submit">Save</button>
                        <button type="button" onClick={() => setEditingCategoryId(null)}>Cancel</button>
                      </form>
                    ) : (
                      <span><i style={{ backgroundColor: category.color }} />{category.name}</span>
                    )}

                    {telegramSettingsOpen && (
                      <div
                        className={styles.modalBackdrop}
                        role="presentation"
                        onMouseDown={(event) => {
                          if (event.target === event.currentTarget) setTelegramSettingsOpen(false);
                        }}
                      >
                        <section
                          className={`${styles.editor} ${styles.telegramEditor}`}
                          role="dialog"
                          aria-modal="true"
                          aria-labelledby="telegram-title"
                        >
                          <div className={styles.modalHeader}>
                            <div>
                              <p className={styles.eyebrow}>ACTIVITY CHECK-INS</p>
                              <h2 id="telegram-title">Telegram</h2>
                            </div>
                            <button
                              className={styles.iconButton}
                              onClick={() => setTelegramSettingsOpen(false)}
                              aria-label="Close Telegram settings"
                            >
                              ×
                            </button>
                          </div>
                          {telegramSettingsError && (
                            <div className={styles.dialogError} role="status">{telegramSettingsError}</div>
                          )}
                          {telegramSettingsBusy && !telegramSettings ? (
                            <div className={styles.loadingState}>Loading Telegram settings…</div>
                          ) : telegramSettings ? (
                            <div className={styles.telegramSettingsContent}>
                              <p className={styles.managerIntro}>
                                {telegramSettings.connected
                                  ? telegramSettings.paused
                                    ? "Your Telegram account is linked; check-ins are paused."
                                    : "Your Telegram account is linked and ready for check-ins."
                                  : "Link your private Telegram chat to receive check-ins and log activities by message."}
                              </p>
                              {!telegramSettings.connected && (
                                <div className={styles.telegramLinkSection}>
                                  <button
                                    type="button"
                                    className={styles.primaryButton}
                                    disabled={telegramSettingsBusy}
                                    onClick={generateTelegramLinkCode}
                                  >
                                    {telegramSettingsBusy ? "Creating code…" : "Create one-time link code"}
                                  </button>
                                  {telegramLinkCode && (
                                    <div className={styles.telegramCode}>
                                      <strong>{telegramLinkCode.code}</strong>
                                      <span>
                                        In Telegram, open {telegramLinkCode.bot_username
                                          ? `@${telegramLinkCode.bot_username}`
                                          : "your bot"} and send:
                                      </span>
                                      <code>/link {telegramLinkCode.code}</code>
                                      <small>
                                        Expires {new Intl.DateTimeFormat(undefined, {
                                          hour: "numeric",
                                          minute: "2-digit",
                                        }).format(new Date(telegramLinkCode.expires_at))}. This code can be used once.
                                      </small>
                                    </div>
                                  )}
                                </div>
                              )}
                              <form className={styles.activityForm} onSubmit={saveTelegramPreferences}>
                                <label className={styles.field}>
                                  <span>Check-in interval <small>5–240 minutes</small></span>
                                  <input
                                    type="number"
                                    min={5}
                                    max={240}
                                    step={5}
                                    required
                                    disabled={!telegramSettings.connected}
                                    value={telegramSettings.interval_minutes}
                                    onChange={(event) => setTelegramSettings({
                                      ...telegramSettings,
                                      interval_minutes: Number(event.target.value),
                                    })}
                                  />
                                </label>
                                <label className={styles.field}>
                                  <span>Timezone <small>IANA name, e.g. Asia/Kolkata</small></span>
                                  <input
                                    required
                                    maxLength={64}
                                    disabled={!telegramSettings.connected}
                                    value={telegramSettings.timezone}
                                    onChange={(event) => setTelegramSettings({
                                      ...telegramSettings,
                                      timezone: event.target.value,
                                    })}
                                  />
                                </label>
                                <div className={styles.telegramTimeGrid}>
                                  {([
                                    ["active_start", "Active from"],
                                    ["active_end", "Active until"],
                                    ["quiet_start", "Quiet from"],
                                    ["quiet_end", "Quiet until"],
                                  ] as const).map(([field, label]) => (
                                    <label className={styles.field} key={field}>
                                      <span>{label}</span>
                                      <input
                                        type="time"
                                        required
                                        disabled={!telegramSettings.connected}
                                        value={telegramSettings[field].slice(0, 5)}
                                        onChange={(event) => setTelegramSettings({
                                          ...telegramSettings,
                                          [field]: event.target.value,
                                        })}
                                      />
                                    </label>
                                  ))}
                                </div>
                                <p className={styles.formHint}>
                                  Check-ins pause outside active hours and during quiet hours. Use /pause or /resume in Telegram to toggle them.
                                </p>
                                {telegramSettings.connected && (
                                  <div className={styles.formActions}>
                                    <button className={styles.primaryButton} disabled={telegramSettingsBusy}>
                                      {telegramSettingsBusy ? "Saving…" : "Save preferences"}
                                    </button>
                                  </div>
                                )}
                              </form>
                            </div>
                          ) : null}
                        </section>
                      </div>
                    )}
                    {editingCategoryId !== category.id && (
                      <div className={styles.categoryHeadingActions}>
                        <button
                          onClick={() => {
                            setEditingCategoryId(category.id);
                            setEditingCategoryName(category.name);
                          }}
                        >
                          Rename
                        </button>
                        <button className={styles.textDanger} onClick={() => removeCategory(category)}>Delete</button>
                      </div>
                    )}
                  </div>
                  <div className={styles.subcategoryList}>
                    {category.subcategories.map((subcategory) => (
                      editingSubcategoryId === subcategory.id ? (
                        <form
                          className={styles.renameSubcategoryForm}
                          key={subcategory.id}
                          onSubmit={(event) => {
                            event.preventDefault();
                            void renameSubcategory(subcategory.id);
                          }}
                        >
                          <input
                            autoFocus
                            required
                            maxLength={80}
                            value={editingSubcategoryName}
                            onChange={(event) => setEditingSubcategoryName(event.target.value)}
                          />
                          <button type="submit">Save</button>
                          <button type="button" onClick={() => setEditingSubcategoryId(null)}>×</button>
                        </form>
                      ) : (
                        <span key={subcategory.id}>
                          {subcategory.name}
                          <button
                            onClick={() => {
                              setEditingSubcategoryId(subcategory.id);
                              setEditingSubcategoryName(subcategory.name);
                            }}
                            aria-label={`Rename ${subcategory.name}`}
                          >
                            ✎
                          </button>
                          <button onClick={() => removeSubcategory(subcategory.id)} aria-label={`Delete ${subcategory.name}`}>×</button>
                        </span>
                      )
                    ))}
                  </div>
                  <form className={styles.subcategoryForm} onSubmit={(event) => {
                    event.preventDefault();
                    void addSubcategory(category.id);
                  }}>
                    <input
                      maxLength={80}
                      placeholder="Add a subcategory"
                      value={newSubcategory[category.id] ?? ""}
                      onChange={(event) =>
                        setNewSubcategory((current) => ({ ...current, [category.id]: event.target.value }))
                      }
                    />
                    <button disabled={!newSubcategory[category.id]?.trim()}>Add</button>
                  </form>
                </article>
              ))}
              {categories.length === 0 && <p className={styles.managerIntro}>Add your first category to start logging activities.</p>}
            </div>
            <div className={styles.formActions}>
              <button className={styles.secondaryButton} onClick={() => setCategoryManagerOpen(false)}>Done</button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
