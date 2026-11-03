const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);
let csrfToken: string | null = null;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type Subcategory = {
  id: number;
  category_id: number;
  name: string;
};

export type Category = {
  id: number;
  name: string;
  color: string;
  subcategories: Subcategory[];
};

export type Activity = {
  id: number;
  title: string;
  description: string | null;
  category_id: number;
  subcategory_id: number | null;
  project_id: number | null;
  started_at: string;
  ended_at: string;
  duration_seconds: number;
  notes: string | null;
  tags: string[];
  source: string;
  category: Category;
  subcategory: Subcategory | null;
};

export type GoalMilestone = {
  id: number;
  title: string;
  description: string | null;
  due_date: string | null;
  completed: boolean;
  completed_at: string | null;
};

export type GoalProgressHistory = {
  previous_value: number | null;
  current_value: number | null;
  note: string | null;
  recorded_at: string;
};

export type Goal = {
  id: number;
  title: string;
  description: string | null;
  category_id: number | null;
  category_name: string | null;
  goal_type: "measurable" | "recurring" | "milestone";
  target_value: number | null;
  current_value: number | null;
  current_period_start: string | null;
  unit: string | null;
  recurring_period: "weekly" | "monthly" | null;
  start_date: string;
  deadline: string;
  status: "active" | "completed" | "paused" | "archived";
  progress_percent: number;
  remaining_value: number | null;
  overdue: boolean;
  milestones: GoalMilestone[];
  progress_history: GoalProgressHistory[];
};

export type GoalInput = Pick<
  Goal,
  | "title"
  | "description"
  | "category_id"
  | "goal_type"
  | "target_value"
  | "current_value"
  | "unit"
  | "recurring_period"
  | "start_date"
  | "deadline"
  | "status"
>;

export type ProjectMilestone = {
  id: number;
  title: string;
  description: string | null;
  due_date: string | null;
  completed: boolean;
  completed_at: string | null;
};

export type Project = {
  id: number;
  title: string;
  description: string | null;
  category_id: number | null;
  category_name: string | null;
  status: "active" | "completed" | "paused" | "archived";
  priority: "low" | "medium" | "high";
  start_date: string;
  target_date: string | null;
  completed_at: string | null;
  milestone_count: number;
  completed_milestone_count: number;
  progress_percent: number;
  milestones: ProjectMilestone[];
};

export type ProjectDetail = Project & {
  activities: Activity[];
};

export type ProjectInput = Pick<
  Project,
  "title" | "description" | "category_id" | "status" | "priority" | "start_date" | "target_date"
>;

export type ActivitySummary = {
  total_duration_seconds: number;
  activity_count: number;
  categories: Array<{
    category_id: number;
    category_name: string;
    color: string;
    duration_seconds: number;
    activity_count: number;
  }>;
};

export type AnalyticsCategory = {
  category_id: number;
  category_name: string;
  color: string;
  duration_seconds: number;
  activity_count: number;
};

export type AnalyticsDay = {
  date: string;
  tracked_seconds: number;
  untracked_seconds: number;
  activity_count: number;
  categories: AnalyticsCategory[];
};

export type AnalyticsPeriod = {
  start_date: string;
  end_date: string;
  total_tracked_seconds: number;
  untracked_seconds: number;
  available_seconds: number;
  activity_count: number;
  categories: AnalyticsCategory[];
};

export type Analytics = AnalyticsPeriod & {
  timezone: string;
  days: AnalyticsDay[];
  previous_period: AnalyticsPeriod;
};

export type ActivityInput = {
  title: string;
  description: string | null;
  category_id: number;
  subcategory_id: number | null;
  project_id: number | null;
  started_at: string;
  ended_at: string;
  notes: string | null;
  tags: string[];
  source: string;
};

export type TelegramSettings = {
  connected: boolean;
  paused: boolean;
  bot_username: string | null;
  interval_minutes: number;
  timezone: string;
  active_start: string;
  active_end: string;
  quiet_start: string;
  quiet_end: string;
  next_checkin_at: string | null;
};

export type TelegramLinkCode = {
  code: string;
  expires_at: string;
  bot_username: string | null;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  const method = (init?.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    ...(init?.body ? { "Content-Type": "application/json" } : {}),
    ...Object.fromEntries(new Headers(init?.headers).entries()),
  };
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: "include",
      headers,
    });
  } catch {
    throw new Error("Could not reach the API. Check that the backend is running and try again.");
  }

  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/api/auth/")) {
      csrfToken = null;
      window.dispatchEvent(new Event("personal-life-os:unauthorized"));
    }
    let message = `Request failed (${response.status}).`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        message = body.detail;
      } else if (Array.isArray(body.detail)) {
        const messages = body.detail
          .map((item) =>
            typeof item === "object" &&
            item !== null &&
            "msg" in item &&
            typeof item.msg === "string"
              ? item.msg
              : null,
          )
          .filter((item): item is string => item !== null);
        if (messages.length > 0) message = messages.join(" ");
      }
    } catch {
      // Keep the HTTP status message when the server does not return JSON.
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export type AuthSession = {
  username: string;
  csrf_token: string;
};

export async function getAuthSession() {
  const session = await request<AuthSession>("/api/auth/session");
  csrfToken = session.csrf_token;
  return session;
}

export async function getSetupStatus() {
  return request<{ setup_required: boolean }>("/api/auth/setup-status");
}

export async function setupAccount(input: { username: string; password: string }) {
  const session = await request<AuthSession>("/api/auth/setup", {
    method: "POST",
    body: JSON.stringify(input),
  });
  csrfToken = session.csrf_token;
  return session;
}

export async function login(input: { username: string; password: string }) {
  const session = await request<AuthSession>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(input),
  });
  csrfToken = session.csrf_token;
  return session;
}

