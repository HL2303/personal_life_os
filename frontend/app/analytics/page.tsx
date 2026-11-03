"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  Activity,
  Analytics,
  AnalyticsCategory,
  getActivities,
  getAnalytics,
  logout,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import styles from "../page.module.css";

type PeriodMode = "day" | "week" | "month" | "custom";

function dateKey(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function shiftDate(value: string, days: number) {
  const [year, month, day] = value.split("-").map(Number);
  const result = new Date(year, month - 1, day + days, 12);
  return dateKey(result);
}

function getRange(mode: PeriodMode, anchor: string, customStart: string, customEnd: string) {
  if (mode !== "custom" && !anchor) return { start: "", end: "" };
  if (mode === "custom") return { start: customStart, end: customEnd };
  if (mode === "day") return { start: anchor, end: anchor };
  if (mode === "week") {
    const [year, month, day] = anchor.split("-").map(Number);
    const weekday = new Date(year, month - 1, day, 12).getDay();
    const mondayOffset = weekday === 0 ? -6 : 1 - weekday;
    const start = shiftDate(anchor, mondayOffset);
    return { start, end: shiftDate(start, 6) };
  }
  const [year, month] = anchor.split("-").map(Number);
  return {
    start: dateKey(new Date(year, month - 1, 1, 12)),
    end: dateKey(new Date(year, month, 0, 12)),
  };
}

function moveAnchor(value: string, mode: PeriodMode, direction: number) {
  if (mode === "week") return shiftDate(value, 7 * direction);
  if (mode === "month") {
    const [year, month] = value.split("-").map(Number);
    return dateKey(new Date(year, month - 1 + direction, 1, 12));
  }
  return shiftDate(value, direction);
}

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const remaining = minutes % 60;
  if (hours === 0) return `${remaining}m`;
  if (remaining === 0) return `${hours}h`;
  return `${hours}h ${remaining}m`;
}

function formatDate(value: string, options: Intl.DateTimeFormatOptions = {}) {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    ...options,
  }).format(new Date(year, month - 1, day, 12));
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatTimestampDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function compare(current: number, previous: number) {
  if (previous === 0) return current === 0 ? "No change" : "New";
  const percentage = Math.round(((current - previous) / previous) * 100);
  if (percentage === 0) return "No change";
  return `${percentage > 0 ? "+" : ""}${percentage}%`;
}

function localDateRange(start: string, end: string) {
  const [startYear, startMonth, startDay] = start.split("-").map(Number);
  const [endYear, endMonth, endDay] = end.split("-").map(Number);
  return {
    start: new Date(startYear, startMonth - 1, startDay).toISOString(),
    end: new Date(endYear, endMonth - 1, endDay + 1).toISOString(),
  };
}

function categoryGradient(categories: AnalyticsCategory[], total: number) {
  if (total === 0) return "conic-gradient(#e9eaf0 0deg 360deg)";
  let position = 0;
  const stops = categories
    .filter((category) => category.duration_seconds > 0)
    .map((category) => {
      const start = position;
      position += (category.duration_seconds / total) * 360;
      return `${category.color} ${start}deg ${position}deg`;
    });
  return `conic-gradient(${stops.join(", ")})`;
}

function categoryDuration(categories: AnalyticsCategory[], categoryId: number) {
  return categories.find((item) => item.category_id === categoryId)?.duration_seconds ?? 0;
}

