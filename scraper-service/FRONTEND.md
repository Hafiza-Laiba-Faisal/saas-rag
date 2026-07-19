# Scraper Service — React Frontend Skill

## Project Setup

```bash
# Create React app with Vite + TypeScript + Tailwind
npm create vite@latest scraper-frontend -- --template react-ts
cd scraper-frontend
npm install react-router-dom @tanstack/react-query axios lucide-react recharts
npm install -D tailwindcss @tailwindcss/vite
```

### Tailwind Setup (v4 with Vite plugin)

```ts
// vite.config.ts
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
});
```

```css
/* src/index.css */
@import "tailwindcss";
```

## Routing Structure

```
/src
  /pages
    Layout.tsx              — sidebar + topbar shell
    Dashboard.tsx           — GET /db/stats + recent activity
    CrawlPage.tsx           — POST /crawl + /crawl/smart
    RecursiveCrawl.tsx      — POST /crawl/recursive + job list
    WordPressScrape.tsx     — POST /scrape/wordpress
    FacebookScrape.tsx      — POST /scrape/fb-posts + job poll
    ProfileScrape.tsx       — POST /scrape/profile
    Database.tsx            — GET /db/posts + filters + delete
    Sessions.tsx            — GET /db/sessions
    Auth.tsx                — POST /auth/set-cookies + /auth/fb-login
    Export.tsx              — GET /db/export/excel download
  /components
    ApiResponseDisplay.tsx  — renders success/errors/metrics
    JobPoller.tsx           — polls /status/{job_id} until done
    CrawlResultCard.tsx
    PostCard.tsx
    Sidebar.tsx
    StatsCards.tsx
  /hooks
    useApi.ts               — axios instance + base URL
    useJobPoll.ts           — background job polling hook
  /lib
    api.ts                  — all API call functions
    types.ts                — TypeScript interfaces (match backend schemas)
    utils.ts
  App.tsx                   — router setup
  main.tsx
```

## TypeScript Types (`src/lib/types.ts`)

### Response Envelope

```ts
export interface ApiResponse<T = any> {
  success: boolean;
  data: T | null;
  errors: Array<{ stage: string; reason: string; detail: string }>;
  metrics: { fetch_time_ms: number; parse_time_ms: number; extract_time_ms: number; rendered: boolean };
}
```

### Post / Media

```ts
export interface MediaItem {
  type: "image" | "video" | "audio";
  url: string;
  thumb: string;
  audio_url: string;
  width: number;
  height: number;
}

export interface PostItem {
  id: string;
  caption: string;
  media: MediaItem[];
  likes: number;
  comments: number;
  shares: number;
  posted_at: string;
  post_url: string;
}

export interface PageMeta {
  title: string;
  page_id: string;
  followers: number;
  likes: number;
  category: string;
  about: string;
  website: string;
  phone: string;
  address: string;
  cover_image: string;
  description: string;
  is_verified: boolean;
  links: Record<string, any>[];
}
```

### Scrape Requests

```ts
export interface FbScrapeRequest {
  page_url: string;
  c_user?: string;
  xs?: string;
  datr?: string;
  sb?: string;
  fr?: string;
  browser?: string;
  max_posts?: number;
  scroll_rounds?: number;
  date_from?: string;
  date_to?: string;
}

export interface ProfileScrapeRequest {
  platform: "instagram" | "twitter" | "facebook" | "reddit" | "github" | "tiktok" | "pinterest";
  username: string;
  browser?: string;
  proxy?: string | null;
}

export interface WordPressScrapeRequest {
  url: string;
  max_pages?: number;
  include_pages?: boolean;
  include_media?: boolean;
}
```

### Crawl

```ts
export interface CrawlRequest {
  url: string;
  format?: "json" | "markdown";
}

export interface SmartCrawlRequest {
  url: string;
  timeout?: number;
}

export interface RecursiveCrawlRequest {
  url: string;
  max_depth?: number;
  max_pages?: number;
  allowed_domains?: string[] | null;
  blocked_domains?: string[] | null;
  respect_robots?: boolean;
  timeout?: number;
  follow_external?: boolean;
  workers?: number;
}
```

## API Client (`src/lib/api.ts`)

