# Settings Page Overrides

> **PROJECT:** YouTube to Bilibili Workbench
> **Generated:** 2026-05-09 00:34:55
> **Page Type:** Dashboard / Data View

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout Overrides

- **Max Width:** 1200px (standard workbench)
- **Layout:** Two-column settings grid with the main connection form spanning the widest area
- **Sections:** 1. System status header, 2. Connection and TTS form, 3. Dependency status, 4. AI/account readiness

### Spacing Overrides

- **Content Density:** Medium-high — keep configuration fields scannable without large marketing spacing

### Typography Overrides

- No overrides — use Master typography

### Color Overrides

- **Strategy:** Use the existing workbench neutral panels, restrained borders, and status colors

### Component Overrides

- Use labeled numeric inputs for bounded settings such as TTS concurrency
- Keep save/reset controls grouped near the form title
- Avoid: Placeholder-only inputs

---

## Page-Specific Components

- No unique components for this page

---

## Recommendations

- Forms: Show loading, success, and error state near the form
- Accessibility: Use label with for attribute or wrap input
- Validation: Mirror backend numeric bounds in the HTML input
- Feedback: Preserve saved values and provide an explicit restore action
