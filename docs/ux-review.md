# Income Tracker — UX Review

**Reviewed:** April 2026  
**Version:** Current production build  
**Reviewer:** Senior Product Designer

---

## 1. What Works Well

**The progress visualization is genuinely useful.** The monthly progress card on the dashboard does exactly what a user needs — it shows where they stand relative to their target, and when they've exceeded it, the card celebrates that moment with a pulsing highlight. For someone tracking freelance income, knowing "you've passed your goal by NTD X" is motivating and actionable.

**The calendar view respects the daily rhythm.** Income tracking is organized around the calendar, and the design makes it easy to see at a glance which days have entries and which don't. The color-coded job indicators let users recognize patterns — "Freelance Design weeks look different from Part-time Retail weeks." This is the core loop of the app, and it's done right.

**Work pace estimation adds genuine value.** The tracker estimates working days left and projects whether you'll hit your monthly target. This is the kind of "use what you know" thinking that separates useful apps from data dashboards.

---

## 2. The Core Tension

The app has two personalities. The main dashboard runs as a single-page application in a light, modern aesthetic — all rounded cards, emerald accents, and Plus Jakarta Sans. Then there's a separate `/notes` route built on a completely different design system: dark background, gold accents, DM Serif Display typography, and a sidebar-based layout. Users navigate between these two experiences, and the contrast is jarring. The notes page doesn't feel like part of the same application — it feels like it was designed by a different person for a different purpose.

---

## 3. The User's Day

### The Income Tracker's Day

A freelance worker opens the app to log their day's earnings.

**Today:** They land on the dashboard — a progress bar, two charts, and three stat cards. The information is there, but it's a summary, not a starting point. The user has to read and interpret it before deciding what to do. They click "Tracking" to get to the calendar. They click a day to log income. They fill in a modal. They close it. The cycle repeats daily.

**What it should feel like:** The dashboard should answer one question immediately: "What do I do today?" For a tracker, that's logging income. The current month's calendar should be visible and interactive from the dashboard — not buried behind a navigation click. The user should be able to log income without leaving the dashboard.

**The gap:** One extra click and one extra page load between arriving at the app and doing the core task. For a tool used daily, that friction compounds. The dashboard's three stat cards and two charts are information, not action. The most important thing — "log today's income" — is neither prominent nor accessible from the landing state.

### The Admin's Day

An admin wants to check system-wide activity.

**Today:** They navigate to Admin view, see four stat cards, a user directory table, and a "Recent Activity" list showing the last 10 income records across all users. This is useful for oversight but offers no drill-down. If an admin wants to investigate a spike in income on March 15th, they have to export data or ask users directly.

**What it should feel like:** Admins need situational awareness. They should see trends, not just totals. A chart of system-wide income over the past 30 days, flagged anomalies, and quick access to any user's data would make this view genuinely powerful.

**The gap:** The admin view is a summary with no investigative capability. It's the difference between a car dashboard that shows "engine light on" versus one that tells you which cylinder is misfiring.

---

## 4. What to Cut

**The Summary view's auto-rotating charts.** The view cycles through three chart types every 5 seconds automatically. This feels like a screensaver, not a data tool. Users who want to analyze their income shouldn't have to watch a slideshow. If there are multiple useful chart types, let users toggle between them. Auto-rotation treats analysis like entertainment.

**The separate `/notes` route.** The app already has an embedded notes feature accessible from the navigation. A second, completely different notes page at `/notes` splits the user's attention and breaks visual continuity. Either integrate notes fully into the main app with consistent styling, or remove the embedded notes button from navigation if the dedicated page is the intended experience. Currently, both exist in an awkward middle ground.

**Redundant view-state management.** The app maintains `currentView` in JavaScript state and also parses `?view=` URL parameters, but the URL never updates when views change. This means users can't share or bookmark specific views, and browser back/forward navigation doesn't work. Either commit to proper URL-based routing or remove the URL parameter parsing — maintaining both creates confusion for developers and breaks expected browser behavior.

---

## 5. What's Missing

**Quick income logging from the dashboard.** The single most common action — logging today's income — requires navigating to the Tracking view and clicking a calendar day. A persistent "Log Income" button on the dashboard, or inline quick-log form, would eliminate this trip. The app knows the current date and the user's jobs. It could pre-fill a form and let them confirm in one tap.

**Income editing and deletion.** Users can add income records, but the calendar view and records list show no obvious way to edit or delete an entry once created. If a user mistypes an amount or selects the wrong job, they're stuck with the error. Every create operation needs a matching update and delete path.

**A monthly overview toggle.** The app defaults to the current month everywhere, but users often want to compare this month to last month, or review a specific past period. Date range selection — at minimum, a simple previous/next month toggle on the dashboard — would make historical analysis possible without manual date entry.

**Visual feedback for save operations.** When a user logs income, adds a job, or updates a target, the app responds silently. The operation either worked or didn't. A brief toast notification — "Income logged" or "Job updated" — tells users their action succeeded without ambiguity. This is a low-effort addition that significantly reduces anxiety around whether the app registered their input.

**Consistent empty states.** Some views handle empty data gracefully; others show blank screens or unstyled lists. Each view should have a designed empty state that tells the user what to do next — "Add your first job to start tracking income" rather than an empty grid.

---

## 6. Priorities

### Priority 1: Dashboard as the action center

The dashboard is the first screen users see. Right now it's primarily informational. Making it actionable — adding a quick-log income form or at least showing today's income status prominently — removes the most common trip through the app. This affects every single user, every single day.

### Priority 2: Unified design language

The split between the light-theme dashboard app and the dark-theme notes page needs to be resolved. It doesn't matter which direction — either bring notes into the main app's aesthetic, or make the dashboard dark to match notes — but the inconsistency signals incomplete design thinking. Users notice when they feel like they're using two different products.

### Priority 3: Edit and delete paths

Completing the CRUD cycle for income records is essential. Users make mistakes. The app should support them fixing those mistakes without data exports or manual correction. This is table stakes for any data-entry application.

### Priority 4: Toast notifications

Adding confirmation feedback for all user actions is a 30-minute task that dramatically improves perceived reliability. Users trust apps that tell them what happened. This should be done early because it sets a quality standard for the entire app.

### Priority 5: Historical navigation

Users will inevitably want to look at past months. Adding month navigation to the dashboard and calendar view unlocks the app's full analytical potential. This is especially important for freelancers tracking seasonal patterns or comparing month-over-month growth.

---

## 7. Surface vs. Structure

Most of what's listed above is structural: the dashboard needs to be action-oriented, the two note experiences need to be reconciled, and historical navigation needs to exist. These are not cosmetic changes. They affect the fundamental experience of using the app.

The one surface-level improvement worth calling out: the Summary view's auto-rotating charts. This is pure polish that should be removed or replaced with user-controlled toggling. It adds no analytical value and introduces motion that distracts from the data.

---

*Review written based on code analysis, not user testing. Recommendations are grounded in observed navigation patterns and workflow analysis.*