```ts
import axios from "axios";

const api = axios.create({ baseURL: "http://localhost:8000" });

// ── Info ──
export const getInfo = () => api.get("/");
export const getPlatforms = () => api.get("/platforms");

// ── Auth ──
export const setCookies = (cookies: string) => api.post("/auth/set-cookies", { cookies });
export const fbLogin = (timeout = 300) => api.post(`/auth/fb-login?timeout=${timeout}`);
export const fbStatus = () => api.get("/auth/fb-status");
export const fbCancel = () => api.post("/auth/fb-cancel");
export const fbLogout = () => api.post("/auth/fb-logout");
export const fbCookiesFromProfile = (profile = "Default") =>
  api.get(`/auth/fb-cookies-from-profile?profile=${profile}`);

// ── Scrape ──
export const scrapeFbPosts = (data: FbScrapeRequest) => api.post("/scrape/fb-posts", data);
export const getFbJobStatus = (jobId: string) => api.get(`/scrape/fb-posts/status/${jobId}`);
export const scrapeProfile = (data: ProfileScrapeRequest) => api.post("/scrape/profile", data);
export const scrapeWordPress = (data: WordPressScrapeRequest) => api.post("/scrape/wordpress", data);

// ── Database ──
export const getSessions = () => api.get("/db/sessions");
export const getSession = (id: number) => api.get(`/db/sessions/${id}`);
export const deleteSession = (id: number) => api.delete(`/db/sessions/${id}`);
export const getPosts = (params: Record<string, any>) => api.get("/db/posts", { params });
export const deletePost = (id: number) => api.delete(`/db/posts/${id}`);
export const getStats = () => api.get("/db/stats");
export const exportExcel = (params: Record<string, any>) =>
  api.get("/db/export/excel", { params, responseType: "blob" });

// ── Proxy ──
export const proxyMedia = (url: string) => `/proxy/media?url=${encodeURIComponent(url)}`;
export const proxyDownload = (url: string, audioUrl?: string, filename?: string) => {
  const params = new URLSearchParams({ url });
  if (audioUrl) params.set("audio_url", audioUrl);
  if (filename) params.set("filename", filename);
  return `/proxy-download?${params}`;
};

// ── Crawl ──
export const crawlPage = (data: CrawlRequest) => api.post("/crawl", data);
export const crawlTest = (url: string, format = "json") =>
  api.get(`/crawl/test?url=${encodeURIComponent(url)}&format=${format}`);
export const smartCrawl = (data: SmartCrawlRequest) => api.post("/crawl/smart", data);
export const startRecursiveCrawl = (data: RecursiveCrawlRequest) => api.post("/crawl/recursive", data);
export const getRecursiveStatus = (jobId: string) => api.get(`/crawl/recursive/status/${jobId}`);
export const listRecursiveJobs = () => api.get("/crawl/recursive/jobs");
export const deleteRecursiveJob = (jobId: string) => api.delete(`/crawl/recursive/${jobId}`);
```

## Page-by-Page Blueprint

### 1. Layout (`Layout.tsx`)
- Persistent sidebar with nav links: Dashboard, Crawl, Crawl (Recursive), WordPress, Facebook, Profile, Database, Sessions, Auth, Export
- Topbar showing service name + status indicator (hit `GET /`)
- `<Outlet />` for page content
- Sidebar collapses on mobile

### 2. Dashboard (`Dashboard.tsx`)
- Fetch `GET /db/stats` on mount → show stats cards (total posts, sessions, etc.)
- Fetch `GET /db/sessions` → show recent sessions in a table (last 5)
- Quick-action buttons: "New Crawl", "Scrape WordPress", "Facebook Scrape"
- Metrics panel showing `elapsed_ms` from last crawl

### 3. Crawl Page (`CrawlPage.tsx`)
- Form: URL input + format dropdown (json/markdown)
- Sent on submit to `POST /crawl`
- Display result: title, description, og_image, links (scrollable list), detectors status, metadata table
- Tab to switch to Smart Crawl (`POST /crawl/smart`) — extra quality_score gauge
- Raw JSON viewer toggle

### 4. Recursive Crawl (`RecursiveCrawl.tsx`)
- Form: URL, max_depth, max_pages, workers, timeout, checkboxes (respect_robots, follow_external), allowed/blocked domains
- On submit → `POST /crawl/recursive` → show `job_id` + `poll_url`
- Active jobs list from `GET /crawl/recursive/jobs` — poll each running job every 3s
- Completed jobs show stats table + expandable pages list

### 5. WordPress Scrape (`WordPressScrape.tsx`)
- Form: URL, max_pages, include_pages checkbox, include_media checkbox
- Submit → `POST /scrape/wordpress`
- Result: detection badge (is_wordpress + detected_by), posts list, pages list, media grid, stats

### 6. Facebook Scrape (`FacebookScrape.tsx`)
- Form: page_url + cookie fields (c_user, xs, datr, sb, fr) + browser, max_posts, scroll_rounds, date range
- Submit → `POST /scrape/fb-posts` → get `job_id`
- Use `JobPoller` component to poll `GET /scrape/fb-posts/status/{job_id}` every 2s
- On done: display PageMeta card, posts list with embedded media, reels separately
- "Export to Excel" button pre-filled with current session

### 7. Profile Scrape (`ProfileScrape.tsx`)
- Form: platform dropdown (from `GET /platforms`), username, optional browser/proxy
- Submit → `POST /scrape/profile`
- Display returned data (platform-specific rendering)

