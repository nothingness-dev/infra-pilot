# Design QA — InfraPilot UI

Status: **passed for the implemented local Mock scope**, 2026-10-23.
This is visual/interaction verification, not live Liara or production readiness.

## Reference and method

Read the supplied ZIP README and visually inspected all five Dark/Light comparison
sheets plus the original incident concept. Each page/theme was treated separately.
Compared supplied concepts and browser captures together in local comparison
images, using fit-width normalization because the supplied concept panels are
not browser viewport captures. This is not a pixel-diff or equal-data assertion.

Final captures use the built application, an explicitly Mock Python bridge,
and no Liara credentials. The isolated verification server ran at loopback 8788
to avoid disturbing concurrent local Setup work on the original checkout.

## Results

| Reference sheet | Implemented views, both themes | Result |
| --- | --- | --- |
| 01 Dashboard and Services | Navy/cyan command shell, four consistent summary cards, trend area, analysis, service status, pending review, activity; searchable service table and selected preview | Passed |
| 02 Service Details and Incidents | Identity/source metadata, tabs, metric availability, collection context, related reports; lifecycle summaries, scope/status/collection filters and master-detail table | Passed |
| 03 Incident Details and AI Analysis | Six observation cards, three-column hypothesis/evidence/approval composition, separate action review; actual diagnostic stages and evidence selection | Passed |
| 04 Approvals and Audit Reports | Narrow request list with wide right-side review, real stored decisions/audit, explicit execution absence; report/audit/export tabs and selected summary | Passed |
| 05 Liara Connection and Settings | Three-step honest Mock workflow, unavailable server credential entry and Real source; shared appearance/timezone/preference panels | Passed |
| Original incident concept | Additional incident hierarchy, decorative orb, evidence and separate sensitive-operation review | Used where consistent with primary sheets |

Corrected during QA: hidden desktop drawer buttons, mobile DEMO visibility,
mobile focus containment/return, table overflow containment, service/report
preview placement, approval review width, dashboard lower-card placement,
exact hypothesis-to-evidence navigation and service health filtering.

## Viewports and evidence

- Desktop 1440×960: **all ten pages in both themes**, 20 built-app captures;
  `docs/screenshots/desktop-checks.json` records page/theme/viewport and absence
  of document overflow. REAL remains disabled on all views.
- Tablet 1024×900: service table, incident details, analysis and connection layout;
  actual acknowledged gate decision captured separately.
- Mobile 390×844: dashboard, incident search/filter, details, drawer, approval
  acknowledgement/decision, audit and JSON download; light and dark samples.
  Final responsive captures/checks include newly added scope filters.
- Browser: ChatGPT in-app browser on Windows. No console errors observed in final
  built-app verification. System-theme changes and late-response suppression are
  covered by component tests; no actual OS settings were changed.
- Principal journey and export assertions:
  `docs/screenshots/journey-check.json`. Viewport overrides were reset afterward.

Representative images: [dark dashboard](docs/screenshots/dashboard-dark.jpg),
[light dashboard](docs/screenshots/dashboard-light.jpg),
[incident detail](docs/screenshots/incident-details-dark.jpg),
[approvals](docs/screenshots/approvals-light.jpg),
[mobile detail](docs/screenshots/incident-details-mobile-light.jpg),
[recorded decision](docs/screenshots/approval-recorded-tablet.jpg).

## Intentional content differences and limits

The reference's service names, four-service total, HTTP series, percentage/MiB
values, cause/confidence claims and sample approvals are illustrative. The
existing pipeline supplies one Mock service and four observation scenarios,
null measurements and no supported hypotheses. The app shows those actual
values and unavailable charts instead of reproducing invented healthy data.

The orb is a generated decorative bitmap; the brand mark and icons use Phosphor,
with local Vazirmatn typography. No page is a screenshot background. Dialogs,
search/filter/sort/page, tabs and theme controls are actual components.

Real credential entry, production identity/ACLs, policy editing, free-form AI,
resource series, release bodies and infrastructure execution remain explicitly
unavailable. They are not passed live capabilities or hidden visual defects.
No open P0/P1/P2 visual/interaction issue was found in the verified Mock scope;
this does not claim pixel-identical output or an external accessibility audit.