export async function logout() {
  await request<void>("/api/auth/logout", { method: "POST" });
  csrfToken = null;
}

export function getCategories() {
  return request<Category[]>("/api/categories");
}

export function createCategory(input: { name: string; color: string }) {
  return request<Category>("/api/categories", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateCategory(
  id: number,
  input: Partial<Pick<Category, "name" | "color">>,
) {
  return request<Category>(`/api/categories/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteCategory(id: number) {
  return request<{ deleted: boolean }>(`/api/categories/${id}`, { method: "DELETE" });
}

export function createSubcategory(categoryId: number, name: string) {
  return request<Subcategory>(`/api/categories/${categoryId}/subcategories`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function deleteSubcategory(id: number) {
  return request<{ deleted: boolean }>(`/api/subcategories/${id}`, { method: "DELETE" });
}

export function updateSubcategory(id: number, name: string) {
  return request<Subcategory>(`/api/subcategories/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

export function getActivities(start: string, end: string, categoryId?: number) {
  const params = new URLSearchParams({ start, end });
  if (categoryId !== undefined) params.set("category_id", String(categoryId));
  return request<Activity[]>(`/api/activities?${params}`);
}

export function getActivitySummary(start: string, end: string) {
  const params = new URLSearchParams({ start, end });
  return request<ActivitySummary>(`/api/activities/summary?${params}`);
}

export function getGoals(includeArchived = false) {
  const params = new URLSearchParams({ include_archived: String(includeArchived) });
  return request<Goal[]>(`/api/goals?${params}`);
}

export function saveGoal(input: Partial<GoalInput>, id?: number) {
  return request<Goal>(id ? `/api/goals/${id}` : "/api/goals", {
    method: id ? "PATCH" : "POST",
    body: JSON.stringify(input),
  });
}

export function updateGoalProgress(id: number, current_value: number, note?: string) {
  return request<Goal>(`/api/goals/${id}/progress`, {
    method: "PATCH",
    body: JSON.stringify({ current_value, note }),
  });
}

export function createGoalMilestone(
  goalId: number,
  input: { title: string; description?: string | null; due_date?: string | null },
) {
  return request<Goal>(`/api/goals/${goalId}/milestones`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateGoalMilestone(goalId: number, milestoneId: number, completed: boolean) {
  return request<Goal>(`/api/goals/${goalId}/milestones/${milestoneId}`, {
    method: "PATCH",
    body: JSON.stringify({ completed }),
  });
}

export function deleteGoalMilestone(goalId: number, milestoneId: number) {
  return request<void>(`/api/goals/${goalId}/milestones/${milestoneId}`, { method: "DELETE" });
}

export function deleteGoal(id: number) {
  return request<void>(`/api/goals/${id}`, { method: "DELETE" });
}

export function getProjects(includeArchived = false) {
  const params = new URLSearchParams({ include_archived: String(includeArchived) });
  return request<Project[]>(`/api/projects?${params}`);
}

export function getProject(id: number) {
  return request<ProjectDetail>(`/api/projects/${id}`);
}

export function saveProject(input: Partial<ProjectInput>, id?: number) {
  return request<Project>(id ? `/api/projects/${id}` : "/api/projects", {
    method: id ? "PATCH" : "POST",
    body: JSON.stringify(input),
  });
}

export function createProjectMilestone(
  projectId: number,
  input: { title: string; description?: string | null; due_date?: string | null },
) {
  return request<Project>(`/api/projects/${projectId}/milestones`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateProjectMilestone(projectId: number, milestoneId: number, completed: boolean) {
  return request<Project>(`/api/projects/${projectId}/milestones/${milestoneId}`, {
    method: "PATCH",
    body: JSON.stringify({ completed }),
  });
}

export function deleteProjectMilestone(projectId: number, milestoneId: number) {
  return request<void>(`/api/projects/${projectId}/milestones/${milestoneId}`, { method: "DELETE" });
}

export function deleteProject(id: number) {
  return request<void>(`/api/projects/${id}`, { method: "DELETE" });
}

export function getAnalytics(startDate: string, endDate: string, timezone: string) {
  const params = new URLSearchParams({
    start_date: startDate,
    end_date: endDate,
    timezone,
  });
  return request<Analytics>(`/api/analytics?${params}`);
}

export function saveActivity(input: ActivityInput, id?: number) {
  return request<Activity>(id ? `/api/activities/${id}` : "/api/activities", {
    method: id ? "PATCH" : "POST",
    body: JSON.stringify(input),
  });
}

export function deleteActivity(id: number) {
  return request<void>(`/api/activities/${id}`, { method: "DELETE" });
}

export function getTelegramSettings() {
  return request<TelegramSettings>("/api/telegram/settings");
}

export function createTelegramLinkCode() {
  return request<TelegramLinkCode>("/api/telegram/link-code", { method: "POST" });
}

export function saveTelegramSettings(
  input: Pick<
    TelegramSettings,
    "interval_minutes" | "timezone" | "active_start" | "active_end" | "quiet_start" | "quiet_end"
  >,
) {
  return request<TelegramSettings>("/api/telegram/settings", {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}