### 8. Database / Posts (`Database.tsx`)
- Filter bar: search text, page_url, content_type dropdown, date range, limit
- Table: #, thumbnail, caption (truncated), date, post_url (clickable)
- Delete button per row with confirmation
- Pagination (offset/limit)
- "Export as Excel" button with current filters

### 9. Sessions (`Sessions.tsx`)
- Table from `GET /db/sessions`: session ID, page_url, date, post count
- Click row → navigate to session detail (GET /db/sessions/{id})
- Delete button

### 10. Auth (`Auth.tsx`)
- Tab 1: Cookie Set — textarea for raw `document.cookie` string → POST /auth/set-cookies
- Tab 2: Browser Login — button → POST /auth/fb-login, show QR/manual instructions
- Tab 3: Status — GET /auth/fb-status, show active cookies
- Tab 4: Chrome Profile — input profile name → GET /auth/fb-cookies-from-profile
- Cancel / Logout buttons

### 11. Export (`Export.tsx`)
- Filters: page_url, content_type, date range, post_ids (comma-separated), limit
- "Download Excel" button → `GET /db/export/excel` → triggers file download via blob

## Component Library

### `ApiResponseDisplay.tsx`
```tsx
// Props: { response: ApiResponse }
// Renders:
//   - success: green check + data JSON (collapsible)
//   - error: red alert with {stage}: {reason} — {detail} per error
//   - metrics: small muted text showing fetch/parse/extract times + rendered flag
```

### `JobPoller.tsx`
```tsx
// Props: { jobId: string; statusUrl: (id) => string; onDone: (data) => void; interval?: number }
// Internal:
//   - poll every `interval` ms
//   - show progress bar (0-100%)
//   - show status message
//   - on "done"/"error" → stop polling + call onDone
```

### `CrawlResultCard.tsx`
```tsx
// Props: { data: CrawlResult }
// Renders: title, description, og_image thumbnail, link count badge, detector status pills, raw HTML length, formatted output preview
```

### `PostCard.tsx`
```tsx
// Props: { post: PostItem }
// Renders: caption, media carousel (images/video thumb), likes/comments/shares, date, link
```

## Styling Guidelines
- Tailwind CSS utility classes only (no CSS modules)
- Dark sidebar (slate-900) with white text
- Main content area: white/gray-50 background
- Cards with rounded-xl, shadow-sm, border
- Buttons: indigo-600 primary, slate-200 secondary, red-600 danger
- Forms: rounded-lg, border, focus:ring-2 focus:ring-indigo-500
- Use `<Suspense>` + fallback loading skeletons for all data fetching
- Toast notifications for success/error via `react-hot-toast` or similar

## State Management
- React Query (`@tanstack/react-query`) for all server state
  - `useQuery` for GET endpoints (auto-cache, stale-while-revalidate)
  - `useMutation` for POST/DELETE (invalidate relevant queries on success)
- No global state store needed (React Query handles server state)
- React's `useState` / `useReducer` for local UI state (forms, toggles)

## Routing (`App.tsx`)

```tsx
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./pages/Layout";
import Dashboard from "./pages/Dashboard";
import CrawlPage from "./pages/CrawlPage";
import RecursiveCrawl from "./pages/RecursiveCrawl";
import WordPressScrape from "./pages/WordPressScrape";
import FacebookScrape from "./pages/FacebookScrape";
import ProfileScrape from "./pages/ProfileScrape";
import Database from "./pages/Database";
import Sessions from "./pages/Sessions";
import Auth from "./pages/Auth";
import Export from "./pages/Export";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="crawl" element={<CrawlPage />} />
          <Route path="crawl/recursive" element={<RecursiveCrawl />} />
          <Route path="wordpress" element={<WordPressScrape />} />
          <Route path="facebook" element={<FacebookScrape />} />
          <Route path="profile" element={<ProfileScrape />} />
          <Route path="database" element={<Database />} />
          <Route path="sessions" element={<Sessions />} />
          <Route path="auth" element={<Auth />} />
          <Route path="export" element={<Export />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
```

## Error Handling Strategy
- Axios interceptor: catch 4xx/5xx → transform into `ApiResponse`-compatible errors
- React Query `onError` for each mutation: show toast
- Each page has an error boundary fallback
- File downloads: catch blob errors and show toast

## CORS Note
Backend already allows all origins (`CORS middleware` in `main.py`).  
For dev, set Vite proxy if needed:

```ts
// vite.config.ts
export default defineConfig({
  server: { proxy: { "/api": "http://localhost:8000" } },
});
```

## Build & Deploy

```bash
npm run build     # → dist/
# Serve dist/ with nginx or deploy to Vercel/Netlify
```