function AnalyticsCharts({ analytics }: { analytics: Analytics }) {
  const maximum = Math.max(1, ...analytics.days.map((day) => day.tracked_seconds));
  const trendPoints = analytics.days
    .map((day, index) => {
      const x = analytics.days.length === 1 ? 400 : (index / (analytics.days.length - 1)) * 760 + 20;
      const y = 205 - (day.tracked_seconds / maximum) * 175;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div className={styles.analyticsCharts}>
      <section className={styles.analyticsPanel}>
        <div className={styles.analyticsPanelHeading}>
          <div>
            <p className={styles.eyebrow}>WHERE YOUR TIME WENT</p>
            <h2>Category distribution</h2>
          </div>
          <span>{formatDuration(analytics.total_tracked_seconds)} tracked</span>
        </div>
        <div className={styles.donutLayout}>
          <div
            className={styles.donutChart}
            style={{ background: categoryGradient(analytics.categories, analytics.total_tracked_seconds) }}
            role="img"
            aria-label="Donut chart showing tracked time by category"
          >
            <div className={styles.donutCenter}>
              <strong>{formatDuration(analytics.total_tracked_seconds)}</strong>
              <span>tracked</span>
            </div>
          </div>
          <div className={styles.chartLegend}>
            {analytics.categories.map((category) => (
              <div className={styles.chartLegendItem} key={category.category_id}>
                <i style={{ backgroundColor: category.color }} />
                <span>{category.category_name}</span>
                <strong>{formatDuration(category.duration_seconds)}</strong>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className={styles.analyticsPanel}>
        <div className={styles.analyticsPanelHeading}>
          <div>
            <p className={styles.eyebrow}>DAY BY DAY</p>
            <h2>Daily tracked hours</h2>
          </div>
          <span>Local calendar days</span>
        </div>
        <div className={styles.barChartScroll}>
          <div className={styles.dailyBarChart}>
            {analytics.days.map((day) => {
              const height = Math.max(2, (day.tracked_seconds / maximum) * 100);
              return (
                <div className={styles.dailyBarColumn} key={day.date} title={`${formatDate(day.date)}: ${formatDuration(day.tracked_seconds)}`}>
                  <span className={styles.dailyBarValue}>{formatDuration(day.tracked_seconds)}</span>
                  <div className={styles.dailyBarTrack}>
                    {day.tracked_seconds > 0 && <i style={{ height: `${height}%` }} />}
                  </div>
                  <span className={styles.dailyBarLabel}>{formatDate(day.date, { day: "numeric" })}</span>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      <section className={styles.analyticsPanel}>
        <div className={styles.analyticsPanelHeading}>
          <div>
            <p className={styles.eyebrow}>CATEGORY RHYTHM</p>
            <h2>Category-wise daily breakdown</h2>
          </div>
          <span>Stacked tracked time</span>
        </div>
        <div className={styles.barChartScroll}>
          <div className={styles.stackedChart}>
            {analytics.days.map((day) => (
              <div className={styles.stackedDay} key={day.date} title={`${formatDate(day.date)}: ${formatDuration(day.tracked_seconds)}`}>
                <div className={styles.stackedBarTrack}>
                  {analytics.categories.map((category) => {
                    const seconds = categoryDuration(day.categories, category.category_id);
                    if (!seconds || !day.tracked_seconds) return null;
                    return (
                      <i
                        key={category.category_id}
                        style={{
                          height: `${(seconds / maximum) * 100}%`,
                          backgroundColor: category.color,
                        }}
                      />
                    );
                  })}
                </div>
                <span>{formatDate(day.date, { day: "numeric" })}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className={styles.analyticsPanel}>
        <div className={styles.analyticsPanelHeading}>
          <div>
            <p className={styles.eyebrow}>YOUR PATTERN</p>
            <h2>Activity trends over time</h2>
          </div>
          <span>Tracked hours per day</span>
        </div>
        <div className={styles.lineChartWrap}>
          <svg
            className={styles.lineChart}
            viewBox="0 0 800 230"
            role="img"
            aria-label="Line chart showing daily tracked time"
            preserveAspectRatio="none"
          >
            <line x1="20" x2="780" y1="205" y2="205" />
            <line x1="20" x2="780" y1="117" y2="117" />
            <line x1="20" x2="780" y1="30" y2="30" />
            <polyline points={trendPoints} />
            {analytics.days.map((day, index) => {
              const x = analytics.days.length === 1 ? 400 : (index / (analytics.days.length - 1)) * 760 + 20;
              const y = 205 - (day.tracked_seconds / maximum) * 175;
              return <circle key={day.date} cx={x} cy={y} r="4" />;
            })}
          </svg>
          <div className={styles.lineChartLabels}>
            {analytics.days.filter((_, index) =>
              analytics.days.length <= 8
                ? true
                : index === 0 || index === analytics.days.length - 1 || index % Math.ceil(analytics.days.length / 7) === 0,
            ).map((day) => (
              <span key={day.date}>{formatDate(day.date)}</span>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

export default function AnalyticsPage() {
  const auth = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<PeriodMode>("week");
  const [anchor, setAnchor] = useState("");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<AnalyticsCategory | null>(null);
  const [drilldown, setDrilldown] = useState<Activity[]>([]);
  const [drilldownLoading, setDrilldownLoading] = useState(false);

  useEffect(() => {
    setAnchor(dateKey(new Date()));
    setCustomStart(dateKey(new Date()));
    setCustomEnd(dateKey(new Date()));
  }, []);

  useEffect(() => {
    if (auth.status === "unauthenticated") router.replace("/");
  }, [auth.status, router]);

  const range = useMemo(
    () => getRange(mode, anchor, customStart, customEnd),
    [mode, anchor, customStart, customEnd],
  );
  const timezone = useMemo(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    [],
  );

  useEffect(() => {
    if (auth.status !== "authenticated") return;
    if (!range.start || !range.end || range.end < range.start) {
      setAnalytics(null);
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError("");
    setAnalytics(null);
    getAnalytics(range.start, range.end, timezone)
      .then((result) => {
        if (active) setAnalytics(result);
      })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load analytics.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [auth.status, range.start, range.end, timezone]);

  useEffect(() => {
    if (!selectedCategory || !range.start || !range.end || range.end < range.start) {
      setDrilldown([]);
      return;
    }
    let active = true;
    setDrilldownLoading(true);
    setDrilldown([]);
    const bounds = localDateRange(range.start, range.end);
    getActivities(bounds.start, bounds.end, selectedCategory.category_id)
      .then((result) => {
        if (active) setDrilldown(result);
      })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load activities.");
      })
      .finally(() => {
        if (active) setDrilldownLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedCategory, range.start, range.end]);

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

  const rangeLabel = range.start && range.end
    ? range.start === range.end
      ? formatDate(range.start, { year: "numeric" })
      : `${formatDate(range.start)} – ${formatDate(range.end, { year: "numeric" })}`
    : "Select a date range";
  const trackedChange = analytics
    ? compare(analytics.total_tracked_seconds, analytics.previous_period.total_tracked_seconds)
    : "";
  const activityChange = analytics
    ? compare(analytics.activity_count, analytics.previous_period.activity_count)
    : "";

  if (auth.status !== "authenticated") {
    return <main className={styles.loadingState}>{auth.status === "checking" ? "Checking your secure session…" : "Redirecting…"}</main>;
  }

  return (
    <main className={styles.app}>
      <aside className={styles.sidebar}>
        <Link className={styles.brand} href="/" aria-label="Personal Life OS home">
          <span className={styles.brandMark}>p</span>
          <span>personal<span className={styles.brandLight}>life</span></span>
        </Link>
        <div className={styles.sideLabel}>YOUR SPACE</div>
        <Link className={styles.navItem} href="/">
          <span className={styles.navIcon}>◷</span> Activity
        </Link>
        <Link className={`${styles.navItem} ${styles.navActive}`} href="/analytics" aria-current="page">
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
          <span className={styles.breadcrumb}>My space <span>/</span> Analytics</span>
          <div className={styles.topbarActions}>
            <Link className={styles.manageButton} href="/">Activity log</Link>
          </div>
        </header>
        <div className={styles.content}>
          <div className={styles.headingRow}>
            <div>
              <p className={styles.eyebrow}>SEE THE SHAPE OF YOUR TIME</p>
              <h1>Analytics</h1>
              <p className={styles.subtitle}>Only recorded activities are counted. Gaps stay untracked.</p>
            </div>
          </div>

          <section className={styles.analyticsToolbar} aria-label="Analytics date range">
            <div className={styles.analyticsModeGroup}>
              {(["day", "week", "month", "custom"] as const).map((value) => (
                <button
                  className={mode === value ? styles.analyticsModeActive : ""}
                  key={value}
                  onClick={() => setMode(value)}
                  aria-pressed={mode === value}
                >
                  {value === "day" ? "Day" : value === "week" ? "Week" : value === "month" ? "Month" : "Custom"}
                </button>
              ))}
            </div>
            {mode === "custom" ? (
              <div className={styles.customRange}>
                <label>From <input type="date" value={customStart} onChange={(event) => setCustomStart(event.target.value)} /></label>
                <label>To <input type="date" value={customEnd} onChange={(event) => setCustomEnd(event.target.value)} /></label>
              </div>
            ) : (
              <div className={styles.analyticsRangeNav}>
                <button className={styles.iconButton} onClick={() => setAnchor((current) => moveAnchor(current, mode, -1))} aria-label="Previous period">‹</button>
                <strong>{rangeLabel}</strong>
                <button className={styles.iconButton} onClick={() => setAnchor((current) => moveAnchor(current, mode, 1))} aria-label="Next period">›</button>
              </div>
            )}
          </section>

          {error && <div className={styles.errorBanner} role="alert">{error}</div>}

          {loading && !analytics ? (
            <div className={styles.loadingState}>Loading your analytics…</div>
          ) : analytics ? (
            <>
              <section className={styles.analyticsStats} aria-label="Time summary">
                <article className={styles.statCard}>
                  <span className={styles.statIcon}>◷</span>
                  <span className={styles.statLabel}>TRACKED TIME</span>
                  <strong>{formatDuration(analytics.total_tracked_seconds)}</strong>
                  <span className={styles.statHint}>Previous period: {formatDuration(analytics.previous_period.total_tracked_seconds)} · {trackedChange}</span>
                </article>
                <article className={styles.statCard}>
                  <span className={`${styles.statIcon} ${styles.statIconLavender}`}>▤</span>
                  <span className={styles.statLabel}>ACTIVITIES</span>
                  <strong>{analytics.activity_count}</strong>
                  <span className={styles.statHint}>Previous period: {analytics.previous_period.activity_count} · {activityChange}</span>
                </article>
                <article className={styles.statCard}>
                  <span className={styles.statIcon}>◌</span>
                  <span className={styles.statLabel}>UNTRACKED TIME</span>
                  <strong>{formatDuration(analytics.untracked_seconds)}</strong>
                  <span className={styles.statHint}>Not inferred from missing periods</span>
                </article>
                <article className={styles.statCard}>
                  <span className={styles.statIcon}>◷</span>
                  <span className={styles.statLabel}>AVAILABLE TIME</span>
                  <strong>{formatDuration(analytics.available_seconds)}</strong>
                  <span className={styles.statHint}>Selected local calendar days</span>
                </article>
              </section>

              {loading && <div className={styles.analyticsUpdating}>Updating selected range…</div>}
              <AnalyticsCharts analytics={analytics} />

              <section className={styles.analyticsPanel}>
                <div className={styles.analyticsPanelHeading}>
                  <div>
                    <p className={styles.eyebrow}>YOUR CATEGORIES</p>
                    <h2>Category summaries</h2>
                  </div>
                  <span>Compare with previous period</span>
                </div>
                {analytics.categories.length ? (
                  <div className={styles.categorySummaryGrid}>
                    {analytics.categories.map((category) => {
                      const previous = analytics.previous_period.categories.find(
                        (item) => item.category_id === category.category_id,
                      );
                      const isSelected = selectedCategory?.category_id === category.category_id;
                      return (
                        <button
                          className={`${styles.categorySummary} ${isSelected ? styles.categorySummaryActive : ""}`}
                          key={category.category_id}
                          onClick={() => setSelectedCategory(isSelected ? null : category)}
                          aria-pressed={isSelected}
                        >
                          <span><i style={{ backgroundColor: category.color }} />{category.category_name}</span>
                          <strong>{formatDuration(category.duration_seconds)}</strong>
                          <small>{category.activity_count} activities · prior {formatDuration(previous?.duration_seconds ?? 0)}</small>
                          <small>{compare(category.duration_seconds, previous?.duration_seconds ?? 0)} vs prior</small>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <p className={styles.analyticsEmpty}>Create a category in Activity to see category summaries.</p>
                )}
              </section>

              {selectedCategory && (
                <section className={styles.analyticsPanel} aria-live="polite">
                  <div className={styles.analyticsPanelHeading}>
                    <div>
                      <p className={styles.eyebrow}>ACTIVITY DETAIL</p>
                      <h2><i className={styles.detailCategoryDot} style={{ backgroundColor: selectedCategory.color }} />{selectedCategory.category_name}</h2>
                    </div>
                    <button className={styles.secondaryButton} onClick={() => setSelectedCategory(null)}>Close</button>
                  </div>
                  {drilldownLoading ? (
                    <div className={styles.loadingState}>Loading activities…</div>
                  ) : drilldown.length ? (
                    <div className={styles.drilldownList}>
                      {drilldown.map((activity) => (
                        <article className={styles.drilldownItem} key={activity.id}>
                          <div>
                            <strong>{activity.title}</strong>
                            <span>{formatTimestampDate(activity.started_at)} · {formatTime(activity.started_at)}–{formatTime(activity.ended_at)}</span>
                          </div>
                          <small>{formatDuration(activity.duration_seconds)}</small>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className={styles.analyticsEmpty}>No activities in this category for the selected range.</p>
                  )}
                  <p className={styles.analyticsNote}>Activity durations in this list are the original logged intervals; analytics totals allocate overlapping time once.</p>
                </section>
              )}
            </>
          ) : (
            <div className={styles.analyticsEmpty}>No analytics are available for this range.</div>
          )}
          <footer className={styles.footer}>Your time, thoughtfully accounted for.</footer>
        </div>
      </section>
    </main>
  );
}
